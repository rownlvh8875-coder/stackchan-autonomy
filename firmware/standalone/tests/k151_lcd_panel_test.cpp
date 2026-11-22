// SPDX-License-Identifier: MIT
#include "k151_lcd_panel.hpp"
#include "k151_setup_lvgl.hpp"
#include "k151_codec_port.hpp"
#include "k151_install_hold.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <driver/gpio.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>
#include <string_view>
#include <utility>
#include <vector>

using namespace stackchan::standalone;

struct i2c_master_bus_t {};
struct i2c_master_dev_t { uint16_t address; bool open = false; };
struct esp_lcd_panel_io_t {};
struct lv_obj_t {};
struct lv_event_t { lv_area_t* area; };
struct lv_event_dsc_t {};
struct lv_display_t {
  void* context;
  uint8_t* buffer;
  void (*flush)(lv_display_t*, const lv_area_t*, uint8_t*);
  void (*round)(lv_event_t*);
};

namespace {
std::string_view scenario;
std::atomic_bool stop{false};
i2c_master_bus_t bus, other_bus;
i2c_master_dev_t touch{0x38}, pmic{0x34}, expander{0x58};
esp_lcd_panel_io_t lcd_io;
lv_display_t display{};
lv_obj_t screen, root;
std::array<lv_obj_t, 3> labels;
lv_event_dsc_t descriptor;
std::array<std::string_view, 3> captions;  // Known mock labels only.
uint8_t ldo_enable = 0xbf, ldo_voltage = 0x9a, expander_p1 = 0x83;
bool spi_open = false, lcd_open = false, lv_open = false, display_on = false;
bool sd_cs_driven = false;
uint32_t sd_cs_level = 0;
unsigned label_count = 0, attach_calls = 0, register_writes = 0, frames = 0;
unsigned transmitted_rows = 0, acknowledged_stripes = 0;
uint16_t stripe_start = 0, stripe_end = 0;
void* allocated = nullptr;
std::vector<int> commands;
std::vector<unsigned> delays;

bool failed_before_claim() {
  constexpr std::array early{
      "hold", "wrong_bus", "not_requested", "lvgl_not_initialized", "wrong_panel",
      "panel_read_error", "wrong_pmic", "wrong_expander_mode", "wrong_reset_direction",
      "no_dma_memory", "spi_in_use", "sd_select_error", "sd_pin_config_error",
      "lcd_open_error", "lvgl_error", "lvgl_event_error",
  };
  return std::ranges::find(early, scenario) != early.end();
}

void check_released() {
  assert(!spi_open && !lcd_open && !lv_open && !allocated && !sd_cs_driven);
  assert(!touch.open && !pmic.open && !expander.open);
}
} // namespace

namespace stackchan::standalone {
bool K151InstallHold::device_activation_allowed() { return scenario != "hold"; }
bool K151CodecPort::is_registered_board_bus(i2c_master_bus_handle_t input) {
  return input == &bus;
}
}

