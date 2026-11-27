// SPDX-License-Identifier: MIT
#include "k151_owner_session.hpp"
#include "saved_owner_credentials_fixture.hpp"

#include "k151_display_stop.hpp"
#include "k151_install_hold.hpp"
#include <freertos/task.h>

#include <array>
#include <cassert>
#include <string_view>

using namespace stackchan::standalone;

struct i2c_master_bus_t {};
namespace {
i2c_master_bus_t board_bus;
int board_task, other_task;
void* current_task = &board_task;
int core = 0;
std::atomic_bool stopped{false};
std::string_view scenario;
uint64_t ms = 1000;
uint64_t head_started{};
bool i2c = false, lvgl = false, lcd = false, view = false, head = false, usb = false;
bool head_window = false, panel_reviewed = false, pairing_complete = false, ready_page = false;
bool retry_failed = false;
uint64_t voice_prompt_at = 0;
unsigned touches = 0, receive_calls = 0, activations = 0;
bool unlock_case() { return scenario.starts_with("unlock_"); }
bool unlock_enroll() { return scenario == "unlock_enroll"; }
constexpr std::array<char, kOwnerCodeLength> mock_code{
    '0','1','2','3','4','5','6','7','8','9','A','B','C','D','E','F'};
bool unlock_busy = false;

struct MockUnlock final : OwnerUnlockPort {
  explicit MockUnlock(SavedOwnerCredentials& saved) : saved(saved) {}
  SavedOwnerCredentials& saved;
  uint64_t began = 0;
  unsigned reads = 0, generated = 0, cancelled = 0;
  ReadCode inspect() override {
    ++reads;
    assert(head_window && !usb);
    return unlock_enroll() ? ReadCode::missing : ReadCode::found;
  }
  bool generate(std::span<char, kOwnerCodeLength> out) override {
    assert(unlock_enroll() && pairing_complete && !usb);
    ++generated;
    std::copy(mock_code.begin(), mock_code.end(), out.begin());
    return true;
  }
  bool begin(OwnerCode code) override {
    assert(!began && !usb && std::ranges::equal(code, mock_code));
    began = ms;
    return true;
  }
  State state() const override {
    assert(began);
    return ms - began < 200 || scenario == "unlock_timeout" ? State::deriving : State::ready;
  }
  SavedOwnerCredentials& credentials() override { return saved; }
  void cancel() override { ++cancelled; }
};
}

TaskHandle_t xTaskGetCurrentTaskHandle() { return current_task; }
int xPortGetCoreID() { return core; }
extern "C" int64_t esp_timer_get_time() { return int64_t(ms * 1000); }
extern "C" bool lv_is_initialized() { return lvgl; }
extern "C" void lv_init() { assert(i2c && !lvgl); lvgl = true; }
extern "C" void lv_deinit() { assert(lvgl && !lcd && !view); lvgl = false; }
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t* cfg,
                                       i2c_master_bus_handle_t* out) {
  ++activations;
  assert(cfg->i2c_port == I2C_NUM_1);
  assert(cfg->sda_io_num == 12 && cfg->scl_io_num == 11 && cfg->glitch_ignore_cnt == 7);
  if (i2c || scenario == "bus_failed") return ESP_FAIL;
  i2c = true;
  *out = &board_bus;
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_get_bus_handle(i2c_port_t port, i2c_master_bus_handle_t* out) {
  assert(port == I2C_NUM_1);
  if (!i2c) return ESP_ERR_NOT_FOUND;
  *out = &board_bus;
  return ESP_OK;
}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t bus) {
  assert(bus == &board_bus && i2c && !lcd && !head && !view && !usb);
  i2c = false;
  return scenario == "ambiguous_bus_release" ? ESP_FAIL : ESP_OK;
}

