// SPDX-License-Identifier: MIT
#include "k151_realtime_speech.hpp"

#include "audio_wipe.hpp"
#include "k151_voice_decode.hpp"
#include "live_io_gate.hpp"
#include <algorithm>
#include <array>
#include <esp_crt_bundle.h>
#include <esp_timer.h>
#include <esp_transport_ssl.h>
#include <esp_transport_ws.h>

namespace stackchan::standalone {
namespace {
constexpr char kHost[] = "api.openai.com";
constexpr char kUpgradePath[] = "/v1/realtime?model=gpt-realtime-2.1-mini";
constexpr int kConnectTimeoutMs = 1500;
constexpr int kReadTimeoutMs = 250;
constexpr int kWriteTimeoutMs = 1500;

struct Socket {
  esp_transport_handle_t tls = esp_transport_ssl_init();
  esp_transport_handle_t ws = tls ? esp_transport_ws_init(tls) : nullptr;
  ~Socket() {
    if (ws) {
      (void)esp_transport_close(ws);
      (void)esp_transport_destroy(ws);
    }
    if (tls) (void)esp_transport_destroy(tls);
  }
};

std::optional<uint64_t> live_time(LiveIoGate& gate, uint64_t started) {
  const auto usec = esp_timer_get_time();
  if (usec < 0) return std::nullopt;
  const auto now = static_cast<uint64_t>(usec / 1000);
  if (now < started || !gate.allowed(now)) return std::nullopt;
  return now;
}

bool configure(Socket& socket, std::string_view key) {
  if (!socket.ws || key.size() < 16 || key.size() > 224 ||
      !std::ranges::all_of(key, [](unsigned char ch) { return ch > 0x20 && ch < 0x7f; }))
    return false;
  esp_transport_ssl_crt_bundle_attach(socket.tls, esp_crt_bundle_attach);
  constexpr std::string_view bearer = "Bearer ";
  std::array<uint8_t, 232> auth{};
  std::copy(bearer.begin(), bearer.end(), auth.begin());
  std::copy(key.begin(), key.end(), auth.begin() + bearer.size());
  esp_transport_ws_config_t config{};
  config.ws_path = kUpgradePath;
  config.auth = reinterpret_cast<const char*>(auth.data());
  config.propagate_control_frames = true;
  const bool configured = esp_transport_ws_set_config(socket.ws, &config) == ESP_OK;
  wipe_audio_bytes(auth);
  return configured;
}

class ReceiveBuffer {
 public:
  ~ReceiveBuffer() {
    wipe_audio_bytes(message_);
    wipe_audio_bytes(chunk_);
  }

  bool read(Socket& socket, LiveIoGate& gate, uint64_t started,
            K151RealtimeSpeechExchange& exchange) {
    if (after_control_payload_) {
      // ESP-IDF 6.1 can reuse the last control-frame length if polling the
      // next header times out. Wait for readability before reading it.
      const auto ready = esp_transport_poll_read(socket.ws, kReadTimeoutMs);
      if (ready < 0 || !live_time(gate, started)) return false;
      if (ready == 0) return true;
      after_control_payload_ = false;
    }
    const auto count = esp_transport_read(socket.ws, reinterpret_cast<char*>(chunk_.data()),
                                          chunk_.size(), kReadTimeoutMs);
    if (count < 0 || static_cast<size_t>(count) > chunk_.size() || !live_time(gate, started))
      return false;
    const auto length = static_cast<size_t>(count);
    if (!frame_left_) {
      const auto opcode = esp_transport_ws_get_read_opcode(socket.ws);
      if (opcode == WS_TRANSPORT_OPCODES_NONE) return count == 0;
      if (opcode == WS_TRANSPORT_OPCODES_PING || opcode == WS_TRANSPORT_OPCODES_PONG) {
        if (length > 125) return false;
        after_control_payload_ = length != 0;
        if (opcode == WS_TRANSPORT_OPCODES_PONG) return true;
        constexpr auto pong = static_cast<ws_transport_opcodes_t>(
            WS_TRANSPORT_OPCODES_PONG | WS_TRANSPORT_OPCODES_FIN);
        return esp_transport_ws_send_raw(socket.ws, pong,
                   reinterpret_cast<char*>(chunk_.data()), count, kWriteTimeoutMs) == count;
      }
      if (opcode != (continuation_ ? WS_TRANSPORT_OPCODES_CONT : WS_TRANSPORT_OPCODES_TEXT))
        return false;
      const auto declared = esp_transport_ws_get_read_payload_len(socket.ws);
      if (declared < 0 || static_cast<size_t>(declared) >
              K151RealtimeSpeechExchange::kMaxEventBytes - message_.size()) return false;
      frame_left_ = static_cast<size_t>(declared);
      continuation_ = !esp_transport_ws_get_fin_flag(socket.ws);
    }
    if (length > frame_left_) return false;
    if (message_.capacity() == 0) message_.reserve(K151RealtimeSpeechExchange::kMaxEventBytes);
    message_.insert(message_.end(), chunk_.begin(), chunk_.begin() + length);
    frame_left_ -= length;
    if (frame_left_ || continuation_) return true;
    const bool accepted = exchange.accept(message_);
    wipe_audio_bytes(message_);
    message_.clear();
    return accepted;
  }

