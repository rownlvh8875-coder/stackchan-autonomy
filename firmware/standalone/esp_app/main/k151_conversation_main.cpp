// SPDX-License-Identifier: MIT
// The separate K151 conversation build. The default HOLD uses app_main.cpp.
#include "k151_conversation_owner.hpp"
#include "k151_conversation_policy.hpp"
#include "audio_wipe.hpp"

#include <esp_chip_info.h>
#include <esp_flash.h>
#include <esp_flash_encrypt.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <esp_ota_ops.h>
#include <esp_partition.h>
#include <esp_psram.h>
#include <esp_secure_boot.h>
#include <psa/crypto.h>

#ifdef STACKCHAN_K151_CONVERSATION_SETUP_PROBE
#include <cstdio>
#include <driver/usb_serial_jtag.h>
#else
extern const std::uint8_t model_start[] asm("_binary_srmodels_bin_start");
extern const std::uint8_t model_end[] asm("_binary_srmodels_bin_end");
#endif

namespace stackchan::standalone {
namespace {
constexpr char kTag[] = "SC_K151_BOOT";
bool armed = false; // Only the pinned app task changes or uses this gate.

K151ConversationBootFacts observe_boot() {
  K151ConversationBootFacts facts;
  esp_chip_info_t chip{};
  esp_chip_info(&chip);
  facts.esp32s3 = chip.model == CHIP_ESP32S3;
  facts.chip_revision = chip.revision;
  if (!facts.esp32s3 || facts.chip_revision != 2) return facts;
  std::array<std::uint8_t, 6> mac{};
  std::size_t written = 0;
  const bool identity_read = esp_efuse_mac_get_default(mac.data()) == ESP_OK &&
      std::ranges::any_of(mac, [](auto value) { return value != 0; }) &&
      psa_crypto_init() == PSA_SUCCESS &&
      psa_hash_compute(PSA_ALG_SHA_256, mac.data(), mac.size(), facts.factory_identity_sha256.data(),
                       facts.factory_identity_sha256.size(), &written) == PSA_SUCCESS &&
      written == facts.factory_identity_sha256.size();
  wipe_audio_bytes(mac);
  if (!identity_read) {
    facts.factory_identity_sha256.fill(0);
    return facts;
  }
  const auto* app = esp_ota_get_running_partition();
  if (app) {
    facts.ota1 = app->type == ESP_PARTITION_TYPE_APP &&
                 app->subtype == ESP_PARTITION_SUBTYPE_APP_OTA_1;
    facts.slot_offset = app->address;
    facts.slot_bytes = app->size;
  }
  const auto* nvs = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                             ESP_PARTITION_SUBTYPE_DATA_NVS, "nvs");
  if (nvs) {
    facts.nvs_offset = nvs->address;
    facts.nvs_bytes = nvs->size;
  }
  facts.psram_ready = esp_psram_is_initialized();
  facts.security_matches = nvs && !nvs->encrypted && !esp_flash_encryption_enabled() &&
                           !esp_secure_boot_enabled();
  if (esp_flash_get_physical_size(esp_flash_default_chip, &facts.flash_bytes) != ESP_OK)
    facts.flash_bytes = 0;
  return facts;
}

#ifdef STACKCHAN_K151_CONVERSATION_SETUP_PROBE
void report_setup_startup(K151ConversationBootStage boot, K151OwnerSession::StartupStage setup,
                          bool released) {
  // Setup has finished and released its resources. The probe only transmits a
  // fixed-size verdict and never accepts a host command or a setup gesture.
  usb_serial_jtag_driver_config_t config{};
  config.rx_buffer_size = 128;
  config.tx_buffer_size = 256;
  if (usb_serial_jtag_is_driver_installed() || usb_serial_jtag_driver_install(&config) != ESP_OK)
    return;
  char line[96];
  const int size = std::snprintf(line, sizeof(line), "K151_SETUP_STARTUP_PROBE_V1 %u %u %u\n",
                                 unsigned(boot), unsigned(setup), unsigned(released));
  if (size > 0 && size < int(sizeof(line))) {
    for (unsigned repeat = 0; repeat < 40; ++repeat) {
      (void)usb_serial_jtag_write_bytes(line, size, pdMS_TO_TICKS(25));
      vTaskDelay(pdMS_TO_TICKS(250));
    }
    (void)usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(25));
  }
  (void)usb_serial_jtag_driver_uninstall();
}
#else
bool run_conversation(const K151AdmittedConversation& approval) {
  const auto bytes = reinterpret_cast<std::uintptr_t>(model_end) -
                     reinterpret_cast<std::uintptr_t>(model_start);
  const std::span<const std::uint8_t> pack(model_start, bytes);
  auto& owner = K151ConversationOwner::instance();
  if (!owner.start(approval.audio, approval.physical_lcd_verified)) {
    (void)owner.shutdown();
    return false;
  }

  using Phase = K151ConversationOwner::Phase;
  for (;;) {
    const auto progress = owner.poll();
    if (progress.phase == Phase::cloud_off) {
      const auto mode = approval.mode == K151ConversationBuildMode::one_paid_turn
                        ? K151VoiceMode::one_paid_turn : K151VoiceMode::continuous;
      if (!owner.request_voice({"gpt-transcribe", "gpt-6-luna", std::string(kRealtimeSpeechModel),
                                "marin"}, pack, approval.paid_scope_approved,
                               approval.budget_scope_approved, approval.allow_first_budget, mode)) {
        ESP_LOGE(kTag, "K151 local review could not start");
        break;
      }
    } else if (progress.phase == Phase::trial_complete || progress.phase == Phase::stopped ||
               progress.phase == Phase::fault) {
      if (progress.phase == Phase::fault) ESP_LOGE(kTag, "K151 operating loop stopped on fault");
      break;
    }
    // One tick at 1 kHz. No delay replaces the existing capture deadlines or
    // the independent GPIO STOP monitor during synchronous network/playback.
    vTaskDelay(1);
  }
  return owner.shutdown();
}
#endif
} // namespace

