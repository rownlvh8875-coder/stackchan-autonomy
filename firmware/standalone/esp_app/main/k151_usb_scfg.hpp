// SPDX-License-Identifier: MIT
// Compiled only. NOT INSTALLED or invoked from app_main.
#pragma once

#include <atomic>
#include <cstdint>
#include <utility>
#include "usb_enrollment.hpp"

namespace stackchan::standalone {

class K151ScfgUsbPort final {
 public:
  static const char* compiled_link_marker();
  explicit K151ScfgUsbPort(EnrollmentServer::ProfileStore store)
      : enrollment_(std::move(store)) {}
  K151ScfgUsbPort(const K151ScfgUsbPort&) = delete;
  K151ScfgUsbPort& operator=(const K151ScfgUsbPort&) = delete;

  // Explicit, *trusted local* decisions only. Current app_main never calls.
  // Console MUST use UART0; USB serial is dedicated to SCFG, not stdout.
  bool start(bool local_owner_mode, bool uart_console_verified,
             bool durable_profile_store_ready, const std::atomic_bool& stop_latch);

  // Single bounded chunk (96 bytes) per poll. Incomplete SCFG packets expire
  // inside ScfgStreamReader. No retry, cloud request, or raw PCM command.
  bool poll_once(std::uint64_t monotonic_ms, const std::atomic_bool& stop_latch);

  // May only be called on the CPU core used to install USB Serial/JTAG.
  bool shutdown();
  bool running() const { return running_ && !faulted_; }
  bool faulted() const { return faulted_; }

 private:
  void latch_local_stop();
  void fail();
  ScfgStreamReader reader_;
  EnrollmentServer enrollment_;
  bool running_ = false;
  bool faulted_ = false;
  bool local_stop_latched_ = false;
  bool ever_started_ = false;
};

}  // namespace stackchan::standalone
