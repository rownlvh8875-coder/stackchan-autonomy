// SPDX-License-Identifier: MIT
#pragma once
#include "i2s_common.h"
struct i2s_tdm_config_t { i2s_clk_config clk_cfg; i2s_slot_config slot_cfg; i2s_gpio_config gpio_cfg; };
#define I2S_TDM_CLK_DEFAULT_CONFIG(hz) {hz,8}
#define I2S_TDM_PHILIPS_SLOT_DEFAULT_CONFIG(bits,mode,mask) {bits,mode,mask}
extern "C" esp_err_t i2s_channel_init_tdm_mode(i2s_chan_handle_t,const i2s_tdm_config_t*);
