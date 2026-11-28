// SPDX-License-Identifier: MIT
#pragma once

#include "k151_contract.hpp"
#include <driver/i2c_master.h>

namespace stackchan::standalone::k151 {

inline bool open_board_bus(i2c_master_bus_handle_t& bus) {
  if (bus) return false;
  i2c_master_bus_config_t cfg{};
  cfg.i2c_port = I2C_NUM_1;
  cfg.sda_io_num = static_cast<gpio_num_t>(kI2cSda);
  cfg.scl_io_num = static_cast<gpio_num_t>(kI2cScl);
  cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  cfg.glitch_ignore_cnt = 7;
  cfg.flags.enable_internal_pullup = 1;
  return i2c_new_master_bus(&cfg, &bus) == ESP_OK;
}

inline bool is_registered_board_bus(i2c_master_bus_handle_t bus) {
  i2c_master_bus_handle_t registered = nullptr;
  return bus && i2c_master_get_bus_handle(I2C_NUM_1, &registered) == ESP_OK && bus == registered;
}

} // namespace stackchan::standalone::k151
