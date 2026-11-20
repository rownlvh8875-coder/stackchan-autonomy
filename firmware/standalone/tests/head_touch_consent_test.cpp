// Host-only synthetic Si12T intensity samples. No actual touch sensor or USB.
#include "head_touch_consent.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>

using namespace stackchan::standalone;
static constexpr std::array<uint8_t,3> kClear{0,0,0};
static constexpr std::array<uint8_t,3> kTouch{0,2,0};

// Fixed 50-ms cadence (same as pinned upstream head touch loop).
static TouchConsentEvent feed(HeadTouchConsent& ctrl, uint64_t from,
                              uint64_t to, const std::array<uint8_t,3>& pad) {
  TouchConsentEvent out = TouchConsentEvent::none;
  for (uint64_t t=from; t<=to; t+=50) {
    const auto next = ctrl.sample(pad,t,true,false);
    if (next != TouchConsentEvent::none) out=next;
  }
  return out;
}
static uint64_t establish_presence(HeadTouchConsent& ctrl) {
  assert(ctrl.begin(true,0));
  assert(feed(ctrl,0,300,kClear)==TouchConsentEvent::none);
  assert(feed(ctrl,350,3350,kTouch)==TouchConsentEvent::none);
  assert(feed(ctrl,3400,3700,kClear)==TouchConsentEvent::owner_window_open);
  assert(ctrl.owner_window_open(3700));
  return 3700;
}
static uint64_t confirm_presence(HeadTouchConsent& ctrl, uint64_t start) {
  assert(ctrl.request_final_confirmation(true,start));
  assert(feed(ctrl,start+50,start+350,kClear)==TouchConsentEvent::none);
  assert(feed(ctrl,start+400,start+3400,kTouch)==TouchConsentEvent::none);
  assert(feed(ctrl,start+3450,start+3750,kClear)==TouchConsentEvent::final_confirmed);
  return start+3750;
}

int main() {
  { HeadTouchConsent g;
    assert(!g.begin(false,0));
    establish_presence(g);
    assert(!g.request_final_confirmation(false,3750));
    const auto now=confirm_presence(g,3750);
    assert(g.take_final_confirmation(now,false));
    assert(!g.take_final_confirmation(now,false));
    assert(!g.begin(true,now));
  }
  { // Device powered on with a hand already touching: no false arm.
    HeadTouchConsent g; assert(g.begin(true,0));
    assert(feed(g,0,3500,kTouch)==TouchConsentEvent::none);
    assert(g.phase()==TouchConsentPhase::clear_for_arm);
    assert(!g.owner_window_open(3500));
  }
  { // A short head tap never grants local presence.
    HeadTouchConsent g;assert(g.begin(true,0));
    feed(g,0,300,kClear);feed(g,350,2000,kTouch);
    feed(g,2050,2350,kClear);
    assert(!g.owner_window_open(2350));
  }
  { // Missing I2C samples and out-of-range readings permanently fault.
    HeadTouchConsent g;assert(g.begin(true,0));
    assert(g.sample(kClear,0,true,false)==TouchConsentEvent::none);
    assert(g.sample(kClear,251,true,false)==TouchConsentEvent::invalidated);
    assert(g.phase()==TouchConsentPhase::fault);
    HeadTouchConsent g2;assert(g2.begin(true,0));
    assert(g2.sample({4,0,0},0,true,false)==TouchConsentEvent::invalidated);
    HeadTouchConsent g3;assert(g3.begin(true,0));
    assert(g3.sample(kClear,0,false,false)==TouchConsentEvent::invalidated);
  }
  { // Physical STOP cannot be cleared by USB, sensor reconnection or uptime.
    HeadTouchConsent g;establish_presence(g);
    assert(g.sample(kClear,3750,true,true)==TouchConsentEvent::invalidated);
    assert(!g.owner_window_open(3800));
    assert(!g.begin(true,3800));
    assert(!g.take_final_confirmation(3800,false));
  }
  { // The second confirmation must finish inside 2-minute owner window.
    HeadTouchConsent g;establish_presence(g);
    assert(!g.request_final_confirmation(true,123701));
    assert(g.sample(kClear,123751,true,false)==TouchConsentEvent::invalidated);
  }
  { // After final confirmation, ticket is only usable for 15 seconds.
    HeadTouchConsent g;establish_presence(g);
    auto now=confirm_presence(g,3750);
    assert(!g.take_final_confirmation(now+15001,false));
  }
  { // No polling -> no stale physical confirmation, even within 15s.
    HeadTouchConsent g;establish_presence(g);
    const auto now=confirm_presence(g,3750);
    assert(!g.take_final_confirmation(now+251,false));
    assert(!g.owner_window_open(now+251));
  }
  { // Stale readouts cannot re-open the confirmation stage.
    HeadTouchConsent g;establish_presence(g);
    assert(!g.request_final_confirmation(true,4000)); // last poll 3700
    assert(g.phase()==TouchConsentPhase::owner_window);
  }
  std::cout << "head touch two-gesture physical presence: PASS (no sensors)\n";
}
