// SPDX-License-Identifier: MIT
// K151 standalone compile-only ESP-IDF 6.1 Wi-Fi/SNTP adapter.
// Never constructed/started by the HOLD firmware entrypoint.
#pragma once

#include "network_time_guard.hpp"

#include <atomic>
#include <cstdint>
#include <span>
#include <string_view>

#include <esp_event.h>
#include <esp_netif.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace stackchan::standalone {

class K151WifiTimePort final {
 public:
  static const char* compiled_link_marker();
  K151WifiTimePort() = default;
  K151WifiTimePort(const K151WifiTimePort&) = delete;
  K151WifiTimePort& operator=(const K151WifiTimePort&) = delete;
  ~K151WifiTimePort();

  // These two permissions must be authenticated local/hardware decisions,
  // NOT values read from SCFG or a cloud response. No boot caller exists.
  bool start(bool explicit_owner, bool physical_mode_verified,
             std::span<const uint8_t> ssid, std::string_view passphrase,
             std::string_view api_key, const std::atomic_bool& physical_stop);

  // Called from ONE owner task only. Event callbacks queue bounded tokens.
  bool poll(const std::atomic_bool& physical_stop);
  bool allow_paid_request(bool owner_paid_consent,
                          bool physical_stop) const;
  // Atomic admission flag for the stage controller. The actual network port
  // MUST call live_network_ready() for every outbound I/O operation; a stale
  // flag alone cannot prove time is still trusted.
  const std::atomic_bool& admission_flag() const { return admission_ready_; }
  bool live_network_ready() const;
  bool shutdown();
  bool active() const { return active_ && !faulted_; }
  bool faulted() const { return faulted_; }
  ConnectivityPhase phase() const { return policy_.phase(); }
  // RAM-only; unavailable if not explicitly provisioned.
  std::string_view api_key() const { return active() ? secrets_.api_key() : std::string_view{}; }

 private:
  enum class EventType : uint8_t { started, associated, disconnected, ip, sync };
  struct Event { EventType type; uint64_t epoch_seconds; };
  static void on_event(void* arg, esp_event_base_t base, int32_t id, void* data);
  bool handle_event(const Event& evt, uint64_t now_ms);
  bool fail();
  void cleanup();
  RuntimeSecrets secrets_;
  NetworkTimeGuard policy_;
  QueueHandle_t queue_ = nullptr;
  esp_netif_t* station_ = nullptr;
  esp_event_handler_instance_t start_h_ = nullptr;
  esp_event_handler_instance_t connected_h_ = nullptr;
  esp_event_handler_instance_t disconnect_h_ = nullptr;
  esp_event_handler_instance_t ip_h_ = nullptr;
  esp_event_handler_instance_t sync_h_ = nullptr;
  std::atomic_bool queue_overflow_{false};
  // Disconnect is latched immediately in the ESP event callback, before the
  // owning task drains the event queue; no paid work during that gap.
  std::atomic_bool link_down_{true};
  std::atomic_bool admission_ready_{false};
  std::atomic<uint64_t> last_sync_monotonic_ms_{0};
  std::atomic<uint64_t> last_sync_epoch_seconds_{0};
  bool event_loop_owned_ = false;
  bool wifi_initialized_ = false;
  bool wifi_started_ = false;
  bool sntp_initialized_ = false;
  bool sntp_started_ = false;
  bool received_start_event_ = false;
  bool attempted_ = false;
  std::atomic_bool active_{false};
  std::atomic_bool faulted_{false};
};

} // namespace stackchan::standalone
