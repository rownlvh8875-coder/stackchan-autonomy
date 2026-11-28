// SPDX-License-Identifier: MIT
// The separate K151 conversation build. The default HOLD uses app_main.cpp.
#include "k151_conversation_owner.hpp"
#include "k151_conversation_policy.hpp"
#include "k151_owner_credential_cipher.hpp"
#include "k151_owner_hmac.hpp"
#include "k151_owner_code.hpp"
#include "k151_display_stop.hpp"
#include "nvs_port.hpp"
#include "k151_scps_usb.hpp"
#include "audio_wipe.hpp"

#include <driver/usb_serial_jtag.h>
#include <bootloader_random.h>
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
#include <utility>

#ifdef STACKCHAN_K151_CONVERSATION_SETUP_PROBE
#include <cstdio>
#else
extern const std::uint8_t model_start[] asm("_binary_srmodels_bin_start");
extern const std::uint8_t model_end[] asm("_binary_srmodels_bin_end");
#endif

namespace stackchan::standalone {
namespace {
constexpr char kTag[] = "SC_K151_BOOT";
bool armed = false; // Only the pinned app task changes or uses this gate.

K151ConversationBootFacts observe_boot(const K151ConversationPolicy& policy) {
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
  facts.reversible_unlock_verified = facts.security_matches && app && !app->encrypted &&
                                     K151OwnerCode::available();
  if (nvs && !nvs->encrypted && app && app->encrypted &&
      policy.owner_hmac_slot && K151OwnerHmac::available(*policy.owner_hmac_slot))
    facts.protected_owner_hmac_slot = policy.owner_hmac_slot;
  if (esp_flash_get_physical_size(esp_flash_default_chip, &facts.flash_bytes) != ESP_OK)
    facts.flash_bytes = 0;
  return facts;
}

void report_terminal_usb(const void* data, size_t size) {
  // Only publish the same fixed verdict so the PC can open the port after boot.
  // This driver never reads, sends a handshake, or accesses credentials.
  usb_serial_jtag_driver_config_t config{};
  config.rx_buffer_size = 128;
  config.tx_buffer_size = 256;
  if (usb_serial_jtag_is_driver_installed() || usb_serial_jtag_driver_install(&config) != ESP_OK)
    return;
  for (unsigned repeat = 0; repeat < 40; ++repeat) {
    const int written = usb_serial_jtag_write_bytes(data, size, pdMS_TO_TICKS(25));
    if (written != 0 && written != static_cast<int>(size)) break;
    vTaskDelay(pdMS_TO_TICKS(250));
  }
  (void)usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(25));
  (void)usb_serial_jtag_driver_uninstall();
}

#ifdef STACKCHAN_K151_CONVERSATION_SETUP_PROBE
enum class ProbeTx : unsigned { skipped, unconfirmed, drained };

void report_setup_startup(K151ConversationBootStage boot, K151OwnerSession::StartupStage setup,
                          bool released, ProbeTx tx) {
  char line[96];
  const int size = std::snprintf(line, sizeof(line), "\nK151_SETUP_STARTUP_PROBE_V2 %u %u %u %u\n",
                                 unsigned(boot), unsigned(setup), unsigned(released), unsigned(tx));
  if (size > 0 && size < int(sizeof(line))) report_terminal_usb(line, size);
}
#else
void report_early_setup_failure(scpswire::SetupFailure failure) {
  const std::array code{static_cast<uint8_t>(failure)};
  const auto frame = scpswire::encode(scpswire::Op::local_setup_fault, code);
  if (frame) report_terminal_usb(frame->data(), frame->size());
}

class SetupEntropy final {
 public:
  explicit SetupEntropy(bool enabled) : enabled_(enabled) {
    if (enabled_) bootloader_random_enable();
  }
  ~SetupEntropy() { finish(); }
  void finish() {
    if (!enabled_) return;
    bootloader_random_disable();
    enabled_ = false;
  }

