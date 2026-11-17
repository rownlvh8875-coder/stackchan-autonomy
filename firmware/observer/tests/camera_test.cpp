// SPDX-License-Identifier: MIT
#include "observer_camera.h"
#include <cassert>
using namespace scob;
struct Queue : FrameQueue {
    uint8_t old[8]{}, fresh[8]{}, factory[8]{1};
    unsigned takes = 0, gives = 0, encodes = 0;
    bool short_frame = false, bad_queue = false, no_frame = false;
    uint64_t now_ms() override { return 1000; }
    bool take(RawFrame& f) override {
        if (no_frame) return false;
        f = {takes++ ? fresh : old, short_frame ? 2u : 8u, 8, 2, 2, Pixel::RGB565};
        return true;
    }
    bool give() override { ++gives; return !bad_queue; }
    Result encode(const RawFrame& f, Capture&) override {
        ++encodes; assert(f.data == fresh); assert(factory[0] == 1); return Result::Ok;
    }
};
int main() {
    Capture c;
    Queue q; assert(capture_fresh(q, c) == Result::Ok);
    assert(q.takes == 2 && q.gives == 2 && q.encodes == 1 && c.captured_ms == 1000);
    Queue short_q; short_q.short_frame = true;
    assert(capture_fresh(short_q, c) == Result::Unavailable && short_q.encodes == 0 && short_q.gives == 2);
    Queue bad; bad.bad_queue = true;
    assert(capture_fresh(bad, c) == Result::Unavailable && bad.encodes == 0 && bad.gives == 1);
    Queue absent; absent.no_frame = true;
    assert(capture_fresh(absent, c) == Result::Unavailable && absent.gives == 0);
    RawFrame f{q.fresh, 8, 8, 2, 2, Pixel::RGB565};
    assert(valid_raw(f)); f.data = nullptr; assert(!valid_raw(f));
    f.data=q.fresh; f.mapped_size=7; assert(!valid_raw(f));
    f.mapped_size=8; f.pixel=Pixel::Unsupported; assert(!valid_raw(f));
    f.pixel=Pixel::YUYV; f.width=1; f.height=4; assert(!valid_raw(f));
}
