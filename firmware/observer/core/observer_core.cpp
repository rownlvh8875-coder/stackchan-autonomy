// SPDX-License-Identifier: MIT
#include "observer_core.h"
#include <algorithm>
#include <cstring>

namespace scob {
static uint32_t u32(const uint8_t* b) {
    return (uint32_t(b[0]) << 24) | (uint32_t(b[1]) << 16) | (uint32_t(b[2]) << 8) | b[3];
}
static void put32(uint8_t* b, uint32_t v) {
    for (int i = 3; i >= 0; --i) { b[i] = uint8_t(v); v >>= 8; }
}
static std::string hex(const uint8_t* b, size_t n) {
    std::string out;
    static const char* digits = "0123456789abcdef";
    for (size_t i = 0; i < n; ++i) { out += digits[b[i] >> 4]; out += digits[b[i] & 15]; }
    return out;
}
uint32_t crc32(const uint8_t* b, size_t n, uint32_t initial) {
    uint32_t crc = ~initial;
    for (size_t i = 0; i < n; ++i) {
        crc ^= b[i];
        for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
bool send(Sink& sink, uint8_t kind, const Id& nonce, const uint8_t* data, size_t n) {
    if (n > (kind == 0x84 ? 131072u : 4096u)) return false;
    std::array<uint8_t, 32> header{};
    std::memcpy(header.data(), "SCOB", 4);
    header[4] = 1; header[5] = kind;
    std::copy(nonce.begin(), nonce.end(), header.begin() + 8);
    put32(header.data() + 24, uint32_t(n));
    put32(header.data() + 28, crc32(data, n, crc32(header.data(), 28)));
    return sink.write(header.data(), header.size()) && (!n || sink.write(data, n));
}
static bool json(Sink& sink, uint8_t kind, const Id& nonce, const std::string& text) {
    return send(sink, kind, nonce, reinterpret_cast<const uint8_t*>(text.data()), text.size());
}
static void error(Sink& sink, const Id& nonce, const char* code) {
    json(sink, 0xff, nonce, std::string("{\"error\":\"") + code + "\"}");
}
static std::string event(const Event& e, const char* provenance, unsigned maximum) {
    if (!e.known || e.kind > maximum) return "null";
    return "{\"kind\":" + std::to_string(e.kind) + ",\"age_ms\":" + std::to_string(e.age_ms) +
           ",\"provenance\":\"" + provenance + "\"}";
}
static std::string state_fields(const State& s, const Id& boot) {
    return "\"boot_id\":\"" + hex(boot.data(), boot.size()) + "\",\"uptime_ms\":" +
        std::to_string(s.uptime_ms) + ",\"touch\":" + event(s.touch, "hal_head_pet_event", 4) +
        ",\"imu\":" + event(s.imu, "hal_imu_motion_event", 2) +
        ",\"head_pose\":null,\"pose_verified\":false";
}
void Dispatcher::reset() { used_ = 0; expected_ = 32; noise_ = 0; }
void Dispatcher::feed(const uint8_t* data, size_t n, Sink& sink) {
    for (size_t i = 0; i < n; ++i) {
        input_[used_++] = data[i];
        if (used_ <= 4 && input_[used_ - 1] != uint8_t("SCOB"[used_ - 1])) {
            const bool restart = data[i] == 'S';
            used_ = restart ? 1 : 0;
            if (restart) input_[0] = 'S';
            if (++noise_ > 1024 * 1024) reset();
            continue;
        }
        if (used_ == 32) {
            const uint32_t length = u32(input_.data() + 24);
            if (input_[4] != 1 || input_[6] || input_[7] || length > 16 ||
                (input_[5] != 1 && input_[5] != 2 && input_[5] != 3) ||
                (input_[5] == 1 ? length != 0 : length != 16)) {
                Id nonce{}; std::copy_n(input_.begin() + 8, 16, nonce.begin());
                error(sink, nonce, "PROTOCOL"); reset(); continue;
            }
            expected_ = 32 + length;
        }
        if (used_ >= 32 && used_ == expected_) { dispatch(sink); reset(); }
    }
}
void Dispatcher::dispatch(Sink& sink) {
    Id nonce{}; std::copy_n(input_.begin() + 8, 16, nonce.begin());
    if (u32(input_.data() + 28) != crc32(input_.data() + 32, expected_ - 32,
                                       crc32(input_.data(), 28))) {
        error(sink, nonce, "PROTOCOL"); return;
    }
    for (size_t i = 0; i < std::min(count_, recent_.size()); ++i) {
        if (recent_[i] == nonce) { error(sink, nonce, "REPLAY"); return; }
    }
    recent_[count_++ % recent_.size()] = nonce;
    const Id boot = backend_.boot_id();
    if (input_[5] == 1) {
        const auto device = backend_.device_id();
        json(sink, 0x81, nonce,
            "{\"contract_version\":1,\"firmware\":\"unofficial-observer-prototype\","
            "\"upstream\":\"28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400\",\"read_only\":true,"
            "\"boot_id\":\"" + hex(boot.data(), boot.size()) + "\",\"device_id\":\"" +
            hex(device.data(), device.size()) + "\",\"capabilities\":[\"status\",\"snapshot\"]}");
        return;
    }
    if (!std::equal(boot.begin(), boot.end(), input_.begin() + 32)) {
        error(sink, nonce, "BOOT_CHANGED"); return;
    }
    if (input_[5] == 2) { json(sink, 0x82, nonce, "{" + state_fields(backend_.status(), boot) + "}"); return; }
    struct Cleanup { Backend& b; ~Cleanup() { b.release(); } } cleanup{backend_};
    Capture capture;
    const Result result = backend_.capture(capture);
    if (result != Result::Ok) { error(sink, nonce, result == Result::Busy ? "BUSY" : "UNAVAILABLE"); return; }
    if (!capture.data || !capture.size || capture.size > 131072 || !capture.width || !capture.height ||
        capture.width > 640 || capture.height > 640 || capture.width * capture.height > 307200) {
        error(sink, nonce, "UNAVAILABLE"); return;
    }
    const auto s = backend_.status();
    if (capture.captured_ms > s.uptime_ms || s.uptime_ms - capture.captured_ms > 2000) {
        error(sink, nonce, "UNAVAILABLE"); return;
    }
    const std::string meta = "{" + state_fields(s, boot) + ",\"image_id\":\"" +
        hex(nonce.data(), nonce.size()) + "\",\"captured_ms\":" + std::to_string(capture.captured_ms) +
        ",\"width\":" + std::to_string(capture.width) + ",\"height\":" + std::to_string(capture.height) +
        ",\"byte_count\":" + std::to_string(capture.size) + ",\"sha256\":\"" +
        hex(capture.sha.data(), capture.sha.size()) + "\"}";
    if (json(sink, 0x83, nonce, meta)) send(sink, 0x84, nonce, capture.data, capture.size);
}
} // namespace scob
