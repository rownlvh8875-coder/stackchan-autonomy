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
#include <optional>
#include <string_view>
#include <utility>
#include <vector>

using namespace stackchan::standalone;

struct i2c_master_bus_t {};
struct i2c_master_dev_t { uint16_t address; bool open = false; };
struct esp_lcd_panel_io_t {};
struct lv_obj_t {};
struct lv_event_t { lv_area_t* area; };
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
std::array<lv_obj_t, 37> unlock_labels;
std::array<std::string_view, unlock_labels.size()> unlock_captions;
unsigned unlock_label_count = 0;
std::array<std::string_view, 3> captions;  // Known mock labels only.
uint8_t ldo_enable = 0xbf, ldo_voltage = 0x9a, expander_p1 = 0x83;
uint8_t expander_p0 = 0x07, p0_direction = 0x18, p1_direction = 0x0c, p0_drive = 0x10;
uint8_t initial_p0{}, initial_p1{}, initial_drive{}, initial_irq_direction{}, initial_ldo_enable{};
bool release_failed_once = false;
unsigned ft_contact_reads = 0, irq_ack_reads = 0;
unsigned handoff_first_contact_read = 1;
uint8_t screen_contacts = 0;
int touch_x = 0, touch_y = 0;
bool spi_open = false, lcd_open = false, lv_open = false, display_on = false;
bool sd_cs_driven = false;
uint32_t sd_cs_level = 0;
unsigned label_count = 0, attach_calls = 0, register_writes = 0, frames = 0;
unsigned transmitted_rows = 0, acknowledged_stripes = 0;
std::optional<lv_area_t> partial_area;
bool rendering_voice_band = false;
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

void check_touch_registers_restored() {
  assert(expander_p0 == initial_p0 && p0_drive == initial_drive);
  assert(p1_direction == initial_irq_direction);
}

void check_released() {
  assert(!spi_open && !lcd_open && !lv_open && !allocated && !sd_cs_driven);
  assert(!touch.open && !pmic.open && !expander.open);
}
} // namespace

namespace stackchan::standalone {
class K151DisplayStop {
 public:
  static bool handoff(K151LcdPanel& panel, i2c_master_bus_handle_t bus,
                      const std::atomic_bool& flag) {
    return panel.handoff_stop_input(bus, flag);
  }
};
class K151ScpsUsbPort {
 public:
  using Review = K151SetupLvgl::ReviewResult;
  static bool begin(K151SetupLvgl& setup, uint64_t now, bool locked = true) {
    return setup.begin_pairing_review(now, locked);
  }
  static Review poll(K151SetupLvgl& setup, uint64_t now, bool locked = true) {
    return setup.poll_pairing_review(now, locked);
  }
};
class K151OwnerSession {
 public:
  using Review = K151SetupLvgl::ReviewResult;
  using Unlock = K151SetupLvgl::UnlockChoice;
  static bool begin_voice(K151SetupLvgl& setup, uint64_t now, bool first_budget,
                          bool one_turn = false, std::optional<RebootTrialBoot> trial = std::nullopt) {
    return setup.begin_voice_review(now, first_budget, true, one_turn, trial);
  }
  static Review poll_voice(K151SetupLvgl& setup, uint64_t now) {
    return setup.poll_voice_review(now, true);
  }
  static void check_unlock(K151SetupLvgl& setup) {
    using Screen = K151SetupLvgl::UnlockScreen;
    constexpr std::array<char, kOwnerCodeLength> code{
        '0','1','2','3','4','5','6','7','8','9','A','B','C','D','E','F'};
    const OwnerCode generated(code);
    const auto sample = [&](uint8_t count, int x, int y) {
      screen_contacts = count;
      touch_x = x;
      touch_y = y;
      return setup.poll_unlock();
    };
    const auto key = [&](int x, int y) {
      assert(sample(1, x, y) == Unlock::waiting);
      return sample(0, x, y);
    };
    assert(setup.present_unlock(Screen::enroll, &generated));
    assert(unlock_captions[1] == std::string_view(code.data(), code.size()));
    assert(key(280, 228) == Unlock::waiting); // Held before screen was ready.
    assert(key(280, 228) == Unlock::confirm);
    assert(setup.present_unlock(Screen::deriving));
    assert(unlock_captions[1] == "Cancel");
    assert(std::ranges::all_of(setup.unlock_input_.code(), [](char c) { return c == '\0'; }));
    assert(sample(0, 0, 0) == Unlock::waiting);
    assert(key(160, 218) == Unlock::cancel);

    assert(setup.present_unlock(Screen::enter));
    assert(sample(0, 0, 0) == Unlock::waiting);
    assert(key(280, 218) == Unlock::waiting); // Require all symbols.
    assert(sample(1, 20, 61) == Unlock::waiting);
    assert(sample(2, 20, 61) == Unlock::waiting);
    assert(sample(0, 20, 61) == Unlock::waiting);
    assert(sample(1, 20, 61) == Unlock::waiting);
    assert(sample(1, 80, 61) == Unlock::waiting); // Dragging cancels this tap.
    assert(sample(0, 80, 61) == Unlock::waiting && !setup.unlock_input_.size());
    for (size_t i = 0; i < code.size(); ++i) {
      assert(key(20 + 38 * (i % 8), 61 + 37 * (i / 8)) == Unlock::waiting);
      assert(setup.unlock_input_.size() == i + 1);
    }
    assert(key(50, 218) == Unlock::waiting && setup.unlock_input_.size() == code.size() - 1);
    assert(key(20 + 38 * 7, 98) == Unlock::waiting);
    assert(std::ranges::equal(setup.unlock_input_.code(), code));
    assert(key(280, 218) == Unlock::confirm);
    assert(setup.finish_unlock(true));
    assert(!unlock_label_count && std::ranges::all_of(setup.unlock_input_.code(),
                                                     [](char c) { return c == '\0'; }));
  }
};
bool K151InstallHold::display_activation_allowed() { return scenario != "hold"; }
}

