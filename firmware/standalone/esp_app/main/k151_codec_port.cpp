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
#include "audio_wipe.hpp"
#include "k151_dma_tx_tail.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <utility>
#include <driver/i2c_master.h>
#include <esp_attr.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr char kTag[] = "SC_K151_AUDIO";
constexpr size_t kMaxFrames = kPcmFramesPerTenMs; // 10ms of PCM, NOT a driver timeout bound.
static_assert(kMaxFrames == DmaTxTail::kFramesPerDescriptor);
static_assert(k151::kProbeAddresses[k151::index(k151::Device::mic_es7210)] ==
              (ES7210_CODEC_DEFAULT_ADDR >> 1));
static_assert(k151::kProbeAddresses[k151::index(k151::Device::amp_aw88298)] ==
              (AW88298_CODEC_DEFAULT_ADDR >> 1));
constexpr int kLowVolume = 10;
constexpr int kInputGain = 30;
constexpr int kI2cPort = 1;

// I2S0 has one TX owner. Keep ISR storage alive even if SDK teardown fails.
DRAM_ATTR DmaTxTail tx_tail;
std::atomic_flag tx_tail_owned = ATOMIC_FLAG_INIT;

bool IRAM_ATTR observe_codec_tx_tail(i2s_chan_handle_t, i2s_event_data_t* event, void* user) {
  auto& tail = *static_cast<DmaTxTail*>(user);
  tail.on_sent(event ? event->dma_buf : nullptr, event ? event->size : 0);
  return false;
}

bool disable_owned_channel(i2s_chan_handle_t channel) {
  i2s_chan_info_t info{};
  if (i2s_channel_get_info(channel, &info) != ESP_OK) {
    (void)i2s_channel_disable(channel); // Best effort; uncertainty remains faulted.
    return false;
  }
  // SDK set_fmt/enable/close can change the channel behind our port. A cached
  // flag would issue a second disable and turn a healthy close into a fault.
  return !info.is_enabled || i2s_channel_disable(channel) == ESP_OK;
}
} // namespace

const char* K151CodecPort::compiled_link_marker() {
  auto volatile prepare = &K151CodecPort::prepare;
  (void)prepare;
  return "K151 ES7210/AW88298 24kHz guarded driver compiled; NOT STARTED";
}

K151CodecPort::~K151CodecPort() { (void)shutdown(); }

bool K151CodecPort::prepare_microphone_only(const std::atomic_bool& owner,
                                            const std::atomic_bool& stop,
                                            const K151MicOnlyEvidence& evidence) {
  if (attempted_ || !owner.load() || stop.load() || !evidence.verified()) return false;
  mic_owner_ = &owner;
  mic_stop_ = &stop;
  return prepare_hardware();
}

bool K151CodecPort::fail() {
  if (microphone_only() && fault_) return false;
  fault_ = true;
  if (microphone_only()) (void)shutdown();
  else (void)quiet();
  return false;
}

bool K151CodecPort::prepare(bool physical_owner_approval, bool exact_k151_identity,
                             bool amp_reset_and_power_verified) {
  // No network, GPIO reset or peripheral operations if any prerequisite is missing.
  // These booleans are NOT supplied by a USB frame, configuration blob or app_main.
  if (attempted_ || !physical_owner_approval || !exact_k151_identity ||
      !amp_reset_and_power_verified) return false;
  return prepare_hardware();
}

bool K151CodecPort::prepare_hardware() {
  attempted_ = true;
  if (!input_allowed() || !prepare_i2s() || !input_allowed()) return fail();
  prepare_stage_ = K151MicWakeStage::codec_prepare;
  if (!prepare_codecs() || !input_allowed()) return fail();
  // Output is deliberately NOT opened and the amplifier is NOT enabled.
  prepared_ = true;
  return true;
}

