// SPDX-License-Identifier: MIT
// Compiled for ESP32-S3 but dormant. No device/radio/clock state is touched
// unless an independently approved local owner runtime calls start().
#include "k151_wifi_time.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <ctime>

#include <esp_timer.h>
#include <esp_wifi.h>
#include <esp_wifi_default.h>
#include <esp_netif_sntp.h>
#include <esp_event.h>
#include <sdkconfig.h>

namespace stackchan::standalone {
namespace {
constexpr size_t kQueueLength = 16;
constexpr char kNtpServer[] = "pool.ntp.org";
static_assert(CONFIG_LWIP_SNTP_UPDATE_DELAY < NetworkTimeGuard::kMaxClockAgeMs,
              "SNTP must refresh before K151 clock admission expires");
uint64_t millis() {
  const int64_t t = esp_timer_get_time();
  return t <= 0 ? 0 : static_cast<uint64_t>(t / 1000);
}
} // namespace

const char* K151WifiTimePort::compiled_link_marker() {
  return "K151 Wi-Fi/SNTP RAM-only credential adapter compiled; NOT STARTED";
}

K151WifiTimePort::~K151WifiTimePort() { (void)shutdown(); }

void K151WifiTimePort::on_event(void* arg, esp_event_base_t base,
                                 int32_t id, void* data) {
  auto* self = static_cast<K151WifiTimePort*>(arg);
  if (!self || !self->queue_) return;
  Event evt{};
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    evt.type = EventType::started;
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) {
    evt.type = EventType::associated;
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    evt.type = EventType::disconnected;
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    evt.type = EventType::ip;
  } else if (base == NETIF_SNTP_EVENT && id == NETIF_SNTP_TIME_SYNC && data) {
    const auto* sync = static_cast<const esp_netif_sntp_time_sync_t*>(data);
    if (sync->tv.tv_sec <= 0) return;
    evt.type = EventType::sync;
    evt.epoch_seconds = static_cast<uint64_t>(sync->tv.tv_sec);
  } else {
    return;
  }
  if (evt.type == EventType::disconnected || evt.type == EventType::ip ||
      evt.type == EventType::sync) {
    std::lock_guard<std::mutex> lock(self->route_mutex_);
    if (evt.type != EventType::sync) {
      // Revoke before the owner drains the queue. An older queued clock sync
      // must not restore admission after this callback changes the route.
      self->link_down_.store(true, std::memory_order_release);
      self->admission_ready_.store(false, std::memory_order_release);
      ++self->route_revision_;
    }
    evt.route_revision = self->route_revision_;
  }
  // The event task only enqueues, never writes NVS, opens a paid request,
  // logs SSID/key, or modifies policy concurrently with poll().
  if (xQueueSend(self->queue_, &evt, 0) != pdTRUE)
    self->queue_overflow_.store(true);
}

