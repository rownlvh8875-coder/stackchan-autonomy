// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <driver/i2c_master.h>

inline constexpr gpio_num_t GPIO_NUM_3 = 3;
inline constexpr gpio_num_t GPIO_NUM_4 = 4;
inline constexpr gpio_num_t GPIO_NUM_21 = 21;
inline constexpr gpio_num_t GPIO_NUM_35 = 35;
enum gpio_mode_t { GPIO_MODE_INPUT, GPIO_MODE_OUTPUT };
enum gpio_pullup_t { GPIO_PULLUP_DISABLE, GPIO_PULLUP_ENABLE };
enum gpio_pulldown_t { GPIO_PULLDOWN_DISABLE };
enum gpio_int_type_t { GPIO_INTR_DISABLE };
struct gpio_config_t {
  uint64_t pin_bit_mask;
  gpio_mode_t mode;
  gpio_pullup_t pull_up_en;
  gpio_pulldown_t pull_down_en;
  gpio_int_type_t intr_type;
};
extern "C" esp_err_t gpio_config(const gpio_config_t* config);
extern "C" esp_err_t gpio_set_level(gpio_num_t gpio_num, uint32_t level);
extern "C" esp_err_t gpio_set_direction(gpio_num_t gpio_num, gpio_mode_t mode);
extern "C" int gpio_get_level(gpio_num_t gpio_num);
