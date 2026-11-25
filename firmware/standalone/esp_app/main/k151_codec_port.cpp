// SPDX-License-Identifier: MIT
// K151-specific ESP-IDF 6.1 / esp_codec_dev 1.6.2 audio transport.
// Sources for pins and TDM: M5Stack StackChan@28b9f0c and
// xiaozhi-esp32@49b4380/main/boards/m5stack/core-s3/cores3_audio_codec.cc.
// Nothing invokes hardware operations from app_main.
#include "k151_codec_port.hpp"
#include "k151_board_bus.hpp"
#include "k151_contract.hpp"
#include "pcm_frame.hpp"
#include "k151_output_evidence.hpp"
#include "board_evidence.hpp"
#include "audio_wipe.hpp"
#include "k151_dma_tx_tail.hpp"
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
#include "k151_conversation_policy.hpp"
#endif

#include <algorithm>
#include <array>
#include <cstdint>
#include <utility>
#include <driver/i2c_master.h>
#include <esp_attr.h>
#include <esp_log.h>
#include <esp_rom_sys.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace stackchan::standalone {
namespace {
constexpr char kTag[] = "SC_K151_AUDIO";
constexpr size_t kMaxFrames = kPcmFramesPerTenMs; // 10ms of PCM, NOT a driver timeout bound.
static_assert(kMaxFrames == DmaTxTail::kFramesPerDescriptor);
#ifndef STACKCHAN_K151_SPEAKER_PROBE
static_assert(k151::kProbeAddresses[k151::index(k151::Device::mic_es7210)] ==
              (ES7210_CODEC_DEFAULT_ADDR >> 1));
#endif
static_assert(k151::kProbeAddresses[k151::index(k151::Device::amp_aw88298)] ==
              (AW88298_CODEC_DEFAULT_ADDR >> 1));
constexpr int kLowVolume = 10;
constexpr int kInputGain = 30;
constexpr int kI2cPort = 1;
constexpr int kBoardReadTimeoutMs = 30;
constexpr int64_t kStandbySwitchLimitUs = 10'000;
constexpr unsigned kStandbySwitchPollLimit = 8;
constexpr uint32_t kStandbySwitchPollPauseUs = 1'000;
constexpr uint8_t kAmpResetBit = 1 << 2; // AW9523 P0_2 -> AW88298 RSTN.
constexpr uint8_t kP0Output = 0x02;

// I2S0 has one TX owner. Keep ISR storage alive even if SDK teardown fails.
DRAM_ATTR DmaTxTail tx_tail;
DRAM_ATTR portMUX_TYPE tx_tail_lock = portMUX_INITIALIZER_UNLOCKED;
std::atomic_flag tx_tail_owned = ATOMIC_FLAG_INIT;

bool IRAM_ATTR observe_codec_tx_tail(i2s_chan_handle_t, i2s_event_data_t* event, void* user) {
  auto& tail = *static_cast<DmaTxTail*>(user);
  portENTER_CRITICAL_ISR(&tx_tail_lock);
  tail.on_sent(event ? event->dma_buf : nullptr, event ? event->size : 0);
  portEXIT_CRITICAL_ISR(&tx_tail_lock);
  return false;
}

void abandon_tx_tail() {
  portENTER_CRITICAL(&tx_tail_lock);
  tx_tail.abandon();
  portEXIT_CRITICAL(&tx_tail_lock);
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

bool channel_is_idle(i2s_chan_handle_t channel) {
  i2s_chan_info_t info{};
  return channel && i2s_channel_get_info(channel, &info) == ESP_OK && !info.is_enabled;
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
  if (speaker_probe_build() || attempted_ || !owner.load() || stop.load() ||
      !evidence.verified()) return false;
  owner_ = &owner;
  stop_ = &stop;
  receive_only_ = true;
  return prepare_hardware();
}

bool K151CodecPort::fail() {
  if (microphone_only() && fault_) return false;
  fault_ = true;
  if (microphone_only()) (void)shutdown();
  else (void)quiet();
  return false;
}

bool K151CodecPort::is_registered_board_bus(i2c_master_bus_handle_t bus) {
  return k151::is_registered_board_bus(bus);
}

bool K151CodecPort::prepare(const std::atomic_bool& owner, const std::atomic_bool& stop,
                           const K151AudioBoardEvidence& evidence,
                           i2c_master_bus_handle_t borrowed_bus) {
  if (attempted_ || !owner.load() || stop.load() || !evidence.verified() ||
      (borrowed_bus && !is_registered_board_bus(borrowed_bus)))
    return false;
  owner_ = &owner;
  stop_ = &stop;
  i2c_bus_ = borrowed_bus;
  if (prepare_hardware()) return true;
  (void)shutdown();
  return false;
}

bool K151CodecPort::prepare_hardware() {
  attempted_ = true;
  if (!input_allowed() || !prepare_i2s() || !input_allowed()) return fail();
  prepare_stage_ = K151MicWakeStage::codec_prepare;
  if (!prepare_codecs() || (!microphone_only() && !quiesce_channels()) ||
      !input_allowed()) return fail();
  // Output is deliberately NOT opened and the amplifier is NOT enabled.
  prepared_ = true;
  return true;
}

bool K151CodecPort::quiesce_channels() {
  // RX has its own channel, while the SDK can leave its paired TX running to
  // supply clocks without logically opening playback. Stop both independently.
  const bool rx_stopped = speaker_probe_build() ||
      (disable_owned_channel(rx_) && channel_is_idle(rx_));
  const bool tx_stopped = disable_owned_channel(tx_);
  return rx_stopped && tx_stopped && channel_is_idle(tx_);
}

bool K151CodecPort::attach_board_device(uint16_t address) {
  if (board_device_ || !input_allowed()) return false;
  i2c_device_config_t cfg{};
  cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  cfg.device_address = address;
  cfg.scl_speed_hz = 100000;
  return i2c_master_bus_add_device(i2c_bus_, &cfg, &board_device_) == ESP_OK;
}

bool K151CodecPort::read_board_register(uint8_t reg, uint8_t& value) {
  return i2c_master_transmit_receive(board_device_, &reg, 1, &value, 1,
                                     kBoardReadTimeoutMs) == ESP_OK;
}

#ifdef STACKCHAN_K151_SPEAKER_PROBE
std::optional<uint16_t> K151CodecPort::read_amp_observation(uint8_t reg) {
  constexpr int kObservationReadTimeoutMs = 10;
  std::array<uint8_t, 2> word{};
  if (!amp_observer_ || i2c_master_transmit_receive(amp_observer_, &reg, 1, word.data(),
      word.size(), kObservationReadTimeoutMs) != ESP_OK) return std::nullopt;
  return (static_cast<uint16_t>(word[0]) << 8) | word[1];
}
#endif

bool K151CodecPort::set_amplifier_reset(bool held) {
  // Holding reset remains available after STOP on the validated duplex pin.
  const auto allowed = [&] { return (held && reset_controlled_) || input_allowed(); };
  uint8_t output{};
  if (!board_device_ || !allowed() || !read_board_register(kP0Output, output) ||
      !allowed()) return false;
  const auto desired = static_cast<uint8_t>(held ? output & ~kAmpResetBit :
                                                   output | kAmpResetBit);
  const uint8_t command[]{kP0Output, desired};
  if (output != desired &&
      i2c_master_transmit(board_device_, command, sizeof(command), kBoardReadTimeoutMs) != ESP_OK)
    return false;
  return allowed() && read_board_register(kP0Output, output) &&
         output == desired && allowed();
}

bool K151CodecPort::prepare_board() {
  constexpr uint8_t audio_ldo_enable_bits = 0x03; // CoreS3 ALDO1/ALDO2.
  const auto read = [&](uint8_t reg, uint8_t& value) {
    return input_allowed() && read_board_register(reg, value) && input_allowed();
  };
  prepare_stage_ = K151MicWakeStage::board_power;
  if (!attach_board_device(k151::kProbeAddresses[k151::index(k151::Device::pmic_axp2101)]))
    return false;
  uint8_t id{}, enable{};
  const bool rails = read(0x03, id) && id == 0x4a &&
      read(k151::kPmicLdoRegisters.front(), enable) &&
      (enable & audio_ldo_enable_bits) == audio_ldo_enable_bits;
  const bool pmic_released = release_board_device();
  if (rails && !pmic_released) prepare_stage_ = K151MicWakeStage::board_release;
  if (!rails || !pmic_released) return false;
#ifdef STACKCHAN_K151_SPEAKER_PROBE
  // Reserve a read-only observer before the reset and protected startup.
  if (attach_board_device(k151::kProbeAddresses[k151::index(k151::Device::amp_aw88298)]))
    amp_observer_ = std::exchange(board_device_, nullptr);
#endif

  // Preserve every unrelated output bit, GPIO mode and direction.
  prepare_stage_ = K151MicWakeStage::amplifier_reset;
  if (!attach_board_device(k151::kProbeAddresses[k151::index(k151::Device::io_aw9523)]))
    return false;
  uint8_t mode{}, direction{}, drive{};
  const bool gpio = read(0x10, id) && id == 0x23 &&
      read(k151::kAw9523P0ModeRegister, mode) && (mode & kAmpResetBit) &&
      read(0x04, direction) && !(direction & kAmpResetBit) &&
      (microphone_only() || (read(0x11, drive) && (drive & 0x10)));
  reset_controlled_ = gpio && !microphone_only();
  const bool held = gpio && set_amplifier_reset(true);
  if (!microphone_only()) return held && input_allowed(); // Retain expander for teardown.
  const bool removed = release_board_device();
  if (held && !removed) prepare_stage_ = K151MicWakeStage::board_release;
  return held && removed && input_allowed();
}

bool K151CodecPort::release_board_device() {
  const auto result = i2c_master_bus_rm_device(board_device_);
  // Pinned IDF rejects a busy device before unlinking or freeing it.
  if (result != ESP_ERR_INVALID_STATE) board_device_ = nullptr;
  return result == ESP_OK;
}

bool K151CodecPort::prepare_i2s() {
  prepare_stage_ = K151MicWakeStage::i2c_bus;
  if (!i2c_bus_) {
    if (!k151::open_board_bus(i2c_bus_)) return false;
    owns_i2c_bus_ = true;
  }
  if (!prepare_board()) return false;

  prepare_stage_ = K151MicWakeStage::i2s_rx;
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan.dma_desc_num = DmaTxTail::kDescriptorCount;
  chan.dma_frame_num = DmaTxTail::kFramesPerDescriptor;
  chan.auto_clear_after_cb = !microphone_only();
  if (!input_allowed() ||
      i2s_new_channel(&chan, microphone_only() ? nullptr : &tx_,
                      speaker_probe_build() ? nullptr : &rx_) != ESP_OK)
    return false;
  if (microphone_only()) {
    if (!data_port_.attach_receive_only(rx_)) return false;
  } else if (!prepare_i2s_tx()) {
    return false;
  }
  if constexpr (speaker_probe_build()) {
    return input_allowed();
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

  return input_allowed() && i2s_channel_init_tdm_mode(rx_, &rx_cfg) == ESP_OK;
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
#ifdef STACKCHAN_K151_SPEAKER_PROBE
  return input_allowed();
#else
  return input_allowed() && prepare_input_codec();
#endif
}

bool K151CodecPort::prepare_output_codec() {
  // Configure I2S while RSTN is low. AW88298 requires RSTN high for >1 ms
  // before valid I2S clocks and I2C configuration. Use the existing reset
  // intervals and then start the TX clock with the amplifier in standby.
  if (!input_allowed()) return false;
  vTaskDelay(pdMS_TO_TICKS(10) + 1);
  if (!input_allowed() || !set_amplifier_reset(false)) return false;
  vTaskDelay(pdMS_TO_TICKS(50) + 1);
  std::optional<bool>* before_codec_init = nullptr;
  std::optional<bool>* after_codec_init = nullptr;
#ifdef STACKCHAN_K151_SPEAKER_PROBE
  before_codec_init = &speaker_reset_observations_.before_codec_init;
  after_codec_init = &speaker_reset_observations_.after_codec_init;
  // The diagnostic takes one read-only SYSST sample before driving TX clocks.
  // The later standby checks validate the chip identity and retain the existing
  // protection decision. SYSINT is clear-on-read and is never sampled here.
  if (amp_observer_ && input_allowed()) {
    const auto status = read_amp_observation(0x01); // SYSST
    if (status && input_allowed())
      speaker_reset_observations_.before_tx = (*status & aw88298_protection::undervoltage) != 0;
  }
#endif
  if (!input_allowed() || i2s_channel_enable(tx_) != ESP_OK || !input_allowed()) return false;

  audio_codec_i2c_cfg_t i2c_cfg = {};
  i2c_cfg.port = static_cast<i2c_port_t>(kI2cPort);
  i2c_cfg.addr = AW88298_CODEC_DEFAULT_ADDR;
  i2c_cfg.bus_handle = i2c_bus_;
  out_ctrl_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
  gpio_if_ = audio_codec_new_gpio();
  if (!out_ctrl_ || !gpio_if_ || !out_control_.attach(out_ctrl_) ||
      !out_control_.aw88298_standby_verified(before_codec_init) || !input_allowed()) return false;

  aw88298_codec_cfg_t out_cfg = {};
  out_cfg.ctrl_if = out_control_.interface();
  out_cfg.gpio_if = gpio_if_;
  out_cfg.reset_pin = GPIO_NUM_NC; // The port owns the external AW9523 reset.
  out_cfg.hw_gain.pa_voltage = 5.0f;
  out_cfg.hw_gain.codec_dac_voltage = 3.3f;
  out_cfg.hw_gain.pa_gain = 1;
  out_codec_ = aw88298_codec_new(&out_cfg);
  if (!out_codec_ || !out_control_.muted_startup_verified() ||
      !out_control_.aw88298_standby_verified(after_codec_init) || !input_allowed()) return false;

  esp_codec_dev_cfg_t dev_cfg = {};
  dev_cfg.dev_type = ESP_CODEC_DEV_TYPE_OUT;
  dev_cfg.codec_if = out_codec_;
  dev_cfg.data_if = data_port_.interface();
  out_dev_ = esp_codec_dev_new(&dev_cfg);
  return out_dev_ != nullptr;
}

#ifndef STACKCHAN_K151_SPEAKER_PROBE
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
#endif

bool K151CodecPort::microphone_on() {
  if (speaker_probe_build()) return false;
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
  (void)shutdown();
  return false;
}

bool K151CodecPort::capture_idle() const {
  // This is also called during STOP when the live owner flag can be false.
  return prepared_ && !faulted() && !microphone_only() && !input_open_ && !output_open_ &&
         (speaker_probe_build() || channel_is_idle(rx_)) && channel_is_idle(tx_);
}

bool K151CodecPort::start_fresh_capture() {
  if (speaker_probe_build() || !prepared() || microphone_only() || input_open_ || output_open_)
    return false;
  if (!out_control_.aw88298_standby_verified()) return fail();
  if (!microphone_on()) return false;
  // The pinned IDF drops the RX queue on enable after a confirmed disable.
  // Discard one complete bounded block after reopening, before exposing PCM.
  std::array<int16_t, kMaxFrames> first{};
  ScopedPcmWipe clear{first};
  return capture_mono_24k(first);
}

bool K151CodecPort::close_microphone(bool* driver_closed) {
  if (!input_open_) return !in_control_.faulted();
  const int rc = esp_codec_dev_close(in_dev_);
  const bool closed = rc == 0 && data_port_.disabled(ESP_CODEC_DEV_TYPE_IN);
  const bool channels_stopped = microphone_only() || quiesce_channels();
  if (driver_closed) *driver_closed = closed && channels_stopped;
  if (!closed || !in_control_.healthy()) return false;
  input_open_ = false;
  return channels_stopped;
}

bool K151CodecPort::capture_mono_24k(std::span<int16_t> mono) {
  wipe_pcm(mono);
  if (speaker_probe_build()) return false;
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

bool K151CodecPort::playback_enabled_by_build() {
  if constexpr (speaker_probe_build()) return true;
#ifdef STACKCHAN_K151_CONVERSATION_IMAGE
  return k151_conversation_boot_armed();
#else
  // Source-derived AW9523/AXP2101 sequence is not a measured K151 power-up.
  // The DMA observer still needs physical reset, mute and codec-idle evidence.
  if (!kK151PhysicalOutputEnabledInHoldImage ||
      !kK151SafeDmaDrainDriverAvailable) return false;
  return true;
#endif
}

bool K151CodecPort::playback_available() const {
  return playback_enabled_by_build() && !microphone_only() && tx_tail_registered_ && prepared();
}

bool K151CodecPort::speaker_on_low_volume(const std::atomic_bool& consent) {
  using Stage = K151SpeakerStartupStage;
  speaker_startup_ = {Stage::admission};
  if (!playback_available() || input_open_ || output_open_) return false;
  if (!consent.load()) return false;
  // Board bring-up can leave RX clocked before the SDK codec was ever opened.
  // Quiesce the physical channel before enabling playback in the shared port.
  if (!speaker_probe_build() && !disable_owned_channel(rx_)) {
    fault_ = true;
    (void)shutdown();
    return false;
  }
  if (!consent.load() || !prepared()) return fail();
  esp_codec_dev_sample_info_t fs = {};
  fs.bits_per_sample = 16;
  fs.channel = 1;
  fs.sample_rate = k151::kOutputHz;
  // Preserve a best-effort close even after a partially failed open.
  output_open_ = true;
  speaker_startup_.stage = Stage::codec_open;
  if (esp_codec_dev_open(out_dev_, &fs) != 0) return fail();
  speaker_startup_.stage = Stage::codec_ready;
  if (!data_port_.ready(ESP_CODEC_DEV_TYPE_OUT) || !out_control_.healthy()) return fail();
  speaker_startup_.stage = Stage::i2s_tx_state;
  i2s_chan_info_t tx_info{};
  if (i2s_channel_get_info(tx_, &tx_info) != ESP_OK || !tx_info.is_enabled ||
      (speaker_probe_build() ? tx_info.pair_chan != nullptr : !channel_is_idle(rx_))) return fail();
  const auto allowed = [&] {
    return consent.load() && prepared() && data_port_.ready(ESP_CODEC_DEV_TYPE_OUT);
  };
  speaker_startup_.stage = Stage::volume;
  if (!allowed() || esp_codec_dev_set_out_vol(out_dev_, kLowVolume) != 0) return fail();
#ifdef STACKCHAN_K151_SPEAKER_PROBE
  const auto read_voltage = [&]() -> k151::VoltageReading {
    if (!amp_observer_) return {k151::PowerSample::not_seen};
    const auto vdd = read_amp_observation(0x12); // VDD
    return vdd ? k151::decode_aw88298_vdd(*vdd) : k151::VoltageReading{k151::PowerSample::read_failed};
  };
  const auto read_followup = [&]() -> std::optional<bool> {
    const auto status = read_amp_observation(0x01); // SYSST
    if (!status) return std::nullopt;
    return (*status & aw88298_protection::undervoltage) != 0;
  };
  speaker_startup_ = out_control_.start_aw88298_low_volume(
      allowed, esp_timer_get_time, [] { vTaskDelay(1); }, read_voltage, read_followup);
#else
  speaker_startup_ =
      out_control_.start_aw88298_low_volume(allowed, esp_timer_get_time, [] { vTaskDelay(1); });
#endif
  return speaker_startup_.stage == Stage::none ? true : fail();
}

K151SpeakerCleanupStage K151CodecPort::wait_for_standby_switch_off(
    const std::atomic_bool* consent, bool stopping) {
  using Cleanup = K151SpeakerCleanupStage;
  const auto allowed = [&] {
    i2s_chan_info_t info{};
    const bool admitted = stopping ? prepared_ && !faulted()
                                   : consent && input_allowed() && consent->load();
    return admitted && data_port_.ready(ESP_CODEC_DEV_TYPE_OUT) &&
        i2s_channel_get_info(tx_, &info) == ESP_OK && info.is_enabled;
  };
  if (!out_control_.request_aw88298_amplifier_off(allowed))
    return allowed() ? Cleanup::standby_amplifier_request : Cleanup::standby_interrupted;
  const auto started = esp_timer_get_time();
  if (started < 0) return Cleanup::standby_clock_fault;
  auto previous = started;
  const auto check = [&] {
    if (!allowed()) return Cleanup::standby_interrupted;
    const auto now = esp_timer_get_time();
    if (now < previous) return Cleanup::standby_clock_fault;
    previous = now;
    return now - started < kStandbySwitchLimitUs ? Cleanup::none : Cleanup::standby_switch_timeout;
  };
  // HMUTE and AMPPD are verified with the codec system still enabled. Poll
  // only SWS. An I2C read failure is terminal, as is late delivery.
  for (unsigned poll = 0; poll < kStandbySwitchPollLimit; ++poll) {
    if (const auto stage = check(); stage != Cleanup::none) return stage;
    const auto switching = out_control_.aw88298_switching();
    if (!switching) return Cleanup::standby_switch_status_read;
    if (const auto stage = check(); stage != Cleanup::none) return stage;
    if (!*switching) return Cleanup::none;
    // The 100 Hz probe tick could consume the entire 10 ms budget at once.
    if (poll + 1 < kStandbySwitchPollLimit) esp_rom_delay_us(kStandbySwitchPollPauseUs);
  }
  return Cleanup::standby_switch_timeout;
}

bool K151CodecPort::speaker_off(const std::atomic_bool* consent) {
  using Cleanup = K151SpeakerCleanupStage;
  const auto data = std::exchange(output_data_, OutputData::empty);
  if (!output_open_) return !out_control_.faulted();
  const bool normal_end = data == OutputData::drain_confirmed;
  const bool stopping = !normal_end && data != OutputData::empty && prepared_ && !faulted() &&
      (!input_allowed() || (consent && !consent->load()));
  const bool check_switching = normal_end || stopping;
  // STOP allows only the shutdown sequence. Hard mute is verified first, then
  // AMPPD and SWS are checked with the existing TX clock. No more PCM or drain.
  const auto before_close = check_switching
      ? wait_for_standby_switch_off(consent, stopping) : Cleanup::none;
  const bool standby_requested = out_control_.request_aw88298_standby();
  // Close even on a failed check, then require the final standby readback.
  const int rc = esp_codec_dev_close(out_dev_);
  const bool codec_closed = rc == 0 && data_port_.disabled(ESP_CODEC_DEV_TYPE_OUT);
  if (codec_closed) output_open_ = false;
  const bool closed = codec_closed && (!check_switching || channel_is_idle(tx_));
  auto standby_failure = Cleanup::none;
  const bool verified = standby_requested && before_close == Cleanup::none && closed &&
      out_control_.aw88298_standby_verified(nullptr, &standby_failure);
  const bool still_allowed = !normal_end || (consent && input_allowed() && consent->load());
  if (verified && still_allowed) return true;

  if (before_close != Cleanup::none) note_speaker_cleanup_failure(before_close);
  else if (!standby_requested) note_speaker_cleanup_failure(Cleanup::standby_request);
  else if (!closed) note_speaker_cleanup_failure(Cleanup::output_disable);
  else note_speaker_cleanup_failure(verified ? Cleanup::standby_interrupted : standby_failure);
  fault_ = true;
  // Reset is a fallback on uncertainty, never a successful completed turn.
  const bool reset_verified = reset_controlled_ && set_amplifier_reset(true);
  if (!reset_verified) cleanup_unverified_ = true;
#ifdef STACKCHAN_K151_SPEAKER_STOP_PROBE
  speaker_stop_reset_latch_verified_ |= reset_verified;
#endif
  return false;
}

#ifdef STACKCHAN_K151_SPEAKER_STOP_PROBE
bool K151CodecPort::speaker_stop_tx_idle() const { return channel_is_idle(tx_); }
#endif

bool K151CodecPort::play_mono_24k(std::span<const int16_t> mono) {
  output_data_ = OutputData::empty;
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
  output_data_ = OutputData::queued;
  return true;
}

bool K151CodecPort::wait_for_tx_tail(const std::atomic_bool& owner,
                                    const std::atomic_bool& consent,
                                    const std::atomic_bool& stop) {
  const auto data = std::exchange(output_data_, OutputData::empty);
  if (!tx_tail_registered_ || !output_open_ || data != OutputData::queued)
    return false;
  const auto allowed = [&] {
    return owner.load() && consent.load() && !stop.load() &&
           prepared() && data_port_.ready(ESP_CODEC_DEV_TYPE_OUT);
  };
  const auto reject = [&] {
    abandon_tx_tail();
    return fail();
  };
  i2s_chan_info_t info{};
  if (!allowed() || i2s_channel_get_info(tx_, &info) != ESP_OK || !info.is_enabled ||
      info.total_dma_buf_size % DmaTxTail::kDescriptorCount != 0)
    return reject();
  const auto started = esp_timer_get_time();
  if (!allowed()) return reject();
  portENTER_CRITICAL(&tx_tail_lock);
  const bool armed = tx_tail.arm(info.total_dma_buf_size / DmaTxTail::kDescriptorCount,
                                 started);
  portEXIT_CRITICAL(&tx_tail_lock);
  if (!armed) return reject();

  for (;;) {
    if (!allowed()) return reject();
    portENTER_CRITICAL(&tx_tail_lock);
    // esp_timer_get_time() is lock-free and callable with interrupts masked.
    const auto result = tx_tail.poll(esp_timer_get_time);
    portEXIT_CRITICAL(&tx_tail_lock);
    if (result == DmaTxTail::Result::observed && allowed()) {
      output_data_ = OutputData::dma_complete;
      return true;
    }
    if (result != DmaTxTail::Result::waiting) return reject();
    vTaskDelay(1);
  }
}

bool K151CodecPort::drain_output_before_mute() {
  // AudioGuard separately requires speaker_off() to verify amplifier standby.
  const auto data = std::exchange(output_data_, OutputData::empty);
  const bool drained = data == OutputData::dma_complete && output_open_ && !input_open_ &&
      prepared() && data_port_.ready(ESP_CODEC_DEV_TYPE_OUT);
  if (drained) output_data_ = OutputData::drain_confirmed;
  return drained;
}

bool K151CodecPort::quiet() {
  // Attempt both paths even when one close fails. A failed close is NOT mute proof.
  const bool mic_ok = microphone_off();
  const bool spk_ok = speaker_off();
  return mic_ok && spk_ok;
}

bool K151CodecPort::shutdown() {
  using Cleanup = K151SpeakerCleanupStage;
  const bool previously_faulted = faulted();
  in_control_.begin_cleanup();
  out_control_.begin_cleanup();
  bool input_driver_closed = true;
  const bool mic_ok = close_microphone(&input_driver_closed);
  const bool speaker_ok = speaker_off();
  bool cleanup_ok = true;
  const auto check_cleanup = [&](bool ok, Cleanup stage) {
    if (!ok) {
      note_speaker_cleanup_failure(stage);
      cleanup_ok = false;
    }
  };
  check_cleanup(input_driver_closed, Cleanup::i2s_disable);
  check_cleanup(speaker_ok, Cleanup::codec_control);
  if (in_dev_) { esp_codec_dev_delete(in_dev_); in_dev_ = nullptr; }
  if (out_dev_) { esp_codec_dev_delete(out_dev_); out_dev_ = nullptr; }
  if (in_codec_)
    check_cleanup(audio_codec_delete_codec_if(std::exchange(in_codec_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::codec_release);
  if (out_codec_)
    check_cleanup(audio_codec_delete_codec_if(std::exchange(out_codec_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::codec_release);
  if (reset_controlled_) {
    check_cleanup(set_amplifier_reset(true), Cleanup::amplifier_reset);
    reset_controlled_ = false;
  }
  // Codec destruction can itself issue register operations whose errors the
  // SDK drops. Observe before detaching/freeing either original control object.
  const bool controls_ok = !in_control_.faulted() && !out_control_.faulted();
  if (in_control_.cleanup_faulted() || out_control_.cleanup_faulted())
    note_speaker_cleanup_failure(Cleanup::codec_control);
  in_control_.detach(); out_control_.detach();
  if (in_ctrl_)
    check_cleanup(audio_codec_delete_ctrl_if(std::exchange(in_ctrl_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::interface_release);
  if (out_ctrl_)
    check_cleanup(audio_codec_delete_ctrl_if(std::exchange(out_ctrl_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::interface_release);
  if (gpio_if_)
    check_cleanup(audio_codec_delete_gpio_if(std::exchange(gpio_if_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::interface_release);
  data_port_.detach();
  if (data_if_)
    check_cleanup(audio_codec_delete_data_if(std::exchange(data_if_, nullptr)) == ESP_CODEC_DEV_OK,
                  Cleanup::interface_release);
  if (rx_) {
    check_cleanup(disable_owned_channel(rx_), Cleanup::i2s_disable);
    const bool deleted = i2s_del_channel(rx_) == ESP_OK;
    check_cleanup(deleted, Cleanup::i2s_release);
    if (deleted) rx_ = nullptr; // IDF rejects a running channel before freeing it.
  }
  if (tx_) {
    if (tx_tail_registered_) abandon_tx_tail();
    check_cleanup(disable_owned_channel(tx_), Cleanup::i2s_disable);
    const bool deleted = i2s_del_channel(tx_) == ESP_OK;
    check_cleanup(deleted, Cleanup::i2s_release);
    if (deleted) {
      tx_ = nullptr;
      if (tx_tail_registered_) {
        portENTER_CRITICAL(&tx_tail_lock);
        tx_tail.reset_after_release();
        portEXIT_CRITICAL(&tx_tail_lock);
        tx_tail_registered_ = false;
        tx_tail_owned.clear();
      }
    }
  }
  if (board_device_) check_cleanup(release_board_device(), Cleanup::i2c_release);
#ifdef STACKCHAN_K151_SPEAKER_PROBE
  if (amp_observer_)
    check_cleanup(i2c_master_bus_rm_device(std::exchange(amp_observer_, nullptr)) == ESP_OK,
                  Cleanup::i2c_release);
#endif
  if (i2c_bus_ && !board_device_) {
    if (owns_i2c_bus_) {
      check_cleanup(i2c_del_master_bus(i2c_bus_) == ESP_OK, Cleanup::i2c_release);
      // Pinned IDF can report pin-deinit error after freeing the bus wrapper.
      // Never retry this ambiguous pointer or assume reclamation after failure.
      owns_i2c_bus_ = false;
    }
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
