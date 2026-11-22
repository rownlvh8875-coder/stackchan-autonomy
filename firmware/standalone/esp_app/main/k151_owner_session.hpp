// SPDX-License-Identifier: MIT
#pragma once

#include "k151_head_touch_owner.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_owner_setup.hpp"
#include "k151_scps_usb.hpp"
#include "k151_setup_lvgl.hpp"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <optional>

namespace stackchan::standalone {

// One pinned device task owns I2C1, LVGL and the USB driver. Credentials can
// only leave setup through the existing voice bootstrap on that task.
class K151OwnerSession final {
 public:
  enum class Step { idle, head_touch, pairing, ready, stopped, fault };
  struct ReadySetup {
    K151LocalOwnerSetup& setup;
    K151LcdPanel& panel;
    i2c_master_bus_handle_t bus;
  };

  K151OwnerSession();
  ~K151OwnerSession();
  K151OwnerSession(const K151OwnerSession&) = delete;
  K151OwnerSession& operator=(const K151OwnerSession&) = delete;

  // Both inputs are independently established for this board before start.
  // A successful SPI transfer alone cannot attest the physical screen.
  bool start(bool exact_board_verified, bool physical_lcd_verified);
  Step poll();
  // Borrow until voice and its independent STOP monitor have shut down.
  std::optional<ReadySetup> handoff();
  // Remain on the owner task; a failed release may be retried before teardown.
  bool shutdown();
  static const char* compiled_link_marker();

 private:
  bool on_owner_task() const;
  Step abort_setup();

  const std::atomic_bool& stop_;
  std::atomic_bool owner_{false};
  std::atomic_bool setup_input_{false};
  K151LcdPanel panel_{stop_};
  K151SetupLvgl view_{stop_};
  K151HeadTouchOwner touch_{owner_, stop_};
  K151LocalOwnerSetup setup_{owner_, setup_input_, stop_};
  K151ScpsUsbPort usb_{touch_, setup_, view_, stop_};
  i2c_master_bus_handle_t bus_ = nullptr;
  TaskHandle_t task_ = nullptr;
  int core_ = -1;
  uint64_t last_sample_ms_ = 0;
  bool owns_lvgl_ = false;
  bool board_verified_ = false;
  bool lcd_verified_ = false;
  bool handoff_taken_ = false;
  Step step_ = Step::idle;
};

}  // namespace stackchan::standalone
