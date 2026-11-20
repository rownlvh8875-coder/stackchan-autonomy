#include "live_io_gate.hpp"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
using namespace stackchan::standalone;

int main() {
  std::atomic_bool network{true}, consent{true}, stop{false};
  auto make=[&](uint64_t deadline) {
    return LiveIoGate([&]() { return network.load(); },consent,stop,deadline);
  };
  {
    auto gate=make(1000);
    assert(gate.allowed(100));
    assert(gate.allowed(999));
    assert(!gate.allowed(1000) && gate.revoked());
    assert(!gate.allowed(200));
  }
  {
    auto gate=make(1000);
    network.store(false);
    assert(!gate.allowed(100));
    network.store(true);
    assert(!gate.allowed(101)); // No re-enable of a partially sent request.
  }
  {
    auto gate=make(1000);
    assert(gate.allowed(100));
    consent.store(false);
    assert(!gate.allowed(101));
    consent.store(true);
    assert(!gate.allowed(102));
  }
  {
    auto gate=make(1000);
    assert(gate.allowed(100));
    stop.store(true);
    assert(!gate.allowed(101));
    stop.store(false);
    assert(!gate.allowed(102));
  }
  {
    LiveIoGate fail_closed({},consent,stop,1000);
    assert(!fail_closed.allowed(100));
  }
  std::cout << "live I/O admission: PASS (network revoke, STOP, no retry)\n";
}