bool K151CodecPort::prepare_microphone_board() {
  constexpr int timeout_ms = 30;
  constexpr uint8_t audio_ldo_enable_bits = 0x03; // CoreS3 ALDO1/ALDO2.
  constexpr uint8_t amp_reset = 1 << 2; // AW9523 P0_2 -> AW88298 RSTN.
  constexpr uint8_t p0_output = 0x02;
  constexpr uint8_t p0_direction = 0x04;
  const auto read = [&](i2c_master_dev_handle_t dev, uint8_t reg, uint8_t& value) {
    return input_allowed() &&
           i2c_master_transmit_receive(dev, &reg, 1, &value, 1, timeout_ms) == ESP_OK &&
           input_allowed();
  };
  const auto with_device = [&](k151::Device device, const auto& operation) {
    if (!input_allowed()) return false;
    i2c_device_config_t cfg{};
    cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    cfg.device_address = k151::kProbeAddresses[k151::index(device)];
    cfg.scl_speed_hz = 100000;
    if (i2c_master_bus_add_device(i2c_bus_, &cfg, &board_device_) != ESP_OK)
      return false;
    const bool checked = operation(board_device_);
    const bool removed = release_board_device();
    if (checked && !removed) prepare_stage_ = K151MicWakeStage::board_release;
    return checked && removed && input_allowed();
  };

  // Reject unfamiliar or disabled rails without changing the PMIC.
  prepare_stage_ = K151MicWakeStage::board_power;
  if (!with_device(k151::Device::pmic_axp2101, [&](auto dev) {
        uint8_t id{}, enable{};
        return read(dev, 0x03, id) && id == 0x4a &&
               read(dev, k151::kPmicLdoRegisters.front(), enable) &&
               (enable & audio_ldo_enable_bits) == audio_ldo_enable_bits;
      })) return false;

  // Keep RSTN asserted even on teardown. Factory initialization will release
  // it after restore/reboot. Do not change the mode or direction of any pin.
  prepare_stage_ = K151MicWakeStage::amplifier_reset;
  return with_device(k151::Device::io_aw9523, [&](auto dev) {
    uint8_t id{}, mode{}, direction{}, output{};
    if (!read(dev, 0x10, id) || id != 0x23 ||
        !read(dev, k151::kAw9523P0ModeRegister, mode) || !(mode & amp_reset) ||
        !read(dev, p0_direction, direction) || (direction & amp_reset) ||
        !read(dev, p0_output, output)) return false;
    const uint8_t held = output & ~amp_reset;
    const uint8_t command[]{p0_output, held};
    if (output != held &&
        (!input_allowed() ||
         i2c_master_transmit(dev, command, sizeof(command), timeout_ms) != ESP_OK))
      return false;
    return read(dev, p0_output, output) && output == held;
  });
}

bool K151CodecPort::release_board_device() {
  const auto result = i2c_master_bus_rm_device(board_device_);
  // Pinned IDF rejects a busy device before unlinking or freeing it.
  if (result != ESP_ERR_INVALID_STATE) board_device_ = nullptr;
  return result == ESP_OK;
}

