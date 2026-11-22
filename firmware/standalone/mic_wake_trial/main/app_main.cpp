// SPDX-License-Identifier: MIT
#include "bench_gate.hpp"
#include "board_evidence.hpp"
#include "k151_mic_wake_trial.hpp"
#include <driver/usb_serial_jtag.h>
#include <esp_chip_info.h>
#include <esp_ota_ops.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <array>
#include <atomic>
#include <cstdio>

namespace stackchan::standalone {
std::span<const uint8_t> linked_mic_trial_model();
}

namespace {
using namespace stackchan::standalone;
std::atomic_bool owner{false}, stop{false}, reader_done{false};

#ifdef STACKCHAN_K151_QUESTION_TRIAL
constexpr char kBootMarker[] = "K151_RECEIVE_ONLY_QUESTION_TRIAL_NOT_OPERATIONAL";
constexpr char kChallengeMarker[] = "WAIT_QUESTION_LOCAL_START";

void announce_question() {
  std::puts("{\"mic_trial\":\"QUESTION_NOW\",\"operating_admission\":false}");
  (void)std::fflush(stdout);
}

const char* question_result_name(K151QuestionTrialResult result) {
  switch (result) {
    case K151QuestionTrialResult::not_run: return "not_run";
    case K151QuestionTrialResult::stopped: return "stopped";
    case K151QuestionTrialResult::memory_denied: return "memory_denied";
    case K151QuestionTrialResult::prepare_failed: return "prepare_failed";
    case K151QuestionTrialResult::open_failed: return "open_failed";
    case K151QuestionTrialResult::clock_fault: return "clock_fault";
    case K151QuestionTrialResult::read_failed: return "read_failed";
    case K151QuestionTrialResult::no_endpoint: return "no_endpoint";
    case K151QuestionTrialResult::endpoint: return "endpoint";
    case K151QuestionTrialResult::release_failed: return "release_failed";
    case K151QuestionTrialResult::quiet_timeout: return "quiet_timeout";
  }
  return nullptr;
}
#else
constexpr char kBootMarker[] = "K151_RECEIVE_ONLY_WAKE_TRIAL_NOT_OPERATIONAL";
constexpr char kChallengeMarker[] = "WAIT_LOCAL_START";
#endif

void announce_listening() {
  std::puts("{\"mic_trial\":\"LISTEN_NOW\",\"operating_admission\":false}");
  (void)std::fflush(stdout);
}

void reader(void*) {
  const uint32_t nonce = esp_random();
  BenchGate gate{nonce, esp_timer_get_time() / 1000, true};
  while (!gate.stopped() && !reader_done.load()) {
    char c{};
    const int count = usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(20));
    const auto now = esp_timer_get_time() / 1000;
    if (count < 0) break;
    if (count == 1) {
      if (gate.feed(c, now)) {
        std::printf("{\"mic_trial\":\"%s\",\"nonce\":\"%08lX\",\"wait_ms\":60000}\n",
                    kChallengeMarker, static_cast<unsigned long>(nonce));
        (void)std::fflush(stdout);
      }
    } else {
      gate.tick(now);
    }
    if (gate.running()) owner = true;
  }
  stop = true;
  owner = false;
  vTaskDelete(nullptr);
}

void hold() {
  stop = true;
  owner = false;
  reader_done = true;
  std::puts("{\"mic_trial\":\"HOLD_UNTIL_RESET\",\"operating_admission\":false}");
  (void)std::fflush(stdout);
}
}

extern "C" void app_main() {
  std::puts(kBootMarker);
  esp_chip_info_t chip{};
  esp_chip_info(&chip);
  const auto* slot = esp_ota_get_running_partition();
  const bool expected_location = slot && slot->type == ESP_PARTITION_TYPE_APP &&
      slot->subtype == ESP_PARTITION_SUBTYPE_APP_OTA_1 &&
      k151::board_probe_location_allowed(slot->address, slot->size,
                                        chip.model == CHIP_ESP32S3, chip.revision);
  if (!expected_location) {
    std::puts("{\"mic_trial\":\"RUNNING_LOCATION_OR_CHIP_DENIED\"}");
    hold();
    return;
  }

  usb_serial_jtag_driver_config_t cfg{};
  cfg.rx_buffer_size = 128;
  cfg.tx_buffer_size = 1024;
  if (usb_serial_jtag_driver_install(&cfg) != ESP_OK ||
      xTaskCreate(reader, "mic_trial_stop", 4096, nullptr, 6, nullptr) != pdPASS) {
    hold();
    return;
  }
  while (!owner.load() && !stop.load()) vTaskDelay(pdMS_TO_TICKS(10));
  if (owner.load() && !stop.load()) {
    // This app has one I2S caller, using the port's exclusive RX allocation.
    // It still checks the two board chips live before opening any channel.
    const K151MicOnlyEvidence evidence{expected_location, true};
#ifdef STACKCHAN_K151_QUESTION_TRIAL
    static K151MicWakeTrial trial{announce_listening, announce_question};
#else
    static K151MicWakeTrial trial{announce_listening};
#endif
    const auto result = trial.run_embedded(owner, stop, evidence, linked_mic_trial_model());
    std::array<char, 256> report{};
    if (format_k151_mic_wake_report(result, trial.diagnostic(), trial.take_input_counts(), report) != 0)
      std::fputs(report.data(), stdout);
#ifdef STACKCHAN_K151_QUESTION_TRIAL
    const auto question = trial.question_diagnostic();
    if (const char* name = question_result_name(question.result)) {
      std::printf("{\"mic_question_trial\":\"MIC_QUESTION_TRIAL_V1\",\"result\":\"%s\","
                  "\"codec_cleanup_unverified\":%s,\"operating_admission\":false}\n",
                  name, question.codec_cleanup_unverified ? "true" : "false");
    }
#endif
  }
  hold();
}
