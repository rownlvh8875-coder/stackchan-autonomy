// SPDX-License-Identifier: MIT
#include "k151_board_bus.hpp"
#include "k151_display_stop.hpp"
#include "k151_head_touch_owner.hpp"
#include "k151_lcd_panel.hpp"
#include <driver/usb_serial_jtag.h>
#include <esp_chip_info.h>
#include <esp_ota_ops.h>

#include <cassert>
#include <cstdio>
#include <cstring>
#include <string_view>

using namespace stackchan::standalone;

extern "C" void app_main();
struct i2c_master_bus_t {};
struct lv_display_t {};
struct lv_obj_t {};

namespace {
i2c_master_bus_t board;
lv_display_t lcd_display;
lv_obj_t screen, label;
esp_partition_t partition{0x510000, 0x4f0000, 0, 17};
std::atomic_bool stop{false};
std::string_view scenario, input;
bool bus_open{}, usb_open{}, lvgl{}, panel{}, head{}, irq{}, irq_cleanup_failed{};
bool host_stop_sent{};
bool waiting_for_host_start{};
char host_line[32]{};
unsigned frames{}, gaps{}, random_calls{};
uint32_t ms = 1000, head_since{}, armed_since{};
}

void esp_chip_info(esp_chip_info_t* chip) {
  *chip = {scenario == "wrong_chip" ? 1 : CHIP_ESP32S3, 2};
}
const esp_partition_t* esp_ota_get_running_partition() { return &partition; }
uint32_t esp_random() { return random_calls++ == 0 ? 0xc07acafe : 12345678U; }
extern "C" int64_t esp_timer_get_time() { return 1000 * static_cast<int64_t>(ms); }
void vTaskDelay(unsigned wait) {
  ms += wait;
  if (irq && ms - armed_since >= (scenario == "early_irq" ? 25U : 400U))
    stop = scenario != "host_stop";
}
int usb_serial_jtag_read_bytes(void* byte, uint32_t length, uint32_t timeout) {
  assert(usb_open && length == 1);
  if (timeout && (scenario == "no_command" || gaps++ < 4)) {
    ms += timeout;
    return 0;
  }
  if (scenario == "host_stop" && head && ms - head_since >= 200U && !host_stop_sent) {
    host_stop_sent = true;
    input = "STOP\n";
  }
  if (waiting_for_host_start && input.empty()) {
    waiting_for_host_start = false;
    if (!std::fgets(host_line, sizeof(host_line), stdin)) return -1;
    input = host_line;
  }
  if (input.empty()) { ms += timeout; return 0; }
  *static_cast<char*>(byte) = input.front();
  input.remove_prefix(1);
  return 1;
}
bool usb_serial_jtag_is_driver_installed() { return usb_open; }
int usb_serial_jtag_driver_install(usb_serial_jtag_driver_config_t*) {
  assert(!usb_open);
  usb_open = true;
  return ESP_OK;
}
int usb_serial_jtag_driver_uninstall() { assert(usb_open); usb_open = false; return ESP_OK; }
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t* config,
                                       i2c_master_bus_handle_t* out) {
  assert(usb_open && !bus_open && input.empty());
  assert(config->i2c_port == I2C_NUM_1 && config->sda_io_num == 12 && config->scl_io_num == 11);
  bus_open = true;
  *out = &board;
  return ESP_OK;
}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t bus) {
  assert(bus_open && bus == &board && !irq && !head && !panel && !lvgl);
  bus_open = false;
  return ESP_OK;
}
extern "C" bool lv_is_initialized() { return lvgl; }
extern "C" void lv_init() { assert(bus_open && !lvgl); lvgl = true; }
extern "C" void lv_deinit() { assert(lvgl && !panel); lvgl = false; }
extern "C" lv_obj_t* lv_display_get_screen_active(lv_display_t* handle) {
  assert(handle == &lcd_display && panel);
  return &screen;
}
extern "C" lv_obj_t* lv_label_create(lv_obj_t* parent) {
  assert(parent == &screen);
  return &label;
}
extern "C" void lv_obj_center(lv_obj_t* obj) { assert(obj == &label); }
extern "C" void lv_label_set_text(lv_obj_t* obj, const char* text) {
  assert(obj == &label && std::strstr(text, "12345678"));
}

namespace stackchan::standalone {
const std::atomic_bool& K151DisplayStop::flag() { return stop; }
K151DisplayStop::ArmResult K151DisplayStop::arm(i2c_master_bus_handle_t bus, K151LcdPanel&) {
  assert(bus_open && bus == &board && head && panel && frames == 2);
  if (scenario == "arm_failure") return ArmResult::owned_unarmed;
  irq = true;
  armed_since = ms;
  return ArmResult::armed;
}
bool K151DisplayStop::disarm() {
  irq_cleanup_failed = scenario == "cleanup_failure";
  if (irq_cleanup_failed) return false;
  irq = false;
  return true;
}
K151LcdPanel::~K151LcdPanel() = default;
bool K151LcdPanel::start(i2c_master_bus_handle_t bus, bool requested) {
  assert(bus == &board && lvgl && bus_open && requested);
  if (scenario == "panel_failure") return false;
  display_ = &lcd_display;
  panel = true;
  return true;
}
bool K151LcdPanel::present_now() { ++frames; return scenario != "frame_failure"; }
bool K151LcdPanel::shutdown() { assert(!irq && !head); panel = false; return true; }
K151HeadTouchOwner::~K151HeadTouchOwner() = default;
bool K151HeadTouchOwner::attach_for_setup(i2c_master_bus_handle_t bus, bool verified, bool exclusive) {
  assert(bus == &board && panel && frames == 1 && verified && exclusive && !head);
  head = true;
  head_since = ms;
  return true;
}
TouchConsentEvent K151HeadTouchOwner::poll_once(uint64_t now) {
  assert(now == ms && head && !irq);
  if (scenario == "head_fault") return TouchConsentEvent::invalidated;
  if (scenario != "no_head" && now - head_since >= 3400U)
    return TouchConsentEvent::owner_window_open;
  return TouchConsentEvent::none;
}
bool K151HeadTouchOwner::detach() { assert(!irq); head = false; return true; }
}

int main(int argc, char* argv[]) {
  assert(argc == 2);
  scenario = argv[1];
  input = "HELLO\nSTART C07ACAFE\n";
  if (scenario == "wrong_nonce") input = "HELLO\nSTART 00000000\n";
  if (scenario == "no_hello") input = "START C07ACAFE\n";
  if (scenario == "interactive") {
    assert(std::setvbuf(stdout, nullptr, _IOFBF, 4096) == 0);
    input = "HELLO\n";
    waiting_for_host_start = true;
  }
  if (scenario == "wrong_slot") partition.address = 0x20000;
  if (scenario == "wrong_subtype") partition.subtype = 16;
  if (scenario == "already_on_usb") usb_open = true;
  app_main();
  if (scenario == "cleanup_failure") {
    assert(irq_cleanup_failed && irq && head && panel && lvgl && bus_open);
  } else {
    assert(!bus_open && !head && !panel && !lvgl && !irq);
  }
  assert(usb_open == (scenario == "already_on_usb"));
  if (scenario == "no_head") assert(ms - head_since <= 10051);
}
