// SPDX-License-Identifier: MIT
// Real bounded transport and decoder, with synthetic SDK I/O.
#include "k151_realtime_speech.hpp"

#include <cassert>
#include <cstring>
#include <esp_crt_bundle.h>
#include <esp_transport_ws.h>
#include <string_view>

using namespace stackchan::standalone;

struct esp_transport {};

namespace {
constexpr std::string_view kSession =
    R"({"type":"session.created","session":{"type":"realtime","audio":{"output":{"format":{"type":"audio/pcm","rate":24000}}}}})";
constexpr std::string_view kConversation =
    R"({"event_id":"event_a","type":"conversation.created","conversation":{"id":"conv_a","object":"realtime.conversation"}})";
constexpr std::string_view kCreated =
    R"({"type":"response.created","response":{"id":"resp_a","status":"in_progress","metadata":{"stackchan":"speech"}}})";
constexpr std::string_view kDelta =
    R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"AID/fw=="})";
constexpr std::string_view kAudioDone =
    R"({"type":"response.output_audio.done","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0})";
constexpr std::string_view kDone =
    R"({"type":"response.done","response":{"id":"resp_a","status":"completed","status_details":null}})";

enum class Case { success, stop, deadline, deny_permit, oversized, redirect, short_write, binary };

struct Frame {
  std::string_view data;
  ws_transport_opcodes_t opcode = WS_TRANSPORT_OPCODES_TEXT;
  bool fin = true;
  // Includes SDK partial reads within a single WebSocket frame.
  int declared = static_cast<int>(data.size());
};

const std::vector<Frame> frames{
    {kSession.substr(0, 9), WS_TRANSPORT_OPCODES_TEXT, false},
    {{}, WS_TRANSPORT_OPCODES_NONE},
    {kSession.substr(9), WS_TRANSPORT_OPCODES_CONT},
    {kConversation},
    {kCreated.substr(0, 25), WS_TRANSPORT_OPCODES_TEXT, true, int(kCreated.size())},
    {kCreated.substr(25), WS_TRANSPORT_OPCODES_TEXT, true, int(kCreated.size())},
    {"ping", WS_TRANSPORT_OPCODES_PING},
    {kDelta}, {kAudioDone}, {kDone},
};

esp_transport tls, ws;
Frame current{};
Case scenario;
std::atomic_bool stopped{false};
int64_t usec = 1'000'000;
unsigned read_count = 0, sends = 0, pongs = 0, connects = 0, spends = 0, closes = 0, destroys = 0;
bool crt_bundle = false, authorized = false;
constexpr uint64_t kDeadlineMs = 1110;
}

