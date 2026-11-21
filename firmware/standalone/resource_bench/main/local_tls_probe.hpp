// SPDX-License-Identifier: MIT
#pragma once

#include <functional>
#include <memory>

namespace stackchan::standalone {

// A diagnostic TLS 1.2 pair with memory BIOs and a volatile test identity.
// Keep this object alive while measuring the existing synthesis buffers.
class LocalTlsProbe final {
 public:
  LocalTlsProbe();
  ~LocalTlsProbe();
  LocalTlsProbe(const LocalTlsProbe&) = delete;
  LocalTlsProbe& operator=(const LocalTlsProbe&) = delete;

  static constexpr const char* kHostname = "bench.stackchan.invalid";
  bool run(const std::function<bool()>& allowed, const char* hostname = kHostname);
  const char* stage() const { return stage_; }
  int handshake_error() const { return handshake_error_; }

 private:
  struct Pair;
  std::unique_ptr<Pair> pair_;
  bool attempted_ = false;
  const char* stage_ = "idle";
  int handshake_error_ = 0;
};

} // namespace stackchan::standalone
