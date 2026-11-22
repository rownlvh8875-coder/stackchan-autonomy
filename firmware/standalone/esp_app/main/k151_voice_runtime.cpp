// SPDX-License-Identifier: MIT
#include "k151_voice_runtime.hpp"

#include "k151_audio_hold_hooks.hpp"
#include "k151_mic_wake_memory.hpp"
#include "k151_question_pcm.hpp"
#include <ctime>
#include <esp_timer.h>
#include <utility>

namespace stackchan::standalone {
namespace {
bool turn_psram_available() {
  multi_heap_info_t heap{};
  heap_caps_get_info(&heap, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  return heap.total_free_bytes >= kRequiredPsramFree &&
         heap.largest_free_block >= kRequiredLargestPsramBlock &&
         heap.largest_free_block <= heap.total_free_bytes;
}
} // namespace

K151VoiceRuntime::K151VoiceRuntime(
    PersistentGuard& ledger, K151WifiTimePort& network,
    const std::atomic_bool& local_owner, const std::atomic_bool& paid_consent,
    const std::atomic_bool& budget_writes, const std::atomic_bool& stop,
    K151AudioBoardEvidence evidence, i2c_master_bus_handle_t board_bus,
    std::function<bool(K151VoiceStatus)> show_status)
    : ledger_(ledger), network_(network),
      owner_(local_owner), consent_(paid_consent), budget_writes_(budget_writes), stop_(stop),
      evidence_(evidence), board_bus_(board_bus),
      show_status_(std::move(show_status)),
      audio_(k151_audio_hooks(codec_, owner_, stop_, consent_, evidence_, board_bus_)),
      mic_(codec_), sink_(codec_, stop, paid_consent, local_owner),
      speaker_(audio_, sink_, stop, paid_consent, busy_,
               []() -> std::optional<uint64_t> {
                 const auto now_us = esp_timer_get_time();
                 if (now_us < 0) return std::nullopt;
                 return static_cast<uint64_t>(now_us / 1000);
               }),
      api_(network, paid_consent, local_owner, stop),
      dialog_(session_, ledger, api_.api(), speaker_, stop, paid_consent,
              network.admission_flag(), busy_),
      bridge_(mic_, stop, busy_),
      turn_(session_, ledger, dialog_, bridge_, audio_, stop, paid_consent, busy_,
            k151_allocate_question_pcm),
      wake_(session_, dialog_, mic_, audio_, model_),
      loop_(session_, ledger, wake_, turn_, audio_, model_, stop, paid_consent, busy_,
            [this] { return live_ready(); }) {}

K151VoiceRuntime::~K151VoiceRuntime() { stop(); }

bool K151VoiceRuntime::authorized() const {
  return owner_.load() && consent_.load() && budget_writes_.load() && !stop_.load();
}

bool K151VoiceRuntime::admission_ready() const {
  return authorized() && codec_.playback_available() && !audio_.stopped() &&
         ledger_.has_budget() && !ledger_.fatal() &&
         network_.live_network_ready() && k151_mic_wake_internal_heap_available() &&
         authorized();
}

bool K151VoiceRuntime::live_ready() const {
  // Check whole-turn capacity before opening the wake or question microphone.
  // After capture starts, allocations already consume some of that capacity.
  // Keep checking the internal heap floor at the actual turn boundaries.
  const bool before_capture = audio_.state() == AudioState::idle &&
      (session_.state() == State::wake_wait || session_.state() == State::ready ||
       session_.state() == State::cooldown);
  if (phase_ != Phase::operating || (before_capture && !turn_psram_available()) ||
      !admission_ready()) return false;
  switch (session_.state()) {
    case State::transcribe: return publish_status(K151VoiceStatus::transcribing);
    case State::think: return publish_status(K151VoiceStatus::generating);
    case State::synthesize: return publish_status(K151VoiceStatus::synthesizing);
    case State::play: return publish_status(K151VoiceStatus::playing);
    default: return true;
  }
}

bool K151VoiceRuntime::publish_status(K151VoiceStatus status) const {
  return authorized() && (!show_status_ || show_status_(status)) && authorized();
}

bool K151VoiceRuntime::start(VoiceModelConfig models, std::span<const uint8_t> model_pack) {
  if (phase_ != Phase::cold || !K151CodecPort::playback_enabled_by_build() ||
      !evidence_.verified() || !K151CodecPort::is_registered_board_bus(board_bus_) ||
      model_pack.empty() || !models.valid() ||
      !ledger_.has_budget() || ledger_.fatal() || !network_.active() || !authorized())
    return false;
  models_ = std::move(models);
  model_pack_ = model_pack;
  phase_ = Phase::waiting_network;
  return true;
}

bool K151VoiceRuntime::start_voice() {
  if (!k151_mic_wake_internal_heap_available() || !turn_psram_available() ||
      !network_.live_network_ready() || !audio_.initialize(authorized(), evidence_.verified()) ||
      !admission_ready()) return false;
  // Use the same checked read-only pack as the receive-only trial, so the
  // factory partition layout does not need a separate model partition.
  if (!model_.prepare_embedded(owner_, stop_, std::exchange(model_pack_, {}))) return false;
  const auto now_us = esp_timer_get_time();
  if (now_us < 0 || !turn_psram_available() || !model_.ready() || !admission_ready()) return false;
  session_.boot(static_cast<uint64_t>(now_us / 1000), true, model_.ready());
  session_.cloud_enable(true); // This local start already checked paid consent.
  phase_ = Phase::operating;
  return true;
}

NativeVoiceStep K151VoiceRuntime::poll() {
  if (phase_ == Phase::cold || phase_ == Phase::stopped) return NativeVoiceStep::stopped;
  if (authorized() && network_.poll(stop_) && authorized()) {
    if (phase_ == Phase::waiting_network) {
      if (!network_.live_network_ready()) return NativeVoiceStep::waiting_network;
      if (!start_voice()) {
        stop();
        return NativeVoiceStep::stopped;
      }
    }
    const auto now_us = esp_timer_get_time();
    const auto unix_time = std::time(nullptr);
    if (now_us >= 0 && unix_time >= 0) {
      const auto step = loop_.poll(static_cast<uint64_t>(now_us / 1000),
                                  static_cast<uint64_t>(unix_time), models_);
      bool shown = false;
      switch (step) {
        case NativeVoiceStep::listening: shown = publish_status(K151VoiceStatus::listening); break;
        case NativeVoiceStep::questioning: shown = publish_status(K151VoiceStatus::question); break;
        case NativeVoiceStep::answered:
        case NativeVoiceStep::cooldown: shown = publish_status(K151VoiceStatus::returning); break;
        case NativeVoiceStep::trial_standby: shown = publish_status(K151VoiceStatus::trial_finished); break;
        default: break;
      }
      if (shown) return step;
    }
  }
  stop();
  return NativeVoiceStep::stopped;
}

void K151VoiceRuntime::stop() {
  if (phase_ == Phase::cold || phase_ == Phase::stopped) return;
  phase_ = Phase::stopped;
  model_pack_ = {};
  session_.cloud_enable(false);
  if (audio_.state() != AudioState::cold) {
    (void)loop_.cancel();
    (void)codec_.shutdown();
  }
  model_.close();
  (void)network_.shutdown();
}

const char* K151VoiceRuntime::compiled_link_marker() {
  // Keep the call graph in the Xtensa ELF without starting any ports.
  auto volatile start = &K151VoiceRuntime::start;
  auto volatile poll = &K151VoiceRuntime::poll;
  (void)start;
  (void)poll;
  return "K151 native voice owner loop linked; NOT STARTED";
}
} // namespace stackchan::standalone