extern "C" int64_t esp_timer_get_time() { return usec; }
extern "C" esp_err_t esp_crt_bundle_attach(void*) { return ESP_OK; }
extern "C" esp_transport_handle_t esp_transport_ssl_init() { return &tls; }
extern "C" esp_transport_handle_t esp_transport_ws_init(esp_transport_handle_t parent) {
  assert(parent == &tls);
  return &ws;
}
extern "C" void esp_transport_ssl_crt_bundle_attach(esp_transport_handle_t parent,
                                                    esp_err_t (*attach)(void*)) {
  assert(parent == &tls && attach == esp_crt_bundle_attach);
  crt_bundle = true;
}
extern "C" esp_err_t esp_transport_ws_set_config(esp_transport_handle_t t,
                                                 const esp_transport_ws_config_t* config) {
  assert(t == &ws && crt_bundle && config->propagate_control_frames);
  assert(std::string_view(config->auth) == "Bearer synthetic-test-token");
  assert(std::string_view(config->ws_path) == "/v1/realtime?model=gpt-realtime-2.1-mini");
  authorized = true;
  return ESP_OK;
}
extern "C" esp_err_t esp_transport_ws_set_auth(esp_transport_handle_t t, const char* value) {
  assert(t == &ws && connects == 1 && authorized && !value);
  authorized = false;
  return ESP_OK;
}
extern "C" int esp_transport_connect(esp_transport_handle_t t, const char* host, int port, int timeout) {
  assert(t == &ws && port == 443 && timeout == 1500 && spends == 1 && authorized);
  assert(std::string_view(host) == "api.openai.com" && !connects++);
  return 0;
}
extern "C" int esp_transport_ws_get_upgrade_request_status(esp_transport_handle_t t) {
  assert(t == &ws);
  return scenario == Case::redirect ? 307 : 101;
}
extern "C" int esp_transport_read(esp_transport_handle_t t, char* data, int size, int timeout) {
  assert(t == &ws && !authorized && timeout == 250 && !stopped && read_count < frames.size());
  current = frames[read_count++];
  usec += 10'000;
  if (current.data == kDelta) {
    if (scenario == Case::stop) stopped = true;
    if (scenario == Case::deadline) usec = kDeadlineMs * 1000;
    if (scenario == Case::oversized) current.declared = 32 * 1024 + 1;
    if (scenario == Case::binary) current.opcode = WS_TRANSPORT_OPCODES_BINARY;
  }
  assert(current.data.size() <= static_cast<size_t>(size));
  if (!current.data.empty()) std::memcpy(data, current.data.data(), current.data.size());
  return static_cast<int>(current.data.size());
}
extern "C" ws_transport_opcodes_t esp_transport_ws_get_read_opcode(esp_transport_handle_t t) {
  assert(t == &ws);
  return current.opcode;
}
extern "C" int esp_transport_ws_get_read_payload_len(esp_transport_handle_t t) {
  assert(t == &ws);
  return current.declared;
}
extern "C" bool esp_transport_ws_get_fin_flag(esp_transport_handle_t t) {
  assert(t == &ws);
  return current.fin;
}
extern "C" int esp_transport_ws_send_raw(esp_transport_handle_t t, ws_transport_opcodes_t opcode,
                                         const char* data, int size, int timeout) {
  assert(t == &ws && !authorized && timeout == 1500 && !stopped);
  const std::string_view payload(data, size);
  if (opcode == (WS_TRANSPORT_OPCODES_FIN | WS_TRANSPORT_OPCODES_PONG)) {
    assert(payload == "ping" && current.opcode == WS_TRANSPORT_OPCODES_PING && !pongs++);
    return size;
  }
  assert(opcode == (WS_TRANSPORT_OPCODES_FIN | WS_TRANSPORT_OPCODES_TEXT) && read_count == 3);
  assert(payload.find(R"("type":"response.create")") != std::string_view::npos &&
         payload.find("test reply") != std::string_view::npos && !sends++);
  return scenario == Case::short_write ? size - 1 : size;
}
extern "C" int esp_transport_close(esp_transport_handle_t t) {
  assert(t == &ws && !closes++);
  return 0;
}
extern "C" esp_err_t esp_transport_destroy(esp_transport_handle_t t) {
  assert(t == (destroys ? &tls : &ws));
  ++destroys;
  return ESP_OK;
}

void test_realtime_transport() {
  const std::atomic_bool allowed{true};
  const VoiceApiRequest req{VoiceApiStage::synthesize, kRealtimeSpeechPath, kRealtimeSpeechModel,
                            "test reply", "marin", {}, {}, 1, 1000, kDeadlineMs, 0, false, true};
  K151RealtimeSpeechPort port;
  for (const auto next : {Case::success, Case::stop, Case::deadline, Case::deny_permit,
                          Case::oversized, Case::redirect, Case::short_write, Case::binary}) {
    scenario = next;
    stopped = false;
    usec = 1'000'000;
    read_count = sends = pongs = connects = spends = closes = destroys = 0;
    crt_bundle = authorized = false;
    std::vector<uint8_t> pcm{10, 11};
    uint64_t finished = 0;
    const bool ok = port.synthesize_once(req, "synthetic-test-token", [] { return true; },
        allowed, stopped, [&] { return ++spends == 1 && scenario != Case::deny_permit; },
        pcm, finished);
    assert(ok == (scenario == Case::success));
    assert(connects == unsigned(scenario != Case::deny_permit) && spends == 1);
    assert(closes == 1 && destroys == 2);
    if (ok) {
      const std::vector<uint8_t> expected{0, 128, 255, 127};
      assert(pcm == expected && finished == 1100 && sends == 1 && pongs == 1);
    } else {
      assert(pcm.empty() && !finished);
      assert(sends == unsigned(scenario != Case::deny_permit && scenario != Case::redirect));
    }
  }
}
