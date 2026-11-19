// SPDX-License-Identifier: MIT
// Compile-only K151 standalone probe. NO motor, Wi-Fi, I2S or USB requests.
#include "k151_contract.hpp"
#include "k151_codec_port.hpp"
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
