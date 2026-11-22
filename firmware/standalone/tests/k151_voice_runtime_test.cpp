// SPDX-License-Identifier: MIT
// Real runtime, audio hooks, wake/turn loop and API binding with host-only device doubles.
#include "k151_voice_runtime.hpp"
#include "k151_voice_bootstrap.hpp"
#include "k151_install_hold.hpp"
#include "k151_head_touch_owner.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <esp_heap_caps.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <string_view>
#include <utility>

using namespace stackchan::standalone;

struct i2c_master_bus_t {};

namespace {
std::string_view scenario;
std::atomic_bool owner{true}, consent{true}, stop{false};
std::atomic_bool budget_writes{true}, trusted_input{true};
std::array<uint8_t, 1> pack{0x12};
int64_t now_us = 1'000'000;
int network_starts = 0, network_polls = 0, network_stops = 0, codec_starts = 0, codec_stops = 0;
int model_starts = 0, model_stops = 0, mic_opens = 0, capture_reads = 0;
int calls = 0, plays = 0;
bool codec_running = false, mic_open = false, amp_open = false, model_loaded = false;
bool pending_pcm = false;
i2c_master_bus_t menu_bus;
bool board_bus_registered = true;
int nvs_init_calls = 0, nvs_write_opens = 0, nvs_sets = 0, nvs_commits = 0;
std::vector<uint8_t> durable_budget, durable_profile{0x7b}, staged;
bool staged_profile = false;

struct Store final : AtomicKv {
  std::vector<uint8_t> budget;
  ReadValue read(std::string_view key, size_t max) override {
    assert(key == "budget" && budget.size() <= max);
    return budget.empty() ? ReadValue{ReadCode::missing, {}} :
                            ReadValue{ReadCode::found, budget};
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    assert(key == "budget");
    budget.assign(bytes.begin(), bytes.end());
    return true;
  }
};

bool control_open(const audio_codec_ctrl_if_t*) { return true; }
int register_op(const audio_codec_ctrl_if_t*, int, int, void*, int) { return 0; }
int control_info(const audio_codec_ctrl_if_t*, audio_codec_ctrl_info_t*) { return 0; }

audio_codec_ctrl_if_t fake_control() {
  audio_codec_ctrl_if_t ctrl{};
  ctrl.is_open = control_open;
  ctrl.read_reg = register_op;
  ctrl.write_reg = register_op;
  ctrl.get_info = control_info;
  return ctrl;
}
const audio_codec_ctrl_if_t control = fake_control();
}

extern "C" int64_t esp_timer_get_time() { return now_us; }
extern "C" void heap_caps_get_info(multi_heap_info_t* info, uint32_t caps) {
  const bool available = scenario != "low_heap_after_model" || !model_loaded;
  const size_t size = !available ? 0 : (caps & MALLOC_CAP_SPIRAM) ? 5'000'000 : 256'000;
  *info = {size, size};
}
extern "C" void* heap_caps_malloc(size_t size, uint32_t caps) {
  assert(caps == (MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  return std::malloc(size);
}
extern "C" void heap_caps_free(void* pcm) { std::free(pcm); }
extern "C" bool esp_ptr_external_ram(const void*) { return true; }

extern "C" esp_err_t nvs_flash_init() {
  ++nvs_init_calls;
  if (scenario == "bootstrap_bus_lost_at_init") board_bus_registered = false;
  return scenario == "bootstrap_nvs_init_error" ? ESP_FAIL : ESP_OK;
}
extern "C" esp_err_t nvs_open(const char* space, nvs_open_mode_t mode, nvs_handle_t* handle) {
  assert(std::string_view{space} == "sc_gpt");
  if (scenario == "bootstrap_nvs_read_error") return ESP_FAIL;
  *handle = mode == NVS_READONLY ? 1 : 2;
  if (mode == NVS_READWRITE) {
    ++nvs_write_opens;
    if (scenario == "bootstrap_revoked_at_open") budget_writes = false;
  }
  return ESP_OK;
}
extern "C" esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key, void* out, size_t* len) {
  assert(handle == 1 && std::string_view{key} == "budget");
  if (durable_budget.empty()) return ESP_ERR_NVS_NOT_FOUND;
  if (out) {
    assert(*len == durable_budget.size());
    std::memcpy(out, durable_budget.data(), *len);
    if (scenario == "bootstrap_readback_error") static_cast<uint8_t*>(out)[0] ^= 1;
    if (scenario == "bootstrap_bus_lost_during_restore") board_bus_registered = false;
  }
  *len = durable_budget.size();
  return ESP_OK;
}
extern "C" esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key, const void* bytes,
                                  size_t size) {
  assert(handle == 2);
  staged_profile = std::string_view{key} == "wake_profile";
  assert(staged_profile ? scenario == "bootstrap_scopes_separate" :
                          (std::string_view{key} == "budget" && budget_writes && consent && !stop));
  assert(!mic_open && !amp_open);
  ++nvs_sets;
  const auto* data = static_cast<const uint8_t*>(bytes);
  staged.assign(data, data + size);
  return ESP_OK;
}
extern "C" esp_err_t nvs_commit(nvs_handle_t handle) {
  assert(handle == 2);
  ++nvs_commits;
  if (scenario == "bootstrap_commit_error") return ESP_FAIL;
  (staged_profile ? durable_profile : durable_budget) = staged;
  if (scenario == "bootstrap_stop_at_reservation" && nvs_commits == 2) stop = true;
  return ESP_OK;
}
extern "C" void nvs_close(nvs_handle_t handle) { assert(handle == 1 || handle == 2); }

