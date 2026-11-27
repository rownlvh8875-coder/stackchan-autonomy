// SPDX-License-Identifier: MIT
#pragma once

#include "k151_head_touch_owner.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_owner_setup.hpp"
#include "k151_scps_usb.hpp"
#include "k151_setup_lvgl.hpp"
#include "k151_voice_handoff.hpp"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <optional>

namespace stackchan::standalone {

// One pinned device task owns I2C1, LVGL and the USB driver. Credentials can
// only leave setup through the existing voice bootstrap on that task.
class K151OwnerSession final {
 public:
  enum class Step { idle, head_touch, pairing, ready, voice_review, voice_ready, stopped, fault };
  enum class StartupStage : unsigned {
    idle = 0, preconditions = 1, owner_task = 2, board_bus = 3, lvgl = 4,
    panel = 5, view = 6, presence_frame = 7, head = 8, clock = 9, ready = 10
  };

  K151OwnerSession();
  ~K151OwnerSession();
  K151OwnerSession(const K151OwnerSession&) = delete;
  K151OwnerSession& operator=(const K151OwnerSession&) = delete;

  // Both inputs are independently established for this board before start.
  // A successful SPI transfer alone cannot attest the physical screen.
  // Optional continuous-setup store must come from a verified local provider
  // and outlive the session. With no provider, use the existing RAM-only path.
  bool start(bool exact_board_verified, bool physical_lcd_verified,
             SavedOwnerCredentials* saved = nullptr);
  StartupStage startup_stage() const { return startup_stage_; }
  std::optional<scpswire::SetupFailure> early_setup_failure() const { return early_setup_failure_; }
  // Called by the pinned owner task with the approved deployment scope, only
  // after the encrypted USB session closed. The local display is the sole
  // gesture input for enabling paid voice and budget writes.
  bool request_voice_review(bool paid_scope_approved, bool budget_scope_approved,
                            bool allow_first_budget, bool one_paid_turn = false);
  Step poll();
  // Borrow until voice and its independent STOP monitor have shut down.
  std::optional<K151VoiceHandoff> handoff();
  // Remain on the owner task; a failed release may be retried before teardown.
  bool shutdown();
  static const char* compiled_link_marker();

 private:
  bool on_owner_task() const;
  Step abort_setup(std::optional<scpswire::SetupFailure> diagnosis = std::nullopt);

  const std::atomic_bool& stop_;
  std::atomic_bool owner_{false};
  std::atomic_bool setup_input_{false};
  std::atomic_bool paid_consent_{false};
  std::atomic_bool budget_writes_{false};
  K151LcdPanel panel_{stop_};
  K151SetupLvgl view_{stop_};
  K151HeadTouchOwner touch_{owner_, stop_};
  K151LocalOwnerSetup setup_{owner_, setup_input_, stop_};
  K151ScpsUsbPort usb_{touch_, setup_, view_, stop_};
  SavedOwnerCredentials* saved_ = nullptr;
  i2c_master_bus_handle_t bus_ = nullptr;
  TaskHandle_t task_ = nullptr;
  int core_ = -1;
  uint64_t last_sample_ms_ = 0;
  uint64_t voice_review_started_ms_ = 0;
  bool owns_lvgl_ = false;
  bool board_verified_ = false;
  bool lcd_verified_ = false;
  bool handoff_taken_ = false;
  bool restored_setup_ = false;
  bool allow_first_budget_ = false;
  bool one_paid_turn_ = false;
  bool bus_release_unverified_ = false;
  Step step_ = Step::idle;
  StartupStage startup_stage_ = StartupStage::idle;
  std::optional<scpswire::SetupFailure> early_setup_failure_;
};

}  // namespace stackchan::standalone
