#include "head_touch_consent.hpp"
#include "owner_setup.hpp"
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
using namespace stackchan::standalone;
static constexpr std::array<uint8_t,3> clear{{0,0,0}}, pad_touch{{0,2,0}};
static TouchConsentEvent feed(HeadTouchConsent& g, uint64_t from, uint64_t to, const std::array<uint8_t,3>& pad) {
  TouchConsentEvent seen=TouchConsentEvent::none;
  for (uint64_t ms=from; ms<=to; ms+=50) {auto out=g.sample(pad,ms,true,false);if(out!=TouchConsentEvent::none)seen=out;}
  return seen;
}
int main() {
  { // Independent two-stage local setup: physical touch ≠ trusted secret UI.
    RuntimeSecrets secrets;
    std::atomic_bool owner{false},trusted_input{false},stop{false};
    OwnerSetupController setup(secrets,owner,trusted_input,stop);
    HeadTouchConsent touch;
    assert(touch.begin(true,0));
    feed(touch,0,300,clear);
    feed(touch,350,3350,pad_touch);
    assert(feed(touch,3400,3700,clear)==TouchConsentEvent::owner_window_open);
    owner.store(true);
    assert(!setup.arm(3700)); // Touch alone cannot authorize data entry.
    trusted_input.store(true); // Only future verified local UI may assert.
    assert(setup.arm(3700));
    const std::array<uint8_t,4> ssid{'t','e','s','t'};
    assert(setup.submit_wifi(ssid,"fake-passphrase",3710));
    assert(setup.submit_api_key("fake-testing-token-0123456789",3720));
    assert(!setup.ready());
    assert(touch.request_final_confirmation(true,3750));
    feed(touch,3800,4100,clear);
    feed(touch,4150,7150,pad_touch);
    assert(feed(touch,7200,7500,clear)==TouchConsentEvent::final_confirmed);
    const auto now=uint64_t{7500};
    assert(touch.take_final_confirmation(now,false));
    assert(setup.confirm(now,true));
    assert(setup.ready() && secrets.valid());
    owner.store(false);
    assert(!setup.tick(now+50));
    assert(!secrets.valid());
  }
  std::cout<<"head touch + local owner setup contract PASS\n";
}