extern "C" esp_err_t i2c_master_bus_add_device(
    i2c_master_bus_handle_t handle, const i2c_device_config_t* config,
    i2c_master_dev_handle_t* device) {
  assert(handle == &bus && config->dev_addr_length == I2C_ADDR_BIT_LEN_7);
  assert(config->scl_speed_hz == 100'000);
  for (auto* candidate : {&touch, &pmic, &expander}) {
    if (candidate->address == config->device_address) {
      assert(!candidate->open);
      candidate->open = true;
      *device = candidate;
      ++attach_calls;
      return ESP_OK;
    }
  }
  assert(false);
  return ESP_FAIL;
}
extern "C" esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device) {
  assert(device->open);
  device->open = false;
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit_receive(
    i2c_master_dev_handle_t device, const uint8_t* reg, size_t reg_size,
    uint8_t* data, size_t size, int timeout_ms) {
  assert(device->open && reg_size == 1 && timeout_ms == 30);
  if (device == &touch) {
    assert(*reg == 0xa3 && size == 6);
    if (scenario == "panel_read_error") return ESP_FAIL;
    const std::array<uint8_t, 6> version{0x64, 0x01, 0x01, 0x12, 0, 0x11};
    std::ranges::copy(version, data);
    if (scenario == "wrong_panel") data[3] = 0x10;
  } else if (device == &pmic) {
    assert(size == 1);
    if (*reg == 0x03) *data = scenario == "wrong_pmic" ? 0 : 0x4a;
    else if (*reg == 0x90) *data = ldo_enable;
    else if (*reg == 0x99) *data = ldo_voltage;
    else assert(false);
  } else {
    assert(device == &expander && size == 1);
    if (*reg == 0x10) *data = 0x23;
    else if (*reg == 0x03) *data = expander_p1;
    else if (*reg == 0x05) *data = scenario == "wrong_reset_direction" ? 0x0e : 0x0c;
    else if (*reg == 0x13) *data = scenario == "wrong_expander_mode" ? 0xfd : 0xff;
    else assert(false);
  }
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit(
    i2c_master_dev_handle_t device, const uint8_t* bytes, size_t size, int timeout_ms) {
  assert(device->open && size == 2 && timeout_ms == 30 && lcd_open);
  ++register_writes;
  if (device == &pmic && bytes[0] == 0x90) {
    assert((bytes[1] & 0x7f) == (ldo_enable & 0x7f));
    ldo_enable = bytes[1];
    if (ldo_enable & 0x80) {
      assert(display_on && transmitted_rows == 240 && (ldo_voltage & 0x1f) == 22);
      assert(!delays.empty() && delays.back() > 120);
      if (scenario == "stop_enabling_lamp") stop = true;
    }
  } else if (device == &pmic && bytes[0] == 0x99) {
    assert(!(ldo_enable & 0x80) && (bytes[1] & 0xe0) == (ldo_voltage & 0xe0));
    const auto old = ldo_voltage;
    ldo_voltage = bytes[1];
    if (scenario == "brightness_readback_error" && (ldo_voltage & 0x1f) == 22)
      ldo_voltage = old;
  } else {
    assert(device == &expander && bytes[0] == 0x03 && !(ldo_enable & 0x80));
    assert((bytes[1] & ~2) == (expander_p1 & ~2));
    expander_p1 = bytes[1];
  }
  return ESP_OK;
}
extern "C" void* heap_caps_malloc(size_t size, uint32_t caps) {
  assert(size == 6400 && caps == (MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL) && !allocated);
  if (scenario == "no_dma_memory") return nullptr;
  allocated = std::malloc(size);
  return allocated;
}
extern "C" void heap_caps_free(void* mem) {
  assert(mem == allocated && !lv_open);
  std::free(std::exchange(allocated, nullptr));
}

extern "C" esp_err_t spi_bus_initialize(spi_host_device_t host, const spi_bus_config_t* config,
                                         spi_dma_chan_t dma) {
  assert(!spi_open && host == SPI3_HOST && dma == SPI_DMA_CH_AUTO && allocated);
  assert(config->mosi_io_num == 37 && config->sclk_io_num == 36 && config->miso_io_num == -1);
  assert(config->quadwp_io_num == -1 && config->quadhd_io_num == -1);
  assert(config->data4_io_num == -1 && config->data5_io_num == -1 &&
         config->data6_io_num == -1 && config->data7_io_num == -1);
  assert(config->max_transfer_sz == 6400);
  if (scenario == "spi_in_use") return ESP_ERR_INVALID_STATE;
  spi_open = true;
  return ESP_OK;
}
extern "C" esp_err_t spi_bus_free(spi_host_device_t host) {
  assert(host == SPI3_HOST && spi_open && !lcd_open && !allocated);
  spi_open = false;
  return ESP_OK;
}
extern "C" esp_err_t gpio_set_level(gpio_num_t gpio, uint32_t level) {
  assert(gpio == GPIO_NUM_4 && spi_open && !sd_cs_driven && level == 1);
  if (scenario == "sd_select_error") return ESP_FAIL;
  sd_cs_level = level;
  return ESP_OK;
}
extern "C" esp_err_t gpio_config(const gpio_config_t* pins) {
  assert(spi_open && !sd_cs_driven && sd_cs_level == 1 && !lcd_open);
  assert(pins->pin_bit_mask == (1ULL << GPIO_NUM_4) && pins->mode == GPIO_MODE_OUTPUT &&
         pins->pull_up_en == GPIO_PULLUP_ENABLE && pins->pull_down_en == GPIO_PULLDOWN_DISABLE &&
         pins->intr_type == GPIO_INTR_DISABLE);
  sd_cs_driven = true;
  return scenario == "sd_pin_config_error" ? ESP_FAIL : ESP_OK;
}
extern "C" esp_err_t gpio_set_direction(gpio_num_t gpio, gpio_mode_t direction) {
  assert(gpio == GPIO_NUM_4 && !spi_open && !lcd_open && direction == GPIO_MODE_INPUT);
  assert(sd_cs_driven && sd_cs_level == 1);
  sd_cs_driven = false;
  return ESP_OK;
}
extern "C" esp_err_t esp_lcd_new_panel_io_spi(
    int host, const esp_lcd_panel_io_spi_config_t* config, esp_lcd_panel_io_handle_t* handle) {
  assert(host == SPI3_HOST && spi_open && !lcd_open && sd_cs_driven && sd_cs_level == 1);
  assert(config->cs_gpio_num == 3 && config->dc_gpio_num == 35 && config->spi_mode == 2);
  assert(config->pclk_hz == 40'000'000 && config->trans_queue_depth == 1);
  assert(config->lcd_cmd_bits == 8 && config->lcd_param_bits == 8);
  if (scenario == "lcd_open_error") return ESP_FAIL;
  *handle = &lcd_io;
  lcd_open = true;
  return ESP_OK;
}
extern "C" esp_err_t esp_lcd_panel_io_del(esp_lcd_panel_io_handle_t handle) {
  assert(handle == &lcd_io && lcd_open && spi_open && !lv_open);
  lcd_open = false;
  return ESP_OK;
}
extern "C" esp_err_t esp_lcd_panel_io_tx_param(
    esp_lcd_panel_io_handle_t handle, int command, const void* payload, size_t size) {
  assert(handle == &lcd_io && lcd_open && (expander_p1 & 2));
  commands.push_back(command);
  const auto* data = static_cast<const uint8_t*>(payload);
  switch (command) {
    case 0x2a:
      assert(size == 4 && data[0] == 0 && data[1] == 0 && data[2] == 1 && data[3] == 63);
      break;
    case 0x2b:
      assert(size == 4);
      stripe_start = data[0] * 256 + data[1];
      stripe_end = data[2] * 256 + data[3];
      assert(stripe_start == transmitted_rows && stripe_end == stripe_start + 9);
      break;
    case 0x2c:
      assert(size == 6400 && data == allocated);
      assert(data[0] == 0x12 && data[1] == 0x34);
      if (scenario == "initial_spi_error" || (scenario == "sas_spi_error" && frames == 3))
        return ESP_FAIL;
      transmitted_rows = stripe_end + 1;
      break;
    case 0x29:
      assert(size == 0 && !(ldo_enable & 0x80) && transmitted_rows == 240);
      display_on = true;
      break;
    case 0xe5:
      if (scenario == "init_spi_error") return ESP_FAIL;
      [[fallthrough]];
    default:
      assert(!(ldo_enable & 0x80));
      break;
  }
  return ESP_OK;
}
void vTaskDelay(unsigned ticks) {
  delays.push_back(ticks);
  if (scenario == "stop_reset" && delays.size() == 1) stop = true;
}

extern "C" bool lv_is_initialized() { return scenario != "lvgl_not_initialized"; }
extern "C" lv_display_t* lv_display_create(int32_t width, int32_t height) {
  assert(width == 320 && height == 240 && lcd_open);
  if (scenario == "lvgl_error") return nullptr;
  lv_open = true;
  return &display;
}
extern "C" void lv_display_set_user_data(lv_display_t* disp, void* data) { disp->context = data; }
extern "C" void* lv_display_get_user_data(lv_display_t* disp) { return disp->context; }
extern "C" void lv_display_set_color_format(lv_display_t*, lv_color_format_t format) {
  assert(format == LV_COLOR_FORMAT_RGB565);
}
extern "C" void lv_display_set_buffers_with_stride(
    lv_display_t* disp, void* first, void* second, uint32_t size,
    uint32_t stride, lv_display_render_mode_t mode) {
  assert(first == allocated && !second && size == 6400 && stride == 640);
  assert(mode == LV_DISPLAY_RENDER_MODE_PARTIAL);
  disp->buffer = static_cast<uint8_t*>(first);
}
extern "C" void lv_display_set_flush_cb(
    lv_display_t* disp, void (*cb)(lv_display_t*, const lv_area_t*, uint8_t*)) {
  disp->flush = cb;
}
extern "C" lv_event_dsc_t* lv_display_add_event_cb(
    lv_display_t* disp, void (*cb)(lv_event_t*), lv_event_code_t code, void* data) {
  assert(code == LV_EVENT_INVALIDATE_AREA && !data && disp->flush);
  disp->round = cb;
  return scenario == "lvgl_event_error" ? nullptr : &descriptor;
}
extern "C" void* lv_event_get_param(lv_event_t* event) { return event->area; }
extern "C" lv_obj_t* lv_display_get_screen_active(lv_display_t* disp) {
  assert(disp == &display && lv_open);
  return &screen;
}
extern "C" void lv_obj_invalidate(lv_obj_t* obj) { assert(obj == &screen); }
extern "C" void lv_refr_now(lv_display_t* disp) {
  ++frames;
  transmitted_rows = 0;
  const int limit = scenario == "short_frame" || (scenario == "sas_short_frame" && frames == 3)
                 ? 230 : 240;
  for (int y = 0; y < limit; y += 10) {
    lv_area_t area{11, y, 318, y + 9};
    lv_event_t event{&area};
    disp->round(&event);
    assert(area.x1 == 0 && area.x2 == 319);
    disp->buffer[0] = 0x34;
    disp->buffer[1] = 0x12;
    disp->flush(disp, &area, disp->buffer);
  }
}
extern "C" void lv_draw_sw_rgb565_swap(void* buffer, uint32_t size) {
  assert(buffer == allocated && size == 3200);
  auto* bytes = static_cast<uint8_t*>(buffer);
  std::swap(bytes[0], bytes[1]);
}
extern "C" void lv_display_flush_ready(lv_display_t* disp) {
  assert(lv_open && disp == &display);
  ++acknowledged_stripes;
}
extern "C" void lv_display_delete(lv_display_t* disp) {
  assert(lv_open && disp == &display);
  lv_open = false;
}
extern "C" lv_obj_t* lv_obj_create(lv_obj_t* parent) {
  assert(parent == &screen && lv_open && !label_count);
  return &root;
}
extern "C" lv_obj_t* lv_label_create(lv_obj_t* parent) {
  assert(parent == &root && label_count < labels.size());
  return &labels[label_count++];
}
extern "C" void lv_obj_delete(lv_obj_t* object) {
  assert(object == &root && lv_open);
  label_count = 0;
}
extern "C" void lv_obj_set_size(lv_obj_t* obj, int32_t, int32_t) { assert(obj == &root); }
extern "C" void lv_obj_center(lv_obj_t* obj) { assert(obj == &root); }
extern "C" void lv_obj_align(lv_obj_t*, lv_align_t, int32_t, int32_t) {}
extern "C" void lv_label_set_text(lv_obj_t* label, const char* value) {
  const auto index = label - labels.data();
  assert(index >= 0 && index < 3);
  // Only the compiled-in mock pairing value is examined while it is live.
  if (index == 1 && std::strlen(value) == 8) assert(std::string_view(value) == "12345678");
  captions[index] = index == 0 ? std::string_view(value) : std::string_view{};
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  K151LcdPanel panel(stop);
  K151SetupLvgl setup(stop);
  const bool start_ok = scenario == "ok" || scenario.starts_with("sas_") ||
                        scenario == "stop_after_start";
  auto* handle = scenario == "wrong_bus" ? &other_bus : &bus;
  assert(panel.start(handle, scenario != "not_requested") == start_ok);
  if (!start_ok) {
    check_released();
    assert(!panel.ready() && !panel.display());
    if (failed_before_claim()) {
      assert(register_writes == 0 && ldo_enable == 0xbf && expander_p1 == 0x83);
      if (scenario == "hold" || scenario == "wrong_bus" || scenario == "not_requested" ||
          scenario == "lvgl_not_initialized") assert(attach_calls == 0);
    } else {
      assert(ldo_enable == 0x3f && ldo_voltage == 0x9a && expander_p1 == 0x81);
    }
    return 0;
  }
  assert(panel.ready() && frames == 1 && acknowledged_stripes == 24 && register_writes);
  const std::array initial{0xdd, 0x3a, 0x21, 0x36, 0xd5, 0xb1, 0xc8, 0xcb,
                          0xc9, 0xca, 0xb7, 0xe4, 0xe5, 0x11};
  assert(std::ranges::equal(initial, std::span(commands).first(initial.size())));
  assert(commands.back() == 0x29 && ldo_enable == 0xbf && ldo_voltage == 0x96);
  assert(!setup.attach(panel, false, true, true)); // Wire success grants no panel trust.
  assert(!setup.attach(panel, true, false, true));
  assert(!setup.attach(panel, true, true, false));
  assert(setup.attach(panel, true, true, true) && frames == 2 && setup.attached());
  if (scenario == "stop_after_start") {
    stop = true;
    assert(!setup.attached() && !setup.present_pairing_sas("12345678", true, true, true));
  } else {
    assert(!setup.present_pairing_sas("12345678", false, true, true));
    assert(!setup.present_pairing_sas("invalid", true, true, true));
    assert(frames == 2);
    const bool transfer_ok = scenario == "ok";
    assert(setup.present_pairing_sas("12345678", true, true, true) == transfer_ok);
    assert(frames == 3 && setup.attached() == transfer_ok);
    if (transfer_ok) assert(transmitted_rows == 240 && captions[0] == "USB pairing check");
    else assert(ldo_enable == 0x3f); // No retained visible prior SAS after transfer failure.
  }
  assert(setup.detach(true));
  assert(panel.shutdown());
  check_released();
  assert(ldo_enable == 0x3f && ldo_voltage == 0x9a && expander_p1 == 0x81);
}
