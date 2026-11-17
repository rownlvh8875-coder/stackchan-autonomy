// SPDX-License-Identifier: MIT
// Synthetic backend tests for the production dispatcher, never a hardware build.
#include "observer_core.h"
#include <cassert>
#include <iostream>
#include <iterator>
#include <vector>
#include <cstdio>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif
using namespace scob;
struct Buffer : Sink {
    std::vector<uint8_t> bytes;
    bool fail = false;
    bool write(const uint8_t* p, size_t n) override {
        if (fail) return false;
        bytes.insert(bytes.end(), p, p + n); return true;
    }
};
struct Fake : Backend {
    int captures = 0, releases = 0, statuses = 0;
    Result result = Result::Ok;
    Id boot_id() const override { Id b{}; b.fill(0x11); return b; }
    std::array<uint8_t, 6> device_id() const override { return {0xaa,0xbb,0xcc,0xdd,0xee,0xff}; }
    State status() override { ++statuses; State s; s.uptime_ms = 1000; return s; }
    Result capture(Capture& c) override {
        ++captures; static const uint8_t synthetic[] = {0xff,0xd8,0xff,0xd9};
        c.data = synthetic; c.size = 4; c.width = 16; c.height = 12; c.captured_ms = 990;
        return result;
    }
    void release() override { ++releases; }
};
int main(int argc, char**) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    Fake backend; Dispatcher core(backend); Buffer out;
    if (argc > 1) {
        std::vector<uint8_t> bytes{std::istreambuf_iterator<char>(std::cin), {}};
        for (auto b : bytes) core.feed(&b, 1, out);
        std::cout.write(reinterpret_cast<char*>(out.bytes.data()), out.bytes.size()); return 0;
    }
    const uint8_t check[] = {'1','2','3','4','5','6','7','8','9'};
    assert(crc32(check, 9) == 0xcbf43926);
    auto request = [&](uint8_t kind, unsigned seq, bool wrong_boot = false) {
        Buffer wire; Id nonce{}; nonce[0] = uint8_t(seq); auto boot = backend.boot_id();
        if (wrong_boot) boot[0] ^= 1;
        assert(send(wire, kind, nonce, kind == 1 ? nullptr : boot.data(), kind == 1 ? 0 : 16));
        out.bytes.clear(); core.feed(wire.bytes.data(), wire.bytes.size(), out);
    };
    request(1, 1); assert(out.bytes[5] == 0x81);
    request(2, 2); assert(out.bytes[5] == 0x82 && backend.statuses == 1);
    request(3, 3); assert(out.bytes[5] == 0x83 && backend.captures == 1 && backend.releases == 1);
    request(3, 3); assert(out.bytes[5] == 0xff && backend.captures == 1); // replay
    request(3, 4, true); assert(out.bytes[5] == 0xff && backend.captures == 1);
    request(9, 5); assert(out.bytes[5] == 0xff && backend.captures == 1); // whitelist
    backend.result = Result::Busy;
    request(3, 6); assert(out.bytes[5] == 0xff && backend.releases == 2);
    backend.result = Result::Unavailable;
    request(3, 7); assert(out.bytes[5] == 0xff && backend.releases == 3);
    backend.result = Result::Ok; out.fail = true;
    request(3, 8); assert(backend.captures == 4 && backend.releases == 4);
    std::cout << "HOST_CORE_PASS\n";
}
