#include "network_time_guard.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <string_view>
using namespace stackchan::standalone;
constexpr uint64_t e=1800000000;
int main() {
  RuntimeSecrets s;
  std::array<uint8_t, 4> wifi{'h','o','m','e'};
  assert(!s.provision(wifi,"eightpass","sk-test-secret-device-only",false));
  assert(!s.valid());
  assert(!s.provision(wifi,"short","sk-test-secret-device-only",true));
  assert(!s.provision(wifi,"eightpass","short",true));
  assert(s.provision(wifi,"eightpass","sk-test-secret-device-only",true));
  assert(s.valid() && s.ssid().size()==4 && s.passphrase()=="eightpass");
  s.clear();
  assert(!s.valid() && s.ssid().empty() && s.api_key().empty());
  EphemeralApiKey request_key;
  assert(!request_key.load("short"));
  assert(request_key.view().empty());
  assert(request_key.load("sk-test-secret-device-only"));
  assert(request_key.view() == "sk-test-secret-device-only");
  request_key.clear();
  assert(request_key.view().empty());
  std::string long_hex(64,'a');
  assert(s.provision(wifi,long_hex,"sk-test-secret-device-only",true));
  s.clear();
  assert(!s.provision(wifi,std::string(64,'g'),"sk-test-secret-device-only",true));
  NetworkTimeGuard n;
  assert(n.phase()==ConnectivityPhase::hold);
  assert(!n.arm(false,true,100));
  assert(!n.arm(true,false,100));
  assert(n.arm(true,true,100));
  assert(!n.can_attempt_paid_request(100,e,true,false));
  auto a=n.claim_connect(100);
  assert(a && *a==1);
  assert(!n.claim_connect(100));
  assert(!n.associated(5,101));
  assert(n.associated(1,101));
  assert(!n.time_synchronized(1,e,102)); // IP required
  assert(n.ip_acquired(1,102));
  assert(!n.time_synchronized(100,e,103));
  assert(!n.time_synchronized(1,1500000000,103));
  assert(n.time_synchronized(1,e,103));
  assert(n.can_attempt_paid_request(203,e,true,false));
  assert(!n.can_attempt_paid_request(203,e,false,false));
  assert(!n.can_attempt_paid_request(203,e,true,true));
  assert(!n.can_attempt_paid_request(203,e+100,true,false));
  assert(n.can_attempt_paid_request(2103,e+2,true,false));
  // Periodic SNTP while already ready is normal and must not fatal-fault.
  assert(n.time_synchronized(1,e+2,2104));
  assert(n.can_attempt_paid_request(2104,e+2,true,false));
  // DHCP IP renewal invalidates readiness and requests another SNTP sample.
  assert(n.ip_acquired(1,2110));
  assert(n.phase()==ConnectivityPhase::waiting_time);
  assert(!n.can_attempt_paid_request(2110,e+2,true,false));
  assert(n.time_synchronized(1,e+2,2111));
  n.disconnected(2200);
  assert(n.phase()==ConnectivityPhase::offline && n.next_retry_ms()==3200);
  assert(!n.can_attempt_paid_request(2200,e+2,true,false));
  assert(!n.claim_connect(3199));
  a=n.claim_connect(3200);
  assert(a && *a==2);
  assert(!n.associated(1,3201));
  assert(n.associated(2,3202));
  assert(n.ip_acquired(2,3203));
  assert(!n.time_synchronized(1,e+3,3204));
  assert(n.time_synchronized(2,e+3,3204));
  assert(n.can_attempt_paid_request(3204,e+3,true,false));
  n.disconnected(3300);
  assert(n.next_retry_ms()==4300);
  a=n.claim_connect(4300); assert(a && *a==3);
  assert(n.associated(3,4301) && n.ip_acquired(3,4302));
  assert(!n.time_synchronized(3,e+1000,4303));
  assert(n.phase()==ConnectivityPhase::fault);
  assert(!n.can_attempt_paid_request(4303,e+1000,true,false));
  assert(!n.arm(true,true,4303));
  {
    NetworkTimeGuard t;
    assert(t.arm(true,true,1));
    auto token=t.claim_connect(1);
    assert(token && t.associated(*token,2) && t.ip_acquired(*token,3));
    assert(t.time_synchronized(*token,e,3));
    assert(!t.can_attempt_paid_request(3+NetworkTimeGuard::kMaxClockAgeMs+1,
                                      e+901,true,false));
    assert(t.tick(3+NetworkTimeGuard::kMaxClockAgeMs+1));
    assert(t.phase()==ConnectivityPhase::waiting_time);
    assert(t.time_synchronized(*token,e+901,3+NetworkTimeGuard::kMaxClockAgeMs+1));
    t.stop();
    assert(!t.can_attempt_paid_request(999999,e+1000,true,false));
    assert(!t.claim_connect(999999));
  }
  {
    NetworkTimeGuard t;
    assert(t.arm(true,true,1000));
    auto token=t.claim_connect(1000);
    assert(token);
    t.disconnected(1200);
    assert(t.next_retry_ms()==2200);
    assert(!t.tick(1100)); // monotonic rollback => fatal
    assert(t.phase()==ConnectivityPhase::fault);
  }
  std::cout<<"network time policy: PASS (RAM secret, retry, clock, STOP)\n";
}
