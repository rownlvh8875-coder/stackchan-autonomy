// SPDX-License-Identifier: MIT
#include "k151_lcd_panel.hpp"

#include "board_evidence.hpp"
#include "k151_codec_port.hpp"
#include "k151_contract.hpp"
#include "k151_install_hold.hpp"
#include <array>
#include <driver/gpio.h>
#include <driver/spi_master.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr unsigned kWidth = k151::kScreenWidth;
constexpr unsigned kHeight = k151::kScreenHeight;
constexpr unsigned kStripeRows = 10;
constexpr unsigned kStride = kWidth * sizeof(uint16_t);
constexpr unsigned kStripeBytes = kStride * kStripeRows;
constexpr int kI2cTimeoutMs = 30;
constexpr auto kSdSelect = GPIO_NUM_4; // microSD shares LCD SPI clock and MOSI.
constexpr uint8_t kLdoEnable = 0x90;
constexpr uint8_t kDldo1Enable = 0x80;
constexpr uint8_t kDldo1Voltage = 0x99;
constexpr uint8_t kVoltageMask = 0x1f;
constexpr uint8_t kBacklightLevel = 22; // Vendor brightness mapping at 25%.
constexpr uint8_t kP1Output = 0x03;
constexpr uint8_t kLcdReset = 0x02; // AW9523B P1_1, active low.

// ILI9342E register settings from M5Stack StackChan firmware,
// 28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400, MIT,
// copyright (c) 2026 M5Stack Technology CO LTD. See M5STACK-MIT-LICENSE.txt.
struct InitRegister {
  uint8_t address;
  uint8_t length;
  std::array<uint8_t, 15> bytes;
};
constexpr InitRegister kPanelRegisters[]{
    {0xdd, 1, {0x01}}, {0x3a, 1, {0x55}}, {0x21, 0, {}}, {0x36, 1, {0x08}},
    {0xd5, 1, {0x00}}, {0xb1, 1, {0x22}}, {0xc8, 1, {0x38}}, {0xcb, 1, {0x1c}},
    {0xc9, 1, {0x1a}}, {0xca, 1, {0x1a}}, {0xb7, 4, {0x5a, 0x41, 0x11, 0x19}},
    {0xe4, 15, {0x04, 0x08, 0x11, 0x06, 0x12, 0x07, 0x3a, 0x76,
                0x47, 0x07, 0x0f, 0x0a, 0x11, 0x19, 0x05}},
    {0xe5, 15, {0x02, 0x03, 0x07, 0x06, 0x12, 0x07, 0x36, 0x5f,
                0x48, 0x06, 0x10, 0x0c, 0x16, 0x14, 0x09}},
};

bool attach_device(i2c_master_bus_handle_t bus, k151::Device id, i2c_master_dev_handle_t& dev) {
  i2c_device_config_t config{};
  config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  config.device_address = k151::kProbeAddresses[k151::index(id)];
  config.scl_speed_hz = 100'000;
  return i2c_master_bus_add_device(bus, &config, &dev) == ESP_OK;
}

bool release_device(i2c_master_dev_handle_t& dev) {
  if (!dev) return true;
  const auto result = i2c_master_bus_rm_device(dev);
  // Pinned IDF returns INVALID_STATE before unlinking a busy device.
  if (result != ESP_ERR_INVALID_STATE) dev = nullptr;
  return result == ESP_OK;
}

bool read_register(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t& out) {
  return i2c_master_transmit_receive(dev, &reg, 1, &out, 1, kI2cTimeoutMs) == ESP_OK;
}

bool set_bits(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t mask, uint8_t value) {
  uint8_t before{}, observed{};
  if (!read_register(dev, reg, before)) return false;
  const auto after = static_cast<uint8_t>((before & ~mask) | (value & mask));
  if (after == before) return true;
  const uint8_t command[]{reg, after};
  return i2c_master_transmit(dev, command, sizeof(command), kI2cTimeoutMs) == ESP_OK &&
         read_register(dev, reg, observed) && observed == after;
}

void wait_at_least(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms) + 1); }
} // namespace

K151LcdPanel::~K151LcdPanel() { (void)shutdown(); }

bool K151LcdPanel::locate_panel(i2c_master_bus_handle_t bus) {
  if (!attach_device(bus, k151::Device::touch_ft6336, touch_)) return false;
  constexpr uint8_t reg = 0xa3;
  std::array<uint8_t, 6> version{};
  const bool matched = i2c_master_transmit_receive(touch_, &reg, 1, version.data(), version.size(),
                                                    kI2cTimeoutMs) == ESP_OK &&
                       k151::ft6336_9342e_signature(version);
  if (!release_device(touch_) || !matched) return false;

  uint8_t id{}, mode{}, direction{};
  return attach_device(bus, k151::Device::pmic_axp2101, pmic_) &&
         read_register(pmic_, 0x03, id) && id == 0x4a &&
         read_register(pmic_, kDldo1Voltage, initial_backlight_level_) &&
         attach_device(bus, k151::Device::io_aw9523, expander_) &&
         read_register(expander_, 0x10, id) && id == 0x23 &&
         read_register(expander_, 0x13, mode) && (mode & kLcdReset) &&
         read_register(expander_, 0x05, direction) && !(direction & kLcdReset);
}

