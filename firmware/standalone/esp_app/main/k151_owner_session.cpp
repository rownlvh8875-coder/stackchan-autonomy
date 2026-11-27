// SPDX-License-Identifier: MIT
#include "k151_owner_session.hpp"

#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_install_hold.hpp"
#include <esp_timer.h>
#include <sdkconfig.h>
#include <utility>

namespace stackchan::standalone {
namespace {
constexpr uint64_t kPollIntervalMs = 50;
constexpr uint64_t kVoiceReviewTimeoutMs = 30'000;
constexpr uint64_t kUnlockInputTimeoutMs = 120'000;
constexpr uint64_t kUnlockDeriveTimeoutMs = 60'000;
#if defined(CONFIG_ESP_CONSOLE_UART_DEFAULT) && !defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED)
constexpr bool kSeparateUartConsole = true;
#else
constexpr bool kSeparateUartConsole = false;
#endif
}

K151OwnerSession::K151OwnerSession() : stop_(K151DisplayStop::flag()) {}
K151OwnerSession::~K151OwnerSession() { (void)shutdown(); }

bool K151OwnerSession::on_owner_task() const {
  return task_ && task_ == xTaskGetCurrentTaskHandle() && core_ == xPortGetCoreID();
}

bool K151OwnerSession::start(bool exact_board_verified, bool physical_lcd_verified,
                             SavedOwnerCredentials* saved, OwnerUnlockPort* unlock) {
  if (task_) return false;
  startup_stage_ = StartupStage::preconditions;
  if ((saved && unlock) || stop_.load() || !exact_board_verified || !physical_lcd_verified ||
      !kSeparateUartConsole || !K151InstallHold::device_activation_allowed() ||
      lv_is_initialized()) return false;
  startup_stage_ = StartupStage::owner_task;
  task_ = xTaskGetCurrentTaskHandle();
  if (!task_) return false;
  core_ = xPortGetCoreID();
  const auto abort = [this] {
    (void)abort_setup();
    return false;
  };

  startup_stage_ = StartupStage::board_bus;
  if (!k151::open_board_bus(bus_) || stop_.load()) return abort();
  startup_stage_ = StartupStage::lvgl;
  lv_init();
  owns_lvgl_ = lv_is_initialized();
  if (!owns_lvgl_) return abort();
  startup_stage_ = StartupStage::panel;
  if (!panel_.start(bus_, true)) return abort();
  startup_stage_ = StartupStage::view;
  if (!view_.attach(panel_, physical_lcd_verified, true, true)) return abort();
  startup_stage_ = StartupStage::presence_frame;
  const bool presence = (saved || unlock)
      ? view_.present_saved_setup(K151SetupLvgl::SavedSetupScreen::presence)
      : view_.present(TouchConsentPhase::clear_for_arm, OwnerSetupPhase::hold, false, false, true);
  if (!presence) return abort();
  startup_stage_ = StartupStage::head;
  if (!touch_.attach_for_setup(bus_, exact_board_verified, true)) return abort();
  startup_stage_ = StartupStage::clock;
  const auto now_us = esp_timer_get_time();
  if (now_us < 0 || stop_.load()) return abort();
  last_sample_ms_ = static_cast<uint64_t>(now_us / 1000);
  board_verified_ = exact_board_verified;
  lcd_verified_ = physical_lcd_verified;
  unlock_ = unlock;
  saved_ = unlock ? &unlock->credentials() : saved;
  startup_stage_ = StartupStage::ready;
  step_ = Step::head_touch;
  return true;
}

bool K151OwnerSession::request_voice_review(bool paid_scope_approved, bool budget_scope_approved,
                                              bool allow_first_budget, bool one_paid_turn) {
  if (!on_owner_task() || step_ != Step::ready || !setup_.ready() || usb_.running() ||
      (saved_ && one_paid_turn) || !paid_scope_approved || !budget_scope_approved || stop_.load())
    return false;
  const auto now_us = esp_timer_get_time();
  if (now_us < 0 || static_cast<uint64_t>(now_us / 1000) < last_sample_ms_) {
    (void)abort_setup();
    return false;
  }
  const auto now = static_cast<uint64_t>(now_us / 1000);
  const bool first_budget_allowed = allow_first_budget && !restored_setup_;
  if (!view_.begin_voice_review(now, first_budget_allowed, true, one_paid_turn)) {
    (void)abort_setup();
    return false;
  }
  voice_review_started_ms_ = last_sample_ms_ = now;
  allow_first_budget_ = first_budget_allowed;
  one_paid_turn_ = one_paid_turn;
  step_ = Step::voice_review;
  return true;
}

K151OwnerSession::Step K151OwnerSession::poll() {
  using Failure = scpswire::SetupFailure;
  if (!task_) return Step::idle;
  if (!on_owner_task()) return Step::fault;
  if (step_ == Step::stopped || step_ == Step::fault) return step_;
  // The borrower must stop voice and its monitor before releasing the bus.
  if (handoff_taken_) {
    if (!stop_.load()) return step_;
    paid_consent_.store(false);
    budget_writes_.store(false);
    return Step::stopped;
  }
  if (stop_.load()) return abort_setup();
  // Do not poll head touch or USB after handoff. Voice owns further access to
  // the display STOP input, and setup timeouts no longer govern the session.
  if (step_ == Step::ready || step_ == Step::voice_ready) return step_;
  const auto now_us = esp_timer_get_time();
  if (now_us < 0) return abort_setup(Failure::clock_invalid);
  const auto now = static_cast<uint64_t>(now_us / 1000);
  if (now < last_sample_ms_) return abort_setup(Failure::clock_backwards);
  if (now - last_sample_ms_ > HeadTouchConsent::kMaxSampleGapMs)
    return abort_setup(Failure::sample_gap);
  if (now - last_sample_ms_ < kPollIntervalMs) return step_;
  last_sample_ms_ = now;

  if (step_ == Step::voice_review) {
    if (!setup_.ready() || now - voice_review_started_ms_ >= kVoiceReviewTimeoutMs)
      return abort_setup();
    const auto review = view_.poll_voice_review(now, true);
    if (review == K151SetupLvgl::ReviewResult::fault || stop_.load()) return abort_setup();
    if (review == K151SetupLvgl::ReviewResult::approved) {
      paid_consent_.store(true);
      budget_writes_.store(true);
      step_ = Step::voice_ready;
    }
    return step_;
  }

  const auto event = touch_.poll_once(now);
  if (stop_.load()) return abort_setup();
  if (event == TouchConsentEvent::invalidated)
    return abort_setup(touch_.last_read_failed() ? Failure::sensor_read : Failure::head_input);
  if (step_ == Step::unlock_input || step_ == Step::unlock_deriving) return poll_unlock(now);
  if (step_ == Step::head_touch && event == TouchConsentEvent::owner_window_open) {
    if (unlock_) {
      const auto present = unlock_->inspect();
      if (present == ReadCode::failure || stop_.load()) return abort_setup();
      if (present == ReadCode::found) {
        if (!view_.present_unlock(K151SetupLvgl::UnlockScreen::enter)) return abort_setup();
        unlock_started_ms_ = now;
        return step_ = Step::unlock_input;
      }
    } else if (saved_) {
      setup_input_.store(true);
      const auto restored = setup_.restore_saved(*saved_, now);
      if (restored == SavedSetupLoad::unusable) return abort_setup();
      if (restored == SavedSetupLoad::restored) {
        if (!view_.present_saved_setup(K151SetupLvgl::SavedSetupScreen::restored))
          return abort_setup();
        restored_setup_ = true;
        return step_ = Step::ready;
      }
      setup_input_.store(false);
    }
    // Admission was verified before start. The USB port independently checks
    // the current head window, shared latches, LCD and unclaimed driver.
    if (!usb_.start(now, board_verified_, lcd_verified_, kSeparateUartConsole, true))
      return abort_setup(Failure::usb_start);
    setup_input_.store(true);
    if (!view_.present(TouchConsentPhase::owner_window, OwnerSetupPhase::hold, true, false, true))
      return abort_setup(Failure::pairing_display);
    step_ = Step::pairing;
  } else if (step_ == Step::pairing) {
    if (!usb_.poll_once(now, true)) return abort_setup();
    if (event == TouchConsentEvent::final_confirmed) {
      if (!usb_.finalize_after_touch(now) || !setup_.ready() ||
          !view_.present(TouchConsentPhase::consumed, setup_.phase(), true, false, true) ||
          !usb_.close_completed_transport() || !setup_.ready()) return abort_setup();
      if (unlock_) {
        std::array<char, kOwnerCodeLength> generated{};
        const OwnerCode code(generated);
        const bool ok = unlock_->generate(generated) &&
            view_.present_unlock(K151SetupLvgl::UnlockScreen::enroll, &code);
        wipe_secret(reinterpret_cast<unsigned char*>(generated.data()), generated.size());
        if (!ok) return abort_setup();
        unlock_enrolling_ = true;
        unlock_started_ms_ = now;
        return step_ = Step::unlock_input;
      }
      step_ = Step::ready;
    }
  }
  return step_;
}

K151OwnerSession::Step K151OwnerSession::poll_unlock(uint64_t now) {
  using Choice = K151SetupLvgl::UnlockChoice;
  const bool deriving = step_ == Step::unlock_deriving;
  if (!owner_.load() || now - unlock_started_ms_ >=
                           (deriving ? kUnlockDeriveTimeoutMs : kUnlockInputTimeoutMs))
    return abort_setup();
  const auto choice = view_.poll_unlock();
  if (choice == Choice::cancel) return step_ = shutdown() ? Step::stopped : Step::fault;
  if (choice == Choice::fault || stop_.load()) return abort_setup();
  if (!deriving) {
    if (choice != Choice::confirm) return step_;
    if (!unlock_->begin(view_.unlock_input_.code()) ||
        !view_.present_unlock(K151SetupLvgl::UnlockScreen::deriving)) return abort_setup();
    unlock_started_ms_ = now;
    return step_ = Step::unlock_deriving;
  }
  const auto state = unlock_->state();
  if (state == OwnerUnlockPort::State::deriving) return step_;
  if (state != OwnerUnlockPort::State::ready) return abort_setup();
  if (!unlock_enrolling_) {
    setup_input_.store(true);
    if (setup_.restore_saved(*saved_, now) != SavedSetupLoad::restored) return abort_setup();
    restored_setup_ = true;
  }
  if (!setup_.ready() || !view_.finish_unlock(restored_setup_)) return abort_setup();
  return step_ = Step::ready;
}

std::optional<K151VoiceHandoff> K151OwnerSession::handoff() {
  if (!on_owner_task() || handoff_taken_ || step_ != Step::voice_ready || !setup_.ready() ||
      !paid_consent_.load() || !budget_writes_.load() || stop_.load())
    return std::nullopt;
  handoff_taken_ = true;
  return K151VoiceHandoff{setup_, panel_, view_, bus_, paid_consent_, budget_writes_,
                         allow_first_budget_, one_paid_turn_,
                         restored_setup_ ? nullptr : saved_};
}

bool K151OwnerSession::shutdown() {
  if (!task_) return true;
  if (!on_owner_task()) return false;
  step_ = Step::stopped;
  paid_consent_.store(false);
  budget_writes_.store(false);
  setup_input_.store(false);
  if (unlock_) unlock_->cancel();
  unlock_ = nullptr;
  saved_ = nullptr;
  setup_.stop();
  if (!usb_.shutdown()) return false;
  const bool head_released = touch_.detach();
  const bool panel_released = !owns_lvgl_ || (view_.detach(true) && panel_.shutdown());
  if (panel_released && owns_lvgl_) {
    lv_deinit();
    owns_lvgl_ = false;
  }
  if (!head_released || !panel_released) return false;
  // IDF can report pin-deinit failure after releasing the bus wrapper.
  // Discard the ambiguous pointer and keep the cleanup failure latched.
  if (bus_ && i2c_del_master_bus(std::exchange(bus_, nullptr)) != ESP_OK)
    bus_release_unverified_ = true;
  return !bus_release_unverified_;
}

K151OwnerSession::Step K151OwnerSession::abort_setup(
    std::optional<scpswire::SetupFailure> diagnosis) {
  const bool early = step_ == Step::head_touch;
  const bool released = shutdown();
  const bool stopped = stop_.load();
  if (early && !stopped) early_setup_failure_ = diagnosis;
  step_ = stopped && released ? Step::stopped : Step::fault;
  return step_;
}

const char* K151OwnerSession::compiled_link_marker() {
  auto volatile start = &K151OwnerSession::start;
  auto volatile poll = &K151OwnerSession::poll;
  auto volatile review = &K151OwnerSession::request_voice_review;
  auto volatile handoff = &K151OwnerSession::handoff;
  (void)start;
  (void)poll;
  (void)review;
  (void)handoff;
  return "K151 local setup owner task linked; NOT STARTED";
}

}  // namespace stackchan::standalone
