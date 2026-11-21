// SPDX-License-Identifier: MIT
// K151-specific ESP-IDF 6.1 / esp_codec_dev 1.6.2 audio transport.
// Sources for pins and TDM: M5Stack StackChan@28b9f0c and
// xiaozhi-esp32@49b4380/main/boards/m5stack/core-s3/cores3_audio_codec.cc.
// Nothing invokes hardware operations from app_main.
#include "k151_codec_port.hpp"
#include "k151_contract.hpp"
#include "pcm_frame.hpp"
#include "k151_output_evidence.hpp"
#include "board_evidence.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <driver/i2c_master.h>
#include <esp_log.h>

namespace stackchan::standalone {
namespace {
constexpr char kTag[] = "SC_K151_AUDIO";
constexpr size_t kMaxFrames = kPcmFramesPerTenMs; // 10ms of PCM, NOT a driver timeout bound.
static_assert(k151::kProbeAddresses[k151::index(k151::Device::mic_es7210)] ==
              (ES7210_CODEC_DEFAULT_ADDR >> 1));
static_assert(k151::kProbeAddresses[k151::index(k151::Device::amp_aw88298)] ==
              (AW88298_CODEC_DEFAULT_ADDR >> 1));
constexpr int kLowVolume = 10;
constexpr int kInputGain = 30;
constexpr int kI2cPort = 1;
} // namespace

const char* K151CodecPort::compiled_link_marker() {
  return "K151 ES7210/AW88298 24kHz guarded driver compiled; NOT STARTED";
}

K151CodecPort::~K151CodecPort() { (void)shutdown(); }

bool K151CodecPort::fail() {
  fault_ = true;
  (void)quiet();
  return false;
}

bool K151CodecPort::prepare(bool physical_owner_approval, bool exact_k151_identity,
                             bool amp_reset_and_power_verified) {
  // No network, GPIO reset or peripheral operations if any prerequisite is missing.
  // These booleans are NOT supplied by a USB frame, configuration blob or app_main.
  if (attempted_ || !physical_owner_approval || !exact_k151_identity ||
      !amp_reset_and_power_verified) return false;
  attempted_ = true;
  if (!prepare_i2s() || !prepare_codecs()) return fail();
  // Output is deliberately NOT opened and the amplifier is NOT enabled.
  prepared_ = true;
  return true;
}

bool K151CodecPort::prepare_i2s() {
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = static_cast<i2c_port_t>(kI2cPort);
  bus_cfg.sda_io_num = static_cast<gpio_num_t>(k151::kI2cSda);
  bus_cfg.scl_io_num = static_cast<gpio_num_t>(k151::kI2cScl);
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = 1;
  if (i2c_new_master_bus(&bus_cfg, &i2c_bus_) != ESP_OK) return false;

  // Two channels on the same peripheral: STD TX and four-slot TDM RX.
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan.dma_desc_num = 6;
  chan.dma_frame_num = 240;
  if (i2s_new_channel(&chan, &tx_, &rx_) != ESP_OK) return false;

  i2s_std_config_t tx_cfg = {};
  tx_cfg.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(k151::kOutputHz);
  tx_cfg.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  tx_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
  tx_cfg.gpio_cfg.mclk = static_cast<gpio_num_t>(k151::kI2sMclk);
  tx_cfg.gpio_cfg.bclk = static_cast<gpio_num_t>(k151::kI2sBclk);
  tx_cfg.gpio_cfg.ws = static_cast<gpio_num_t>(k151::kI2sWs);
  tx_cfg.gpio_cfg.dout = static_cast<gpio_num_t>(k151::kI2sDout);
  tx_cfg.gpio_cfg.din = I2S_GPIO_UNUSED;

  i2s_tdm_config_t rx_cfg = {};
  rx_cfg.clk_cfg = I2S_TDM_CLK_DEFAULT_CONFIG(k151::kInputHz);
  rx_cfg.clk_cfg.bclk_div = 8;
  rx_cfg.slot_cfg = I2S_TDM_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO,
      static_cast<i2s_tdm_slot_mask_t>(I2S_TDM_SLOT0 | I2S_TDM_SLOT1 |
                                        I2S_TDM_SLOT2 | I2S_TDM_SLOT3));
  rx_cfg.gpio_cfg.mclk = static_cast<gpio_num_t>(k151::kI2sMclk);
  rx_cfg.gpio_cfg.bclk = static_cast<gpio_num_t>(k151::kI2sBclk);
  rx_cfg.gpio_cfg.ws = static_cast<gpio_num_t>(k151::kI2sWs);
  rx_cfg.gpio_cfg.dout = I2S_GPIO_UNUSED;
  rx_cfg.gpio_cfg.din = static_cast<gpio_num_t>(k151::kI2sDin);

