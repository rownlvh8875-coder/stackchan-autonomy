// SPDX-License-Identifier: MIT
// Real runtime, audio hooks, wake/turn loop and API binding with host-only device doubles.
#include "k151_voice_runtime.hpp"
#include "k151_voice_bootstrap.hpp"
#include "k151_conversation_owner.hpp"
#include "k151_install_hold.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_display_stop.hpp"
#include "k151_lcd_panel.hpp"
#include "saved_owner_credentials_fixture.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <driver/gpio.h>
#include <esp_heap_caps.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <string_view>
#include <thread>
#include <utility>

#ifdef STACKCHAN_TEST_REALTIME_WIRE
#include <esp_crt_bundle.h>
#include <esp_transport_ws.h>
#endif

using namespace stackchan::standalone;

struct i2c_master_bus_t {};
struct i2c_master_dev_t {
  uint16_t address;
};
struct esp_timer {};
#ifdef STACKCHAN_TEST_REALTIME_WIRE
struct esp_transport {};
#endif

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
#ifdef STACKCHAN_TEST_REALTIME_WIRE
esp_transport tls_socket, ws_socket;
bool speech_connected = false, speech_requested = false;
std::string_view speech_event;
size_t speech_events_read = 0;
#endif
i2c_master_bus_t menu_bus;
bool board_bus_registered = true;
i2c_master_dev_t stop_expander{0x58}, stop_panel{0x38};
i2c_master_dev_handle_t stop_probe = nullptr;
unsigned stop_probe_closes = 0;
std::array<uint8_t, 2> stop_masks{}, initial_stop_masks{};
unsigned stop_mask_writes = 0;
bool restore_failed_once = false;
esp_timer stop_timer;
void (*stop_timer_callback)(void*) = nullptr;
std::atomic_int stop_gpio_level{1};
unsigned gpio_configures = 0, gpio_samples = 0, timer_creates = 0;
bool stop_timer_active = false;
unsigned panel_handoffs = 0;
unsigned wake_detections = 0;
std::vector<K151VoiceStatus> voice_status;
int board_task, other_task;
TaskHandle_t current_task = &board_task;
bool lvgl_on = false, setup_usb = false;
uint64_t review_started_ms = 0;
constexpr std::array kStopDuringRequest{
    "bootstrap_display_stop_during_stt", "bootstrap_display_stop_during_gpt",
    "bootstrap_display_stop_during_tts"};

const std::atomic_bool& stop_source() {
  return scenario.starts_with("bootstrap_") && scenario != "bootstrap_wrong_stop_binding"
       ? K151DisplayStop::flag() : stop;
}

bool conversation_case() { return scenario.starts_with("bootstrap_conversation_"); }
bool restored_conversation() { return scenario.starts_with("bootstrap_conversation_reboot_"); }
bool initial_saved_conversation() { return scenario.starts_with("bootstrap_conversation_save_"); }
bool continuous_conversation() {
  return scenario == "bootstrap_conversation_continuous" || restored_conversation() ||
         initial_saved_conversation();
}
bool realtime_conversation() {
  return continuous_conversation() || scenario == "bootstrap_conversation_realtime" ||
         scenario == "bootstrap_conversation_tts_failure";
}
int failed_conversation_call() {
  if (scenario == "bootstrap_conversation_stt_failure") return 1;
  if (scenario == "bootstrap_conversation_gpt_failure") return 2;
  if (scenario == "bootstrap_conversation_tts_failure") return 3;
  return 0;
}

void display_press() {
  assert(stop_timer_active && stop_timer_callback);
  stop_gpio_level = 0;
  // Simulate the independent ESP_TIMER_TASK while the caller is blocked.
  std::thread dispatch([] { stop_timer_callback(nullptr); });
  dispatch.join();
  stop_gpio_level = 1;
  assert(K151DisplayStop::flag());
}
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
TaskHandle_t xTaskGetCurrentTaskHandle() { return current_task; }
int xPortGetCoreID() { return 0; }
extern "C" bool lv_is_initialized() { return lvgl_on; }
extern "C" void lv_init() { assert(board_bus_registered); lvgl_on = true; }
extern "C" void lv_deinit() { assert(!setup_usb && !codec_running); lvgl_on = false; }
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t* config,
                                       i2c_master_bus_handle_t* out) {
  assert(conversation_case() && !board_bus_registered && config->i2c_port == I2C_NUM_1);
  board_bus_registered = true;
  *out = &menu_bus;
  return ESP_OK;
}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t bus) {
  assert(bus == &menu_bus && board_bus_registered && !stop_probe && !stop_timer_active);
  assert(!lvgl_on && !setup_usb && !codec_running && !model_loaded);
  board_bus_registered = false;
  return ESP_OK;
}

