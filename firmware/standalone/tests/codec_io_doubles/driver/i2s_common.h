// SPDX-License-Identifier: MIT
// Minimal host declarations only; actual SDK validates the target build.
#pragma once
#include <cstddef>
#include <cstdint>
#include <esp_err.h>
struct i2s_channel_obj;
using i2s_chan_handle_t = i2s_channel_obj*;
struct i2s_event_data_t { void* dma_buf; size_t size; };
using i2s_isr_callback_t = bool (*)(i2s_chan_handle_t, i2s_event_data_t*, void*);
struct i2s_event_callbacks_t { i2s_isr_callback_t on_sent; };
constexpr int I2S_NUM_0=0, I2S_ROLE_MASTER=1, I2S_GPIO_UNUSED=-1, GPIO_NUM_NC=-1;
constexpr int I2S_DATA_BIT_WIDTH_16BIT=16, I2S_SLOT_MODE_STEREO=2, I2S_STD_SLOT_BOTH=3;
constexpr int I2S_SLOT_BIT_WIDTH_16BIT=16;
using i2s_tdm_slot_mask_t=int;
constexpr int I2S_TDM_SLOT0=1, I2S_TDM_SLOT1=2, I2S_TDM_SLOT2=4, I2S_TDM_SLOT3=8;
struct i2s_chan_config_t {
  int id,role;
  uint32_t dma_desc_num,dma_frame_num;
  bool auto_clear_after_cb;
};
#define I2S_CHANNEL_DEFAULT_CONFIG(n,r) {n,r,6,240,false}
struct i2s_clk_config { uint32_t sample_rate_hz; int bclk_div; };
struct i2s_slot_config {
  int data_bit_width,slot_mode,slot_mask;
  int slot_bit_width=0,total_slot=0,ws_width=0;
  bool left_align=false;
};
struct i2s_gpio_config { int mclk,bclk,ws,dout,din; };
struct i2s_chan_info_t { bool is_enabled; i2s_chan_handle_t pair_chan; uint32_t total_dma_buf_size; };
extern "C" {
esp_err_t i2s_new_channel(const i2s_chan_config_t*,i2s_chan_handle_t*,i2s_chan_handle_t*);
esp_err_t i2s_channel_enable(i2s_chan_handle_t);
esp_err_t i2s_channel_disable(i2s_chan_handle_t);
esp_err_t i2s_del_channel(i2s_chan_handle_t);
esp_err_t i2s_channel_get_info(i2s_chan_handle_t,i2s_chan_info_t*);
esp_err_t i2s_channel_read(i2s_chan_handle_t,void*,size_t,size_t*,uint32_t);
esp_err_t i2s_channel_write(i2s_chan_handle_t,const void*,size_t,size_t*,uint32_t);
esp_err_t i2s_channel_register_event_callback(i2s_chan_handle_t,const i2s_event_callbacks_t*,void*);
esp_err_t i2s_channel_preload_data(i2s_chan_handle_t,const void*,size_t,size_t*);
}
