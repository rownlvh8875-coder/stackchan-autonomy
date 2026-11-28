// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <driver/gpio.h>
#include <driver/spi_master.h>
struct esp_lcd_panel_io_t;
using esp_lcd_panel_io_handle_t = esp_lcd_panel_io_t*;
struct esp_lcd_panel_io_spi_config_t {
  gpio_num_t cs_gpio_num, dc_gpio_num;
  int spi_mode;
  unsigned pclk_hz, trans_queue_depth;
  int lcd_cmd_bits, lcd_param_bits;
};
extern "C" {
esp_err_t esp_lcd_new_panel_io_spi(int bus, const esp_lcd_panel_io_spi_config_t*,
                                  esp_lcd_panel_io_handle_t*);
esp_err_t esp_lcd_panel_io_tx_param(esp_lcd_panel_io_handle_t, int, const void*, size_t);
esp_err_t esp_lcd_panel_io_del(esp_lcd_panel_io_handle_t);
}