extern "C" esp_err_t i2c_master_bus_add_device(
    i2c_master_bus_handle_t bus, const i2c_device_config_t* config,
    i2c_master_dev_handle_t* device) {
  assert(bus == &menu_bus && board_bus_registered && !stop_timer_active && !stop_probe);
  assert(panel_handoffs == 1);
  assert(config->dev_addr_length == I2C_ADDR_BIT_LEN_7 && config->scl_speed_hz == 100'000);
  assert(config->device_address == stop_expander.address ||
         config->device_address == stop_panel.address);
  *device = stop_probe = config->device_address == stop_expander.address
                      ? &stop_expander : &stop_panel;
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device) {
  assert(device == stop_probe && !stop_timer_active);
  if (++stop_probe_closes == 1 && scenario == "bootstrap_stop_probe_busy")
    return ESP_ERR_INVALID_STATE;
  stop_probe = nullptr;
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit_receive(
    i2c_master_dev_handle_t device, const uint8_t* reg, size_t size,
    uint8_t* value, size_t count, int timeout_ms) {
  assert(device == stop_probe && !stop_timer_active);
  assert(size == 1 && count == 1 && timeout_ms == 30);
  if (nvs_init_calls) assert(device == &stop_expander && (*reg == 0x06 || *reg == 0x07));
  if (device == &stop_panel) {
    assert(*reg == 0xa4);
    *value = scenario == "bootstrap_stop_panel_polling" ? 0 : 1;
    return ESP_OK;
  }
  assert(device == &stop_expander);
  switch (*reg) {
    case 0x10: *value = scenario == "bootstrap_stop_irq_bad_id" ? 0 : 0x23; break;
    case 0x12:
    case 0x13: *value = 0xff; break;
    case 0x04: *value = 0x18; break;
    case 0x05: *value = scenario == "bootstrap_stop_irq_bad_direction" ? 0x08 : 0x0c; break;
    case 0x06:
    case 0x07: *value = stop_masks[*reg - 0x06]; break;
    default: assert(false); // No read of either interrupt-clearing register.
  }
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit(i2c_master_dev_handle_t device,
                                          const uint8_t* command, size_t len, int timeout_ms) {
  assert(device == &stop_expander && device == stop_probe && !stop_timer_active);
  assert(len == 2 && timeout_ms == 30 && (command[0] == 0x06 || command[0] == 0x07));
  ++stop_mask_writes;
  const auto port = command[0] - 0x06;
  if (scenario == "bootstrap_stop_mask_readback_failed" && stop_mask_writes == 2)
    return ESP_OK;
  stop_masks[port] = command[1];
  if (scenario == "bootstrap_stop_mask_write_failed" && stop_mask_writes == 1)
    return ESP_FAIL; // Error after the simulated device accepted the write.
  if ((scenario == "bootstrap_display_stop_restore_retry" ||
       scenario == "bootstrap_stop_arming_restore_retry") && port == 0 &&
      command[1] == initial_stop_masks[port] && !restore_failed_once) {
    restore_failed_once = true;
    return ESP_FAIL;
  }
  return ESP_OK;
}
extern "C" esp_err_t gpio_config(const gpio_config_t* gpio) {
  assert(!nvs_init_calls && (!stop_probe || stop_probe == &stop_expander) && !stop_timer_active);
  assert(gpio->pin_bit_mask == (1UL << GPIO_NUM_21) && gpio->mode == GPIO_MODE_INPUT &&
         gpio->pull_up_en == GPIO_PULLUP_DISABLE && gpio->pull_down_en == GPIO_PULLDOWN_DISABLE &&
         gpio->intr_type == GPIO_INTR_DISABLE);
  ++gpio_configures;
  if (scenario == "bootstrap_stop_held_at_arm") stop_gpio_level = 0;
  return scenario == "bootstrap_stop_gpio_error" ||
         scenario == "bootstrap_stop_arming_restore_retry" ? ESP_FAIL : ESP_OK;
}
extern "C" int gpio_get_level(gpio_num_t gpio) {
  assert(gpio == GPIO_NUM_21 && gpio_configures == 1);
  assert(!stop_probe || stop_probe == &stop_expander);
  ++gpio_samples;
  return stop_gpio_level.load();
}
extern "C" esp_err_t esp_timer_create(const esp_timer_create_args_t* args,
                                       esp_timer_handle_t* handle) {
  assert(args->callback && !args->arg && args->dispatch_method == ESP_TIMER_TASK &&
         args->skip_unhandled_events && !stop_timer_callback && gpio_samples == 1);
  ++timer_creates;
  if (scenario == "bootstrap_stop_timer_create") return ESP_ERR_NO_MEM;
  stop_timer_callback = args->callback;
  *handle = &stop_timer;
  return ESP_OK;
}
extern "C" esp_err_t esp_timer_start_periodic(esp_timer_handle_t timer, uint64_t period_us) {
  assert(timer == &stop_timer && stop_timer_callback && !stop_timer_active && period_us == 10'000);
  if (scenario == "bootstrap_stop_timer_start") return ESP_FAIL;
  stop_timer_active = true;
  if (scenario == "bootstrap_stop_before_budget") stop_gpio_level = 0;
  if (scenario == "bootstrap_stop_consent_lost_arming") consent = false;
  return ESP_OK;
}
extern "C" esp_err_t esp_timer_stop(esp_timer_handle_t timer) {
  assert(timer == &stop_timer && K151DisplayStop::flag());
  return std::exchange(stop_timer_active, false) ? ESP_OK : ESP_ERR_INVALID_STATE;
}
extern "C" esp_err_t esp_timer_delete(esp_timer_handle_t timer) {
  assert(timer == &stop_timer && stop_timer_callback && !stop_timer_active);
  const auto late_callback = std::exchange(stop_timer_callback, nullptr);
  const auto reads_before = gpio_samples;
  late_callback(nullptr);
  assert(gpio_samples == reads_before); // An already dispatched callback is harmless.
  return ESP_OK;
}
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
  if (scenario != "bootstrap_scopes_separate") {
    assert(stop_timer_active && (stop_masks[0] & 0x18) == 0x18 && (stop_masks[1] & 0x0c) == 0x08);
  }
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
                          (std::string_view{key} == "budget" && budget_writes && consent && !stop_source()));
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
  if (scenario == "bootstrap_stop_at_reservation" && nvs_commits == 2) display_press();
  return ESP_OK;
}
extern "C" void nvs_close(nvs_handle_t handle) { assert(handle == 1 || handle == 2); }

extern "C" esp_err_t i2c_master_get_bus_handle(i2c_port_t port, i2c_master_bus_handle_t* out) {
  assert(port == I2C_NUM_1);
  if (!board_bus_registered) return ESP_ERR_INVALID_STATE;
  *out = &menu_bus;
  return ESP_OK;
}

namespace stackchan::standalone {
bool K151InstallHold::device_activation_allowed() { return scenario != "bootstrap_hold"; }
K151LcdPanel::~K151LcdPanel() = default;
bool K151LcdPanel::start(i2c_master_bus_handle_t bus, bool owner_task) {
  return bus == &menu_bus && owner_task && lvgl_on;
}
bool K151LcdPanel::shutdown() { return !setup_usb && !stop_probe && !stop_timer_active; }
bool K151LcdPanel::handoff_stop_input(i2c_master_bus_handle_t bus,
                                      const std::atomic_bool& expected_stop) {
  assert(bus == &menu_bus && &expected_stop == &stop_ && &expected_stop == &stop_source());
  assert(!stop_ && !stop_probe && !stop_timer_active && !network_starts && !nvs_init_calls);
  assert(++panel_handoffs == 1);
  return scenario != "bootstrap_stop_lcd_handoff_refused";
}
K151HeadTouchOwner::~K151HeadTouchOwner() = default;
bool K151HeadTouchOwner::attach_for_setup(i2c_master_bus_handle_t bus, bool exact, bool exclusive) {
  return bus == &menu_bus && exact && exclusive;
}
TouchConsentEvent K151HeadTouchOwner::poll_once(uint64_t) {
  if (setup_usb) return TouchConsentEvent::final_confirmed;
  owner_mode_ = true;
  return TouchConsentEvent::owner_window_open;
}
bool K151HeadTouchOwner::detach() { owner_mode_ = false; return !setup_usb; }
bool K151SetupLvgl::attach(K151LcdPanel&, bool exact, bool lock, bool local) {
  return exact && lock && local && lvgl_on;
}
bool K151SetupLvgl::present(TouchConsentPhase, OwnerSetupPhase, bool, bool, bool lock) {
  return lock && lvgl_on;
}
bool K151SetupLvgl::present_saved_setup(SavedSetupScreen) {
  return (restored_conversation() || initial_saved_conversation()) &&
         lvgl_on && !setup_usb && !network_starts;
}
bool K151SetupLvgl::detach(bool lock) { return lock && !setup_usb && !codec_running; }
bool K151SetupLvgl::begin_voice_review(uint64_t now, bool first, bool lock, bool one_turn) {
  assert(first == !restored_conversation());
  assert(lock && !setup_usb && !network_starts && !nvs_init_calls);
  assert(one_turn == !continuous_conversation());
  review_started_ms = now;
  return true;
}
K151SetupLvgl::ReviewResult K151SetupLvgl::poll_voice_review(uint64_t now, bool lock) {
  assert(lock && review_started_ms && !setup_usb && !network_starts && !nvs_init_calls);
  return now - review_started_ms >= 1200 ? ReviewResult::approved : ReviewResult::waiting;
}
bool K151SetupLvgl::present_voice_status(K151VoiceStatus status) {
  assert(conversation_case() && lvgl_on && stop_timer_active && !setup_usb && !K151DisplayStop::flag());
  if (!voice_status.empty() && voice_status.back() == status) return true;
  voice_status.push_back(status);
  const int calls_this_turn = calls - 3 * plays;
  if (status == K151VoiceStatus::connecting) assert(!nvs_init_calls && !network_starts);
  if (status == K151VoiceStatus::question) assert(mic_open && calls_this_turn == 0);
  switch (status) {
    case K151VoiceStatus::transcribing: assert(!mic_open && !amp_open && calls_this_turn == 0); break;
    case K151VoiceStatus::generating: assert(!mic_open && !amp_open && calls_this_turn == 1); break;
    case K151VoiceStatus::synthesizing: assert(!mic_open && !amp_open && calls_this_turn == 2); break;
    case K151VoiceStatus::playing: assert(!mic_open && !amp_open && calls_this_turn == 3); break;
    default: break;
  }
  if (status == K151VoiceStatus::trial_finished) {
    assert(mic_opens == 3 && plays == 1 && !mic_open && !amp_open && !pending_pcm);
    assert(!codec_running && !model_loaded && codec_stops == 1 && network_stops == 1);
  }
  if (status == K151VoiceStatus::transcribing && scenario == "bootstrap_conversation_stop_during_display")
    display_press();
  return !K151DisplayStop::flag();
}
void K151SecurePcSetup::stop() {}
K151ScpsUsbPort::~K151ScpsUsbPort() { assert(!setup_usb); }
bool K151ScpsUsbPort::start(uint64_t, bool exact, bool panel, bool uart, bool exclusive) {
  assert(exact && panel && uart && exclusive && lvgl_on && !restored_conversation());
  return running_ = setup_usb = true;
}
bool K151ScpsUsbPort::poll_once(uint64_t, bool lock) { return lock && setup_usb; }
bool K151ScpsUsbPort::finalize_after_touch(uint64_t now) {
  constexpr std::array<uint8_t, 4> ssid{'t', 'e', 's', 't'};
  return setup_.arm(now) && setup_.submit_wifi(ssid, "mock-password", now) &&
         setup_.submit_api_key("not-a-real-key-test", now) && setup_.confirm(now, true);
}
bool K151ScpsUsbPort::close_completed_transport() { return shutdown(); }
bool K151ScpsUsbPort::shutdown() { running_ = setup_usb = false; return true; }
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
  assert((conversation_case() || &given_owner == &owner) &&
         &given_stop == &stop_source() && given_owner && !given_stop && consent);
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
  assert(capture_idle() && model_loaded && consent && !stop_source());
  ++mic_opens;
  capture_reads = 0;
  wake_detections = 0;
  return mic_open = true;
}
bool K151CodecPort::microphone_off() { mic_open = false; return true; }
bool K151CodecPort::capture_mono_24k(std::span<int16_t> pcm) {
  assert(mic_open && !amp_open && pcm.size() == 240);
  const int frame = capture_reads++ / 2;
  const int onset = QuestionCapture::kInitialQuietFrames;
  const bool question_capture = mic_opens == 2 || (continuous_conversation() && mic_opens == 4);
  const bool question_frame = question_capture && frame >= onset && frame < onset + 4;
  const int16_t level = mic_opens == 4 ? 2400 : 2000;
  std::fill(pcm.begin(), pcm.end(), question_frame ? level : 0);
  return true;
}
bool K151CodecPort::speaker_on_low_volume(const std::atomic_bool& given_consent) {
  assert((conversation_case() || &given_consent == &consent) &&
         given_consent && !stop_source() && capture_idle() && calls == 3 * (plays + 1));
#ifdef STACKCHAN_TEST_REALTIME_WIRE
  assert(!speech_connected && speech_requested);
#endif
  return amp_open = true;
}
bool K151CodecPort::play_mono_24k(std::span<const int16_t> pcm) {
  assert(amp_open && !mic_open);
#ifdef STACKCHAN_TEST_REALTIME_WIRE
  assert(pcm.size() == 1 && pcm.front() == (plays == 0 ? 10 : 20));
#else
  assert(pcm.size() == 240 && pcm.front() == 10);
#endif
  ++plays;
  if (plays == 2 && scenario == "bootstrap_conversation_reboot_stop_playback")
    display_press();
  return pending_pcm = true;
}
bool K151CodecPort::wait_for_tx_tail(const std::atomic_bool&, const std::atomic_bool&,
                                    const std::atomic_bool&) {
  return pending_pcm && amp_open;
}
bool K151CodecPort::drain_output_before_mute() {
  return std::exchange(pending_pcm, false) && amp_open;
}
bool K151CodecPort::speaker_off(const std::atomic_bool*) { amp_open = false; return true; }
bool K151CodecPort::shutdown() {
  assert(!mic_open && !amp_open);
  if (codec_running) {
    ++codec_stops;
    if (scenario == "bootstrap_conversation_stop_during_release") display_press();
  }
  prepared_ = codec_running = false;
  if (scenario == "bootstrap_conversation_unverified_release") cleanup_unverified_ = true;
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
  assert((conversation_case() || &given_owner == &owner) && given_owner &&
         &given_stop == &stop_source() && supplied.data() == pack.data());
  assert(codec_running && !mic_open && !amp_open && consent && !given_stop);
  ++model_starts;
  if (scenario == "model_failure") return false;
  format_ = {16000, 160, 1, 16};
  if (scenario == "stop_during_model") stop = true;
  return model_loaded = true;
}
bool K151WakeNetPort::ready() const { return model_loaded && owner && !stop_source(); }
bool K151WakeNetPort::reset() { return ready(); }
NativeWakeResult K151WakeNetPort::detect(std::span<int16_t>) {
  if (conversation_case() && wake_detections++ < 2) return NativeWakeResult::none;
  const bool hear_wake = mic_opens == 1 || (continuous_conversation() && mic_opens == 3);
  return hear_wake ? NativeWakeResult::detected : NativeWakeResult::none;
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
  const int call_in_turn = calls - 3 * plays;
  assert(call_in_turn >= 0 && call_in_turn < 3 && req.endpoint == expected[call_in_turn]);
  assert(!realtime_conversation() || call_in_turn < 2);
  if (call_in_turn == 0) {
    if (scenario.starts_with("bootstrap_")) {
      const auto ledger = BudgetLedger::restore(durable_budget);
      const int already_charged = restored_conversation() ? 1 : 0;
      assert(ledger && ledger->count() == static_cast<size_t>(plays + 1 + already_charged));
      assert(nvs_commits == plays + 2 - already_charged);
    }
    assert(req.pcm24k.size() == 4 * QuestionCapture::kFrame);
    for (int16_t sample : req.pcm24k) assert(sample == (plays == 0 ? 2000 : 2400));
  }
#ifdef STACKCHAN_TEST_REALTIME_WIRE
  assert(realtime_conversation() && call_in_turn < 2 && !setup_usb);
  constexpr std::string_view transcript = R"({"text":"test question"})";
  constexpr std::string_view answer =
      R"({"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"test reply"}]}]})";
  assert(call_in_turn == 0 || req.text == "test question");
  assert(req.model == (call_in_turn == 0 ? "gpt-transcribe" : "gpt-6-luna"));
  const auto wire = call_in_turn == 0 ? transcript : answer;
  out.body.assign(wire.begin(), wire.end());
  ++calls;