bool K151LcdPanel::open_display() {
  stripe_ = static_cast<uint8_t*>(heap_caps_malloc(kStripeBytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA));
  if (!stripe_) return false;

  spi_bus_config_t bus{};
  bus.mosi_io_num = 37;
  bus.miso_io_num = -1;
  bus.sclk_io_num = 36;
  bus.quadwp_io_num = -1;
  bus.quadhd_io_num = -1;
  bus.data4_io_num = -1;
  bus.data5_io_num = -1;
  bus.data6_io_num = -1;
  bus.data7_io_num = -1;
  bus.max_transfer_sz = kStripeBytes;
  if (spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK) return false;
  spi_owned_ = true;

  // Set the output latch before driving active-low TF_CS. SPI initialization
  // sends no transactions, and this pin stays high throughout LCD traffic.
  if (gpio_set_level(kSdSelect, 1) != ESP_OK) return false;
  sd_cs_claimed_ = true;
  gpio_config_t sd{};
  sd.pin_bit_mask = 1ULL << kSdSelect;
  sd.mode = GPIO_MODE_OUTPUT;
  sd.pull_up_en = GPIO_PULLUP_ENABLE;
  sd.pull_down_en = GPIO_PULLDOWN_DISABLE;
  sd.intr_type = GPIO_INTR_DISABLE;
  if (gpio_config(&sd) != ESP_OK) return false;

  esp_lcd_panel_io_spi_config_t interface{};
  interface.cs_gpio_num = GPIO_NUM_3;
  interface.dc_gpio_num = GPIO_NUM_35;
  interface.spi_mode = 2;
  interface.pclk_hz = 40'000'000;
  interface.trans_queue_depth = 1;
  interface.lcd_cmd_bits = 8;
  interface.lcd_param_bits = 8;
  if (esp_lcd_new_panel_io_spi(SPI3_HOST, &interface, &io_) != ESP_OK) return false;

  display_ = lv_display_create(kWidth, kHeight);
  if (!display_) return false;
  lv_display_set_user_data(display_, this);
  lv_display_set_color_format(display_, LV_COLOR_FORMAT_RGB565);
  lv_display_set_buffers_with_stride(display_, stripe_, nullptr, kStripeBytes, kStride,
                                     LV_DISPLAY_RENDER_MODE_PARTIAL);
  lv_display_set_flush_cb(display_, flush);
  const auto before = lv_display_get_event_count(display_);
  lv_display_add_event_cb(display_, round_area, LV_EVENT_INVALIDATE_AREA, nullptr);
  return lv_display_get_event_count(display_) == before + 1;
}

bool K151LcdPanel::initialize_controller() {
  if (stop_.load()) return false;
  backlight_claimed_ = true;
  if (!set_bits(pmic_, kLdoEnable, kDldo1Enable, 0) || stop_.load()) return false;
  controller_claimed_ = true;
  if (!set_bits(expander_, kP1Output, kLcdReset, 0)) return false;
  wait_at_least(20);
  if (stop_.load() || !set_bits(expander_, kP1Output, kLcdReset, kLcdReset)) return false;
  wait_at_least(10);
  for (const auto& reg : kPanelRegisters) {
    if (stop_.load() ||
        esp_lcd_panel_io_tx_param(io_, reg.address, reg.bytes.data(), reg.length) != ESP_OK)
      return false;
  }
  if (stop_.load() || esp_lcd_panel_io_tx_param(io_, 0x11, nullptr, 0) != ESP_OK) return false;
  wait_at_least(120);
  return !stop_.load();
}

bool K151LcdPanel::start(i2c_master_bus_handle_t bus, bool local_display_requested) {
  if (attempted_ || stop_.load() || !local_display_requested ||
      !K151InstallHold::device_activation_allowed() || !lv_is_initialized() ||
      !K151CodecPort::is_registered_board_bus(bus))
    return false;
  attempted_ = true;
  // Write the initial frame with the backlight disabled before displaying it.
  if (locate_panel(bus) && !stop_.load() && open_display() && initialize_controller() &&
      present_now() && esp_lcd_panel_io_tx_param(io_, 0x29, nullptr, 0) == ESP_OK) {
    wait_at_least(120);
    if (!stop_.load() && set_bits(pmic_, kDldo1Voltage, kVoltageMask, kBacklightLevel) &&
        !stop_.load() && set_bits(pmic_, kLdoEnable, kDldo1Enable, kDldo1Enable) &&
        !stop_.load())
      return true;
  }
  fault_ = true;
  (void)shutdown();
  return false;
}

