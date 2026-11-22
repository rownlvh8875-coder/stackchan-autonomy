// SPDX-License-Identifier: MIT
#include "k151_https_voice.hpp"

#include <cassert>
#include <cstring>
#include <esp_http_client.h>

using namespace stackchan::standalone;

struct esp_http_client {
  esp_http_client_config_t config{};
};

namespace {
constexpr std::string_view kReply = R"({"output_text":"mock"})";
enum class Phase { header, body };
enum class Outcome { success, stop, deadline, error };

esp_http_client client;
Phase phase;
Outcome outcome;
std::atomic_bool stopped{false};
int64_t elapsed_ms;
int permits, opens, writes, headers, reads, closes, cleanups;
size_t delivered;

int pause_read(int calls) {
  if (outcome == Outcome::error) return ESP_FAIL;
  if (outcome == Outcome::deadline || calls == 1) {
    elapsed_ms += 1500;
    if (outcome == Outcome::stop) stopped = true;
    return -ESP_ERR_HTTP_EAGAIN;
  }
  return ESP_OK;
}
}

extern "C" int64_t esp_timer_get_time() { return (1000 + elapsed_ms) * 1000; }
extern "C" esp_err_t esp_crt_bundle_attach(void*) { return ESP_OK; }

extern "C" esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t* config) {
  assert(config->method == HTTP_METHOD_POST && config->timeout_ms == 1500);
  assert(config->crt_bundle_attach == esp_crt_bundle_attach && config->disable_auto_redirect);
  assert(std::string_view(config->host) == "api.openai.com");
  assert(std::string_view(config->path) == "/v1/responses");
  client.config = *config;
  return &client;
}
extern "C" esp_err_t esp_http_client_set_header(esp_http_client_handle_t, const char*, const char*) {
  return ESP_OK;
}
extern "C" esp_err_t esp_http_client_open(esp_http_client_handle_t h, int size) {
  assert(h == &client && permits == 1 && size > 0 && !opens++);
  return ESP_OK;
}
extern "C" int esp_http_client_write(esp_http_client_handle_t h, const char* data, int size) {
  assert(h == &client && size > 0 && opens == 1 && !writes++);
  assert(std::string_view(data, size).find("synthetic question") != std::string_view::npos);
  return size;
}
extern "C" int64_t esp_http_client_fetch_headers(esp_http_client_handle_t h) {
  assert(h == &client && writes == 1 && !stopped && elapsed_ms < 30000);
  if (++headers == 1) {
    esp_http_client_event_t event{HTTP_EVENT_ON_HEADER, h->config.user_data, "content-type",
                                  "application/json"};
    assert(h->config.event_handler(&event) == ESP_OK);
  }
  if (phase == Phase::header) {
    const auto result = pause_read(headers);
    if (result != ESP_OK) return result;
  }
  return kReply.size();
}
extern "C" int esp_http_client_get_status_code(esp_http_client_handle_t) { return 200; }
extern "C" esp_http_client_transport_t esp_http_client_get_transport_type(esp_http_client_handle_t) {
  return HTTP_TRANSPORT_OVER_SSL;
}
extern "C" bool esp_http_client_is_chunked_response(esp_http_client_handle_t) { return false; }
extern "C" int esp_http_client_read(esp_http_client_handle_t h, char* data, int size) {
  assert(h == &client && !stopped && elapsed_ms < 30000);
  ++reads;
  if (phase == Phase::body) {
    if (outcome == Outcome::success) {
      if (reads == 2) return pause_read(1);
    } else {
      const auto result = pause_read(reads);
      if (result != ESP_OK) return result;
    }
  }
  const auto remaining = kReply.size() - delivered;
  if (!remaining) return 0;
  const auto count = phase == Phase::body && reads == 1 ? kReply.size() / 2 : remaining;
  assert(size >= static_cast<int>(count));
  std::memcpy(data, kReply.data() + delivered, count);
  delivered += count;
  return count;
}
extern "C" bool esp_http_client_is_complete_data_received(esp_http_client_handle_t) {
  return delivered == kReply.size();
}
extern "C" esp_err_t esp_http_client_close(esp_http_client_handle_t h) {
  assert(h == &client && !closes++);
  return ESP_OK;
}
extern "C" esp_err_t esp_http_client_cleanup(esp_http_client_handle_t h) {
  assert(h == &client && closes == 1 && !cleanups++);
  return ESP_OK;
}

int main() {
  const std::atomic_bool owner{true};
  const K151HttpsVoicePort::Request request{httpwire::Endpoint::responses, "model", {},
                                            "synthetic question", {}};
  const K151HttpsVoicePort port;
  for (const auto test_phase : {Phase::header, Phase::body}) {
    phase = test_phase;
    for (const auto test_outcome : {Outcome::success, Outcome::stop, Outcome::deadline, Outcome::error}) {
      outcome = test_outcome;
      stopped = false;
      elapsed_ms = 0;
      permits = opens = writes = headers = reads = closes = cleanups = 0;
      delivered = 0;
      K151HttpsVoicePort::Reply reply;
      const bool ok = port.post_once(request, "mock-token", [] { return true; }, owner, stopped,
                                     [] { return ++permits == 1; }, reply);
      assert(ok == (outcome == Outcome::success));
      assert(permits == 1 && opens == 1 && writes == 1 && closes == 1 && cleanups == 1);
      const auto phase_calls = phase == Phase::header ? headers : reads;
      if (ok) {
        assert(std::string(reply.body.begin(), reply.body.end()) == kReply);
        assert(reply.received_ms == 2500);
        assert(phase_calls == (phase == Phase::header ? 2 : 4));
      } else {
        assert(reply.body.empty() && reply.received_ms == 0);
        assert(phase_calls == (outcome == Outcome::deadline ? 20 : 1));
      }
    }
  }
}