#else
  out.body.assign(1, static_cast<uint8_t>(++calls));
#endif
  out.received_ms = static_cast<uint64_t>(now_us / 1'000);
  if (calls == failed_conversation_call()) return false;
  if (scenario == "revoke_during_stt") consent = false;
  if (scenario == "bootstrap_revoke_storage_at_stt") budget_writes = false;
  if (scenario == kStopDuringRequest[call_in_turn]) display_press();
  return true;
}
#ifndef STACKCHAN_TEST_REALTIME_WIRE
bool K151VoiceDecoder::transcription(std::span<const uint8_t>, std::string& out) {
  out = "test question"; return true;
}
bool K151VoiceDecoder::response_text(std::span<const uint8_t>, std::string& out) {
  out = "test reply"; return true;
}
bool K151VoiceDecoder::speech_pcm(std::span<const uint8_t>, std::vector<int16_t>& out) {
  out.assign(240, 10); return true;
}
bool K151RealtimeSpeechPort::synthesize_once(const VoiceApiRequest& request, std::string_view key,
    const std::function<bool()>& network_ready, const std::atomic_bool& paid,
    const std::atomic_bool& stopped, const std::function<bool()>& spend,
    std::vector<uint8_t>& pcm, uint64_t& completed_ms) const {
  assert(realtime_conversation() && calls == 3 * plays + 2 && !mic_open && !amp_open);
  assert(request.fixed_path == "/v1/realtime" && request.model == "gpt-realtime-2.1-mini");
  assert(request.voice == "marin" && request.text == "test reply" && request.pcm24k.empty());
  assert(key == "mock-only-credential" && paid && !stopped && network_ready() && spend() && !spend());
  ++calls;
  if (calls == failed_conversation_call()) return false;
  pcm = {10, 0};
  completed_ms = static_cast<uint64_t>(now_us / 1'000);
  return true;
}
#endif
}