bool K151WifiTimePort::start(bool explicit_owner, bool physical_mode_verified,
                             std::span<const uint8_t> ssid,
                             std::string_view passphrase, std::string_view api_key,
                             const std::atomic_bool& physical_stop) {
  if (attempted_ || !explicit_owner || !physical_mode_verified ||
      physical_stop.load()) return false;
  attempted_ = true;
  bool secrets_ok = false;
  {
    std::lock_guard<std::mutex> lock(secrets_mutex_);
    secrets_ok = secrets_.provision(ssid, passphrase, api_key, true);
  }
  if (!secrets_ok || !policy_.arm(true, secrets_ok, millis())) return fail();

  queue_ = xQueueCreate(kQueueLength, sizeof(Event));
  if (!queue_) return fail();
  // Refuse an already occupied default event loop; never take over a running
  // manufacturer application or its network stack.
  if (esp_netif_init() != ESP_OK ||
      esp_event_loop_create_default() != ESP_OK) return fail();
  event_loop_owned_ = true;
  station_ = esp_netif_create_default_wifi_sta();
  if (!station_) return fail();

  wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
  init.nvs_enable = 0; // NO Wi-Fi driver NVS read/write.
  if (esp_wifi_init(&init) != ESP_OK) return fail();
  wifi_initialized_ = true;
  if (esp_wifi_set_storage(WIFI_STORAGE_RAM) != ESP_OK ||
      esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK) return fail();
  wifi_config_t config{};
  std::copy(secrets_.ssid().begin(), secrets_.ssid().end(), config.sta.ssid);
  std::copy(secrets_.passphrase().begin(), secrets_.passphrase().end(),
            reinterpret_cast<char*>(config.sta.password));
  config.sta.failure_retry_cnt = 0; // policy owns bounded retry timing.
  config.sta.pmf_cfg.capable = true;
  const esp_err_t configured = esp_wifi_set_config(WIFI_IF_STA, &config);
  wipe_secret(reinterpret_cast<volatile unsigned char*>(&config), sizeof(config));
  if (configured != ESP_OK) return fail();

  if (esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_START,
       &K151WifiTimePort::on_event, this, &start_h_) != ESP_OK ||
      esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED,
       &K151WifiTimePort::on_event, this, &connected_h_) != ESP_OK ||
      esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
       &K151WifiTimePort::on_event, this, &disconnect_h_) != ESP_OK ||
      esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
       &K151WifiTimePort::on_event, this, &ip_h_) != ESP_OK ||
      esp_event_handler_instance_register(NETIF_SNTP_EVENT, NETIF_SNTP_TIME_SYNC,
       &K151WifiTimePort::on_event, this, &sync_h_) != ESP_OK) return fail();

  esp_sntp_config_t ntp = ESP_NETIF_SNTP_DEFAULT_CONFIG(kNtpServer);
  ntp.start = false;
  ntp.wait_for_sync = false;
  if (esp_netif_sntp_init(&ntp) != ESP_OK) return fail();
  sntp_initialized_ = true;
  if (physical_stop.load()) return fail();
  if (esp_wifi_start() != ESP_OK) return fail();
  wifi_started_ = true;
  active_ = true;
  return true;
}

bool K151WifiTimePort::handle_event(const Event& evt, uint64_t now_ms) {
  switch (evt.type) {
    case EventType::started:
      received_start_event_ = true;
      return true;
    case EventType::associated:
      // On a delayed stale association, the policy rejects invalid phases.
      return policy_.associated(policy_.attempt_id(), now_ms);
    case EventType::disconnected:
      policy_.disconnected(now_ms);
      return true;
    case EventType::ip:
      if (!policy_.ip_acquired(policy_.attempt_id(), now_ms)) return false;
      acquired_ip_revision_ = evt.route_revision;
      // On renewal the same esp-netif SNTP service is already running.
      // Starting it twice is not a recovery operation and may fail.
      if (sntp_started_) return true;
      if (esp_netif_sntp_start() != ESP_OK) return false;
      sntp_started_ = true;
      return true;
    case EventType::sync: {
      std::lock_guard<std::mutex> lock(route_mutex_);
      if (!acquired_ip_revision_ || evt.route_revision != acquired_ip_revision_ ||
          evt.route_revision != route_revision_) return true;
      // SNTP is ordinary, unauthenticated; only time plausibility is checked.
      const bool accepted = policy_.time_synchronized(
          policy_.attempt_id(), evt.epoch_seconds, now_ms);
      if (accepted) {
        admission_ready_.store(false, std::memory_order_release);
        last_sync_epoch_seconds_.store(evt.epoch_seconds, std::memory_order_release);
        last_sync_monotonic_ms_.store(now_ms, std::memory_order_release);
        link_down_.store(false, std::memory_order_release);
        admission_ready_.store(true, std::memory_order_release);
      }
      return accepted;
    }
  }
  return false;
}

bool K151WifiTimePort::poll(const std::atomic_bool& physical_stop) {
  if (!active_ || faulted_) return false;
  if (physical_stop.load() || queue_overflow_.load()) return fail();
  if (!policy_.tick(millis())) return fail();
  if (policy_.phase() != ConnectivityPhase::ready)
    admission_ready_.store(false, std::memory_order_release);
  Event event{};
  for (size_t n = 0; n < kQueueLength &&
          xQueueReceive(queue_, &event, 0) == pdTRUE; ++n) {
    if (physical_stop.load() || !handle_event(event, millis())) return fail();
  }
  if (received_start_event_ && policy_.phase() == ConnectivityPhase::offline) {
    auto attempt = policy_.claim_connect(millis());
    if (attempt && esp_wifi_connect() != ESP_OK) policy_.disconnected(millis());
  }
  if (physical_stop.load()) admission_ready_.store(false, std::memory_order_release);
  return !faulted_ && !physical_stop.load();
}