bool K151CodecPort::prepare_i2s() {
  prepare_stage_ = K151MicWakeStage::i2c_bus;
  i2c_master_bus_config_t bus_cfg = {};
  bus_cfg.i2c_port = static_cast<i2c_port_t>(kI2cPort);
  bus_cfg.sda_io_num = static_cast<gpio_num_t>(k151::kI2cSda);
  bus_cfg.scl_io_num = static_cast<gpio_num_t>(k151::kI2cScl);
  bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
  bus_cfg.glitch_ignore_cnt = 7;
  bus_cfg.flags.enable_internal_pullup = 1;
  if (i2c_new_master_bus(&bus_cfg, &i2c_bus_) != ESP_OK) return false;
  if (microphone_only() && !prepare_microphone_board()) return false;

  prepare_stage_ = K151MicWakeStage::i2s_rx;
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan.dma_desc_num = DmaTxTail::kDescriptorCount;
  chan.dma_frame_num = DmaTxTail::kFramesPerDescriptor;
  chan.auto_clear_after_cb = !microphone_only();
  if (!input_allowed() ||
      i2s_new_channel(&chan, microphone_only() ? nullptr : &tx_, &rx_) != ESP_OK)
    return false;
  if (microphone_only()) {
    if (!data_port_.attach_receive_only(rx_)) return false;
  } else if (!prepare_i2s_tx()) {
    return false;
  }

  i2s_tdm_config_t rx_cfg = {};
  rx_cfg.clk_cfg = I2S_TDM_CLK_DEFAULT_CONFIG(k151::kInputHz);
  rx_cfg.clk_cfg.bclk_div = 8;
  const auto slot_mask = static_cast<i2s_tdm_slot_mask_t>(microphone_only()
      ? (I2S_TDM_SLOT0 | I2S_TDM_SLOT1)
      : (I2S_TDM_SLOT0 | I2S_TDM_SLOT1 | I2S_TDM_SLOT2 | I2S_TDM_SLOT3));
  rx_cfg.slot_cfg = I2S_TDM_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO, slot_mask);
  if (microphone_only()) {
    // Same final 2-slot/16-bit TDM format as esp_codec_dev 1.6.2 set_drv_fs.
    rx_cfg.slot_cfg.total_slot = 2;
    rx_cfg.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_16BIT;
    rx_cfg.slot_cfg.ws_width = 16;
    rx_cfg.slot_cfg.left_align = true;
  }
  rx_cfg.gpio_cfg.mclk = static_cast<gpio_num_t>(k151::kI2sMclk);
  rx_cfg.gpio_cfg.bclk = static_cast<gpio_num_t>(k151::kI2sBclk);
  rx_cfg.gpio_cfg.ws = static_cast<gpio_num_t>(k151::kI2sWs);
  rx_cfg.gpio_cfg.dout = I2S_GPIO_UNUSED;
  rx_cfg.gpio_cfg.din = static_cast<gpio_num_t>(k151::kI2sDin);

  if (!input_allowed() ||
      i2s_channel_init_tdm_mode(rx_, &rx_cfg) != ESP_OK) return false;
  if (microphone_only()) return true; // Leave RX disabled until microphone_on.
  if (i2s_channel_enable(tx_) != ESP_OK) return false;
  if (i2s_channel_enable(rx_) != ESP_OK) return false;
  return true;
}

bool K151CodecPort::prepare_i2s_tx() {
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
  if (i2s_channel_init_std_mode(tx_, &tx_cfg) != ESP_OK || tx_tail_owned.test_and_set())
    return false;
  i2s_event_callbacks_t callbacks{};
  callbacks.on_sent = observe_codec_tx_tail;
  tx_tail_registered_ = i2s_channel_register_event_callback(tx_, &callbacks, &tx_tail) == ESP_OK;
  if (!tx_tail_registered_) tx_tail_owned.clear();
  return tx_tail_registered_;
}

bool K151CodecPort::prepare_codecs() {
  if (!microphone_only()) {
    audio_codec_i2s_cfg_t i2s_cfg = {};
    i2s_cfg.port = I2S_NUM_0;
    i2s_cfg.rx_handle = rx_;
    i2s_cfg.tx_handle = tx_;
    data_if_ = audio_codec_new_i2s_data(&i2s_cfg);
    if (!data_if_ || !data_port_.attach(data_if_, rx_, tx_) || !prepare_output_codec())
      return false;
  }
  return input_allowed() && prepare_input_codec();
}

