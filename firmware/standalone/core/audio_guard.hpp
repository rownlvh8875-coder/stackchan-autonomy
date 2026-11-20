// SPDX-License-Identifier: MIT
// Exclusive mic/amp lifecycle for future K151 hardware adapter. No GPIO/I2S.
#pragma once

#include <functional>
#include <utility>

namespace stackchan::standalone {

enum class AudioState { cold, idle, capture, playback, stopped, fault };

// These callbacks must be small and bounded. A caller's STOP latch is set
// before waiting on potentially slow drivers; no cloud or servo calls here.
struct AudioHooks {
  std::function<bool()> mic_off;
  std::function<bool()> amp_off;
  std::function<bool()> init_peripherals;
  std::function<bool()> mic_on;
  std::function<bool()> mic_flush;
  std::function<bool()> amp_low_volume_on;
  std::function<bool()> playback_drain;
};

class AudioGuard {
 public:
  explicit AudioGuard(AudioHooks hooks) : hooks_(std::move(hooks)) {}
  AudioState state() const { return state_; }
  bool stopped() const { return stop_latched_; }

  bool initialize(bool local_configuration_ready, bool hardware_identity_confirmed) {
    if (state_ != AudioState::cold || !local_configuration_ready ||
        !hardware_identity_confirmed) return false;
    // Force outputs off BEFORE powering or configuring audio peripherals.
    const bool mic_quiet = call(hooks_.mic_off);
    const bool amp_quiet = call(hooks_.amp_off);
    if (!mic_quiet || !amp_quiet || !call(hooks_.init_peripherals)) return fault();
    state_ = AudioState::idle;
    return true;
  }

  bool capture_begin() {
    if (state_ != AudioState::idle || stop_latched_) return false;
    if (!call(hooks_.amp_off) || !call(hooks_.mic_flush) ||
        !call(hooks_.mic_on)) return fault();
    state_ = AudioState::capture;
    return true;
  }
  bool capture_end() {
    if (state_ != AudioState::capture || stop_latched_) return false;
    if (!call(hooks_.mic_off)) return fault();
    state_ = AudioState::idle;
    return true;
  }
  bool playback_begin() {
    if (state_ != AudioState::idle || stop_latched_) return false;
    if (!call(hooks_.mic_off) || !call(hooks_.amp_low_volume_on)) return fault();
    state_ = AudioState::playback;
    return true;
  }
  bool playback_end() {
    if (state_ != AudioState::playback || stop_latched_) return false;
    // Drain final I2S frames BEFORE power-down and cool-down.
    const bool drained = call(hooks_.playback_drain);
    const bool quiet = call(hooks_.amp_off);
    if (!drained || !quiet) return fault();
    state_ = AudioState::idle;
    return true;
  }
  void stop() {
    stop_latched_ = true;  // Set latch before any potentially slow callback.
    // Never downgrade a previously faulted driver to a resumable STOP state.
    const bool already_faulted = state_ == AudioState::fault;
    state_ = already_faulted ? AudioState::fault : AudioState::stopped;
    // Any uncertainty is still STOPPED/FAULT, never a clean idle retry.
    const bool mic_quiet = call(hooks_.mic_off);
    const bool amp_quiet = call(hooks_.amp_off);
    const bool cleared = call(hooks_.mic_flush);
    if (!mic_quiet || !amp_quiet || !cleared) { state_ = AudioState::fault; }
  }
  bool manual_resume() {
    if (state_ != AudioState::stopped || !stop_latched_) return false;
    const bool mic_quiet = call(hooks_.mic_off);
    const bool amp_quiet = call(hooks_.amp_off);
    if (!mic_quiet || !amp_quiet || !call(hooks_.mic_flush)) return fault();
    stop_latched_ = false;
    state_ = AudioState::idle;
    return true;
  }

 private:
  static bool call(const std::function<bool()>& hook) {
    return hook && hook();
  }
  bool fault() {
    stop_latched_ = true;
    state_ = AudioState::fault;
    // Best effort mute; failure is not reclassified as success.
    if (hooks_.mic_off) (void)hooks_.mic_off();
    if (hooks_.amp_off) (void)hooks_.amp_off();
    return false;
  }
  AudioHooks hooks_;
  AudioState state_ = AudioState::cold;
  bool stop_latched_ = false;
};

}  // namespace stackchan::standalone
