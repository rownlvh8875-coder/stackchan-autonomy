// SPDX-License-Identifier: MIT
// Optional LVGL view ONLY. It NEVER creates or resets a K151 LCD panel.
#pragma once

#include "setup_screen_model.hpp"
#include "k151_voice_status.hpp"
#include "owner_unlock.hpp"
#include <atomic>
#include <optional>
#include <string_view>
#include <lvgl.h>

namespace stackchan::standalone {

class K151LcdPanel;
class K151OwnerSession;

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
  // Pinned LVGL owner only, following voice approval and STOP input handoff.
  bool present_voice_status(K151VoiceStatus status);

 private:
  friend class K151ScpsUsbPort;
  friend class K151OwnerSession;
  enum class ReviewResult : uint8_t { waiting, approved, fault };
  enum class ReviewPhase : uint8_t { idle, wait_clear, wait_press, holding, wait_release, closed };
  enum class SavedSetupScreen : uint8_t { presence, restored };
  bool present_saved_setup(SavedSetupScreen screen);
  enum class UnlockScreen : uint8_t { enter, enroll, deriving };
  enum class UnlockChoice : uint8_t { waiting, confirm, cancel, fault };
  bool present_unlock(UnlockScreen screen, const OwnerCode* generated = nullptr);
  UnlockChoice poll_unlock();
  bool finish_unlock(bool restored);
  void clear_unlock();
  bool add_unlock_label(lv_obj_t* screen, const char* label, int x, int y);
  bool begin_pairing_review(uint64_t now_ms, bool lvgl_lock_held);
  ReviewResult poll_pairing_review(uint64_t now_ms, bool lvgl_lock_held);
  bool begin_voice_review(uint64_t now_ms, bool allow_first_budget, bool lvgl_lock_held,
                          bool one_paid_turn = false);
  ReviewResult poll_voice_review(uint64_t now_ms, bool lvgl_lock_held);
  void wait_for_fresh_contact(uint64_t now_ms);
  ReviewResult poll_contact(uint64_t now_ms, bool lvgl_lock_held);
  bool show_final_touch_prompt();

  const std::atomic_bool& stop_;
  K151LcdPanel* panel_ = nullptr;
  lv_obj_t* root_ = nullptr;
  lv_obj_t* title_ = nullptr;
  lv_obj_t* first_ = nullptr;
  lv_obj_t* second_ = nullptr;
  uint64_t last_review_ms_ = 0;
  uint64_t hold_since_ms_ = 0;
  ReviewPhase review_ = ReviewPhase::idle;
  bool sas_visible_ = false;
  bool voice_review_started_ = false;
  bool save_after_pairing_ = false;
  bool voice_approved_ = false;
  std::optional<K151VoiceStatus> voice_status_;
  std::optional<UnlockScreen> unlock_screen_;
  OwnerCodeInput unlock_input_;
  std::array<lv_obj_t*, 37> unlock_labels_{};
  size_t unlock_labels_count_ = 0;
  bool attempted_ = false;
};
} // namespace stackchan::standalone