bool K151CodecPort::prepare_output_codec() {
  audio_codec_i2c_cfg_t i2c_cfg = {};
  i2c_cfg.port = static_cast<i2c_port_t>(kI2cPort);
  i2c_cfg.addr = AW88298_CODEC_DEFAULT_ADDR;
  i2c_cfg.bus_handle = i2c_bus_;
  out_ctrl_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
  gpio_if_ = audio_codec_new_gpio();
  if (!out_ctrl_ || !gpio_if_ || !out_control_.attach(out_ctrl_)) return false;

  aw88298_codec_cfg_t out_cfg = {};
  out_cfg.ctrl_if = out_control_.interface();
  out_cfg.gpio_if = gpio_if_;
  out_cfg.reset_pin = GPIO_NUM_NC; // External AW9523 reset NOT implemented.
  out_cfg.hw_gain.pa_voltage = 5.0f;
  out_cfg.hw_gain.codec_dac_voltage = 3.3f;
  out_cfg.hw_gain.pa_gain = 1;
  out_codec_ = aw88298_codec_new(&out_cfg);
  if (!out_codec_ || !out_control_.muted_startup_verified()) return false;

  esp_codec_dev_cfg_t dev_cfg = {};
  dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_OUT;
  dev_cfg.codec_if = out_codec_;
  dev_cfg.data_if = data_port_.interface();
  out_dev_ = esp_codec_dev_new(&dev_cfg);
  return out_dev_ != nullptr;
}

bool K151CodecPort::prepare_input_codec() {
  audio_codec_i2c_cfg_t i2c_cfg = {};
  i2c_cfg.port = static_cast<i2c_port_t>(kI2cPort);
  i2c_cfg.bus_handle = i2c_bus_;
  i2c_cfg.addr = ES7210_CODEC_DEFAULT_ADDR;
  in_ctrl_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
  if (!in_ctrl_ || !in_control_.attach(in_ctrl_) || !input_allowed()) return false;
  es7210_codec_cfg_t in_cfg = {};
  in_cfg.ctrl_if = in_control_.interface();
  in_cfg.mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2 | ES7210_SEL_MIC3;
  in_codec_ = es7210_codec_new(&in_cfg);
  if (!in_codec_ || !in_control_.healthy() || !input_allowed()) return false;
  esp_codec_dev_cfg_t dev_cfg = {};
  dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_IN;
  dev_cfg.codec_if = in_codec_;
  dev_cfg.data_if = data_port_.interface();
  in_dev_ = esp_codec_dev_new(&dev_cfg);
  return in_dev_ != nullptr;
}

bool K151CodecPort::microphone_on() {
  if (!input_allowed()) return fail();
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
  if (esp_codec_dev_open(in_dev_, &fs) != 0 || !data_port_.ready(ESP_CODEC_DEV_TYPE_IN) ||
      !in_control_.healthy() || !input_allowed()) return fail();
  if (esp_codec_dev_set_in_channel_gain(
          in_dev_, ESP_CODEC_DEV_MAKE_CHANNEL_MASK(0), kInputGain) != 0 ||
      !in_control_.healthy() || !input_allowed()) return fail();
  return true;
}

bool K151CodecPort::microphone_off() {
  if (close_microphone()) return true;
  if (microphone_only()) return fail();
  fault_ = true;
  return false;
}

bool K151CodecPort::close_microphone(bool* driver_closed) {
  if (!input_open_) return !in_control_.faulted();
  const int rc = esp_codec_dev_close(in_dev_);
  const bool closed = rc == 0 && data_port_.disabled(ESP_CODEC_DEV_TYPE_IN);
  if (driver_closed) *driver_closed = closed;
  if (!closed || !in_control_.healthy()) return false;
  input_open_ = false;
  return true;
}

bool K151CodecPort::capture_mono_24k(std::span<int16_t> mono) {
  wipe_pcm(mono);
  if (!input_allowed()) return fail();
  if (!prepared() || !input_open_ || output_open_ || mono.empty() ||
      mono.size() > kMaxFrames) return false;
  std::array<int16_t, kMaxFrames * 2> interleaved = {};
  ScopedPcmWipe clear{interleaved};
  const int rc = esp_codec_dev_read(in_dev_, interleaved.data(),
                                    static_cast<int>(mono.size() * 2 * sizeof(int16_t)));
  if (rc != 0 || !data_port_.ready(ESP_CODEC_DEV_TYPE_IN) || !input_allowed()) {
    wipe_pcm(interleaved);
    return fail();
  }
  if (!extract_k151_mic0(std::span<const int16_t>(interleaved.data(), mono.size() * 2), mono)) {
    return fail();
  }
  if (!input_allowed()) {
    wipe_pcm(mono);
    wipe_pcm(interleaved);
    return fail();
  }
  return true;
}