bool k151_conversation_boot_armed() { return armed; }

} // namespace stackchan::standalone

extern "C" void app_main() {
  using namespace stackchan::standalone;
#if defined(STACKCHAN_K151_CONVERSATION_SETUP_PROBE)
  const auto& policy = k151_local_conversation_policy();
  const auto facts = local_conversation_scope_complete(policy) ? observe_boot()
                                                              : K151ConversationBootFacts{};
  const auto boot = conversation_boot_stage(policy, facts);
  const auto approval = admit_conversation_boot(policy, facts);
  auto setup_stage = K151OwnerSession::StartupStage::idle;
  bool released = true;
  if (approval) {
    static K151OwnerSession setup;
    armed = true;
    (void)setup.start(approval->audio.exact_board_verified, approval->physical_lcd_verified);
    setup_stage = setup.startup_stage();
    released = setup.shutdown();
    armed = false;
  }
  report_setup_startup(boot, setup_stage, released);
  if (!released) for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
#else
#ifdef STACKCHAN_K151_PRIVATE_POLICY
  ESP_LOGI(kTag, "%s", k151_local_release_marker());
#else
  ESP_LOGW(kTag, "K151_CONVERSATION_REVIEW_NO_RELEASE");
#endif
  const auto& policy = k151_local_conversation_policy();
  if (!local_conversation_scope_complete(policy)) return;
  const auto facts = observe_boot();
  const auto approval = admit_conversation_boot(policy, facts);
  if (!approval) {
    ESP_LOGE(kTag, "K151 operating boot evidence refused at %u",
             unsigned(conversation_boot_stage(policy, facts)));
    return;
  }
  armed = true;
  const bool released = run_conversation(*approval);
  armed = false;
  if (!released) {
    ESP_LOGE(kTag, "K151 operating cleanup requires reset");
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
  }
#endif
}