namespace stackchan::standalone {
bool K151InstallHold::device_activation_allowed() { return scenario != "bootstrap_hold"; }
K151HeadTouchOwner::~K151HeadTouchOwner() = default;
bool K151HeadTouchOwner::finish_owner_setup(K151LocalOwnerSetup& setup, uint64_t now_ms) {
  return setup.confirm(now_ms, true); // This host fixture supplies the physical confirmation.
}

K151BoundedI2s::K151BoundedI2s() : audio_codec_data_if_t{} {}
K151CodecPort::~K151CodecPort() { assert(!codec_running); }
bool K151CodecPort::playback_enabled_by_build() { return scenario != "hold_build"; }
bool K151CodecPort::is_registered_board_bus(i2c_master_bus_handle_t bus) {
  return bus == &menu_bus && board_bus_registered;
}
bool K151CodecPort::prepare(const std::atomic_bool& given_owner,
                           const std::atomic_bool& given_stop,
                           const K151AudioBoardEvidence& evidence,
                           i2c_master_bus_handle_t borrowed_bus) {
  assert(borrowed_bus == &menu_bus);
  if (!is_registered_board_bus(borrowed_bus)) return false;
  assert(&given_owner == &owner && &given_stop == &stop && owner && !stop && consent);
  assert(evidence.verified() && network_polls == 2 && !codec_running);
  ++codec_starts;
  if (scenario == "codec_failure") return false;
  assert(in_control_.attach(&control) && out_control_.attach(&control));
  owner_ = &given_owner;
  stop_ = &given_stop;
  prepared_ = codec_running = true;
  if (scenario == "revoke_during_codec") consent = false;
  return true;
}
bool K151CodecPort::playback_available() const { return prepared(); }
bool K151CodecPort::capture_idle() const { return codec_running && !mic_open && !amp_open; }
bool K151CodecPort::start_fresh_capture() {
  assert(capture_idle() && model_loaded && consent && !stop);
  ++mic_opens;
  capture_reads = 0;
  return mic_open = true;
}
bool K151CodecPort::microphone_off() { mic_open = false; return true; }
bool K151CodecPort::capture_mono_24k(std::span<int16_t> pcm) {
  assert(mic_open && !amp_open && pcm.size() == 240);
  const int frame = capture_reads++ / 2;
  const int onset = QuestionCapture::kInitialQuietFrames;
  const bool question = mic_opens == 2 && frame >= onset && frame < onset + 4;
  std::fill(pcm.begin(), pcm.end(), question ? 2000 : 0);
  return true;
}
bool K151CodecPort::speaker_on_low_volume(const std::atomic_bool& given_consent) {
  assert(&given_consent == &consent && consent && !stop && capture_idle() && calls == 3);
  return amp_open = true;
}
bool K151CodecPort::play_mono_24k(std::span<const int16_t> pcm) {
  assert(amp_open && !mic_open && pcm.size() == 240 && pcm.front() == 10);
  ++plays;
  return pending_pcm = true;
}
bool K151CodecPort::wait_for_tx_tail(const std::atomic_bool&, const std::atomic_bool&,
                                    const std::atomic_bool&) {
  return pending_pcm && amp_open;
}
bool K151CodecPort::drain_output_before_mute() {
  return std::exchange(pending_pcm, false) && amp_open;
}
bool K151CodecPort::speaker_off() { amp_open = false; return true; }
bool K151CodecPort::shutdown() {
  assert(!mic_open && !amp_open);
  if (codec_running) ++codec_stops;
  prepared_ = codec_running = false;
  return true;
}

K151WifiTimePort::~K151WifiTimePort() = default;
bool K151WifiTimePort::start(bool, bool, std::span<const uint8_t>, std::string_view,
                            std::string_view, const std::atomic_bool&) {
  ++network_starts;
  if (scenario.starts_with("bootstrap_")) {
    assert(BudgetLedger::restore(durable_budget).has_value());
    if (scenario == "bootstrap_wifi_revoke_owner") owner = false;
    if (scenario == "bootstrap_wifi_revoke_storage") budget_writes = false;
  }
  return active_ = true;
}
bool K151WifiTimePort::poll(const std::atomic_bool&) {
  assert(active());
  ++network_polls;
  admission_ready_ = network_polls >= 2;
  if (scenario == "revoke_during_poll") consent = false;
  return scenario != "network_failure";
}
bool K151WifiTimePort::shutdown() {
  assert(!codec_running && !model_loaded);
  if (active_.exchange(false)) ++network_stops;
  admission_ready_ = false;
  return true;
}
bool K151WifiTimePort::live_network_ready() const { return active() && admission_ready_.load(); }
bool K151WifiTimePort::copy_api_key(EphemeralApiKey& out) const {
  return live_network_ready() && out.load("mock-only-credential");
}

bool K151WakeNetPort::prepare_embedded(const std::atomic_bool& given_owner,
                                      const std::atomic_bool& given_stop,
                                      std::span<const uint8_t> supplied) {
  assert(&given_owner == &owner && &given_stop == &stop && supplied.data() == pack.data());
  assert(codec_running && !mic_open && !amp_open && consent && !stop);
  ++model_starts;
  if (scenario == "model_failure") return false;
  format_ = {16000, 160, 1, 16};
  if (scenario == "stop_during_model") stop = true;
  return model_loaded = true;
}
bool K151WakeNetPort::ready() const { return model_loaded && owner && !stop; }
bool K151WakeNetPort::reset() { return ready(); }
NativeWakeResult K151WakeNetPort::detect(std::span<int16_t>) {
  return mic_opens == 1 ? NativeWakeResult::detected : NativeWakeResult::none;
}
void K151WakeNetPort::close() {
  if (model_loaded) ++model_stops;
  model_loaded = false;
}

bool K151HttpsVoicePort::post_once(const Request& req, std::string_view,
    const std::function<bool()>& ready, const std::atomic_bool& allowed,
    const std::atomic_bool& stopped, const std::function<bool()>& spend, Reply& out) const {
  assert(!mic_open && !amp_open && ready() && allowed && !stopped && spend() && !spend());
  const std::array expected{httpwire::Endpoint::transcription, httpwire::Endpoint::responses,
                            httpwire::Endpoint::speech};
  assert(calls < 3 && req.endpoint == expected[calls]);
  if (calls == 0) {
    if (scenario.starts_with("bootstrap_")) {
      const auto ledger = BudgetLedger::restore(durable_budget);
      assert(ledger && ledger->count() == 1 && nvs_commits == 2);
    }
    assert(req.pcm24k.size() == 4 * QuestionCapture::kFrame);
    for (int16_t sample : req.pcm24k) assert(sample == 2000);
  }
  out.body.assign(1, static_cast<uint8_t>(++calls));
  out.received_ms = static_cast<uint64_t>(now_us / 1'000);
  if (scenario == "revoke_during_stt") consent = false;
  if (scenario == "bootstrap_revoke_storage_at_stt") budget_writes = false;
  return true;
}
bool K151VoiceDecoder::transcription(std::span<const uint8_t>, std::string& out) {
  out = "test question"; return true;
}
bool K151VoiceDecoder::response_text(std::span<const uint8_t>, std::string& out) {
  out = "test reply"; return true;
}
bool K151VoiceDecoder::speech_pcm(std::span<const uint8_t>, std::vector<int16_t>& out) {
  out.assign(240, 10); return true;
}
}

void exercise_bootstrap() {
  if (scenario == "bootstrap_scopes_separate") {
    IsolatedNvs enrollment;
    assert(enrollment.init_without_erase());
    enrollment.set_local_write_approval(true);
    const std::array<uint8_t, 1> value{0x28};
    assert(!enrollment.commit("budget", value));
    assert(enrollment.commit("wake_profile", value));
    assert(durable_profile[0] == value[0] && durable_budget.empty() && nvs_commits == 1);
    IsolatedNvs voice(owner, consent, budget_writes, stop);
    assert(voice.init_without_erase());
    assert(!voice.commit("wake_profile", value));
    assert(nvs_write_opens == 1);
    return;
  }

  const bool previous = scenario == "bootstrap_existing";
  if (previous || scenario == "bootstrap_bus_lost_during_restore") {
    auto ledger = BudgetLedger::fresh();
    assert(ledger.reserve(1'795'100'000, true, [](auto) { return true; }));
    durable_budget = ledger.serialize();
  } else if (scenario == "bootstrap_corrupt") {
    durable_budget = {1, 2, 3};
  }
  const auto initial_budget = durable_budget;
  K151HeadTouchOwner touch(owner, stop);
  owner = true;
  K151LocalOwnerSetup setup(owner, trusted_input, stop);
  const std::array<uint8_t, 4> ssid{'t', 'e', 's', 't'};
  assert(setup.arm(1000) && setup.submit_wifi(ssid, "mock-password", 1000));
  assert(setup.submit_api_key("not-a-real-key-test", 1000));
  if (scenario != "bootstrap_unconfirmed") assert(touch.finish_owner_setup(setup, 1000));
  if (scenario == "bootstrap_no_budget_scope") budget_writes = false;
  i2c_master_bus_t wrong_bus;
  auto board_bus = &menu_bus;
  if (scenario == "bootstrap_missing_bus") board_bus = nullptr;
  if (scenario == "bootstrap_wrong_bus") board_bus = &wrong_bus;
  K151VoiceBootstrap bootstrap(setup, consent, budget_writes, {true, true}, board_bus);
  if (scenario == "bootstrap_manual_stop") {
    bootstrap.stop();
    assert(!setup.ready());
  }
  const bool first_provision = !previous && scenario != "bootstrap_first_denied";
  const bool turn = scenario == "bootstrap_first_turn" ||
                    scenario == "bootstrap_stop_at_reservation" ||
                    scenario == "bootstrap_revoke_storage_at_stt";
  const bool accepted = previous || turn || scenario == "bootstrap_usb_detached";
  assert(bootstrap.start({"stt", "gpt", "tts", "voice"}, pack, first_provision) == accepted);
  assert(durable_profile == std::vector<uint8_t>{0x7b});
  if (!accepted) {
    assert(bootstrap.poll() == NativeVoiceStep::stopped && calls == 0 && codec_starts == 0);
    const bool early = scenario == "bootstrap_unconfirmed" || scenario == "bootstrap_hold" ||
                       scenario == "bootstrap_no_budget_scope" ||
                       scenario == "bootstrap_manual_stop" ||
                       scenario == "bootstrap_missing_bus" || scenario == "bootstrap_wrong_bus";
    assert(nvs_init_calls == int(!early));
    const bool during_wifi = scenario.starts_with("bootstrap_wifi_");
    const bool began_writing = during_wifi || scenario == "bootstrap_commit_error" ||
                              scenario == "bootstrap_readback_error";
    assert(network_starts == int(during_wifi) && network_stops == network_starts);
    assert(nvs_sets == int(began_writing));
    assert(nvs_write_opens == int(began_writing || scenario == "bootstrap_revoked_at_open"));
    if (!began_writing || scenario == "bootstrap_commit_error")
      assert(durable_budget == initial_budget);
    if (!early) {
      assert(!setup.ready());
      assert(!bootstrap.start({"stt", "gpt", "tts", "voice"}, pack, true));
    }
    return;
  }
  assert(nvs_init_calls == 1 && network_starts == 1 && !setup.ready());
  assert(nvs_commits == int(!previous) && codec_starts == 0);
  if (previous) assert(durable_budget == initial_budget);
  if (scenario == "bootstrap_usb_detached") trusted_input = false;
  assert(bootstrap.poll() == NativeVoiceStep::waiting_network);
  assert(bootstrap.poll() == NativeVoiceStep::questioning && codec_starts == 1);
  if (turn) {
    const bool stop_at_reservation = scenario == "bootstrap_stop_at_reservation";
    const bool revoke_at_stt = scenario == "bootstrap_revoke_storage_at_stt";
    const bool interrupted = stop_at_reservation || revoke_at_stt;
    auto outcome = NativeVoiceStep::questioning;
    for (int i = 0; i < 200 && outcome == NativeVoiceStep::questioning; ++i) {
      now_us += 20'000;
      outcome = bootstrap.poll();
    }
    assert(outcome == (interrupted ? NativeVoiceStep::stopped : NativeVoiceStep::answered));
    assert(calls == (stop_at_reservation ? 0 : revoke_at_stt ? 1 : 3) &&
           plays == int(!interrupted));
    const auto stored = BudgetLedger::restore(durable_budget);
    assert(nvs_commits == 2 && stored && stored->count() == 1);
  } else {
    budget_writes = false;
    assert(bootstrap.poll() == NativeVoiceStep::stopped);
  }
  bootstrap.stop();
  assert(!mic_open && !amp_open && codec_stops == 1 && model_stops == 1 && network_stops == 1);
  assert(durable_profile == std::vector<uint8_t>{0x7b});
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  if (scenario.starts_with("bootstrap_")) {
    exercise_bootstrap();
    return 0;
  }
  Store store;
  PersistentGuard ledger(store);
  assert(scenario == "no_budget" || ledger.provision_budget(true));
  K151WifiTimePort network;
  assert(network.start(true, true, {}, {}, {}, stop));
  if (scenario == "no_consent") consent = false;
  if (scenario == "not_owner") owner = false;
  if (scenario == "stop_before_start") stop = true;
  K151VoiceRuntime runtime(ledger, network, owner, consent, budget_writes, stop,
                           {scenario != "wrong_board", true}, &menu_bus);
  const VoiceModelConfig models{"stt", "gpt", "tts", "voice"};
  if (scenario == "hold_build" || scenario == "not_owner" ||
      scenario == "no_consent" || scenario == "wrong_board" || scenario == "no_budget" || stop) {
    assert(!runtime.start(models, pack));
    assert(runtime.poll() == NativeVoiceStep::stopped);
    assert(network.active() && network_polls == 0 && codec_starts == 0);
    return 0;
  }
  assert(runtime.start(models, pack));
  assert(network_polls == 0 && codec_starts == 0);
  if (scenario == "network_failure" || scenario == "revoke_during_poll") {
    assert(runtime.poll() == NativeVoiceStep::stopped);
    assert(network_stops == 1 && codec_starts == 0);
    return 0;
  }
  assert(runtime.poll() == NativeVoiceStep::waiting_network);
  assert(network_polls == 1 && codec_starts == 0 && !model_loaded);
  if (scenario == "stop_waiting") stop = true;
  if (scenario == "bus_lost_waiting") board_bus_registered = false;
  const bool revoke_stt = scenario == "revoke_during_stt";
  if (scenario != "end_to_end" && !revoke_stt) {
    assert(runtime.poll() == NativeVoiceStep::stopped);
    assert(runtime.poll() == NativeVoiceStep::stopped && !runtime.start(models, pack));
    assert(network_stops == 1 && !mic_open && !amp_open && calls == 0);
    if (scenario == "bus_lost_waiting") assert(codec_starts == 0 && model_starts == 0);
    const bool expected_codec = scenario != "stop_waiting" && scenario != "codec_failure" &&
                                scenario != "bus_lost_waiting";
    assert(codec_stops == int(expected_codec));
    assert(model_stops == int(scenario == "stop_during_model" || scenario == "low_heap_after_model"));
    return 0;
  }
  assert(runtime.poll() == NativeVoiceStep::questioning);
  for (int i = 0; i < 200; ++i) {
    now_us += 20'000;
    const auto state = runtime.poll();
    if (revoke_stt && state == NativeVoiceStep::stopped) {
      assert(calls == 1 && plays == 0 && ledger.reserved_conversations() == 1);
      assert(!mic_open && !amp_open && codec_stops == 1 && model_stops == 1 && network_stops == 1);
      return 0;
    }
    if (state == NativeVoiceStep::answered) break;
    assert(state == NativeVoiceStep::questioning);
  }
  assert(calls == 3 && plays == 1 && ledger.reserved_conversations() == 1);
  assert(!mic_open && !amp_open && !pending_pcm);
  now_us += 600'000;
  assert(runtime.poll() == NativeVoiceStep::listening && mic_opens == 3);
  stop = true;
  assert(runtime.poll() == NativeVoiceStep::stopped);
  assert(!mic_open && codec_stops == 1 && model_stops == 1 && network_stops == 1);
}