  if (i2s_channel_init_std_mode(tx_, &tx_cfg) != ESP_OK ||
      i2s_channel_init_tdm_mode(rx_, &rx_cfg) != ESP_OK) return false;
  if (i2s_channel_enable(tx_) != ESP_OK) return false;
  tx_enabled_ = true;
  if (i2s_channel_enable(rx_) != ESP_OK) return false;
  rx_enabled_ = true;
  return true;
}

bool K151CodecPort::prepare_codecs() {
  audio_codec_i2s_cfg_t i2s_cfg = {};
  i2s_cfg.port = I2S_NUM_0;
  i2s_cfg.rx_handle = rx_;
  i2s_cfg.tx_handle = tx_;
  data_if_ = audio_codec_new_i2s_data(&i2s_cfg);
  if (!data_if_) return false;

  audio_codec_i2c_cfg_t i2c_cfg = {};
  i2c_cfg.port = static_cast<i2c_port_t>(kI2cPort);
  i2c_cfg.addr = AW88298_CODEC_DEFAULT_ADDR;
  i2c_cfg.bus_handle = i2c_bus_;
  out_ctrl_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
  gpio_if_ = audio_codec_new_gpio();
  if (!out_ctrl_ || !gpio_if_) return false;

  aw88298_codec_cfg_t out_cfg = {};
  out_cfg.ctrl_if = out_ctrl_;
  out_cfg.gpio_if = gpio_if_;
  out_cfg.reset_pin = GPIO_NUM_NC; // External AW9523 reset NOT implemented.
  out_cfg.hw_gain.pa_voltage = 5.0f;
  out_cfg.hw_gain.codec_dac_voltage = 3.3f;
  out_cfg.hw_gain.pa_gain = 1;
  out_codec_ = aw88298_codec_new(&out_cfg);
  if (!out_codec_) return false;

  esp_codec_dev_cfg_t dev_cfg = {};
  dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_OUT;
  dev_cfg.codec_if = out_codec_;
  dev_cfg.data_if = data_if_;
  out_dev_ = esp_codec_dev_new(&dev_cfg);
  if (!out_dev_) return false;

  i2c_cfg.addr = ES7210_CODEC_DEFAULT_ADDR;
  in_ctrl_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
  if (!in_ctrl_) return false;
  es7210_codec_cfg_t in_cfg = {};
  in_cfg.ctrl_if = in_ctrl_;
  in_cfg.mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2 | ES7210_SEL_MIC3;
  in_codec_ = es7210_codec_new(&in_cfg);
  if (!in_codec_) return false;
  dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_IN;
  dev_cfg.codec_if = in_codec_;
  in_dev_ = esp_codec_dev_new(&dev_cfg);
  return in_dev_ != nullptr;
}

bool K151CodecPort::microphone_on() {
  if (!prepared() || input_open_ || output_open_) return false;
  esp_codec_dev_sample_info_t fs = {};
  fs.bits_per_sample = 16;
  fs.channel = 2; // Channel 0 mic and channel 1 reference, not stereo music.
  fs.channel_mask = ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0) |
                    ESP_CODEC_DEV_MAKE_CHANNEL_MASK(1);
  fs.sample_rate = k151::kInputHz;
  // Even an unsuccessful open can leave codec state uncertain.
  // Track it before the call so fail() attempts an independent close.
  input_open_ = true;
  if (esp_codec_dev_open(in_dev_, &fs) != 0) return fail();
  if (esp_codec_dev_set_in_channel_gain(
          in_dev_, ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0), kInputGain) != 0) return fail();
  return true;
}

bool K151CodecPort::microphone_off() {
  if (!input_open_) return true;
  const int rc = esp_codec_dev_close(in_dev_);
  if (rc != 0) { fault_ = true; return false; }
  input_open_ = false;
  return true;
}

bool K151CodecPort::capture_mono_24k(std::span<int16_t> mono) {
  if (!prepared() || !input_open_ || output_open_ || mono.empty() ||
      mono.size() > kMaxFrames) return false;
  std::array<int16_t, kMaxFrames * 2> interleaved = {};
  const int rc = esp_codec_dev_read(in_dev_, interleaved.data(),
                                    static_cast<int>(mono.size() * 2 * sizeof(int16_t)));
  if (rc != 0) {
    std::fill(mono.begin(), mono.end(), 0);
    return fail();
  }
  if (!extract_k151_mic0(std::span<const int16_t>(interleaved.data(), mono.size() * 2), mono)) {
    return fail();
  }
  std::fill(interleaved.begin(), interleaved.end(), 0);
  return true;
}

