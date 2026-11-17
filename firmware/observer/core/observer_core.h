// SPDX-License-Identifier: MIT
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace scob {
using Id = std::array<uint8_t, 16>;
struct Event { bool known = false; unsigned kind = 0; uint64_t age_ms = 0; };
struct State { uint64_t uptime_ms = 0; Event touch, imu; };
struct Capture {
    const uint8_t* data = nullptr;
    size_t size = 0;
    unsigned width = 0, height = 0;
    uint64_t captured_ms = 0;
    std::array<uint8_t, 32> sha{};
};
enum class Result { Ok, Busy, Unavailable };
struct Backend {
    virtual ~Backend() = default;
    virtual Id boot_id() const = 0;
    virtual std::array<uint8_t, 6> device_id() const = 0;
    virtual State status() = 0;
    virtual Result capture(Capture&) = 0;
    virtual void release() = 0;
};
struct Sink { virtual ~Sink() = default; virtual bool write(const uint8_t*, size_t) = 0; };
uint32_t crc32(const uint8_t*, size_t, uint32_t initial = 0);
bool send(Sink&, uint8_t kind, const Id& nonce, const uint8_t*, size_t);
class Dispatcher {
public:
    explicit Dispatcher(Backend& backend) : backend_(backend) {}
    void feed(const uint8_t*, size_t, Sink&);
    void reset();
private:
    Backend& backend_;
    std::array<uint8_t, 48> input_{};
    size_t used_ = 0, expected_ = 32, noise_ = 0;
    std::array<Id, 16> recent_{};
    size_t count_ = 0;
    void dispatch(Sink&);
};
} // namespace scob
