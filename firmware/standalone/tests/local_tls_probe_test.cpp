// SPDX-License-Identifier: MIT
#include "local_tls_probe.hpp"

#include <cassert>
#include <iostream>
#include <string_view>

#ifdef NDEBUG
#error "Run the TLS probe test with assertions enabled"
#endif

using stackchan::standalone::LocalTlsProbe;

int main() {
  const auto allow = [] { return true; };
  {
    LocalTlsProbe probe;
    const bool established = probe.run(allow);
    if (!established)
      std::cerr << "TLS failed at " << probe.stage() << ' ' << probe.handshake_error() << '\n';
    assert(established);
    assert(!probe.run(allow));
  }
  {
    LocalTlsProbe probe;
    assert(!probe.run(allow, "wrong.stackchan.invalid"));
    assert(std::string_view(probe.stage()) == "handshake");
    assert(probe.handshake_error() != 0);
    assert(!probe.run(allow));
  }
  {
    LocalTlsProbe probe;
    unsigned checks = 0;
    assert(!probe.run([&] { return ++checks < 6; }));
    assert(checks == 6);
    assert(!probe.run(allow));
  }
  {
    LocalTlsProbe probe;
    assert(!probe.run([&] { return std::string_view(probe.stage()) != "handshake"; }));
    assert(std::string_view(probe.stage()) == "handshake");
    assert(probe.handshake_error() == 0 && !probe.run(allow));
  }
  std::cout << "Verified memory TLS 1.2, wrong hostname rejection and STOP\n";
}