bool K151CodecPort::speaker_on_low_volume() {
  // Source-derived AW9523/AXP2101 sequence is not a measured K151 power-up.
  // No real reset, mute verification or DMA-drain observer exists in this image.
  if (!kK151PhysicalOutputEnabledInHoldImage ||
      !kK151SafeDmaDrainDriverAvailable) return false;
  if (!prepared() || input_open_ || output_open_) return false;
  esp_codec_dev_sample_info_t fs = {};
  fs.bits_per_sample = 16;
  fs.channel = 1;
  fs.sample_rate = k151::kOutputHz;
  // Preserve a best-effort close even after a partially failed open.
  output_open_ = true;
  if (esp_codec_dev_open(out_dev_, &fs) != 0) return fail();
  if (esp_codec_dev_set_out_vol(out_dev_, kLowVolume) != 0) return fail();
  return true;
}

bool K151CodecPort::speaker_off() {
  if (!output_open_) return true;
  const int rc = esp_codec_dev_close(out_dev_);
  if (rc != 0) { fault_ = true; return false; }
  output_open_ = false;
  return true;
}

bool K151CodecPort::play_mono_24k(std::span<const int16_t> mono) {
  if (!prepared() || !output_open_ || input_open_ ||
      !valid_pcm_playback(mono)) return false;
  // Copy avoids const-casting the caller's buffer through esp_codec_dev.
  std::array<int16_t, kMaxFrames> chunk = {};
  std::copy(mono.begin(), mono.end(), chunk.begin());
  const int rc = esp_codec_dev_write(out_dev_, chunk.data(),
                                     static_cast<int>(mono.size() * sizeof(int16_t)));
  std::fill(chunk.begin(), chunk.end(), 0);
  if (rc != 0) return fail();
  return true;
}

bool K151CodecPort::drain_output_before_mute() {
  // esp_codec_dev_write success is NOT independently verified amp/DMA drain.
  // Do not substitute a fixed delay or a queue-accepted acknowledgement.
  return false;
}

bool K151CodecPort::quiet() {
  // Attempt both paths even when one close fails. A failed close is NOT mute proof.
  const bool mic_ok = microphone_off();
  const bool spk_ok = speaker_off();
  return mic_ok && spk_ok;
}

bool K151CodecPort::shutdown() {
  const bool previously_faulted = fault_;
  bool ok = quiet();
  if (in_dev_) { esp_codec_dev_delete(in_dev_); in_dev_ = nullptr; }
  if (out_dev_) { esp_codec_dev_delete(out_dev_); out_dev_ = nullptr; }
  if (in_codec_) { audio_codec_delete_codec_if(in_codec_); in_codec_ = nullptr; }
  if (out_codec_) { audio_codec_delete_codec_if(out_codec_); out_codec_ = nullptr; }
  if (in_ctrl_) { audio_codec_delete_ctrl_if(in_ctrl_); in_ctrl_ = nullptr; }
  if (out_ctrl_) { audio_codec_delete_ctrl_if(out_ctrl_); out_ctrl_ = nullptr; }
  if (gpio_if_) { audio_codec_delete_gpio_if(gpio_if_); gpio_if_ = nullptr; }
  if (data_if_) { audio_codec_delete_data_if(data_if_); data_if_ = nullptr; }
  if (rx_) {
    if (rx_enabled_ && i2s_channel_disable(rx_) != ESP_OK) ok = false;
    rx_enabled_ = false;
    if (i2s_del_channel(rx_) != ESP_OK) ok = false;
    rx_ = nullptr;
  }
  if (tx_) {
    if (tx_enabled_ && i2s_channel_disable(tx_) != ESP_OK) ok = false;
    tx_enabled_ = false;
    if (i2s_del_channel(tx_) != ESP_OK) ok = false;
    tx_ = nullptr;
  }
  if (i2c_bus_) {
    if (i2c_del_master_bus(i2c_bus_) != ESP_OK) ok = false;
    i2c_bus_ = nullptr;
  }
  prepared_ = false;
  if (!ok) { fault_ = true; ESP_LOGE(kTag, "audio shutdown uncertain"); }
  // Releasing a handle cannot prove the earlier hardware fault was cleared.
  return ok && !previously_faulted;
}

} // namespace stackchan::standalone