namespace stackchan::standalone {
const std::atomic_bool& K151DisplayStop::flag() { return stopped; }
bool K151InstallHold::device_activation_allowed() { return scenario != "hold"; }
K151LcdPanel::~K151LcdPanel() { assert(!lcd || scenario == "existing_bus"); }
bool K151LcdPanel::start(i2c_master_bus_handle_t bus, bool requested) {
  assert(i2c && bus == &board_bus && lvgl && requested);
  return lcd = scenario != "panel_failed";
}
bool K151LcdPanel::shutdown() { assert(!view && !usb); lcd = false; return true; }
bool K151SetupLvgl::attach(K151LcdPanel&, bool verified, bool lock, bool local) {
  assert(lvgl && lcd && verified && lock && local);
  return view = scenario != "view_failed";
}
bool K151SetupLvgl::present_saved_setup(SavedSetupScreen screen) {
  assert(screen == SavedSetupScreen::presence && view && !usb);
  return scenario == "save_first_pairing" || unlock_case();
}
bool K151SetupLvgl::present_unlock(UnlockScreen screen, const OwnerCode* generated) {
  assert(unlock_case() && !usb && view);
  unlock_busy = screen == UnlockScreen::deriving;
  if (!unlock_busy) {
    assert((screen == UnlockScreen::enroll) == unlock_enroll());
    assert((generated != nullptr) == unlock_enroll());
    unlock_input_.set_generated(generated ? *generated : OwnerCode(mock_code));
  }
  return true;
}
K151SetupLvgl::UnlockChoice K151SetupLvgl::poll_unlock() {
  if (!unlock_busy) return UnlockChoice::confirm;
  if (scenario == "unlock_cancel") return UnlockChoice::cancel;
  if (scenario == "unlock_stop") stopped = true;
  return UnlockChoice::waiting;
}
bool K151SetupLvgl::finish_unlock(bool restored) {
  assert(unlock_case() && unlock_busy && restored == !unlock_enroll() && !usb);
  ready_page = true;
  return true;
}
bool K151SetupLvgl::present(TouchConsentPhase phase, OwnerSetupPhase ready,
                           bool input, bool error, bool lock) {
  assert(lock && view && !error);
  if (scenario == "presence_frame_failed" && phase == TouchConsentPhase::clear_for_arm)
    return false;
  if (phase == TouchConsentPhase::owner_window) assert(usb && input);
  if (ready == OwnerSetupPhase::ready) {
    assert(phase == TouchConsentPhase::consumed && usb && pairing_complete && input);
    if (scenario == "ready_frame_failed") return false;
    ready_page = true;
  }
  return true;
}
bool K151SetupLvgl::detach(bool lock) { assert(lock && !usb); view = false; return true; }
bool K151SetupLvgl::begin_voice_review(uint64_t now, bool first_budget, bool lock, bool one_turn) {
  assert(now == ms && lock && view && ready_page && !usb);
  assert(first_budget == (scenario != "existing_ledger_scope" && scenario != "unlock_restored"));
  assert(!one_turn);
  voice_prompt_at = now;
  return scenario != "voice_frame_failed";
}
K151SetupLvgl::ReviewResult K151SetupLvgl::poll_voice_review(uint64_t now, bool lock) {
  assert(now == ms && lock && view && voice_prompt_at && !usb);
  if (scenario == "voice_read_failed") return ReviewResult::fault;
  if (scenario == "voice_review_timeout" || now - voice_prompt_at < 1200U)
    return ReviewResult::waiting;
  if (scenario == "stop_during_voice_review") stopped = true;
  return ReviewResult::approved;
}
bool K151HeadTouchOwner::attach_for_setup(i2c_master_bus_handle_t bus, bool exact, bool exclusive) {
  assert(i2c && lcd && view && bus == &board_bus && exact && exclusive);
  head_started = ms;
  return head = scenario != "head_failed";
}
TouchConsentEvent K151HeadTouchOwner::poll_once(uint64_t now) {
  assert(head && i2c && now == ms);
  ++touches;
  last_read_failed_ = scenario == "head_read_error";
  if (last_read_failed_ || (now - head_started >= 30000U && scenario != "unlock_timeout"))
    return TouchConsentEvent::invalidated;
  if (!head_window && scenario != "no_head_touch" && now - head_started >= 3050U) {
    owner_mode_ = true;
    head_window = true;
    return TouchConsentEvent::owner_window_open;
  }
  if (panel_reviewed && now >= head_started + 6400U)
    return TouchConsentEvent::final_confirmed;
  return TouchConsentEvent::none;
}
bool K151HeadTouchOwner::detach() {
  assert(!usb);
  owner_mode_ = false;
  if (head && scenario == "cleanup_retry" && !retry_failed) {
    retry_failed = true;
    return false;
  }
  head = false;
  return true;
}
K151HeadTouchOwner::~K151HeadTouchOwner() { assert(!head); }
K151ScpsUsbPort::~K151ScpsUsbPort() { assert(!usb); }
void K151SecurePcSetup::stop() {}
bool K151ScpsUsbPort::start(uint64_t now, bool exact, bool panel, bool uart, bool exclusive) {
  assert(now == ms && exact && panel && uart && exclusive && lcd && head_window && !usb);
  return usb = scenario != "usb_failed";
}
bool K151ScpsUsbPort::poll_once(uint64_t now, bool lock) {
  assert(now == ms && lock && usb && head_window && !pairing_complete);
  ++receive_calls;
  if (scenario == "usb_stop") stopped = true;
  if (scenario == "review_failed" || stopped) return false;
  if (receive_calls >= 5) panel_reviewed = true;
  return true;
}
bool K151ScpsUsbPort::finalize_after_touch(uint64_t now) {
  assert(now == ms && usb && panel_reviewed && !ready_page);
  constexpr std::array<uint8_t, 4> ssid{'t','e','s','t'};
  pairing_complete = setup_.arm(now) && setup_.submit_wifi(ssid, "synthetic-password", now) &&
      setup_.submit_api_key("synthetic-unit-test-token", now) && setup_.confirm(now, true);
  return pairing_complete;
}
bool K151ScpsUsbPort::close_completed_transport() {
  assert(usb && pairing_complete && ready_page);
  if (scenario == "stop_while_draining") stopped = true;
  if (scenario == "ack_failed" || stopped) return false;
  usb = false;
  return true;
}
bool K151ScpsUsbPort::shutdown() { usb = false; return true; }
}

