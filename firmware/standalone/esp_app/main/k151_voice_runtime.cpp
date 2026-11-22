// SPDX-License-Identifier: MIT
#include "k151_voice_runtime.hpp"

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
    PersistentGuard& ledger, K151CodecPort& codec, AudioGuard& audio,
    K151WifiTimePort& network, const std::atomic_bool& local_owner,
    const std::atomic_bool& paid_consent, const std::atomic_bool& stop)
    : ledger_(ledger), codec_(codec), audio_(audio), network_(network),
      owner_(local_owner), consent_(paid_consent), stop_(stop),
      mic_(codec), sink_(codec, stop, paid_consent, local_owner),
      speaker_(audio, sink_, stop, paid_consent, busy_,
               []() -> std::optional<uint64_t> {
                 const auto now_us = esp_timer_get_time();
                 if (now_us < 0) return std::nullopt;
                 return static_cast<uint64_t>(now_us / 1000);
               }),
      api_(network, paid_consent, local_owner, stop),
      dialog_(session_, ledger, api_.api(), speaker_, stop, paid_consent,
              network.admission_flag(), busy_),
      bridge_(mic_, stop, busy_),
      turn_(session_, ledger, dialog_, bridge_, audio, stop, paid_consent, busy_,
            k151_allocate_question_pcm),
      wake_(session_, dialog_, mic_, audio, model_),
      loop_(session_, ledger, wake_, turn_, audio, model_, stop, paid_consent, busy_,
            [this] { return live_ready(); }) {}

K151VoiceRuntime::~K151VoiceRuntime() { stop(); }

bool K151VoiceRuntime::admission_ready() const {
  return owner_.load() && consent_.load() && !stop_.load() &&
         codec_.playback_available() && !audio_.stopped() &&
         ledger_.has_budget() && !ledger_.fatal() &&
         network_.live_network_ready() && k151_mic_wake_internal_heap_available() &&
         owner_.load() && consent_.load() && !stop_.load();
}

bool K151VoiceRuntime::live_ready() const {
  // Check whole-turn capacity before opening the wake or question microphone.
  // After capture starts, allocations already consume some of that capacity.
  // Keep checking the internal heap floor at the actual turn boundaries.
  const bool before_capture = audio_.state() == AudioState::idle &&
      (session_.state() == State::wake_wait || session_.state() == State::ready ||
       session_.state() == State::cooldown);
  return active_ && (!before_capture || turn_psram_available()) && admission_ready();
}

bool K151VoiceRuntime::start(VoiceModelConfig models, std::span<const uint8_t> model_pack) {
  if (attempted_ || model_pack.empty() || !models.valid() || audio_.state() != AudioState::idle ||
      !admission_ready() || !turn_psram_available()) return false;
  attempted_ = active_ = true;
  // Use the same checked read-only pack as the receive-only trial, so the
  // factory partition layout does not need a separate model partition.
  const bool prepared = model_.prepare_embedded(owner_, stop_, model_pack);
  const auto now_us = esp_timer_get_time();
  if (!prepared || now_us < 0 || !turn_psram_available() ||
      !admission_ready() || !model_.ready()) {
    stop();
    return false;
  }
  models_ = std::move(models);
  session_.boot(static_cast<uint64_t>(now_us / 1000), true, true);
  session_.cloud_enable(true); // This local start already checked paid consent.
  return true;
}

NativeVoiceStep K151VoiceRuntime::poll() {
  if (!active_) return NativeVoiceStep::stopped;
  if (!stop_.load() && owner_.load() && consent_.load() && network_.poll(stop_)) {
    const auto now_us = esp_timer_get_time();
    const auto unix_time = std::time(nullptr);
    if (now_us >= 0 && unix_time >= 0) {
      const auto step = loop_.poll(static_cast<uint64_t>(now_us / 1000),
                                  static_cast<uint64_t>(unix_time), models_);
      if (step != NativeVoiceStep::stopped) return step;
    }
  }
  stop();
  return NativeVoiceStep::stopped;
}

void K151VoiceRuntime::stop() {
  if (!active_) return;
  active_ = false;
  session_.cloud_enable(false);
  (void)loop_.cancel();
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