#ifdef STACKCHAN_TEST_REALTIME_WIRE
extern "C" esp_err_t esp_crt_bundle_attach(void*) { return ESP_OK; }
extern "C" esp_transport_handle_t esp_transport_ssl_init() { return &tls_socket; }
extern "C" esp_transport_handle_t esp_transport_ws_init(esp_transport_handle_t parent) {
  assert(parent == &tls_socket && !speech_connected);
  return &ws_socket;
}
extern "C" void esp_transport_ssl_crt_bundle_attach(esp_transport_handle_t parent,
                                                    esp_err_t (*attach)(void*)) {
  assert(parent == &tls_socket && attach == esp_crt_bundle_attach);
}
extern "C" esp_err_t esp_transport_ws_set_config(esp_transport_handle_t ws,
                                                 const esp_transport_ws_config_t* config) {
  assert(ws == &ws_socket && config->propagate_control_frames);
  assert(std::string_view(config->auth) == "Bearer mock-only-credential");
  assert(std::string_view(config->ws_path) == "/v1/realtime?model=gpt-realtime-2.1-mini");
  return ESP_OK;
}
extern "C" int esp_transport_connect(esp_transport_handle_t ws, const char* host, int port,
                                     int timeout) {
  assert(ws == &ws_socket && std::string_view(host) == "api.openai.com" && port == 443);
  assert(timeout == 1500 && !setup_usb && !mic_open && !amp_open && !speech_connected);
  assert(calls == 3 * plays + 2);
  ++calls;
  speech_connected = true;
  speech_requested = false;
  speech_events_read = 0;
  return 0;
}
extern "C" int esp_transport_ws_get_upgrade_request_status(esp_transport_handle_t ws) {
  assert(ws == &ws_socket && speech_connected);
  return 101;
}
extern "C" esp_err_t esp_transport_ws_set_auth(esp_transport_handle_t ws, const char* auth) {
  assert(ws == &ws_socket && speech_connected && !auth);
  return ESP_OK;
}
extern "C" int esp_transport_read(esp_transport_handle_t ws, char* out, int size, int timeout) {
  constexpr std::array<std::string_view, 6> events{
      R"({"type":"session.created","session":{"type":"realtime","audio":{"output":{"format":{"type":"audio/pcm","rate":24000}}}}})",
      R"({"type":"conversation.created","conversation":{"id":"conv_a"}})",
      R"({"type":"response.created","response":{"id":"resp_a","status":"in_progress","metadata":{"stackchan":"speech"}}})",
      R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"CgA="})",
      R"({"type":"response.output_audio.done","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0})",
      R"({"type":"response.done","response":{"id":"resp_a","status":"completed"}})",
  };
  assert(ws == &ws_socket && speech_connected && timeout == 250);
  assert(speech_events_read < events.size());
  assert(speech_requested == (speech_events_read != 0));
  speech_event = events[speech_events_read++];
  if (speech_events_read == 4 && plays == 1)
    speech_event = R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"FAA="})";
  if (speech_events_read == events.size() && calls == failed_conversation_call())
    speech_event = R"({"type":"response.done","response":{"id":"resp_a","status":"incomplete"}})";
  assert(speech_event.size() <= static_cast<size_t>(size));
  std::memcpy(out, speech_event.data(), speech_event.size());
  now_us += 1'000;
  return static_cast<int>(speech_event.size());
}
extern "C" int esp_transport_poll_read(esp_transport_handle_t, int) {
  assert(false && "no control frame in this exchange");
  return -1;
}
extern "C" ws_transport_opcodes_t esp_transport_ws_get_read_opcode(esp_transport_handle_t ws) {
  assert(ws == &ws_socket && speech_connected);
  return WS_TRANSPORT_OPCODES_TEXT;
}
extern "C" int esp_transport_ws_get_read_payload_len(esp_transport_handle_t ws) {
  assert(ws == &ws_socket && speech_connected);
  return static_cast<int>(speech_event.size());
}
extern "C" bool esp_transport_ws_get_fin_flag(esp_transport_handle_t ws) {
  assert(ws == &ws_socket && speech_connected);
  return true;
}
extern "C" int esp_transport_ws_send_raw(esp_transport_handle_t ws, ws_transport_opcodes_t opcode,
                                         const char* data, int size, int timeout) {
  assert(ws == &ws_socket && speech_connected && !speech_requested && speech_events_read == 1);
  assert(opcode == (WS_TRANSPORT_OPCODES_FIN | WS_TRANSPORT_OPCODES_TEXT) && timeout == 1500);
  const std::string_view request(data, size);
  assert(request.find(R"("type":"response.create")") != request.npos);
  assert(request.find(R"("text":"test reply")") != request.npos);
  assert(request.find("test question") == request.npos);
  speech_requested = true;
  return size;
}
extern "C" int esp_transport_close(esp_transport_handle_t ws) {
  assert(ws == &ws_socket && speech_connected);
  speech_connected = false;
  return 0;
}
extern "C" esp_err_t esp_transport_destroy(esp_transport_handle_t port) {
  assert((port == &ws_socket || port == &tls_socket) && !speech_connected);
  return ESP_OK;
}
#endif

