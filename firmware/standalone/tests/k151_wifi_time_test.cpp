#include "k151_wifi_time.hpp"

#include <array>
#include <cassert>
#include <cstring>
#include <deque>
#include <functional>
#include <vector>

using namespace stackchan::standalone;

struct MockQueue {
  size_t capacity;
  size_t item_size;
  std::deque<std::vector<uint8_t>> data;
};

namespace {
struct Handler { esp_event_base_t base; int32_t id; EventHandler handle; void* context; };
std::array<Handler, 5> handlers{};
std::function<void()> before_receive;
int64_t now_us = 1000;

void emit(esp_event_base_t base, int32_t id, void* data = nullptr) {
  const auto& entry = handlers.at(id);
  assert(entry.base == base && entry.id == id && entry.handle);
  entry.handle(entry.context, base, id, data);
}

void sync() {
  esp_netif_sntp_time_sync_t sample{};
  sample.tv.tv_sec = std::time(nullptr);
  emit(NETIF_SNTP_EVENT, NETIF_SNTP_TIME_SYNC, &sample);
}
}

QueueHandle_t xQueueCreate(size_t capacity, size_t item_size) {
  return new MockQueue{capacity, item_size, {}};
}
int xQueueSend(QueueHandle_t queue, const void* event, int) {
  if (queue->data.size() == queue->capacity) return 0;
  const auto* bytes = static_cast<const uint8_t*>(event);
  queue->data.emplace_back(bytes, bytes + queue->item_size);
  return pdTRUE;
}
int xQueueReceive(QueueHandle_t queue, void* event, int) {
  if (before_receive) before_receive();
  if (queue->data.empty()) return 0;
  std::memcpy(event, queue->data.front().data(), queue->item_size);
  queue->data.pop_front();
  return pdTRUE;
}
void vQueueDelete(QueueHandle_t queue) { delete queue; }
int64_t esp_timer_get_time() { return now_us; }

esp_err_t esp_event_handler_instance_register(esp_event_base_t base, int32_t id, EventHandler handler,
                                             void* context, esp_event_handler_instance_t* instance) {
  auto& entry = handlers.at(id);
  assert(!entry.handle);
  entry = {base, id, handler, context};
  *instance = &entry;
  return ESP_OK;
}
esp_err_t esp_event_handler_instance_unregister(esp_event_base_t base, int32_t id,
                                               esp_event_handler_instance_t instance) {
  auto& entry = handlers.at(id);
  assert(&entry == instance && entry.base == base && entry.id == id);
  entry = {};
  return ESP_OK;
}

int main() {
  const std::atomic_bool stop{false};
  const std::array<uint8_t, 3> ssid{'l', 'a', 'b'};

  for (const auto route_event : {WIFI_EVENT_STA_DISCONNECTED, IP_EVENT_STA_GOT_IP}) {
    K151WifiTimePort port;
    assert(port.start(true, true, ssid, "lab-passphrase", "fixture-only-token", stop));
    emit(WIFI_EVENT, WIFI_EVENT_STA_START);
    assert(port.poll(stop));
    emit(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED);
    emit(IP_EVENT, IP_EVENT_STA_GOT_IP);
    assert(port.poll(stop));
    sync();
    assert(port.poll(stop) && port.allow_paid_request(true, false));

    sync(); // Queued on the old route, then delayed until after route revocation.
    emit(route_event == WIFI_EVENT_STA_DISCONNECTED ? WIFI_EVENT : IP_EVENT, route_event);
    assert(!port.allow_paid_request(true, false));
    before_receive = [&] {
      assert(!port.admission_flag().load());
      assert(!port.allow_paid_request(true, false));
    };
    assert(port.poll(stop));
    before_receive = {};
    assert(!port.allow_paid_request(true, false));

    if (route_event == WIFI_EVENT_STA_DISCONNECTED) {
      sync(); // Disconnection with a queued SDK notification but no new IP.
      assert(port.poll(stop) && !port.allow_paid_request(true, false));
      now_us += 1'000'000;
      assert(port.poll(stop));
      emit(WIFI_EVENT, WIFI_EVENT_STA_CONNECTED);
      emit(IP_EVENT, IP_EVENT_STA_GOT_IP);
      assert(port.poll(stop));
    }
    sync();
    assert(port.poll(stop) && port.allow_paid_request(true, false));
  }
}