extern "C" esp_err_t i2c_master_get_bus_handle(i2c_port_t port, i2c_master_bus_handle_t* out) {
  assert(port == I2C_NUM_1);
  *out = &bus;
  return ESP_OK;
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
    assert(size == 6);
    if (*reg == 0x02) {
      assert(scenario.starts_with("handoff_") || scenario.starts_with("review_") || scenario == "unlock_screen");
      ++ft_contact_reads;
      std::fill_n(data, size, 0);
      if (scenario.starts_with("review_")) {
        if (scenario == "review_i2c_error") return ESP_FAIL;
        data[0] = screen_contacts;
      }
      if (scenario == "unlock_screen") {
        data[0] = screen_contacts;
        data[1] = static_cast<uint8_t>(touch_x >> 8);
        data[2] = static_cast<uint8_t>(touch_x);
        data[3] = static_cast<uint8_t>(touch_y >> 8);
        data[4] = static_cast<uint8_t>(touch_y);
      }
      if (scenario == "handoff_touch_held" ||
          (scenario == "handoff_late_press" && ft_contact_reads == 2))
        data[0] = 1;
      return ESP_OK;
    }
    assert(*reg == 0xa3);
    if (scenario == "panel_read_error" || scenario == "cold_panel_read_error" ||
        !(expander_p0 & 1)) return ESP_FAIL;
    assert(p1_direction & 0x04);
    if (scenario.starts_with("cold_"))
      assert(delays.size() >= 2 && delays[0] > 5 && delays[1] > 300 && (p0_drive & 0x10));
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
    if (*reg == 0x00 || *reg == 0x01) {
      assert(ft_contact_reads == handoff_first_contact_read && irq_ack_reads == *reg);
      assert(scenario.starts_with("handoff_") || scenario.starts_with("review_voice_status") ||
             scenario.starts_with("review_voice_trial_"));
      ++irq_ack_reads;
      *data = 0;
      return *reg == 0x01 && scenario == "handoff_i2c_error" ? ESP_FAIL : ESP_OK;
    }
    if (*reg == 0x10) *data = 0x23;
    else if (*reg == 0x02) *data = expander_p0;
    else if (*reg == 0x03) *data = expander_p1;
    else if (*reg == 0x04) *data = p0_direction;
    else if (*reg == 0x05) *data = scenario == "wrong_reset_direction" ? 0x0e : p1_direction;
    else if (*reg == 0x11) *data = p0_drive;
    else if (*reg == 0x12) *data = 0xff;
    else if (*reg == 0x13) *data = scenario == "wrong_expander_mode" ? 0xfd : 0xff;
    else assert(false);
  }
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit(
    i2c_master_dev_handle_t device, const uint8_t* bytes, size_t size, int timeout_ms) {
  assert(device->open && size == 2 && timeout_ms == 30);
  ++register_writes;
  if (device == &pmic && bytes[0] == 0x90) {
    assert(lcd_open);
    assert((bytes[1] & 0x7f) == (ldo_enable & 0x7f));
    ldo_enable = bytes[1];
    if (ldo_enable & 0x80) {
      assert(display_on && transmitted_rows == 240 && (ldo_voltage & 0x1f) == 22);
      assert(!delays.empty() && delays.back() > 120);
      if (scenario == "stop_enabling_lamp") stop = true;
    }
  } else if (device == &pmic && bytes[0] == 0x99) {
    assert(lcd_open);
    assert(!(ldo_enable & 0x80) && (bytes[1] & 0xe0) == (ldo_voltage & 0xe0));
    const auto old = ldo_voltage;
    ldo_voltage = bytes[1];
    if (scenario == "brightness_readback_error" && (ldo_voltage & 0x1f) == 22)
      ldo_voltage = old;
  } else {
    assert(device == &expander);
    if (bytes[0] == 0x03) {
      assert(lcd_open && !(ldo_enable & 0x80));
      assert((bytes[1] & ~2) == (expander_p1 & ~2));
      expander_p1 = bytes[1];
    } else if (bytes[0] == 0x05) {
      assert(!(expander_p0 & 1) && (bytes[1] & ~4) == (p1_direction & ~4));
      if (delays.size() > 2) assert(delays.back() > 5);
      p1_direction = bytes[1];
    } else if (bytes[0] == 0x11) {
      assert((bytes[1] & ~0x10) == (p0_drive & ~0x10));
      assert(!(expander_p0 & 1) && (p1_direction & 4));
      p0_drive = bytes[1];
    } else {
      assert(bytes[0] == 0x02 && (p0_drive & 0x10) && (p1_direction & 4));
      assert((bytes[1] & ~1) == (expander_p0 & ~1) && !delays.empty() && delays[0] > 5);
      expander_p0 = bytes[1];
      if (scenario == "cold_reset_write_error" && (expander_p0 & 1)) return ESP_FAIL;
      if (scenario == "cold_restore_retry" && !(expander_p0 & 1) && !release_failed_once) {
        release_failed_once = true;
        return ESP_FAIL;
      }
    }
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
      if (scenario == "review_voice_status_stop" && rendering_voice_band && stripe_start == 90)
        stop = true;
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
  if ((scenario == "stop_reset" || scenario == "cold_stop_before_release") &&
      delays.size() == 1) stop = true;
  if (scenario == "cold_stop_after_release" && delays.size() == 2) stop = true;
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
extern "C" void lv_display_add_event_cb(
    lv_display_t* disp, void (*cb)(lv_event_t*), lv_event_code_t code, void* data) {
  assert(code == LV_EVENT_INVALIDATE_AREA && !data && disp->flush);
  if (scenario != "lvgl_event_error") disp->round = cb;
}
extern "C" uint32_t lv_display_get_event_count(lv_display_t* disp) {
  return disp->round ? 1 : 0;
}
extern "C" void* lv_event_get_param(lv_event_t* event) { return event->area; }
extern "C" lv_obj_t* lv_display_get_screen_active(lv_display_t* disp) {
  assert(disp == &display && lv_open);
  return &screen;
}
extern "C" void lv_obj_invalidate(lv_obj_t* obj) { assert(obj == &screen); }
extern "C" lv_result_t lv_obj_invalidate_area(const lv_obj_t* obj, const lv_area_t* area) {
  assert(obj == &screen && area->y1 == 90 && area->y2 == 149 && !partial_area);
  partial_area = *area;
  return LV_RESULT_OK;
}
extern "C" void lv_refr_now(lv_display_t* disp) {
  ++frames;
  const auto band = std::exchange(partial_area, std::nullopt);
  rendering_voice_band = band.has_value();
  const int start = band ? band->y1 : 0;
  transmitted_rows = start;
  const int limit = band ? band->y2 + 1 + (scenario == "review_voice_status_spill" ? 10 : 0) :
                    scenario == "short_frame" || (scenario == "sas_short_frame" && frames == 3)
                     || (scenario == "review_short_frame" && frames == 4)
                     || (scenario == "review_final_short_frame" && frames == 5)
                     || (scenario == "review_voice_banner_failure" && frames == 7)
                 ? 230 : 240;
  for (int y = start; y < limit; y += 10) {
    lv_area_t area{11, y, 318, y + 9};
    lv_event_t event{&area};
    disp->round(&event);
    assert(area.x1 == 0 && area.x2 == 319);
    disp->buffer[0] = 0x34;
    disp->buffer[1] = 0x12;
    disp->flush(disp, &area, disp->buffer);
  }
  rendering_voice_band = false;
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
  if (parent == &screen && scenario == "unlock_screen") {
    assert(unlock_label_count < unlock_labels.size());
    return &unlock_labels[unlock_label_count++];
  }
  assert(parent == &root && label_count < labels.size());
  return &labels[label_count++];
}
extern "C" void lv_obj_delete(lv_obj_t* object) {
  if (scenario == "unlock_screen" && object != &root) {
    const auto index = object - unlock_labels.data();
    assert(index >= 0 && index < static_cast<ptrdiff_t>(unlock_labels.size()) && unlock_label_count);
    unlock_captions[index] = {};
    --unlock_label_count;
    return;
  }
  assert(object == &root && lv_open);
  label_count = 0;
}
extern "C" void lv_obj_set_size(lv_obj_t* obj, int32_t, int32_t) { assert(obj == &root); }
extern "C" void lv_obj_center(lv_obj_t* obj) { assert(obj == &root); }
extern "C" void lv_obj_align(lv_obj_t*, lv_align_t, int32_t, int32_t) {}
extern "C" void lv_label_set_text(lv_obj_t* label, const char* value) {
  if (scenario == "unlock_screen" && label == &unlock_labels[1]) {
    assert(std::ranges::all_of(std::string_view(value), [](char c) { return c == '*'; }));
    return;
  }
  const auto index = label - labels.data();
  assert(index >= 0 && index < 3);
  // Only the compiled-in mock pairing value is examined while it is live.
  if (index == 1 && std::strlen(value) == 8) assert(std::string_view(value) == "12345678");
  if (index == 1 && std::string_view(value).starts_with("Send question audio to OpenAI")) {
    assert(scenario.starts_with("review_voice_"));
    const char* expected = scenario == "review_voice_existing"
        ? "Update existing NVS budget log" : "Create or update NVS budget log";
    if (scenario == "review_voice_trial_after") expected = "Verify and update NVS budget";
    assert(std::string_view(value).ends_with(expected));
  }
  const bool trial_prompt = index == 2 && scenario == "review_voice_trial_after";
  captions[index] = index == 0 || trial_prompt ? std::string_view(value) : std::string_view{};
}
extern "C" void lv_label_set_text_static(lv_obj_t* label, const char* value) {
  if (scenario == "unlock_screen") {
    for (size_t i = 0; i < unlock_labels.size(); ++i)
      if (label == &unlock_labels[i]) { unlock_captions[i] = value; return; }
    return;
  }
  assert(label == &labels[1] && (scenario.starts_with("review_voice_status") ||
                                 scenario.starts_with("review_voice_trial_")));
  captions[1] = value;
}

int main(int argc, char** argv) {
  assert(argc == 2);
  scenario = argv[1];
  if (scenario.starts_with("cold_")) {
    expander_p0 = scenario == "cold_other_output_high" ? 2 : 0;
    expander_p1 = p0_direction = p1_direction = p0_drive = 0;
    ldo_enable = 0x3f;
  }
  initial_p0 = expander_p0;
  initial_p1 = expander_p1;
  initial_drive = p0_drive;
  initial_irq_direction = p1_direction;
  initial_ldo_enable = ldo_enable;
  K151LcdPanel panel(stop);
  K151SetupLvgl setup(stop);
  const bool cold_ok = scenario == "cold_start" || scenario == "cold_restore_retry" ||
                       scenario == "cold_restore_with_foreign_output";
  const bool handoff_case = scenario.starts_with("handoff_");
  const bool review_case = scenario.starts_with("review_");
  const bool start_ok = scenario == "ok" || cold_ok || handoff_case || scenario.starts_with("sas_") ||
                        scenario == "stop_after_start" || review_case || scenario == "unlock_screen";
  auto* handle = scenario == "wrong_bus" ? &other_bus : &bus;
  assert(panel.start(handle, scenario != "not_requested") == start_ok);
  if (!start_ok) {
    check_released();
    check_touch_registers_restored();
    assert(!panel.ready() && !panel.display());
    if (failed_before_claim()) {
      assert(register_writes == 0 && ldo_enable == 0xbf && expander_p1 == 0x83);
      if (scenario == "hold" || scenario == "wrong_bus" || scenario == "not_requested" ||
          scenario == "lvgl_not_initialized") assert(attach_calls == 0);
    } else if (scenario.starts_with("cold_")) {
      assert(ldo_enable == initial_ldo_enable && ldo_voltage == 0x9a && expander_p1 == initial_p1);
      assert(!frames && commands.empty());
      if (scenario == "cold_other_output_high") assert(!register_writes && delays.empty());
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
  if (scenario == "unlock_screen") {
    K151OwnerSession::check_unlock(setup);
    assert(setup.detach(true) && panel.shutdown());
    check_released();
    return 0;
  }
  if (handoff_case) {
    const std::atomic_bool wrong_flag{false};
    assert(!K151DisplayStop::handoff(panel, &bus, wrong_flag));
    assert(!K151DisplayStop::handoff(panel, &other_bus, stop));
    assert(ft_contact_reads == 0 && irq_ack_reads == 0);
    const bool stopped = scenario == "handoff_stopped";
    stop = stopped;
    assert(K151DisplayStop::handoff(panel, &bus, stop) == (scenario == "handoff_idle"));
    const bool acked = !stopped && scenario != "handoff_touch_held";
    const bool rechecked = acked && scenario != "handoff_i2c_error";
    assert(irq_ack_reads == (acked ? 2u : 0u));
    assert(ft_contact_reads == (rechecked ? 2u : stopped ? 0u : 1u));
    if (scenario == "handoff_idle") {
      assert(!K151DisplayStop::handoff(panel, &bus, stop));
      assert(!K151DisplayStop::handoff(panel, &bus, stop));
      assert(irq_ack_reads == 2 && ft_contact_reads == 2);
    }
  } else if (review_case) {
    using Review = K151ScpsUsbPort::Review;
    const unsigned no_reads = ft_contact_reads;
    assert(!K151ScpsUsbPort::begin(setup, 1000));
    assert(K151ScpsUsbPort::poll(setup, 1000) == Review::fault);
    assert(ft_contact_reads == no_reads);
    assert(setup.present_pairing_sas("12345678", true, true, true));
    assert(!K151ScpsUsbPort::begin(setup, 1000, false));
    if (scenario == "review_short_frame") {
      assert(!K151ScpsUsbPort::begin(setup, 1000) && !setup.attached());
      assert(K151ScpsUsbPort::poll(setup, 1000) == Review::fault);
      assert(frames == 4 && ft_contact_reads == no_reads);
      assert(setup.detach(true) && panel.shutdown());
      check_released();
      return 0;
    }
    assert(K151ScpsUsbPort::begin(setup, 1000));
    assert(frames == 4 && !K151ScpsUsbPort::begin(setup, 1000));
    const auto poll = [&](uint64_t ms, uint8_t contacts, bool locked = true) {
      screen_contacts = contacts;
      return K151ScpsUsbPort::poll(setup, ms, locked);
    };
    if (scenario.starts_with("review_voice_")) {
      assert(!K151OwnerSession::begin_voice(setup, 1000, true));
      assert(poll(1000, 0) == Review::waiting);
      for (uint64_t ms = 1100; ms <= 2100; ms += 100) assert(poll(ms, 1) == Review::waiting);
      assert(poll(2200, 0) == Review::approved && frames == 5);
      assert(setup.present(TouchConsentPhase::consumed, OwnerSetupPhase::ready, true, false, true));
      const bool expect_banner = scenario != "review_voice_banner_failure";
      const bool one_turn = scenario == "review_voice_one_turn";
      std::optional<RebootTrialBoot> trial;
      if (scenario == "review_voice_trial_before") trial = RebootTrialBoot::before_reboot;
      if (scenario == "review_voice_trial_after") trial = RebootTrialBoot::after_reboot;
      const bool first_budget = scenario != "review_voice_existing" &&
                                trial != RebootTrialBoot::after_reboot;
      assert(K151OwnerSession::begin_voice(setup, 2400, first_budget, one_turn, trial)
             == expect_banner);
      if (expect_banner) {
        if (trial == RebootTrialBoot::before_reboot)
          assert(captions[0] == "TRIAL: ONE PAID TURN");
        else if (trial == RebootTrialBoot::after_reboot) {
          assert(captions[0] == "TRIAL: TWO PAID TURNS");
          assert(captions[2] == "Saw Reboot ready?\nHold 1 sec and release");
        } else
          assert(captions[0] == (one_turn ? "PAID VOICE (ONE TURN)" : "PAID OPENAI VOICE"));
        assert(!K151OwnerSession::begin_voice(setup, 2400, true));
        assert(K151ScpsUsbPort::poll(setup, 2400) == Review::fault);
        const auto voice = [&](uint64_t now, uint8_t count) {
          screen_contacts = count;
          return K151OwnerSession::poll_voice(setup, now);
        };
        for (uint64_t now = 2400; now <= 3500; now += 100)
          assert(voice(now, 1) == Review::waiting); // Already-held touch cannot approve.
        assert(voice(3600, 0) == Review::waiting);
        for (uint64_t now = 3700; now <= 4700; now += 100)
          assert(voice(now, 1) == Review::waiting);
        assert(voice(4800, 0) == Review::approved && captions[0] == "VOICE APPROVED");
        assert(voice(4900, 0) == Review::fault);
        if (trial) {
          handoff_first_contact_read = ft_contact_reads + 1;
          assert(K151DisplayStop::handoff(panel, &bus, stop));
          if (trial == RebootTrialBoot::before_reboot) {
            assert(setup.present_voice_status(K151VoiceStatus::connecting));
            assert(setup.present_voice_status(K151VoiceStatus::reboot_ready));
            assert(captions[1] == "Reboot ready. Power off and on.");
          } else {
            assert(setup.present_voice_status(K151VoiceStatus::checking_budget));
            assert(captions[1] == "Checking saved budget");
            assert(setup.present_voice_status(K151VoiceStatus::budget_verified));
            assert(captions[1] == "Previous budget verified");
          }
        }
        if (scenario.starts_with("review_voice_status")) {
          using Status = K151VoiceStatus;
          assert(!setup.present_voice_status(Status::connecting)); // STOP monitor has no route yet.
          handoff_first_contact_read = ft_contact_reads + 1;
          assert(K151DisplayStop::handoff(panel, &bus, stop));
          const auto reads = ft_contact_reads;
          assert(!setup.present(TouchConsentPhase::consumed, OwnerSetupPhase::ready,
                                true, false, true));
          assert(setup.present_voice_status(Status::connecting) && transmitted_rows == 240);
          const auto stripes = acknowledged_stripes;
          const bool normal = scenario == "review_voice_status";
          assert(setup.present_voice_status(Status::listening) == normal);
          assert(ft_contact_reads == reads && irq_ack_reads == 2);
          assert(captions[0] == "STACKCHAN VOICE" && captions[1] == "Say Hi StackChan");
          if (normal) {
            assert(transmitted_rows == 150 && acknowledged_stripes == stripes + 6);
            assert(setup.present_voice_status(Status::listening) && acknowledged_stripes == stripes + 6);
            assert(setup.present_voice_status(Status::question) && acknowledged_stripes == stripes + 12);
            assert(captions[1] == "Say your question" && ft_contact_reads == reads);
            assert(setup.present_voice_status(Status::transcribing));
            assert(captions[1] == "Transcribing question");
            assert(setup.present_voice_status(Status::generating));
            assert(captions[1] == "Generating answer");
            assert(setup.present_voice_status(Status::synthesizing));
            assert(captions[1] == "Synthesizing speech");
            assert(acknowledged_stripes == stripes + 30 && ft_contact_reads == reads);
          } else {
            assert(transmitted_rows == (stop ? 100 : 150));
            assert(!setup.present_voice_status(Status::question));
          }
        }
      } else {
        assert(K151OwnerSession::poll_voice(setup, 2400) == Review::fault);
      }
    } else if (scenario == "review_ok" || scenario == "review_final_short_frame") {
      assert(poll(1000, 0) == Review::waiting);
      for (uint64_t ms = 1100; ms <= 2100; ms += 100) assert(poll(ms, 1) == Review::waiting);
      const auto expected = scenario == "review_ok" ? Review::approved : Review::fault;
      assert(poll(2200, 0) == expected && frames == 5);
      assert(poll(2300, 0) == Review::fault);
    } else if (scenario == "review_held_early") {
      for (uint64_t ms = 1000; ms <= 2100; ms += 100) assert(poll(ms, 1) == Review::waiting);
      assert(poll(2200, 0) == Review::waiting);
      for (uint64_t ms = 2300; ms <= 3300; ms += 100) assert(poll(ms, 1) == Review::waiting);
      assert(poll(3400, 0) == Review::approved);
    } else if (scenario == "review_brief_or_multiple") {
      assert(poll(1000, 0) == Review::waiting);
      assert(poll(1100, 1) == Review::waiting);
      assert(poll(1200, 0) == Review::waiting);
      for (uint64_t ms = 1300; ms <= 2300; ms += 100) assert(poll(ms, 2) == Review::waiting);
      assert(poll(2400, 0) == Review::waiting && frames == 4);
    } else if (scenario == "review_prompt_replaced") {
      assert(setup.present(TouchConsentPhase::hold, OwnerSetupPhase::hold, false, false, true));
      assert(poll(1000, 0) == Review::fault);
    } else {
      const auto when = scenario == "review_gap" ? 1251U :
                        scenario == "review_clock_back" ? 999U : 1000U;
      if (scenario == "review_stop") stop = true;
      assert(poll(when, scenario == "review_invalid_count" ? 15 : 0,
                  scenario != "review_lost_lock") == Review::fault);
      assert(frames == 4);
    }
  } else if (scenario == "stop_after_start") {
    stop = true;
    assert(!setup.attached() && !setup.present_pairing_sas("12345678", true, true, true));
  } else {
    assert(!setup.present_pairing_sas("12345678", false, true, true));
    assert(!setup.present_pairing_sas("invalid", true, true, true));
    assert(frames == 2);
    const bool transfer_ok = scenario == "ok" || cold_ok;
    assert(setup.present_pairing_sas("12345678", true, true, true) == transfer_ok);
    assert(frames == 3 && setup.attached() == transfer_ok);
    if (transfer_ok) assert(transmitted_rows == 240 && captions[0] == "USB pairing check");
    else assert(ldo_enable == 0x3f); // No retained visible prior SAS after transfer failure.
  }
  assert(setup.detach(true));
  if (scenario == "cold_restore_with_foreign_output") {
    expander_p0 |= 0x02; // Another board subsystem still owns a high output.
    assert(!panel.shutdown() && expander.open && !panel.ready());
    assert(expander_p0 == 0x02 && (p0_drive & 0x10) && (p1_direction & 4));
    expander_p0 &= ~0x02;
  }
  if (scenario == "cold_restore_retry") {
    assert(!panel.shutdown() && release_failed_once && expander.open);
    assert(!panel.ready() && p1_direction != initial_irq_direction);
  }
  assert(panel.shutdown());
  check_released();
  assert(ldo_enable == 0x3f && ldo_voltage == 0x9a && expander_p1 == (initial_p1 & ~2));
  check_touch_registers_restored();
}