void exercise_conversation() {
  using Phase = K151ConversationOwner::Phase;
  auto& conversation = K151ConversationOwner::instance();
  board_bus_registered = false;
  const bool realtime = realtime_conversation();
  const bool continuous = continuous_conversation();
  const VoiceModelConfig models{realtime ? "gpt-transcribe" : "stt", realtime ? "gpt-6-luna" : "gpt",
                                realtime ? "gpt-realtime-2.1-mini" : "tts",
                                realtime ? "marin" : "voice"};
  const auto request = [&](bool paid, bool budget) {
    const auto mode = continuous ? K151VoiceMode::continuous : K151VoiceMode::one_paid_turn;
    return conversation.request_voice(models, pack, paid, budget, true, mode);
  };
  MockOwnerRecords records;
  MockOwnerCipher cipher;
  SavedOwnerCredentials saved(records, cipher);
  if (restored_conversation()) {
    RuntimeSecrets previous_boot;
    constexpr std::array<uint8_t, 4> ssid{'t', 'e', 's', 't'};
    assert(previous_boot.provision(ssid, "mock-password", "not-a-real-key-test", true));
    assert(saved.save_first(previous_boot, [] { return true; }));
    if (scenario != "bootstrap_conversation_reboot_no_budget") {
      auto ledger = BudgetLedger::fresh();
      assert(ledger.reserve(static_cast<uint64_t>(std::time(nullptr)) - 120, true,
                            [](auto) { return true; }));
      durable_budget = ledger.serialize();
    }
  } else if (initial_saved_conversation()) {
    records.fail_commit = scenario == "bootstrap_conversation_save_failed";
    records.before_commit = [] {
      const auto budget = BudgetLedger::restore(durable_budget);
      assert(budget && budget->count() == 0 && nvs_commits == 1 &&
             stop_timer_active && !network_starts && !setup_usb);
    };
  }
  assert(!request(true, true) &&
         conversation.start({true, true}, true,
                            restored_conversation() || initial_saved_conversation() ? &saved : nullptr));
  assert(!cipher.opens);
  now_us += 50'000;
  if (!restored_conversation()) {
    assert(conversation.poll().phase == Phase::setup && setup_usb);
    now_us += 50'000;
  }
  assert(conversation.poll().phase == Phase::cloud_off && !setup_usb);
  assert(cipher.opens == (restored_conversation() ? 1U : 0U));
  if (initial_saved_conversation()) assert(records.commits == 0 && records.data.empty());
  if (restored_conversation() || initial_saved_conversation())
    assert(!conversation.request_voice(models, pack, true, true, false, K151VoiceMode::one_paid_turn));
  assert(!request(false, true) && !request(true, false) && !review_started_ms);
  assert(!calls && !network_starts && !nvs_init_calls);
  assert(request(true, true));
  current_task = &other_task;
  assert(conversation.poll().phase == Phase::fault && !conversation.shutdown() && board_bus_registered);
  current_task = &board_task;
  for (unsigned i = 0; i < 23; ++i) {
    now_us += 50'000;
    assert(conversation.poll().phase == Phase::voice_review && !network_starts && !nvs_init_calls);
  }
  now_us += 50'000;
  const auto started = conversation.poll().phase;
  if (scenario == "bootstrap_conversation_reboot_no_budget") {
    assert(started == Phase::fault && !network_starts && !nvs_commits && !calls && !mic_opens);
    assert(!board_bus_registered && !stop_timer_active && !setup_usb);
    return;
  }
  if (initial_saved_conversation()) {
    assert(records.commits == 1 && cipher.seals == 1 && nvs_commits == 1 && !calls && !mic_opens);
    if (records.fail_commit) {
      assert(started == Phase::fault && records.data.empty() && !network_starts &&
             !board_bus_registered && !stop_timer_active);
    } else {
      assert(started == Phase::voice && !records.data.empty() && network_starts == 1);
      display_press();
      assert(conversation.poll().phase == Phase::stopped && !board_bus_registered &&
             !stop_timer_active && network_stops == 1 && !calls && !mic_opens);
    }
    return;
  }
  assert(started == Phase::voice && network_starts == 1 && !setup_usb);
  assert(conversation.poll().voice == NativeVoiceStep::waiting_network);
  assert(voice_status == std::vector<K151VoiceStatus>{K151VoiceStatus::connecting});
  if (scenario == "bootstrap_conversation_stop") {
    display_press();
    assert(conversation.poll().phase == Phase::stopped && !board_bus_registered &&
           !calls && !mic_opens && !setup_usb);
    return;
  }
  auto state = conversation.poll();
  assert(state.voice == NativeVoiceStep::listening && voice_status.back() == K151VoiceStatus::listening);
  const auto capture_and_answer = [&] {
    for (int i = 0; i < 4 && state.voice == NativeVoiceStep::listening; ++i) {
      now_us += 20'000;
      state = conversation.poll();
    }
    assert(state.voice == NativeVoiceStep::questioning && voice_status.back() == K151VoiceStatus::question);
    for (unsigned i = 0; i < 200 && state.voice == NativeVoiceStep::questioning; ++i) {
      now_us += 20'000;
      state = conversation.poll();
    }
  };
  capture_and_answer();
  if (scenario == "bootstrap_conversation_stop_during_display") {
    assert(state.phase == Phase::stopped && !calls && !plays && !board_bus_registered);
    assert(voice_status.back() == K151VoiceStatus::transcribing);
    return;
  }
  if (const auto failed_call = failed_conversation_call()) {
    assert(state.phase == Phase::showing_trial_result && state.voice == NativeVoiceStep::stopped);
    const std::array stages{K151VoiceStatus::transcribing, K151VoiceStatus::generating,
                            K151VoiceStatus::synthesizing};
    assert(voice_status.back() == stages[failed_call - 1]);
    assert(calls == failed_call && !plays && !mic_open && !amp_open);
#ifdef STACKCHAN_TEST_REALTIME_WIRE
    assert(!speech_connected && speech_requested);
#endif
    assert(board_bus_registered && lvgl_on && !stop_timer_active && network_stops == 1);
    now_us += 2'999'000;
    assert(conversation.poll().phase == Phase::showing_trial_result && board_bus_registered);
    now_us += 1'000;
    assert(conversation.poll().phase == Phase::stopped);
    assert(!board_bus_registered && !lvgl_on && calls == failed_call && !request(true, true));
    return;
  }
  assert(state.phase == Phase::voice && state.voice == NativeVoiceStep::answered && calls == 3);
  now_us += 600'000;
  state = conversation.poll();
  if (continuous) {
    assert(state.phase == Phase::voice && state.voice == NativeVoiceStep::listening);
    assert(voice_status.back() == K151VoiceStatus::listening && mic_opens == 3 && mic_open);
    assert(!amp_open && stop_timer_active && calls == 3 && plays == 1);
    capture_and_answer();
    if (scenario == "bootstrap_conversation_reboot_stop_playback") {
      assert(state.phase == Phase::stopped && !board_bus_registered && !stop_timer_active);
      assert(calls == 6 && plays == 2 && !mic_open && !amp_open && network_stops == 1);
      now_us += 600'000;
      assert(conversation.poll().phase == Phase::stopped && calls == 6 && plays == 2);
      return;
    }
    assert(state.phase == Phase::voice && state.voice == NativeVoiceStep::answered);
    assert(calls == 6 && plays == 2 && !mic_open && !amp_open && !pending_pcm);
    assert(nvs_commits == (restored_conversation() ? 2 : 3));
    now_us += 600'000;
    state = conversation.poll();
    assert(state.phase == Phase::voice && state.voice == NativeVoiceStep::listening);
    assert(voice_status.back() == K151VoiceStatus::listening && mic_opens == 5 && mic_open);
    assert(network_starts == 1 && model_starts == 1 && codec_starts == 1);
    display_press();
    assert(conversation.poll().phase == Phase::stopped && !mic_open && !board_bus_registered);
    assert(calls == 6 && !stop_timer_active && network_stops == 1);
    return;
  }
  assert(mic_opens == 3 && plays == 1 && !pending_pcm && !mic_open && !amp_open);
  if (scenario == "bootstrap_conversation_stop_during_release") {
    assert(state.phase == Phase::stopped && !board_bus_registered && !stop_timer_active);
    assert(voice_status.back() == K151VoiceStatus::returning && calls == 3);
    return;
  }
  if (scenario == "bootstrap_conversation_unverified_release") {
    assert(state.phase == Phase::fault && !conversation.shutdown() && board_bus_registered);
    assert(voice_status.back() == K151VoiceStatus::returning);
    std::_Exit(0); // The real owner task and borrowed board live until reset.
  }
  assert(state.phase == Phase::showing_trial_result && state.voice == NativeVoiceStep::trial_standby);
  const std::vector expected{K151VoiceStatus::connecting, K151VoiceStatus::listening,
      K151VoiceStatus::question, K151VoiceStatus::transcribing, K151VoiceStatus::generating,
      K151VoiceStatus::synthesizing, K151VoiceStatus::playing,
      K151VoiceStatus::returning, K151VoiceStatus::trial_finished};
  assert(voice_status == expected);
  assert(board_bus_registered && lvgl_on && !stop_timer_active && network_stops == 1);
  now_us += 2'999'000;
  assert(conversation.poll().phase == Phase::showing_trial_result && board_bus_registered);
  now_us += 1'000;
  assert(conversation.poll().phase == Phase::trial_complete);
  assert(!board_bus_registered && !lvgl_on && !stop_timer_active && !request(true, true));
  assert(conversation.poll().phase == Phase::trial_complete && calls == 3 && nvs_commits == 2);
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
  K151HeadTouchOwner touch(owner, stop_source());
  owner = true;
  K151LocalOwnerSetup setup(owner, trusted_input, stop_source());
  const std::array<uint8_t, 4> ssid{'t', 'e', 's', 't'};
  assert(setup.arm(1000) && setup.submit_wifi(ssid, "mock-password", 1000));
  assert(setup.submit_api_key("not-a-real-key-test", 1000));
  if (scenario != "bootstrap_unconfirmed") assert(touch.finish_owner_setup(setup, 1000));
  if (scenario == "bootstrap_no_budget_scope") budget_writes = false;
  i2c_master_bus_t wrong_bus;
  auto board_bus = &menu_bus;
  if (scenario == "bootstrap_missing_bus") board_bus = nullptr;
  if (scenario == "bootstrap_wrong_bus") board_bus = &wrong_bus;
  K151LcdPanel panel(stop_source());
  const bool paid_trial = scenario == "bootstrap_one_paid_trial";
  K151VoiceBootstrap bootstrap(setup, panel, consent, budget_writes, {true, true}, board_bus,
      paid_trial ? K151VoiceMode::one_paid_turn : K151VoiceMode::continuous);
  if (scenario == "bootstrap_manual_stop") {
    bootstrap.stop();
    assert(!setup.ready());
  }
  const bool first_provision = !previous && scenario != "bootstrap_first_denied";
  const auto stop_at = std::ranges::find(kStopDuringRequest, scenario);
  const bool stop_inside_request = stop_at != kStopDuringRequest.end();
  const int stop_stage = static_cast<int>(stop_at - kStopDuringRequest.begin()) + 1;
  const bool turn = paid_trial || stop_inside_request || scenario == "bootstrap_first_turn" ||
                    scenario == "bootstrap_stop_at_reservation" ||
                    scenario == "bootstrap_revoke_storage_at_stt";
  const bool restore_retry = scenario == "bootstrap_display_stop_restore_retry";
  const bool stop_waiting_network =
      restore_retry || scenario == "bootstrap_display_stop_waiting_network";
  const bool preconfigured = scenario == "bootstrap_stop_masks_already_configured";
  const bool accepted = previous || turn || stop_waiting_network || preconfigured ||
                       scenario == "bootstrap_usb_detached";
  assert(bootstrap.start({"stt", "gpt", "tts", "voice"}, pack, first_provision) == accepted);
  assert(durable_profile == std::vector<uint8_t>{0x7b});
  if (!accepted) {
    assert(bootstrap.poll() == NativeVoiceStep::stopped && calls == 0 && codec_starts == 0);
    const bool early = scenario == "bootstrap_unconfirmed" || scenario == "bootstrap_hold" ||
                       scenario == "bootstrap_no_budget_scope" ||
                       scenario == "bootstrap_manual_stop" ||
                       scenario == "bootstrap_missing_bus" || scenario == "bootstrap_wrong_bus" ||
                       scenario == "bootstrap_wrong_stop_binding";
    const bool stop_admission_failed = scenario.starts_with("bootstrap_stop_") &&
                                       scenario != "bootstrap_stop_at_reservation";
    assert(nvs_init_calls == int(!early && !stop_admission_failed));
    assert(!stop_probe && !stop_timer_active && !stop_timer_callback);
    assert(stop_masks == initial_stop_masks);
    if (early) assert(!panel_handoffs && !gpio_configures && !timer_creates);
    if (scenario == "bootstrap_stop_lcd_handoff_refused")
      assert(panel_handoffs == 1 && !stop_probe_closes && !gpio_configures && !timer_creates);
    if (stop_admission_failed) assert(K151DisplayStop::flag() && !setup.ready());
    if (scenario == "bootstrap_stop_probe_busy") assert(stop_probe_closes == 2);
    if (scenario == "bootstrap_stop_arming_restore_retry") assert(restore_failed_once);
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
  assert(nvs_init_calls == 1 && network_starts == 1 && !setup.ready() && stop_timer_active);
  assert(nvs_commits == int(!previous) && codec_starts == 0);
  if (previous) assert(durable_budget == initial_budget);
  if (scenario == "bootstrap_usb_detached") trusted_input = false;
  assert(bootstrap.poll() == NativeVoiceStep::waiting_network);
  if (stop_waiting_network) {
    display_press();
    assert(bootstrap.poll() == NativeVoiceStep::stopped);
    assert(calls == 0 && codec_starts == 0 && model_starts == 0 && network_stops == 1);
    assert(!stop_timer_active && !stop_timer_callback && K151DisplayStop::flag());
    if (restore_retry) {
      assert(restore_failed_once && stop_probe == &stop_expander);
      bootstrap.stop();
    }
    assert(!stop_probe && stop_masks == initial_stop_masks);
    return;
  }
  assert(bootstrap.poll() == NativeVoiceStep::questioning && codec_starts == 1);
  if (turn) {
    const bool stop_at_reservation = scenario == "bootstrap_stop_at_reservation";
    const bool revoke_at_stt = scenario == "bootstrap_revoke_storage_at_stt";
    const bool interrupted = stop_at_reservation || revoke_at_stt || stop_inside_request;
    auto outcome = NativeVoiceStep::questioning;
    for (int i = 0; i < 200 && outcome == NativeVoiceStep::questioning; ++i) {
      now_us += 20'000;
      outcome = bootstrap.poll();
    }
    assert(outcome == (interrupted ? NativeVoiceStep::stopped : NativeVoiceStep::answered));
    const int expected_calls =
        stop_at_reservation ? 0 : revoke_at_stt ? 1 : stop_inside_request ? stop_stage : 3;
    assert(calls == expected_calls &&
           plays == int(!interrupted));
    const auto stored = BudgetLedger::restore(durable_budget);
    assert(nvs_commits == 2 && stored && stored->count() == 1);
    if (interrupted) assert(!stop_timer_active && !stop_timer_callback && K151DisplayStop::flag());
    if (paid_trial) {
      now_us += 100'000;
      assert(bootstrap.poll() == NativeVoiceStep::cooldown && mic_opens == 2);
      now_us += 500'000;
      assert(bootstrap.poll() == NativeVoiceStep::trial_standby);
      assert(mic_opens == 3 && !mic_open && !amp_open);
      assert(bootstrap.poll() == NativeVoiceStep::stopped);
      assert(calls == 3 && plays == 1 && nvs_commits == 2);
    }
  } else {
    budget_writes = false;
    assert(bootstrap.poll() == NativeVoiceStep::stopped);
  }
  bootstrap.stop();
  assert(!stop_timer_active && !stop_timer_callback && K151DisplayStop::flag());
  assert(!stop_probe && stop_masks == initial_stop_masks);
  if (preconfigured) assert(stop_mask_writes == 0);
  assert(!mic_open && !amp_open && codec_stops == 1 && model_stops == 1 && network_stops == 1);
  assert(durable_profile == std::vector<uint8_t>{0x7b});
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  if (scenario == "bootstrap_stop_masks_already_configured") stop_masks = {0xff, 0xfb};
  initial_stop_masks = stop_masks;
  if (conversation_case()) {
    exercise_conversation();
    return 0;
  }
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
