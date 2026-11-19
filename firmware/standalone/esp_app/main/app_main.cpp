// SPDX-License-Identifier: MIT
// Compile-only K151 standalone probe. NO motor, Wi-Fi, I2S or USB requests.
#include "k151_contract.hpp"
#include "k151_codec_port.hpp"
#include "k151_readonly_probe.hpp"
#include "k151_usb_scfg.hpp"
#include "k151_usb_enrollment_store.hpp"
#include "offline_voice_cycle.hpp"
#include "k151_https_voice.hpp"
#include "k151_voice_api_adapter.hpp"
#include "k151_wifi_time.hpp"
#include "k151_owner_setup.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_setup_lvgl.hpp"
#include "k151_secure_pc_setup.hpp"
#include "k151_voice_decode.hpp"
namespace stackchan::standalone { const char* offline_voice_cycle_compiled_marker(); }
#include "nvs_port.hpp"
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
  ESP_LOGI(kTag, "%s", K151WifiTimePort::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151LocalOwnerSetup::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151HeadTouchOwner::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151SetupLvgl::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151SecurePcSetup::compiled_link_marker());
  ESP_LOGI(kTag, "%s", K151VoiceDecoder::compiled_link_marker());

  IsolatedNvs nvs;
  if (!nvs.init_without_erase()) {
    ESP_LOGE(kTag, "NVS init failed; no erase or recovery attempted");
  } else {
    PersistentGuard guard(nvs);
    const ProfileLoad profile_state = guard.restore_profile();
    const bool budget_restored = guard.restore_budget();
    Session session;
    session.boot(0, false, profile_state == ProfileLoad::valid);
    ESP_LOGW(kTag, "Readonly check: profile=%d budget=%d; cloud=OFF state=%d",
             static_cast<int>(profile_state), static_cast<int>(budget_restored),
             static_cast<int>(session.state()));
  }
  for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