int main(int argc, char* argv[]) {
  assert(argc == 2);
  scenario = argv[1];
  const bool saved_pairing = scenario == "save_first_pairing";
  MockOwnerRecords records;
  MockOwnerCipher cipher;
  SavedOwnerCredentials saved(records, cipher);
  MockUnlock unlock(saved);
  if (unlock_case() && !unlock_enroll()) {
    RuntimeSecrets previous;
    constexpr std::array<uint8_t, 4> ssid{'t', 'e', 's', 't'};
    assert(previous.provision(ssid, "synthetic-password", "synthetic-unit-test-token", true));
    assert(saved.save_first(previous, [] { return true; }));
    records.commits = 0;
    cipher.reject = scenario == "unlock_wrong";
  }
  K151OwnerSession session;
  assert(!session.handoff());
  if (scenario == "existing_lvgl") lvgl = true;
  if (scenario == "existing_bus") i2c = true;
  const auto started = session.start(scenario != "wrong_board", scenario != "unverified_lcd",
                                     saved_pairing ? &saved : nullptr,
                                     unlock_case() ? &unlock : nullptr);
  using Startup = K151OwnerSession::StartupStage;
  if (scenario == "hold" || scenario == "wrong_board" || scenario == "unverified_lcd" ||
      scenario == "existing_lvgl" || scenario == "existing_bus") {
    assert(!started && activations == (scenario == "existing_bus" ? 1U : 0U) &&
           !session.handoff());
    assert(session.startup_stage() ==
           (scenario == "existing_bus" ? Startup::board_bus : Startup::preconditions));
    assert(session.shutdown());
    assert(lvgl == (scenario == "existing_lvgl") && i2c == (scenario == "existing_bus"));
    return 0;
  }
  assert(activations == 1);
  const auto failed_stage = scenario == "bus_failed" ? Startup::board_bus :
      scenario == "panel_failed" ? Startup::panel :
      scenario == "view_failed" ? Startup::view :
      scenario == "presence_frame_failed" ? Startup::presence_frame :
      scenario == "head_failed" ? Startup::head : Startup::ready;
  if (failed_stage != Startup::ready) {
    assert(!started && !i2c && !lvgl && !session.handoff());
    assert(session.startup_stage() == failed_stage);
    return 0;
  }
  assert(started && i2c && lvgl && head && !usb);
  assert(!session.start(true, true));
  assert(session.startup_stage() == Startup::ready);
  using Step = K151OwnerSession::Step;
  using Failure = scpswire::SetupFailure;
  assert(!session.request_voice_review(true, true, true));
  if (scenario == "wrong_task" || scenario == "wrong_core") {
    if (scenario == "wrong_task") current_task = &other_task;
    else core = 1;
    assert(session.poll() == Step::fault && !session.handoff() && !session.shutdown());
    assert(!touches && head && i2c);
    current_task = &board_task;
    core = 0;
    assert(session.shutdown() && !i2c);
    return 0;
  }
  if (scenario == "clock_backward" || scenario == "clock_gap") {
    ms = scenario == "clock_backward" ? 999 : 1251;
    assert(session.poll() == Step::fault && !touches && !i2c);
    assert(session.early_setup_failure() ==
           (scenario == "clock_backward" ? Failure::clock_backwards : Failure::sample_gap));
    return 0;
  }
  Step terminal = Step::idle;
  const uint64_t end = scenario == "unlock_timeout" ? 70000 :
                       scenario == "no_head_touch" ? 31000 : 8000;
  for (; ms <= end; ms += 50) {
    terminal = session.poll();
    if (terminal == Step::fault || terminal == Step::stopped || terminal == Step::ready) break;
    assert(records.commits == 0);
    const unsigned previous = touches;
    assert(session.poll() == terminal && touches == previous);
    assert(!session.handoff());
  }
  if (saved_pairing)
    assert(terminal == Step::ready && pairing_complete && records.reads == 1 &&
           records.commits == 0 && cipher.seals == 0 && records.data.empty());
  if (unlock_case()) {
    assert(unlock.reads == 1 && unlock.began && unlock.generated == unsigned(unlock_enroll()));
    assert(!usb && !records.commits && (unlock_enroll() || receive_calls == 0));
    if (scenario != "unlock_restored" && !unlock_enroll()) {
      const bool cancelled = scenario == "unlock_cancel" || scenario == "unlock_stop";
      assert(terminal == (cancelled ? Step::stopped : Step::fault) && unlock.cancelled == 1);
      assert(!i2c && !session.handoff() && !session.request_voice_review(true, true, true));
      return 0;
    }
    assert(terminal == Step::ready);
  }
  if (terminal == Step::ready) {
    assert(terminal == Step::ready && i2c && head && lcd && !usb);
    assert(!session.handoff() && !voice_prompt_at);
    assert(!session.request_voice_review(false, true, true) && !voice_prompt_at);
    assert(!session.request_voice_review(true, false, true) && !voice_prompt_at);
    const bool first = scenario != "existing_ledger_scope";
    if (scenario == "voice_frame_failed") {
      assert(!session.request_voice_review(true, true, first));
      assert(session.poll() == Step::fault && !i2c && !session.handoff());
      return 0;
    }
    assert(session.request_voice_review(true, true, first) && voice_prompt_at == ms);
    assert(!session.request_voice_review(true, true, first));
    const unsigned previous = touches;
    const unsigned previous_usb = receive_calls;
    for (unsigned i = 0; i < 610; ++i) {
      ms += 50;
      terminal = session.poll();
      if (terminal != Step::voice_review) break;
      assert(!session.handoff());
    }
    assert(touches == previous && receive_calls == previous_usb);
    if (scenario == "voice_read_failed" || scenario == "voice_review_timeout" ||
        scenario == "stop_during_voice_review") {
      assert(terminal == (stopped ? Step::stopped : Step::fault));
      assert(!session.handoff() && !i2c);
      return 0;
    }
    assert(terminal == Step::voice_ready);
    const auto handoff = session.handoff();
    assert(handoff && handoff->setup.ready() && handoff->bus == &board_bus);
    assert(handoff->paid_consent && handoff->budget_writes &&
           handoff->allow_first_budget == (first && scenario != "unlock_restored"));
    assert(handoff->save_after_setup == ((saved_pairing || unlock_enroll()) ? &saved : nullptr));
    assert(!session.handoff());
    ms += 1000;
    assert(session.poll() == Step::voice_ready && touches == previous && !usb);
    if (scenario == "stop_after_handoff") {
      stopped = true;
      assert(session.poll() == Step::stopped && i2c && head && lcd && !handoff->setup.ready());
      assert(!handoff->paid_consent && !handoff->budget_writes);
    }
    if (scenario == "cleanup_retry") assert(!session.shutdown() && i2c && retry_failed);
    const bool released = scenario != "ambiguous_bus_release";
    assert(session.shutdown() == released && !session.handoff() && !handoff->setup.ready());
    assert(session.shutdown() == released);
    assert(!handoff->paid_consent && !handoff->budget_writes);
  } else {
    const bool requested = scenario == "usb_stop" || scenario == "stop_while_draining";
    assert(terminal == (requested ? Step::stopped : Step::fault) && !session.handoff());
    if (scenario == "head_read_error") {
      assert(touches == 1 && !receive_calls && session.early_setup_failure() == Failure::sensor_read);
    } else if (scenario == "no_head_touch") {
      assert(!receive_calls && session.early_setup_failure() == Failure::head_input);
    } else if (scenario == "usb_failed") {
      assert(touches > 1 && !receive_calls && session.early_setup_failure() == Failure::usb_start);
    } else {
      assert(!session.early_setup_failure());
    }
  }
  assert(!i2c && !lvgl && !lcd && !head && !usb);
}
