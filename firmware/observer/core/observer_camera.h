// SPDX-License-Identifier: MIT
#pragma once
#include "observer_core.h"

namespace scob {
enum class Pixel { Unsupported, RGB565, RGB888, YUYV, UYVY, YUV422P, Grey };
struct RawFrame {
    const uint8_t* data = nullptr;
    size_t size = 0, mapped_size = 0;
    unsigned width = 0, height = 0;
    Pixel pixel = Pixel::Unsupported;
};
inline bool valid_raw(const RawFrame& f) {
    if (!f.data || !f.width || !f.height || f.width > 640 || f.height > 640 ||
        f.width * f.height > 307200 || f.size > f.mapped_size) return false;
    size_t channels = 0;
    switch (f.pixel) {
        case Pixel::Grey: channels = 1; break;
        case Pixel::RGB888: channels = 3; break;
        case Pixel::YUYV: case Pixel::UYVY: case Pixel::YUV422P:
            if (f.width % 2) return false;
            channels = 2; break;
        case Pixel::RGB565: channels = 2; break;
        default: return false;
    }
    return f.size == size_t(f.width) * f.height * channels;
}
struct FrameQueue {
    virtual ~FrameQueue() = default;
    virtual uint64_t now_ms() = 0;
    virtual bool take(RawFrame&) = 0;
    virtual bool give() = 0;
    virtual Result encode(const RawFrame&, Capture&) = 0;
};
// Verified K151 DVP has exactly one buffer, no backup element. Never touches the
// official camera's retained frame. The caller holds its existing try-lock.
inline Result capture_fresh(FrameQueue& q, Capture& out) {
    struct Lease {
        FrameQueue& q; bool active = true;
        bool finish() { active = false; return q.give(); }
        ~Lease() { if (active) q.give(); }
    };
    out.captured_ms = q.now_ms(); // conservative bound BEFORE discarding/requeue
    RawFrame old;
    if (!q.take(old)) return Result::Unavailable;
    { Lease lease{q}; if (!lease.finish()) return Result::Unavailable; }
    RawFrame fresh;
    if (!q.take(fresh)) return Result::Unavailable;
    Lease lease{q};
    const Result result = valid_raw(fresh) ? q.encode(fresh, out) : Result::Unavailable;
    return lease.finish() ? result : Result::Unavailable;
}
} // namespace scob