bool K151CodecPort::playback_available() const {
  // Source-derived AW9523/AXP2101 sequence is not a measured K151 power-up.
  // The DMA observer still needs physical reset, mute and codec-idle evidence.
  if (!kK151PhysicalOutputEnabledInHoldImage ||
      !kK151SafeDmaDrainDriverAvailable) return false;
  return !microphone_only() && tx_tail_registered_ && prepared();
}

bool K151CodecPort::speaker_on_low_volume() {
  if (!playback_available() || input_open_ || output_open_) return false;
  esp_codec_dev_sample_info_t fs = {};
  fs.bits_per_sample = 16;
  fs.channel = 1;
  fs.sample_rate = k151::kOutputHz;
  // Preserve a best-effort close even after a partially failed open.
  output_open_ = true;
  if (esp_codec_dev_open(out_dev_, &fs) != 0 || !data_port_.ready(ESP_CODEC_DEV_TYPE_OUT) ||
      !out_control_.healthy()) return fail();
  if (esp_codec_dev_set_out_vol(out_dev_, kLowVolume) != 0 || !out_control_.healthy()) return fail();
  return true;
}

bool K151CodecPort::speaker_off() {
  output_pending_ = false;
  if (!output_open_) return !out_control_.faulted();
  const int rc = esp_codec_dev_close(out_dev_);
  if (rc != 0 || !data_port_.disabled(ESP_CODEC_DEV_TYPE_OUT) || !out_control_.healthy()) {
    fault_ = true; return false;
  }
  output_open_ = false;
  return true;
}

bool K151CodecPort::play_mono_24k(std::span<const int16_t> mono) {
  if (!prepared() || !output_open_ || input_open_ ||
      !valid_pcm_playback(mono)) return false;
  // Copy avoids const-casting the caller's buffer through esp_codec_dev.
  std::array<int16_t, kMaxFrames> chunk = {};
  ScopedPcmWipe clear{chunk};
  std::copy(mono.begin(), mono.end(), chunk.begin());
  const int rc = esp_codec_dev_write(out_dev_, chunk.data(),
                                     static_cast<int>(mono.size() * sizeof(int16_t)));
  wipe_pcm(chunk);
  if (rc != 0 || !data_port_.ready(ESP_CODEC_DEV_TYPE_OUT)) return fail();
  output_pending_ = true;
  return true;
}

bool K151CodecPort::wait_for_tx_tail(const std::atomic_bool& owner,
                                    const std::atomic_bool& consent,
                                    const std::atomic_bool& stop) {
  if (!tx_tail_registered_ || !output_open_ || !std::exchange(output_pending_, false))
    return false;
  const auto allowed = [&] {
    return owner.load() && consent.load() && !stop.load() &&
           prepared() && data_port_.ready(ESP_CODEC_DEV_TYPE_OUT);
  };
  const auto reject = [&] {
    tx_tail.abandon();
    return fail();
  };
  i2s_chan_info_t info{};
  if (!allowed() || i2s_channel_get_info(tx_, &info) != ESP_OK || !info.is_enabled ||
      info.total_dma_buf_size % DmaTxTail::kDescriptorCount != 0)
    return reject();
  const auto started = esp_timer_get_time();
  if (!allowed() ||
      !tx_tail.arm(info.total_dma_buf_size / DmaTxTail::kDescriptorCount, started))
    return reject();

  for (;;) {
    if (!allowed()) return reject();
    const auto result = tx_tail.poll(esp_timer_get_time);
    if (result == DmaTxTail::Result::observed && allowed()) return true;
    if (result != DmaTxTail::Result::waiting) return reject();
    vTaskDelay(1);
  }
}