 private:
  std::array<uint8_t, 1024> chunk_{};
  std::vector<uint8_t> message_;
  size_t frame_left_ = 0;
  bool continuation_ = false;
  bool after_control_payload_ = false;
};
} // namespace

bool K151RealtimeSpeechPort::synthesize_once(const VoiceApiRequest& request, std::string_view key,
    const std::function<bool()>& network_ready, const std::atomic_bool& consent,
    const std::atomic_bool& stop, const std::function<bool()>& spend_dispatch,
    std::vector<uint8_t>& pcm24k, uint64_t& completed_ms) const {
  wipe_audio_bytes(pcm24k);
  pcm24k.clear();
  completed_ms = 0;
  if (request.stage != VoiceApiStage::synthesize || request.model != kRealtimeSpeechModel ||
      request.fixed_path != kRealtimeSpeechPath || !request.pcm24k.empty() ||
      !request.pcm_output || request.store || request.deadline_ms <= request.started_ms ||
      request.deadline_ms - request.started_ms > 30000U || !spend_dispatch) return false;
  LiveIoGate gate(network_ready, consent, stop, request.deadline_ms);
  if (!live_time(gate, request.started_ms)) return false;
  auto body = K151RealtimeSpeechExchange::response_request(request.voice, request.text);
  if (!body) return false;
  Socket socket;
  if (!configure(socket, key) || !live_time(gate, request.started_ms) || !spend_dispatch() ||
      !live_time(gate, request.started_ms)) return false;
  if (esp_transport_connect(socket.ws, kHost, 443, kConnectTimeoutMs) != 0 ||
      esp_transport_ws_get_upgrade_request_status(socket.ws) != 101 ||
      esp_transport_ws_set_auth(socket.ws, nullptr) != ESP_OK) return false;

  K151RealtimeSpeechExchange exchange;
  ReceiveBuffer receive;
  using State = K151RealtimeSpeechExchange::State;
  while (live_time(gate, request.started_ms) && receive.read(socket, gate, request.started_ms, exchange)) {
    if (exchange.state() == State::ready) {
      if (!exchange.begin_response() || !live_time(gate, request.started_ms)) return false;
      constexpr auto text = static_cast<ws_transport_opcodes_t>(
          WS_TRANSPORT_OPCODES_TEXT | WS_TRANSPORT_OPCODES_FIN);
      const auto size = static_cast<int>(body->size());
      const auto sent = esp_transport_ws_send_raw(socket.ws, text, body->data(), size, kWriteTimeoutMs);
      wipe_audio_bytes({reinterpret_cast<uint8_t*>(body->data()), body->size()});
      if (sent != size) return false;
    }
    if (exchange.state() == State::complete) {
      const auto now = live_time(gate, request.started_ms);
      if (!now) return false;
      completed_ms = *now;
      pcm24k = exchange.take_pcm();
      return !pcm24k.empty();
    }
  }
  return false;
}

} // namespace stackchan::standalone
