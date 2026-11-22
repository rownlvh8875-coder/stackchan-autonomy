// SPDX-License-Identifier: MIT
#include "board_probe_sdk.hpp"
#include "k151_mic_wake_trial.hpp"
#ifdef STACKCHAN_K151_SILENT_TX_PROBE
#include "k151_silent_tx_probe.hpp"
#endif
#include <cassert>
#include <chrono>
#include <cstdio>
#include <string_view>
#include <thread>
#include <utility>

using namespace stackchan::standalone;

namespace stackchan::standalone {
std::span<const uint8_t> linked_mic_trial_model() {
  static constexpr uint8_t pack[]{1, 2};
  return pack;
}
}

namespace {
std::string_view scenario;
std::thread reader_task;
std::atomic_bool listening{false};
int sessions = 0;
}

void esp_chip_info(esp_chip_info_t* chip) {
  chip->model = scenario == "chip" ? 1 : 9;
  chip->revision = scenario == "revision" ? 3 : 2;
}
const esp_partition_t* esp_ota_get_running_partition() {
  static esp_partition_t slot{scenario == "slot" ? 0x20000u : 0x510000u,
                              scenario == "size" ? 0x4e0000u : 0x4f0000u,
                              scenario == "type" ? 1 : ESP_PARTITION_TYPE_APP,
                              scenario == "subtype" ? 16 : ESP_PARTITION_SUBTYPE_APP_OTA_1};
  return scenario == "missing" ? nullptr : &slot;
}
uint32_t esp_random() { return 1; }
int64_t esp_timer_get_time() {
  static const auto start = std::chrono::steady_clock::now();
  return std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now() - start).count();
}
int usb_serial_jtag_read_bytes(void* out, size_t size, unsigned timeout) {
  assert(size == 1 && timeout == 20);
  const std::string_view command = scenario == "bad_nonce" ? "HELLO\nSTART 00000002\n" :
      scenario == "stop_before" ? "STOP\n" : scenario == "no_hello" ? "START 00000001\n" :
      "HELLO\nSTART 00000001\n";
  static size_t pos = 0;
  if (pos < command.size()) {
    *static_cast<char*>(out) = command[pos++];
    return 1;
  }
  if (scenario == "stop_during" && listening.load()) {
    constexpr std::string_view stop = "STOP\n";
    const auto offset = pos - command.size();
    if (offset < stop.size()) {
      *static_cast<char*>(out) = stop[offset];
      ++pos;
      return 1;
    }
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(1));
  return 0;
}
int usb_serial_jtag_driver_install(const usb_serial_jtag_driver_config_t*) {
  assert(scenario == "detect" || scenario == "stop_during" || scenario == "quiet_timeout" ||
         scenario == "bad_nonce" || scenario == "stop_before" || scenario == "no_hello" ||
         scenario == "usb_error" || scenario == "task_error");
  return scenario == "usb_error" ? -1 : ESP_OK;
}
int xTaskCreate(void (*entry)(void*), const char*, unsigned, void* arg, unsigned, void*) {
  if (scenario == "task_error") return 0;
  reader_task = std::thread(entry, arg);
  return pdPASS;
}
void vTaskDelete(void*) {}
void vTaskDelay(unsigned) { std::this_thread::sleep_for(std::chrono::milliseconds(1)); }

