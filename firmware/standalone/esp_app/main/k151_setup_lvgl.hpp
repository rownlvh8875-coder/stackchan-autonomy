// SPDX-License-Identifier: MIT
// Optional LVGL view ONLY. It NEVER creates or resets a K151 LCD panel.
#pragma once

#include "setup_screen_model.hpp"
#include <atomic>
#include <string_view>
#include <lvgl.h>

namespace stackchan::standalone {

class K151LcdPanel;

class K151SetupLvgl final {
 public:
  static const char* compiled_link_marker();
  K151SetupLvgl(const std::atomic_bool& physical_stop) : stop_(physical_stop) {}
  K151SetupLvgl(const K151SetupLvgl&) = delete;
  K151SetupLvgl& operator=(const K151SetupLvgl&) = delete;

  // View borrows a live port. Detach before destroying the port. The caller
  // supplies local physical readability evidence and holds the LVGL lock.
  bool attach(K151LcdPanel& panel, bool exact_panel_verified,
              bool lvgl_lock_held, bool trusted_local_owner);
  bool present(TouchConsentPhase touch, OwnerSetupPhase owner,
               bool trusted_input_ready, bool sensor_read_failed,
               bool lvgl_lock_held);
  // Non-secret eight-digit SAS only; physical LCD must be independently
  // verified, already initialized, and owned by the caller's LVGL task.
  bool present_pairing_sas(std::string_view code, bool trusted_display,
                           bool owner_window, bool lvgl_lock_held);
  bool detach(bool lvgl_lock_held);
  bool attached() const;

 private:
  const std::atomic_bool& stop_;
  K151LcdPanel* panel_ = nullptr;
  lv_obj_t* root_ = nullptr;
  lv_obj_t* title_ = nullptr;
  lv_obj_t* first_ = nullptr;
  lv_obj_t* second_ = nullptr;
  bool attempted_ = false;
};
} // namespace stackchan::standalone
