// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <cstdint>
#include <driver/i2c_master.h>
#include <esp_lcd_panel_io.h>
#include <lvgl.h>

namespace stackchan::standalone {

class K151DisplayStop;
class K151SetupLvgl;

// Single board/LVGL owner task. LVGL and the borrowed I2C1 bus must outlive
// the panel. Shut down voice and its IRQ monitor before releasing display
// I/O. Only the owner uses SPI3. A completed SPI frame is transport
// evidence. Physical panel identity and readability require a local check.
class K151LcdPanel final {
 public:
  explicit K151LcdPanel(const std::atomic_bool& stop) : stop_(stop) {}
  K151LcdPanel(const K151LcdPanel&) = delete;
  K151LcdPanel& operator=(const K151LcdPanel&) = delete;
  ~K151LcdPanel();

  bool start(i2c_master_bus_handle_t board_bus, bool local_display_requested);
  bool present_now();
  bool shutdown();
  bool ready() const { return display_ && !fault_ && !stop_.load(); }
  lv_display_t* display() const { return display_; }
  static const char* compiled_link_marker();

 private:
  friend class K151DisplayStop;
  friend class K151SetupLvgl;
  bool read_contact_count(uint8_t& count) const;
  bool handoff_stop_input(i2c_master_bus_handle_t bus, const std::atomic_bool& expected_stop);
  bool locate_panel(i2c_master_bus_handle_t bus);
  bool prepare_touch_pins();
  bool restore_touch_pins();
  bool open_display();
  bool initialize_controller();
  bool transmit_rows(unsigned first, unsigned last, uint8_t* pixels);
  static void round_area(lv_event_t* event);
  static void flush(lv_display_t* display, const lv_area_t* area, uint8_t* pixels);

  const std::atomic_bool& stop_;
  i2c_master_bus_handle_t board_bus_ = nullptr;
  i2c_master_dev_handle_t touch_ = nullptr;
  i2c_master_dev_handle_t pmic_ = nullptr;
  i2c_master_dev_handle_t expander_ = nullptr;
  esp_lcd_panel_io_handle_t io_ = nullptr;
  lv_display_t* display_ = nullptr;
  uint8_t* stripe_ = nullptr;
  uint8_t initial_backlight_level_ = 0;
  unsigned next_row_ = 0;
  bool full_refresh_ = false;
  bool attempted_ = false;
  bool spi_owned_ = false;
  bool sd_cs_claimed_ = false;
  bool backlight_claimed_ = false;
  bool controller_claimed_ = false;
  bool touch_irq_changed_ = false;
  bool touch_reset_changed_ = false;
  bool p0_drive_changed_ = false;
  bool stop_input_handed_off_ = false;
  bool fault_ = false;
};

} // namespace stackchan::standalone