bool K151WifiTimePort::live_network_ready() const {
  // This method is safe to call on the HTTPS task. Do not read NetworkTimeGuard
  // directly across tasks: its policy state belongs to the owning poll task.
  if (!active_.load(std::memory_order_acquire) ||
      faulted_.load(std::memory_order_acquire) ||
      link_down_.load(std::memory_order_acquire) ||
      !admission_ready_.load(std::memory_order_acquire)) return false;
  const uint64_t synced_ms = last_sync_monotonic_ms_.load(std::memory_order_acquire);
  const uint64_t epoch = last_sync_epoch_seconds_.load(std::memory_order_acquire);
  const uint64_t now_ms = millis();
  const std::time_t wall = std::time(nullptr);
  if (now_ms < synced_ms || now_ms - synced_ms > NetworkTimeGuard::kMaxClockAgeMs ||
      wall < 0) return false;
  const uint64_t estimated = epoch + (now_ms - synced_ms) / 1000U;
  const uint64_t actual = static_cast<uint64_t>(wall);
  const uint64_t delta = estimated >= actual ? estimated - actual : actual - estimated;
  return delta <= NetworkTimeGuard::kMaxWallSkewSeconds &&
         !link_down_.load(std::memory_order_acquire) &&
         admission_ready_.load(std::memory_order_acquire);
}

bool K151WifiTimePort::allow_paid_request(bool owner_paid_consent,
                                           bool physical_stop) const {
  return owner_paid_consent && !physical_stop && live_network_ready();
}

bool K151WifiTimePort::copy_api_key(EphemeralApiKey& out) const {
  out.clear();
  if (!live_network_ready()) return false;
  std::lock_guard<std::mutex> lock(secrets_mutex_);
  if (!live_network_ready() || !secrets_.valid()) return false;
  return out.load(secrets_.api_key());
}

bool K151WifiTimePort::fail() {
  faulted_ = true;
  policy_.fault();
  cleanup();
  return false;
}

void K151WifiTimePort::cleanup() {
  active_ = false;
  admission_ready_.store(false, std::memory_order_release);
  link_down_.store(true, std::memory_order_release);
  if (wifi_started_) {
    (void)esp_wifi_stop();
    wifi_started_ = false;
  }
  if (sntp_initialized_) {
    esp_netif_sntp_deinit();
    sntp_initialized_ = false;
    sntp_started_ = false;
  }
  if (event_loop_owned_) {
    if (sync_h_) (void)esp_event_handler_instance_unregister(
        NETIF_SNTP_EVENT, NETIF_SNTP_TIME_SYNC, sync_h_);
    if (ip_h_) (void)esp_event_handler_instance_unregister(
        IP_EVENT, IP_EVENT_STA_GOT_IP, ip_h_);
    if (disconnect_h_) (void)esp_event_handler_instance_unregister(
        WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, disconnect_h_);
    if (connected_h_) (void)esp_event_handler_instance_unregister(
        WIFI_EVENT, WIFI_EVENT_STA_CONNECTED, connected_h_);
    if (start_h_) (void)esp_event_handler_instance_unregister(
        WIFI_EVENT, WIFI_EVENT_STA_START, start_h_);
  }
  sync_h_ = nullptr;
  ip_h_ = nullptr;
  disconnect_h_ = nullptr;
  connected_h_ = nullptr;
  start_h_ = nullptr;
  if (wifi_initialized_) {
    (void)esp_wifi_deinit();
    wifi_initialized_ = false;
  }
  if (station_) {
    esp_netif_destroy_default_wifi(station_);
    station_ = nullptr;
  }
  if (event_loop_owned_) {
    (void)esp_event_loop_delete_default();
    event_loop_owned_ = false;
  }
  if (queue_) {
    vQueueDelete(queue_);
    queue_ = nullptr;
  }
  {
    std::lock_guard<std::mutex> lock(secrets_mutex_);
    secrets_.clear();
  }
}

bool K151WifiTimePort::shutdown() {
  policy_.stop();
  cleanup();
  // This does not guarantee physical radio teardown if a driver API failed.
  return !faulted_;
}

} // namespace stackchan::standalone
