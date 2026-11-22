// SPDX-License-Identifier: MIT
// Compile-only K151 standalone probe. NO motor, Wi-Fi, I2S or USB requests.
#include "k151_contract.hpp"
#include "k151_wakenet_port.hpp"
#include "native_wake_controller.hpp" // Compile only; no controller/model constructed.
#include "native_voice_loop.hpp" // Dormant owner loop; no readiness is asserted.
#include "k151_codec_port.hpp"
#include "k151_readonly_probe.hpp"
#include "k151_usb_scfg.hpp"
#include "k151_usb_enrollment_store.hpp"
#include "offline_voice_cycle.hpp"
#include "wake_voice_entry.hpp" // Compile-only: never instantiate on startup.
#include "question_capture.hpp" // Compile-only question segmentation.
#include "k151_question_pcm.hpp" // Compile-only PSRAM question allocator.
#include "k151_mic_reader.hpp" // Dormant codec -> 10ms frame bridge.
#include "k151_mic_wake_trial.hpp" // Link proof only; no microphone trial starts here.
#include "voice_turn_coordinator.hpp" // Compile-only mic/session/API controller.
#include "guarded_voice_speaker.hpp" // Compile-only speaker lifecycle gate.
#include "k151_pcm_speaker_sink.hpp" // Dormant, 10ms-bounded K151 output.
#include "k151_audio_hold_hooks.hpp" // Dormant output proof / no hardware startup.
#include "k151_output_evidence.hpp" // Source-based policy, not physical proof.
#include "audio_memory_admission.hpp" // Compile-only raw PCM headroom policy.
#include "k151_https_voice.hpp"
#include "k151_voice_api_adapter.hpp"
#include "k151_voice_runtime.hpp"
#include "k151_voice_bootstrap.hpp"
#include "k151_wifi_time.hpp"
#include "k151_owner_setup.hpp"
#include "k151_owner_session.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_setup_lvgl.hpp"
#include "k151_lcd_panel.hpp"
#include "k151_secure_pc_setup.hpp"
#include "k151_scps_usb.hpp"
#include "k151_install_hold.hpp"
#include "k151_voice_decode.hpp"
namespace stackchan::standalone { const char* offline_voice_cycle_compiled_marker(); }
#include "standalone_core.hpp"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
constexpr char kTag[] = "SC_STANDALONE_HOLD";
}

extern "C" void app_main() {
  using namespace stackchan::standalone;
  ESP_LOGW(kTag, "NOT APPROVED FOR DEVICE INSTALLATION");
  ESP_LOGW(kTag, "Manufacturer AI and servos are never initialized by this image");
  ESP_LOGW(kTag, "No LCD/audio/USB/Wi-Fi/TLS/API/OTA handlers are started");
  // Link the codec transport into the Xtensa image without construction,
  // I2C/I2S initialization, power-rail changes or microphone enable.
  ESP_LOGI(kTag, "%s", K151CodecPort::compiled_link_marker());
  // Compile/link proof only. NOT an I2C scan or GPIO initialization.
  ESP_LOGI(kTag, "%s", K151ReadOnlyProbe::compiled_link_marker());
  // Dedicated SCFG USB driver is linked for proof but is NOT installed.
  ESP_LOGI(kTag, "%s", K151ScfgUsbPort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151UsbEnrollmentStorage::compiled_link_marker());
  ESP_LOGI(kTag, "%s", offline_voice_cycle_compiled_marker());
  ESP_LOGI(kTag, "%s", K151HttpsVoicePort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151VoiceApiAdapter::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151VoiceRuntime::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151VoiceBootstrap::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151WifiTimePort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151LocalOwnerSetup::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151OwnerSession::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151HeadTouchOwner::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151SetupLvgl::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151LcdPanel::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151SecurePcSetup::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151ScpsUsbPort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151InstallHold::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151VoiceDecoder::compiled_link_marker());

  ESP_LOGI(kTag, "%s", K151WakeNetPort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151MicWakeTrial::compiled_link_marker());

  for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
