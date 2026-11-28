#pragma once

#include <cstddef>
#include <cstdint>
#include <ctime>

using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
using esp_event_base_t = const char*;
using esp_event_handler_instance_t = void*;
using EventHandler = void (*)(void*, esp_event_base_t, int32_t, void*);
inline constexpr char WIFI_EVENT[] = "wifi";
inline constexpr char IP_EVENT[] = "ip";
inline constexpr char NETIF_SNTP_EVENT[] = "sntp";
enum { WIFI_EVENT_STA_START, WIFI_EVENT_STA_CONNECTED, WIFI_EVENT_STA_DISCONNECTED,
       IP_EVENT_STA_GOT_IP, NETIF_SNTP_TIME_SYNC };

struct esp_netif_t {};
struct esp_netif_sntp_time_sync_t { struct { std::time_t tv_sec; } tv; };
struct esp_sntp_config_t { bool start, wait_for_sync; };
#define ESP_NETIF_SNTP_DEFAULT_CONFIG(server) ((void)(server), esp_sntp_config_t{true, true})
struct wifi_init_config_t { int nvs_enable; };
#define WIFI_INIT_CONFIG_DEFAULT() wifi_init_config_t{1}
struct wifi_config_t {
  struct {
    uint8_t ssid[32], password[64];
    int failure_retry_cnt;
    struct { bool capable; } pmf_cfg;
  } sta;
};
enum { WIFI_STORAGE_RAM, WIFI_MODE_STA, WIFI_IF_STA };
#define CONFIG_LWIP_SNTP_UPDATE_DELAY 600000

struct MockQueue;
using QueueHandle_t = MockQueue*;
constexpr int pdTRUE = 1;
QueueHandle_t xQueueCreate(size_t capacity, size_t item_size);
int xQueueSend(QueueHandle_t, const void*, int);
int xQueueReceive(QueueHandle_t, void*, int);
void vQueueDelete(QueueHandle_t);
int64_t esp_timer_get_time();
esp_err_t esp_event_handler_instance_register(esp_event_base_t, int32_t, EventHandler,
                                             void*, esp_event_handler_instance_t*);
esp_err_t esp_event_handler_instance_unregister(esp_event_base_t, int32_t,
                                               esp_event_handler_instance_t);
inline esp_err_t esp_netif_init() { return ESP_OK; }
inline esp_err_t esp_event_loop_create_default() { return ESP_OK; }
inline esp_err_t esp_event_loop_delete_default() { return ESP_OK; }
inline esp_netif_t* esp_netif_create_default_wifi_sta() {
  static esp_netif_t station;
  return &station;
}
inline void esp_netif_destroy_default_wifi(esp_netif_t*) {}
inline esp_err_t esp_wifi_init(const wifi_init_config_t*) { return ESP_OK; }
inline esp_err_t esp_wifi_set_storage(int) { return ESP_OK; }
inline esp_err_t esp_wifi_set_mode(int) { return ESP_OK; }
inline esp_err_t esp_wifi_set_config(int, const wifi_config_t*) { return ESP_OK; }
inline esp_err_t esp_wifi_start() { return ESP_OK; }
inline esp_err_t esp_wifi_connect() { return ESP_OK; }
inline esp_err_t esp_wifi_stop() { return ESP_OK; }
inline esp_err_t esp_wifi_deinit() { return ESP_OK; }
inline esp_err_t esp_netif_sntp_init(const esp_sntp_config_t*) { return ESP_OK; }
inline esp_err_t esp_netif_sntp_start() { return ESP_OK; }
inline void esp_netif_sntp_deinit() {}