void K151LcdPanel::round_area(lv_event_t* event) {
  // The draw buffer and SPI transfer both use one tightly packed full row.
  auto& area = *static_cast<lv_area_t*>(lv_event_get_param(event));
  area.x1 = 0;
  area.x2 = kWidth - 1;
}

bool K151LcdPanel::transmit_rows(unsigned first, unsigned last, uint8_t* pixels) {
  const uint8_t columns[]{0, 0, uint8_t((kWidth - 1) >> 8), uint8_t(kWidth - 1)};
  const uint8_t rows[]{uint8_t(first >> 8), uint8_t(first), uint8_t(last >> 8), uint8_t(last)};
  const size_t pixel_count = (last - first + 1) * kWidth;
  lv_draw_sw_rgb565_swap(pixels, pixel_count);
  // The pinned SPI IO uses synchronous polling for tx_param. Each stripe
  // fits the configured transfer limit and may be reused when it returns.
  return esp_lcd_panel_io_tx_param(io_, 0x2a, columns, sizeof(columns)) == ESP_OK &&
         esp_lcd_panel_io_tx_param(io_, 0x2b, rows, sizeof(rows)) == ESP_OK &&
         !stop_.load() &&
         esp_lcd_panel_io_tx_param(io_, 0x2c, pixels, pixel_count * sizeof(uint16_t)) == ESP_OK;
}

void K151LcdPanel::flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels) {
  auto& panel = *static_cast<K151LcdPanel*>(lv_display_get_user_data(display));
  if (panel.ready()) {
    const bool valid = pixels == panel.stripe_ && area->x1 == 0 &&
                       area->x2 == static_cast<int>(kWidth - 1) && area->y1 >= 0 &&
                       area->y2 >= area->y1 && area->y2 < static_cast<int>(kHeight) &&
                       area->y2 - area->y1 < static_cast<int>(kStripeRows) &&
                       (!panel.full_refresh_ || unsigned(area->y1) == panel.next_row_);
    if (!valid || !panel.transmit_rows(area->y1, area->y2, pixels)) panel.fault_ = true;
    else if (panel.full_refresh_) panel.next_row_ = area->y2 + 1;
  }
  lv_display_flush_ready(display);
}

bool K151LcdPanel::present_now() {
  if (!ready() || full_refresh_) return false;
  auto* active = lv_display_get_screen_active(display_);
  if (!active) return false;
  next_row_ = 0;
  full_refresh_ = true;
  lv_obj_invalidate(active);
  lv_refr_now(display_);
  full_refresh_ = false;
  if (ready() && next_row_ == kHeight) return true;
  fault_ = true;
  if (backlight_claimed_) (void)set_bits(pmic_, kLdoEnable, kDldo1Enable, 0);
  return false;
}

bool K151LcdPanel::shutdown() {
  // Darkness does not depend on a successful SPI transfer.
  if (backlight_claimed_ && set_bits(pmic_, kLdoEnable, kDldo1Enable, 0) &&
      set_bits(pmic_, kDldo1Voltage, kVoltageMask, initial_backlight_level_))
    backlight_claimed_ = false;
  if (controller_claimed_ && set_bits(expander_, kP1Output, kLcdReset, 0))
    controller_claimed_ = false;

  if (display_) {
    lv_display_delete(display_);
    display_ = nullptr;
  }
  if (stripe_) {
    heap_caps_free(stripe_);
    stripe_ = nullptr;
  }
  if (io_ && esp_lcd_panel_io_del(io_) == ESP_OK) io_ = nullptr;
  if (spi_owned_ && !io_ && spi_bus_free(SPI3_HOST) == ESP_OK) spi_owned_ = false;
  if (sd_cs_claimed_ && !spi_owned_ && gpio_set_direction(kSdSelect, GPIO_MODE_INPUT) == ESP_OK)
    sd_cs_claimed_ = false;
  const bool touch_released = release_device(touch_);
  const bool expander_released = !controller_claimed_ && release_device(expander_);
  const bool pmic_released = !backlight_claimed_ && release_device(pmic_);
  return touch_released && expander_released && pmic_released && !io_ && !spi_owned_ &&
         !sd_cs_claimed_;
}

const char* K151LcdPanel::compiled_link_marker() {
  auto volatile start_panel = &K151LcdPanel::start;
  auto volatile refresh = &K151LcdPanel::present_now;
  (void)start_panel;
  (void)refresh;
  return "K151 LCD transport linked; PANEL NOT STARTED";
}

} // namespace stackchan::standalone
