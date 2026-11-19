// SPDX-License-Identifier: MIT
// Compile-only K151 SCPS-exclusive USB Serial/JTAG transport.
// Never instantiated or started by HOLD app_main.
#pragma once

#include "scps_usb_wire.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_owner_setup.hpp"
#include "k151_secure_pc_setup.hpp"
#include "k151_setup_lvgl.hpp"
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace stackchan::standalone {

class K151ScpsUsbPort final {
 public:
  static const char* compiled_link_marker();
  // Must be constructed, polled and destroyed on ONE owning FreeRTOS task/core.
  K151ScpsUsbPort(K151HeadTouchOwner& touch, K151LocalOwnerSetup& setup,
                  K151SetupLvgl& display, const std::atomic_bool& physical_stop)
      : touch_(touch), setup_(setup), display_(display),
        stop_(physical_stop), pairing_(physical_stop) {}
  K151ScpsUsbPort(const K151ScpsUsbPort&)=delete;
  K151ScpsUsbPort& operator=(const K151ScpsUsbPort&)=delete;
  ~K151ScpsUsbPort();

  // Trust must be established OFF-USB. The already verified display and
  // sensor must be owned exclusively; SCFG must not own USB Serial/JTAG.
  bool start(uint64_t now_ms,bool exact_board_verified,
             bool trusted_lcd_verified,bool uart_console_verified,
             bool usb_exclusively_owned);
  bool poll_once(uint64_t now_ms);

  // NEVER called from received USB frames. Only a trusted *local* screen
  // controller, after human SAS comparison, may begin the second hold.
  bool arm_second_touch(uint64_t now_ms,bool local_ui_reviewed);
  // Only the owner task calls this after polling Si12T and consuming a real
  // 3-second head-touch gesture. Sole path to RAM-only credential commit.
  bool finalize_after_touch(uint64_t now_ms);

  bool shutdown();   // Must occur on installing core, may drop queued TX.
  bool running() const { return running_ && !faulted_; }
  bool completed() const { return state_==State::complete; }
  bool faulted() const { return faulted_; }

 private:
  enum class State : uint8_t {
    cold, wait_pc_hello, wait_sealed, pending_local_review,
    waiting_touch, complete, stopped, fault
  };
  bool process(const scpswire::Frame& f,uint64_t now_ms);
  bool send(scpswire::Op kind,std::span<const uint8_t> payload={});
  bool fault();
  void scrub_pending();
  K151HeadTouchOwner& touch_;
  K151LocalOwnerSetup& setup_;
  K151SetupLvgl& display_;
  const std::atomic_bool& stop_;
  K151SecurePcSetup pairing_;
  scpswire::Reader frames_;
  std::vector<uint8_t> pending_; // SEALED bytes only, never plaintext.
  uint64_t began_ms_=0;
  State state_=State::cold;
  bool trusted_lcd_=false;
  bool attempted_=false;
  bool running_=false;
  bool faulted_=false;
};

} // namespace stackchan::standalone
