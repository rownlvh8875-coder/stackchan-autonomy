// SPDX-License-Identifier: MIT
// No network, Wi-Fi, NVS, GPIO or speaker use until a separate owner runtime
// constructs K151VoiceApiAdapter and the paid OfflineVoiceCycle calls api().
#include "k151_voice_api_adapter.hpp"

#include <esp_timer.h>
#include <utility>

namespace stackchan::standalone {

const char* K151HttpChannel::compiled_link_marker() {
  return "K151 fixed-host HTTPS stage adapter compiled; NOT STARTED";
}

bool K151HttpChannel::post_once(
    const VoiceApiRequest& req, const std::function<bool()>& spend_dispatch,
    std::vector<uint8_t>& body, uint64_t& completed_ms) {
  body.clear();
  completed_ms = 0;
  if (!spend_dispatch || !network_.live_network_ready() ||
      !consent_.load() || stop_.load()) return false;
  httpwire::Endpoint endpoint;
  switch (req.stage) {
    case VoiceApiStage::transcribe:
      endpoint = httpwire::Endpoint::transcription;
      break;
    case VoiceApiStage::respond:
      endpoint = httpwire::Endpoint::responses;
      break;
    case VoiceApiStage::synthesize:
      endpoint = httpwire::Endpoint::speech;
      break;
    default:
      return false;
  }
  if (req.fixed_path != httpwire::path(endpoint)) return false;
  EphemeralApiKey one_request_key;
  if (!network_.copy_api_key(one_request_key)) return false;
  K151HttpsVoicePort::Request posted{endpoint, req.model, req.voice,
                                    req.text, req.pcm24k};
  K151HttpsVoicePort::Reply result{};
  // post_once() consumes spend_dispatch() exactly once before establishing
  // TLS. The durable budget was ALREADY spent by OfflineVoiceCycle::stage;
  // this callback consumes only the separate in-RAM session-epoch ticket.
  const auto live_network = [this]() { return network_.live_network_ready(); };
  if (!http_.post_once(posted, one_request_key.view(), live_network,
                       consent_, stop_, spend_dispatch, result)) return false;
  one_request_key.clear();
  if (stop_.load() || !consent_.load() || !network_.live_network_ready()) return false;
  completed_ms = result.received_ms;
  body = std::move(result.body);
  return !body.empty();
}

K151VoiceApiAdapter::K151VoiceApiAdapter(
    const K151WifiTimePort& network,
    const std::atomic_bool& consent, const std::atomic_bool& stop)
    : http_(network, consent, stop),
      binding_(http_, codec_, []() {
        return static_cast<uint64_t>(esp_timer_get_time() / 1000);
      }, stop, consent, network.admission_flag()) {}

const char* K151VoiceApiAdapter::compiled_link_marker() {
  return K151HttpChannel::compiled_link_marker();
}

} // namespace stackchan::standalone