bool K151CodecPort::drain_output_before_mute() {
  // The DMA rotation alone does not observe idle at the amplifier.
  return false;
}

bool K151CodecPort::quiet() {
  // Attempt both paths even when one close fails. A failed close is NOT mute proof.
  const bool mic_ok = microphone_off();
  const bool spk_ok = speaker_off();
  return mic_ok && spk_ok;
}

bool K151CodecPort::shutdown() {
  const bool previously_faulted = faulted();
  in_control_.begin_cleanup();
  out_control_.begin_cleanup();
  bool input_driver_closed = true;
  const bool mic_ok = close_microphone(&input_driver_closed);
  const bool speaker_ok = speaker_off();
  bool cleanup_ok = input_driver_closed && speaker_ok;
  if (in_dev_) { esp_codec_dev_delete(in_dev_); in_dev_ = nullptr; }
  if (out_dev_) { esp_codec_dev_delete(out_dev_); out_dev_ = nullptr; }
  if (in_codec_ && audio_codec_delete_codec_if(std::exchange(in_codec_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  if (out_codec_ && audio_codec_delete_codec_if(std::exchange(out_codec_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  // Codec destruction can itself issue register operations whose errors the
  // SDK drops. Observe before detaching/freeing either original control object.
  const bool controls_ok = !in_control_.faulted() && !out_control_.faulted();
  in_control_.detach(); out_control_.detach();
  if (in_ctrl_ && audio_codec_delete_ctrl_if(std::exchange(in_ctrl_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  if (out_ctrl_ && audio_codec_delete_ctrl_if(std::exchange(out_ctrl_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  if (gpio_if_ && audio_codec_delete_gpio_if(std::exchange(gpio_if_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  data_port_.detach();
  if (data_if_ && audio_codec_delete_data_if(std::exchange(data_if_, nullptr)) != ESP_CODEC_DEV_OK)
    cleanup_ok = false;
  if (rx_) {
    if (!disable_owned_channel(rx_)) cleanup_ok = false;
    if (i2s_del_channel(rx_) != ESP_OK) cleanup_ok = false;
    else rx_ = nullptr; // IDF rejects a running channel before freeing it.
  }
  if (tx_) {
    if (tx_tail_registered_) tx_tail.abandon();
    if (!disable_owned_channel(tx_)) cleanup_ok = false;
    if (i2s_del_channel(tx_) != ESP_OK) cleanup_ok = false;
    else {
      tx_ = nullptr;
      if (tx_tail_registered_) {
        tx_tail.reset_after_release();
        tx_tail_registered_ = false;
        tx_tail_owned.clear();
      }
    }
  }
  if (board_device_ && !release_board_device()) cleanup_ok = false;
  if (i2c_bus_ && !board_device_) {
    if (i2c_del_master_bus(i2c_bus_) != ESP_OK) cleanup_ok = false;
    // Pinned IDF can report pin-deinit error after freeing the bus wrapper.
    // Never retry this ambiguous pointer. Fault remains; reclamation/mute is
    // NOT proven if deletion failed before free. No automatic reset/recovery.
    i2c_bus_ = nullptr;
  }
  prepared_ = false;
  input_open_ = output_open_ = false; // Codec devices gone, never mute proof.
  if (!cleanup_ok || in_control_.cleanup_faulted() || out_control_.cleanup_faulted())
    cleanup_unverified_ = true;
  const bool ok = cleanup_ok && mic_ok && controls_ok;
  if (!ok) {
    fault_ = true;
    ESP_LOGE(kTag, "audio shutdown uncertain");
  }
  // Releasing a handle cannot prove the earlier hardware fault was cleared.
  return ok && !previously_faulted;
}

} // namespace stackchan::standalone