 private:
  bool enabled_;
};

bool run_conversation(const K151AdmittedConversation& approval) {
  const auto bytes = reinterpret_cast<std::uintptr_t>(model_end) -
                     reinterpret_cast<std::uintptr_t>(model_start);
  const std::span<const std::uint8_t> pack(model_start, bytes);
  SavedOwnerCredentials* saved = nullptr;
  OwnerUnlockPort* unlock = nullptr;
  if (approval.owner_hmac_slot) {
    static K151SavedOwnerNvs storage(K151DisplayStop::flag());
    static K151OwnerHmac cipher(*approval.owner_hmac_slot);
    static SavedOwnerCredentials credentials(storage, cipher);
    saved = &credentials;
  } else if (approval.reversible_owner_unlock) {
    static K151OwnerCode credentials(K151DisplayStop::flag());
    unlock = &credentials;
  }
  // The initial USB handshake can generate ephemeral keys before Wi-Fi.
  SetupEntropy entropy(saved || unlock);
  auto& owner = K151ConversationOwner::instance();
  if (!owner.start(approval.audio, approval.physical_lcd_verified, saved, unlock)) {
    (void)owner.shutdown();
    return false;
  }

  using Phase = K151ConversationOwner::Phase;
  for (;;) {
    const auto progress = owner.poll();
    if (progress.phase != Phase::setup) entropy.finish();
    if (progress.phase == Phase::cloud_off) {
      const auto mode = approval.mode == K151ConversationBuildMode::one_paid_turn
                        ? K151VoiceMode::one_paid_turn : K151VoiceMode::continuous;
      std::optional<K151RebootTrialPlan> reboot_trial;
      if (approval.reboot_trial_id)
        reboot_trial = K151RebootTrialPlan{*approval.reboot_trial_id, k151_local_trial_budget_matches};
      if (!owner.request_voice({"gpt-transcribe", "gpt-6-luna", std::string(kRealtimeSpeechModel),
                                "marin"}, pack, approval.paid_scope_approved,
                               approval.budget_scope_approved, approval.allow_first_budget, mode,
                               std::move(reboot_trial))) {
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
  const auto facts = local_conversation_scope_complete(policy) ? observe_boot(policy)
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
  auto tx = ProbeTx::skipped;
  if (setup_stage == K151OwnerSession::StartupStage::ready && released) {
    // Allow Windows to reopen USB after reset. Send one frame, like DEVICE_HELLO.
    vTaskDelay(pdMS_TO_TICKS(3500));
    tx = k151_probe_scps_tx() ? ProbeTx::drained : ProbeTx::unconfirmed;
  }
  report_setup_startup(boot, setup_stage, released, tx);
  if (!released) for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
#else
#ifdef STACKCHAN_K151_PRIVATE_POLICY
  ESP_LOGI(kTag, "%s", k151_local_release_marker());
#else
  ESP_LOGW(kTag, "K151_CONVERSATION_REVIEW_NO_RELEASE");
  ESP_LOGI(kTag, "%s", K151OwnerCredentialCipher::compiled_link_marker());
#endif
  const auto& policy = k151_local_conversation_policy();
  if (!local_conversation_scope_complete(policy)) return;
  const auto facts = observe_boot(policy);
  const auto approval = admit_conversation_boot(policy, facts);
  if (!approval) {
    ESP_LOGE(kTag, "K151 operating boot evidence refused at %u",
             unsigned(conversation_boot_stage(policy, facts)));
    return;
  }
  armed = true;
  const bool released = run_conversation(*approval);
  armed = false;
  if (released) {
    const auto failure = K151ConversationOwner::instance().early_setup_failure();
    if (failure) report_early_setup_failure(*failure);
  }
  if (!released) {
    ESP_LOGE(kTag, "K151 operating cleanup requires reset");
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
  }
#endif
}