#if defined(STACKCHAN_K151_SILENT_TX_PROBE)
K151SilentTxResult stackchan::standalone::run_k151_silent_tx_probe(
    const std::atomic_bool& owner, const std::atomic_bool& stop) {
  assert(owner.load() && !stop.load() && ++sessions == 1);
  if (scenario == "stop_during") {
    listening = true;
    for (int i = 0; !stop.load() && i < 500; ++i) vTaskDelay(1);
    assert(stop.load());
    return K151SilentTxResult::stopped;
  }
  assert(scenario == "detect");
  return K151SilentTxResult::observed;
}
#elif defined(STACKCHAN_K151_QUESTION_ONLY)
K151QuestionTrialDiagnostic stackchan::standalone::run_k151_question_trial(
    const std::atomic_bool& owner, const std::atomic_bool& stop,
    const K151MicOnlyEvidence& evidence, void (*cue)(), K151QuestionTrialMode mode) {
  assert(owner.load() && !stop.load() && evidence.verified() && cue);
  assert(++sessions == 1 && mode == K151QuestionTrialMode::standard);
  if (scenario == "quiet_timeout") return {K151QuestionTrialResult::quiet_timeout};
  cue();
  if (scenario == "stop_during") {
    listening = true;
    for (int i = 0; !stop.load() && i < 500; ++i) vTaskDelay(1);
    assert(stop.load());
    return {K151QuestionTrialResult::stopped};
  }
  assert(scenario == "detect");
  return {K151QuestionTrialResult::endpoint};
}
#else
K151MicWakeTrialResult K151MicWakeTrial::run_embedded(
    const std::atomic_bool& owner, const std::atomic_bool& stop,
    const K151MicOnlyEvidence& evidence, std::span<const uint8_t> pack) {
  assert((scenario == "detect" || scenario == "stop_during" || scenario == "quiet_timeout") &&
         owner.load() && !stop.load());
  assert(evidence.verified() && pack.size() == 2 && pack.front() == 1);
  assert(++sessions == 1 && on_listen_);
#ifdef STACKCHAN_K151_WAKE_ONLY_CONTROL
  assert(on_question_ && question_mode_ == K151QuestionTrialMode::wake_only_control);
#elif defined(STACKCHAN_K151_QUESTION_TRIAL)
  assert(on_question_ && question_mode_ == K151QuestionTrialMode::standard);
#else
  assert(!on_question_);
#endif
  on_listen_();
  if (scenario == "stop_during") {
    listening = true;
    for (int i = 0; !stop.load() && i < 500; ++i) vTaskDelay(1);
    assert(stop.load());
    diagnostic_.stage = K151MicWakeStage::wake_input;
    return K151MicWakeTrialResult::stopped;
  }
  diagnostic_.stage = K151MicWakeStage::complete;
  input_counts_ = {4, 0, 0};
  if (scenario == "quiet_timeout") {
    assert(on_question_);
    question_diagnostic_.result = K151QuestionTrialResult::quiet_timeout;
  } else if (on_question_) {
    on_question_();
    question_diagnostic_.result = question_mode_ == K151QuestionTrialMode::wake_only_control
        ? K151QuestionTrialResult::no_endpoint : K151QuestionTrialResult::endpoint;
  }
  return K151MicWakeTrialResult::detected;
}

std::optional<K151MicWakeInputCounts> K151MicWakeTrial::take_input_counts() {
  return std::exchange(input_counts_, std::nullopt);
}

size_t stackchan::standalone::format_k151_mic_wake_report(
    K151MicWakeTrialResult result, K151MicWakeDiagnostic diagnostic,
    std::optional<K151MicWakeInputCounts> counts,
    std::span<char> output) {
  if (result == K151MicWakeTrialResult::stopped) {
    assert(!counts && diagnostic.stage == K151MicWakeStage::wake_input);
    return std::snprintf(output.data(), output.size(),
        "{\"mic_wake_trial\":\"MIC_WAKE_TRIAL_V4\",\"result\":\"stopped\","
        "\"operating_admission\":false,\"stage\":\"wake_input\","
        "\"codec_cleanup_unverified\":false}\n");
  }
  assert(result == K151MicWakeTrialResult::detected && counts && counts->frames_read == 4);
  assert(diagnostic.stage == K151MicWakeStage::complete);
  return std::snprintf(output.data(), output.size(),
      "{\"mic_wake_trial\":\"MIC_WAKE_TRIAL_V4\",\"result\":\"detected\","
      "\"operating_admission\":false,\"stage\":\"complete\",\"codec_cleanup_unverified\":false,"
      "\"frames_read\":4,\"all_zero_frames\":0,"
      "\"full_scale_samples\":0}\n");
}

#endif

extern "C" void app_main();
int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  app_main();
  if (reader_task.joinable()) reader_task.join();
  assert(sessions ==
         (scenario == "detect" || scenario == "stop_during" || scenario == "quiet_timeout" ? 1 : 0));
}
