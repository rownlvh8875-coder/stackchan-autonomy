// SPDX-License-Identifier: MIT
// Execute actual port against pinned codec headers + no-hardware C ABI doubles.
#include "bench_gate.hpp"
#include "k151_codec_port.hpp"
#include "k151_mic_reader.hpp"
#include "k151_mic_wake_trial.hpp"
#include "native_wake_input.hpp"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <esp_heap_caps.h>
#include <freertos/task.h>
#include <limits>
#include <memory>
#include <string>
#include <string_view>
using namespace stackchan::standalone;
struct i2s_channel_obj { bool enabled=false; bool alive=true; int disables=0,deletes=0; };
struct i2c_master_bus_t { bool alive=true; int deletes=0; };
struct i2c_master_dev_t { uint16_t address; bool open=false; };
struct Dev { const audio_codec_data_if_t* data{}; esp_codec_dev_type_t type{}; bool open=false; };
namespace {
std::string mode;
i2s_channel_obj tx,rx;
i2c_master_bus_t bus;
i2c_master_dev_t pmic{0x34}, expander{0x58};
int reset_writes=0, reset_waits=0, expander_removes=0;
uint8_t output_latch=0xa7;
bool reset_read_back=false;
audio_codec_data_if_t base{};
audio_codec_ctrl_if_t controls[2]{};
const audio_codec_ctrl_if_t* codec_controls[2]{};
audio_codec_gpio_if_t gpio{};
audio_codec_if_t codecs[2]{};
Dev devices[2];
int created=0, deleted=0, data_deletes=0, calls=0, legacy_calls=0, timer_calls=0, gains=0, formats=0;
int controls_created=0, controls_deleted=0;
int bus_created=0, channels_created=0, tdm_inits=0;
int tx_callbacks_registered=0;
std::string phase;
bool base_open=true;
bool mic_only() { return mode.starts_with("mic_only_"); }
bool report_trial=false;
std::atomic_bool local_owner{true}, local_stop{false};
bool mic_wake_trial() { return report_trial || mode.starts_with("mic_only_trial_"); }
bool embedded_trial_chain() { return mode.starts_with("mic_only_trial_chain_"); }
int trial_resets=0, trial_chunks=0, trial_model_drops=0;
int heap_checks=0;
int64_t trial_time_us=1000;
bool regress_next_trial_clock=false;
BenchGate question_gate{1, 1};
constexpr std::string_view question_prefix="mic_only_trial_question_";
bool question_trial() { return mode.starts_with(question_prefix); }
bool direct_question() { return mode.starts_with("mic_only_trial_question_direct_"); }
std::string_view question_case() {
  auto name = std::string_view(mode).substr(question_prefix.size());
  if (direct_question()) name.remove_prefix(std::string_view("direct_").size());
  return name;
}
bool question_control() { return question_case().starts_with("control_"); }
bool question_with_gate() {
  return (question_control() && question_case()!="control_local_limit") ||
         question_case()=="standard_gate_stop";
}
int question_reads=0, question_cues=0, question_reads_at_cue=0;
std::array<int16_t, QuestionCapture::kMaxSamples> question_pcm{};
bool question_allocated=false, question_freed=false;
void announce_question() {
  const int released_wake_channels = direct_question() ? 0 : 1;
  assert(trial_model_drops == released_wake_channels && question_allocated && !question_freed);
  assert(bus_created == released_wake_channels + 1 && bus.deletes == released_wake_channels);
  assert(channels_created == released_wake_channels + 1 && rx.deletes == released_wake_channels);
  assert(rx.enabled && reset_writes==1 && output_latch==0xa3);
  ++question_cues;
  question_reads_at_cue=question_reads;
  if (question_case()=="stop_at_cue") local_stop=true;
}
struct TrialDetector : NativeWakePort {
  ~TrialDetector() override {
    assert(!rx.enabled);
    if (bus_created) assert(!bus.alive);
    if (mode == "mic_only_trial_stop_on_drop") local_stop = true;
    ++trial_model_drops;
  }
  bool ready() const override { return true; }
  NativeWakeFormat format() const override {
    return {16000, mode == "mic_only_trial_format" ? 159u : 512u, 1, 16};
  }
  bool reset() override {
    ++trial_resets;
    assert(bus_created == 0);
    if (mode == "mic_only_trial_stop_on_reset") local_stop = true;
    return mode != "mic_only_trial_reset_fail";
  }
  NativeWakeResult detect(std::span<int16_t> samples) override {
    assert(samples.size() == 512 && rx.enabled);
    if (++trial_chunks == 1) {
      assert(samples[0] == 0);
      if (mode == "mic_only_trial_input_counts") assert(samples[159] == 0);
      else assert(samples[159] > 100 && samples[159] < 160);
    }
    if (mode == "mic_only_trial_stop_in_detect") local_stop = true;
    if (mode == "mic_only_trial_revoke_in_detect") local_owner = false;
    if (mode == "mic_only_trial_slow_detect") trial_time_us += 100001;
    if (mode == "mic_only_trial_poll_duration_boundary") trial_time_us += 90000;
    if (mode == "mic_only_trial_transient_rollback") regress_next_trial_clock=true;
    if (mode == "mic_only_trial_model_error") return NativeWakeResult::error;
    if (question_trial()) {
      const auto test = question_case();
      if (test == "wake_paced_deadline" || test == "wake_cue_deadline")
        return NativeWakeResult::none;
      if (test == "wake_detect_at_deadline" || test == "wake_detect_over_deadline") {
        // At 160 resampled samples per read, the 156th chunk fills on read 500.
        if (trial_chunks < 156) return NativeWakeResult::none;
        if (test == "wake_detect_over_deadline") ++trial_time_us;
        return NativeWakeResult::detected;
      }
    }
    if (mode == "mic_only_trial_wall" || mode == "mic_only_trial_frame_cap" ||
        mode == "mic_only_trial_window_overrun" || mode == "mic_only_trial_window_boundary" ||
        mode == "mic_only_trial_question_no_wake")
      return NativeWakeResult::none;
    return NativeWakeResult::detected;
  }
};
struct WakeDetector : NativeWakePort {
  int chunks = 0;
  bool ready() const override { return true; }
  NativeWakeFormat format() const override { return {16000, 512, 1, 16}; }
  bool reset() override { return true; }
  NativeWakeResult detect(std::span<int16_t> samples) override {
    assert(samples.size() == 512);
    ++chunks;
    assert(samples[0] == 0);
    assert(samples[159] > 100 && samples[159] < 160);
    if (mode == "mic_only_wakenet_late_stop") local_stop = true;
    return NativeWakeResult::detected;
  }
};
bool fail_rx_disable=false;
std::array<std::array<uint8_t, 2>, 16> amp_registers{};
bool ctrl_open(const audio_codec_ctrl_if_t* h) {assert(h==&controls[0] || h==&controls[1]);return true;}
int ctrl_io(const audio_codec_ctrl_if_t* h,int reg,int reg_len,void* data,int n,bool write) {
  assert(h==&controls[0] || h==&controls[1]);const bool out=h==&controls[0];
  assert(reg_len==1 && data && n==(out?2:1));
  auto* bytes=static_cast<uint8_t*>(data);
  if (out && !write && (reg == 0x00 || reg == 0x01)) {
    assert((output_latch & 0x04) && reset_waits == 2);
    bytes[0] = reg == 0x00 ? 0x18 :
        (mode == "duplex_board_switch_active" && phase == "init" ? 0x01 : 0x00);
    bytes[1] = reg == 0x00 && mode != "duplex_board_wrong_amp" ? 0x52 : 0x00;
    return ESP_CODEC_DEV_OK;
  }
  if (out && (reg == 0x04 || reg == 0x05 || reg == 0x0c)) {
    auto& stored = amp_registers[reg];
    if (write) {
      if (reg == 0x04) assert((bytes[1] & 0x43) == 0x03);
      if (reg == 0x05) assert(bytes[1] & 0x10);
      if (reg == 0x0c) assert(bytes[0] == 0x60);
      stored = {bytes[0], bytes[1]};
    } else {
      bytes[0] = stored[0];
      bytes[1] = stored[1];
    }
    return ESP_CODEC_DEV_OK;
  }
  assert(reg==(out?0x06:0x43));
  if(!write){bytes[0]=out?0x12:0;if(out)bytes[1]=0x34;}
  else if(out){assert(bytes[0]==0xb7 && bytes[1]==0x6e);}
  const std::string path=out?"ctrl_out_":"ctrl_in_";
  if (!out && !write &&
      (mode=="mic_only_codec_open_reg_error" || mode=="mic_only_codec_open_and_cleanup_error") &&
      (phase=="open" || (mode=="mic_only_codec_open_and_cleanup_error" && phase=="close")))
    return ESP_CODEC_DEV_DRV_ERR;
  return mode==path+phase+(write?"_write":"_read")?ESP_CODEC_DEV_DRV_ERR:ESP_CODEC_DEV_OK;
}
int ctrl_read(const audio_codec_ctrl_if_t* h,int reg,int len,void* data,int n){return ctrl_io(h,reg,len,data,n,false);}
int ctrl_write(const audio_codec_ctrl_if_t* h,int reg,int len,void* data,int n){return ctrl_io(h,reg,len,data,n,true);}
int ctrl_info(const audio_codec_ctrl_if_t* h,audio_codec_ctrl_info_t* info){assert(ctrl_open(h));info->type=AUDIO_CODEC_CTRL_I2C;return 0;}
void codec_operation(int i,const char* step) {
  phase=step;std::array<uint8_t,3> value{0,0,0x5a};auto* c=codec_controls[i];
  const bool out=i==0;const int reg=out?0x06:0x43,size=out?2:1;
  // ES7210 update_reg_bit discards read error; SDK gain/close discard codec rc.
  (void)c->read_reg(c,reg,1,value.data(),size);
  if((mode=="mic_only_stop_open" || mode=="mic_only_trial_stop_on_open") && phase=="open")local_stop=true;
  if(mode=="mic_only_trial_stop_on_close" && phase=="close")local_stop=true;
  if(out){value[0]^=0xa5;value[1]^=0x5a;}
  (void)c->write_reg(c,reg,1,value.data(),size);assert(value[2]==0x5a);
}
bool sdk_open(const audio_codec_data_if_t* h) { assert(h==&base);return base_open; }
int sdk_enable(const audio_codec_data_if_t* h,esp_codec_dev_type_t type,bool enable) {
  assert(h==&base);
  if(mode==(enable?"enable_fail":"disable_fail"))return ESP_FAIL;
  return enable?i2s_channel_enable(type==ESP_CODEC_DEV_TYPE_IN?&rx:&tx):
                i2s_channel_disable(type==ESP_CODEC_DEV_TYPE_IN?&rx:&tx);
}
int sdk_format(const audio_codec_data_if_t* h,esp_codec_dev_type_t type,esp_codec_dev_sample_info_t*) {
  assert(h==&base);++formats;
  // SDK format callback disables the selected channel before reconfiguration.
  (void)i2s_channel_disable(type==ESP_CODEC_DEV_TYPE_IN?&rx:&tx);
  return mode=="format_fail"?ESP_FAIL:ESP_OK;
}
int legacy_read(const audio_codec_data_if_t*,uint8_t* p,int n) {
  ++legacy_calls;size_t bytes=0;
  return i2s_channel_read(&rx,p,n,&bytes,1000); // pinned SDK1.6.2 behavior
}
int legacy_write(const audio_codec_data_if_t*,uint8_t* p,int n) {
  ++legacy_calls;size_t bytes=0;return i2s_channel_write(&tx,p,n,&bytes,1000);
}
int sdk_close(const audio_codec_data_if_t* h) {assert(h==&base);base_open=false;return 0;}
void zero(std::span<const int16_t> pcm) { for(auto sample:pcm)assert(sample==0); }
}
extern "C" int64_t esp_timer_get_time() {
  ++timer_calls;
  if(mic_wake_trial()) {
    if(mode=="mic_only_trial_invalid_start" && timer_calls==1)return -1;
    if(regress_next_trial_clock) {
      regress_next_trial_clock=false;
      return trial_time_us-1;
    }
    return trial_time_us;
  }
  if(mode=="clock_negative")return -1;
  if(timer_calls==1)return 1000;
  if(mode=="clock_backwards")return 999;
  return mode=="deadline" || mode=="write_deadline" ? 41001 : mode=="boundary" ? 41000 : 2000;
}
extern "C" void* heap_caps_malloc(size_t size,uint32_t caps) {
  assert(question_trial() && size==question_pcm.size()*sizeof(int16_t));
  assert(caps==(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (direct_question()) assert(trial_model_drops == 0 && bus_created == 0 && channels_created == 0);
  else assert(trial_model_drops == 1 && bus_created == 1 && !bus.alive && !rx.alive);
  assert(!question_allocated);
  question_allocated=true;
  if (mode=="mic_only_trial_question_no_memory") return nullptr;
  if (question_with_gate()) {
    trial_time_us=question_case()=="control_gate_stop"?9'001'000:4'001'000;
  }
  question_pcm.fill(12345);
  return question_pcm.data();
}
extern "C" void heap_caps_free(void* pcm) {
  assert(pcm==question_pcm.data() && question_allocated && !question_freed);
  question_freed=true;
  const auto test=question_case();
  if (test=="endpoint" || test=="release_fail" || test=="tail_then_question" ||
      test=="revoke" || test=="short" || test=="frame_cap" || test=="stop_after_speech") {
    const auto samples=QuestionCapture::kFrame*
        static_cast<size_t>((question_reads-question_reads_at_cue)/2);
    zero(std::span(question_pcm).first(samples));
    assert(question_pcm[samples]==12345);
  }
}
#ifndef STACKCHAN_TEST_EMBEDDED_MIC_TRIAL
extern "C" bool esp_ptr_external_ram(const void* ptr) {
  return question_trial() && (ptr==question_pcm.data() || ptr==&question_pcm.back()) &&
      mode!="mic_only_trial_question_bad_placement";
}
#endif

extern "C" void heap_caps_get_info(multi_heap_info_t* info, uint32_t caps) {
  assert(caps==(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  ++heap_checks;
  assert(bus_created==0 && !local_stop && local_owner);
  *info={128*1024,32*1024};
  if (embedded_trial_chain()) {
    assert(heap_checks<=2);
    if (mode=="mic_only_trial_chain_memory" && heap_checks==2) --info->total_free_bytes;
    return;
  }
  assert(heap_checks==1 && trial_resets==1);
  if (mode=="mic_only_trial_live_low_memory") --info->total_free_bytes;
  if (mode=="mic_only_trial_live_fragmented") --info->largest_free_block;
  if (mode=="mic_only_trial_live_bad_metrics") info->largest_free_block=info->total_free_bytes+1;
  if (mode=="mic_only_trial_revoke_during_memory_check") local_owner=false;
  if (mode=="mic_only_trial_stop_during_memory_check") local_stop=true;
}
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t*,i2c_master_bus_handle_t* h){
  if(mode=="mic_only_i2c_bus_fail")return ESP_FAIL;
  if(bus_created) {
    assert(question_trial() && !bus.alive && bus.deletes==1);
    bus.alive=true;
  }
  ++bus_created;
  *h=&bus;return 0;
}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t h){
  assert(h==&bus && h->alive);++h->deletes;
  if(pmic.open || expander.open)return ESP_ERR_INVALID_STATE;
  if(mode=="release_bus_live_error")return ESP_ERR_INVALID_STATE;
  h->alive=false;return mode=="release_bus_freed_error"?ESP_FAIL:ESP_OK;
}
extern "C" esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t h,
                                               const i2c_device_config_t* cfg,
                                               i2c_master_dev_handle_t* out) {
  assert(h==&bus && h->alive && channels_created==bus_created-1);
  assert(cfg->scl_speed_hz==100000 && cfg->dev_addr_length==I2C_ADDR_BIT_LEN_7);
  assert(cfg->device_address==pmic.address || cfg->device_address==expander.address);
  auto& dev=cfg->device_address==pmic.address ? pmic : expander;
  assert(!dev.open);
  dev.open=true;
  *out=&dev;
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t dev) {
  assert(dev->open);
  if(dev==&expander && ++expander_removes==1 && mode=="mic_only_board_cleanup_busy")
    return ESP_ERR_INVALID_STATE;
  dev->open=false;
  return mode=="mic_only_board_cleanup" && dev==&expander ? ESP_FAIL : ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t dev,
                                                 const uint8_t* reg,size_t n,
                                                 uint8_t* value,size_t bytes,int ms) {
  assert(dev->open && n==1 && bytes==1 && ms==30);
  if (mic_only() || dev == &pmic) assert(channels_created==bus_created-1);
  if(dev==&pmic) {
    assert(*reg==0x03 || *reg==0x90);
    *value=*reg==0x03 ? (mode=="mic_only_board_bad_pmic" ||
                        mode=="duplex_board_wrong_pmic" ? 0 : 0x4a)
                     : (mode=="mic_only_board_rails_off" ? 0x01 : 0xbf);
  } else {
    assert(dev==&expander);
    switch(*reg) {
      case 0x10: *value=mode=="mic_only_board_bad_expander" ? 0 : 0x23; break;
      case 0x04: *value=mode=="mic_only_board_input_pin" ? 0x1c : 0x18; break;
      case 0x12: *value=mode=="mic_only_board_led_mode" ? 0xfb : 0xff; break;
      case 0x11: assert(!mic_only()); *value=mode=="duplex_board_wrong_mode" ? 0 : 0x10; break;
      case 0x02:
        if(mode=="mic_only_board_read_error")return ESP_FAIL;
        *value=output_latch;
        if(reset_writes && mode=="mic_only_board_bad_readback")*value^=0x04;
        reset_read_back=((*value & 0x04)==0);
        break;
      default: assert(false);
    }
  }
  return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit(i2c_master_dev_handle_t dev,const uint8_t* data,
                                         size_t size,int ms) {
  assert(dev==&expander && dev->open && size==2 && ms==30 && data[0]==0x02);
  assert((data[1] ^ output_latch) == 0x04);
  if (mic_only() || reset_writes==0) {
    assert(channels_created==0 && data[1]==0xa3 && reset_writes==0);
  } else if (data[1]==0xa7) {
    assert(reset_waits==1 && reset_writes==1 && channels_created==1);
    amp_registers[0x04] = {0x40, 0x03};
    amp_registers[0x05] = {0x00, static_cast<uint8_t>(
        mode == "duplex_board_unmuted" ? 0x00 : 0x10)};
  } else {
    assert(data[1]==0xa3 && reset_waits==2 && reset_writes==2);
  }
  ++reset_writes;
  if(mode=="mic_only_board_write_error")return ESP_FAIL;
  output_latch=data[1];
  if(mode=="mic_only_board_stop_on_write")local_stop=true;
  return ESP_OK;
}
extern "C" esp_err_t i2s_new_channel(const i2s_chan_config_t* c,i2s_chan_handle_t* t,i2s_chan_handle_t* r){
  assert(c->dma_frame_num==240 && r);assert((t==nullptr)==mic_only());
  assert(c->dma_desc_num == 6 && c->auto_clear_after_cb == (t != nullptr));
  assert(reset_read_back && output_latch==0xa3 && !pmic.open);
  assert(expander.open != mic_only());
  if(channels_created) {
    assert(question_trial() && !rx.alive && rx.deletes==1);
    rx.alive=true;
  }
  ++channels_created;
  if(t)*t=&tx;
  *r=&rx;return 0;
}
extern "C" esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t*){assert(!mic_only());return 0;}
extern "C" esp_err_t i2s_channel_register_event_callback(i2s_chan_handle_t h,
    const i2s_event_callbacks_t* callbacks, void* data) {
  assert(!mic_only() && h == &tx && h->alive && !h->enabled);
  assert(callbacks && callbacks->on_sent && data);
  ++tx_callbacks_registered;
  if (mode == "tx_callback_failed") return ESP_FAIL;
  return ESP_OK;
}
void vTaskDelay(unsigned ticks) {
  assert(!mic_only());
  if (reset_waits == 0) {
    assert(ticks == 11 && output_latch == 0xa3 && tx.enabled && rx.enabled);
    if (mode == "duplex_board_stop_in_reset") local_stop = true;
  } else {
    assert(reset_waits == 1 && ticks == 51 && output_latch == 0xa7);
    if (mode == "duplex_board_stop_after_release") local_stop = true;
  }
  ++reset_waits;
}
extern "C" esp_err_t i2s_channel_init_tdm_mode(i2s_chan_handle_t h,const i2s_tdm_config_t* c){
  ++tdm_inits;
  assert(h==&rx && c->clk_cfg.sample_rate_hz==24000 && c->gpio_cfg.dout==I2S_GPIO_UNUSED);
  if(mic_only()) {
    assert(c->slot_cfg.slot_mask==3 && c->slot_cfg.total_slot==2 && c->slot_cfg.left_align);
    assert(c->slot_cfg.ws_width==16 && c->slot_cfg.slot_bit_width==16);
    assert(c->gpio_cfg.mclk==0 && c->gpio_cfg.din==14);
  } else assert(c->slot_cfg.slot_mask==15);
  return 0;
}
extern "C" esp_err_t i2s_channel_enable(i2s_chan_handle_t h){
  assert(!mic_only() || h==&rx);
  assert(h->alive);if(h->enabled)return ESP_ERR_INVALID_STATE;h->enabled=true;return 0;
}
extern "C" esp_err_t i2s_channel_disable(i2s_chan_handle_t h){
  assert(h->alive);++h->disables;
  if(h==&rx && fail_rx_disable)return ESP_FAIL;
  const bool fail_rx=h==&rx && (mode=="release_rx" || mode=="release_both" ||
                               mode=="release_rx_info" || mode=="mic_only_close_failure" ||
                               mode=="mic_only_trial_close_fail");
  const bool fail_tx=h==&tx && (mode=="release_tx" || mode=="release_both");
  if((fail_rx || fail_tx) && h->disables==1)return ESP_FAIL;
  if(!h->enabled)return ESP_ERR_INVALID_STATE;
  h->enabled=false;
  return 0;
}
extern "C" esp_err_t i2s_del_channel(i2s_chan_handle_t h){
  assert(h->alive);++h->deletes;
  if(h->enabled)return ESP_ERR_INVALID_STATE; // Pinned IDF refuses BEFORE free.
  h->alive=false;return 0;
}
extern "C" esp_err_t i2s_channel_get_info(i2s_chan_handle_t h,i2s_chan_info_t* info){assert(h->alive);if(mode=="info_fail" || (mode=="release_rx_info" && h==&rx))return ESP_FAIL;info->is_enabled=h->enabled;info->pair_chan=mode=="mic_only_peer"?&tx:nullptr;return 0;}
extern "C" esp_err_t i2s_channel_read(i2s_chan_handle_t h,void* p,size_t n,size_t* bytes,uint32_t ms) {
  assert(h==&rx && n<=960 && ms==20);++calls;
  if(channels_created == (direct_question() ? 1 : 2)) {
    assert(question_trial());
    const auto test=question_case();
    ++question_reads;
    if(test=="wall" || test=="control_local_limit") trial_time_us+=30000;
    else if(test=="frame_cap") trial_time_us+=1000;
    else trial_time_us+=10000;

    const int since_cue=question_reads-question_reads_at_cue;
    const bool before_cue=question_cues==0;
    if (question_with_gate()) {
      question_gate.tick(trial_time_us/1000);
      if (!before_cue && since_cue==150 && test=="control_stop_on_last_read") {
        for (const char c : std::string_view{"STOP\n"}) question_gate.feed(c,trial_time_us/1000);
      }
      if (question_gate.stopped()) local_stop=true;
    }
    if (!before_cue && since_cue==9 && test=="revoke") local_owner=false;
    if (!before_cue && since_cue==9 && test=="stop_after_speech") local_stop=true;
    if (!before_cue && since_cue==9 && test=="clock") trial_time_us=-1;
    if (before_cue && question_reads==9 && test=="handoff_stop") local_stop=true;
    const bool short_read=(before_cue && question_reads==9 && test=="handoff_short") ||
                          (!before_cue && since_cue==9 && test=="short") ||
                          (!before_cue && since_cue==150 && test=="control_short_read");
    *bytes=short_read?n-4:n;
    auto* pcm=static_cast<int16_t*>(p);
    const bool initial_tail=question_reads<=8 &&
        (test=="wake_tail" || test=="tail_then_question" || test=="interrupted_quiet");
    const bool second_burst=test=="interrupted_quiet" && question_reads>56 && question_reads<=62;
    const bool quiet_only_at_deadline=test=="quiet_at_deadline" && question_reads<=750;
    const bool voice=initial_tail || second_burst ||
        (before_cue ? test=="quiet_timeout" || quiet_only_at_deadline ||
                      (test=="control_local_limit" && question_reads<=200)
                    : test=="wall" || test=="frame_cap" ||
                      (test=="control_endpoint" && since_cue>=93 && since_cue<=100) ||
                      (!question_control() && test!="standard_gate_stop" &&
                       test!="wake_tail" && test!="interrupted_quiet" && test!="silence" &&
                       since_cue<=8));
    for(size_t i=0;i<*bytes/4;++i) {
      pcm[2*i]=voice?(i%2==0?1800:-1800):0;
      pcm[2*i+1]=900;
    }
    return ESP_OK;
  }
  const bool short_read=mode=="short" || mode=="mic_only_short" || mode=="mic_only_trial_short" ||
                        mode=="mic_only_trial_short_cleanup_bad" ||
                        mode=="mic_only_trial_chain_short_read";
  *bytes=short_read?n-4:mode=="overcount"?n+4:n;
  if(mic_wake_trial()) {
    int read_duration_us = 10000;
    if (mode == "mic_only_trial_wall") read_duration_us = 20000;
    if (mode == "mic_only_trial_frame_cap") read_duration_us = 1000;
    if (mode == "mic_only_trial_question_wake_paced_deadline") read_duration_us = 10300;
    trial_time_us += read_duration_us;
    if(mode=="mic_only_trial_stop_in_read")local_stop=true;
    if(mode=="mic_only_trial_clock_backwards")trial_time_us=-1;
    if(mode=="mic_only_trial_window_overrun" && calls==500)++trial_time_us;
  }
  auto* pcm=static_cast<int16_t*>(p);
  const bool input_counts = mode == "mic_only_trial_input_counts";
  for(size_t i=0;i<std::min(*bytes,n)/4;++i) {
    pcm[2*i]=input_counts && calls==1 ? 0 : static_cast<int16_t>(i-100);
    pcm[2*i+1]=input_counts ? std::numeric_limits<int16_t>::max() : 900;
  }
  if (input_counts && calls>1) {
    pcm[0]=std::numeric_limits<int16_t>::min();
    pcm[2]=std::numeric_limits<int16_t>::max();
  }
  if(mode=="base_lost")base_open=false;
  if(mode=="mic_only_revoke")local_owner=false;
  if(mode=="mic_only_stop_read" || mode=="mic_only_release_latched")local_stop=true;
  if(mode=="reentrant") {
    esp_codec_dev_sample_info_t fs{16,2,3,24000,0};
    assert(devices[1].data->set_fmt(devices[1].data,ESP_CODEC_DEV_TYPE_IN,&fs)!=0);
  }
  return mode=="driver_fail"?ESP_ERR_TIMEOUT:ESP_OK;
}
extern "C" esp_err_t i2s_channel_write(i2s_chan_handle_t h,const void*,size_t n,size_t* bytes,uint32_t ms){
  assert(!mic_only());
  assert(h==&tx && ms==20 && n<=480);++calls;*bytes=mode=="write_short"?n-2:n;
  return mode=="write_fail"?ESP_ERR_TIMEOUT:ESP_OK;
}
extern "C" const audio_codec_data_if_t* audio_codec_new_i2s_data(audio_codec_i2s_cfg_t*) {
  assert(!mic_only());
  base.is_open=sdk_open;base.enable=sdk_enable;base.set_fmt=sdk_format;base.read=legacy_read;base.write=legacy_write;base.close=sdk_close;return &base;
}
extern "C" const audio_codec_ctrl_if_t* audio_codec_new_i2c_ctrl(audio_codec_i2c_cfg_t* cfg){
  const bool out=cfg->addr==AW88298_CODEC_DEFAULT_ADDR;
  assert(out || cfg->addr==ES7210_CODEC_DEFAULT_ADDR);
  assert(!out || !mic_only());
  if (out) assert(reset_waits == 2 && output_latch == 0xa7);
  auto* c=&controls[out?0:1];
  assert(!c->is_open);
  ++controls_created;
  c->is_open=ctrl_open;c->read_reg=ctrl_read;c->write_reg=ctrl_write;c->get_info=ctrl_info;return c;
}
extern "C" const audio_codec_gpio_if_t* audio_codec_new_gpio(){assert(!mic_only());return &gpio;}
extern "C" const audio_codec_if_t* aw88298_codec_new(aw88298_codec_cfg_t* cfg) {
  assert(!mic_only());
  const auto* control = cfg->ctrl_if;
  codec_controls[0] = control;
  codec_operation(0, "init");
  uint8_t power[]{0x40, 0x40}, mute[]{0, 0x08}, volume[]{0x30, 0x64};
  if (control->write_reg(control, 0x04, 1, power, 2) != ESP_CODEC_DEV_OK ||
      control->write_reg(control, 0x05, 1, mute, 2) != ESP_CODEC_DEV_OK ||
      control->write_reg(control, 0x0c, 1, volume, 2) != ESP_CODEC_DEV_OK) return nullptr;
  return &codecs[0];
}
extern "C" const audio_codec_if_t* es7210_codec_new(es7210_codec_cfg_t* cfg){codec_controls[1]=cfg->ctrl_if;codec_operation(1,"init");return &codecs[1];}
extern "C" esp_codec_dev_handle_t esp_codec_dev_new(esp_codec_dev_cfg_t* cfg) {
  if(mode=="mic_only_codec_prepare_fail")return nullptr;
  assert(created<2);devices[created]={cfg->data_if,cfg->dev_type,false};return &devices[created++];
}
extern "C" int esp_codec_dev_open(esp_codec_dev_handle_t h,esp_codec_dev_sample_info_t* fs) {
  if(mode=="mic_only_codec_open_fail")return ESP_CODEC_DEV_INVALID_ARG;
  auto* d=static_cast<Dev*>(h);d->open=true;
  d->data->set_fmt(d->data,d->type,fs);d->data->enable(d->data,d->type,true);
  codec_operation(d->type==ESP_CODEC_DEV_TYPE_IN?1:0,"open");
  return 0; // pinned SDK ignores these two callback errors
}
extern "C" int esp_codec_dev_close(esp_codec_dev_handle_t h) {
  auto* d=static_cast<Dev*>(h);if(d->open){codec_operation(d->type==ESP_CODEC_DEV_TYPE_IN?1:0,"close");d->data->enable(d->data,d->type,false);d->open=false;}return 0;
}
extern "C" int esp_codec_dev_set_in_channel_gain(esp_codec_dev_handle_t,uint16_t,float){++gains;codec_operation(1,"gain");return 0;}
extern "C" int esp_codec_dev_set_out_vol(esp_codec_dev_handle_t,int){return 0;}
extern "C" int esp_codec_dev_read(esp_codec_dev_handle_t h,void* p,int n){auto* d=static_cast<Dev*>(h);return d->data->read(d->data,static_cast<uint8_t*>(p),n);}
extern "C" int esp_codec_dev_write(esp_codec_dev_handle_t h,void* p,int n){auto* d=static_cast<Dev*>(h);return d->data->write(d->data,static_cast<uint8_t*>(p),n);}
extern "C" void esp_codec_dev_delete(esp_codec_dev_handle_t h){assert(!static_cast<Dev*>(h)->open);++deleted;}
extern "C" int audio_codec_delete_codec_if(const audio_codec_if_t* c) {
  assert(deleted==created);
  codec_operation(c==&codecs[0]?0:1,"delete");
  return mode=="mic_only_trial_delete_fail" || mode=="mic_only_trial_short_cleanup_bad" ||
         (channels_created==2 && (question_case()=="release_fail" || question_case()=="control_release_fail"))
      ?ESP_CODEC_DEV_INVALID_ARG:ESP_CODEC_DEV_OK;
}
extern "C" int audio_codec_delete_ctrl_if(const audio_codec_ctrl_if_t* c) {
  assert(c==&controls[0] || c==&controls[1]);
  ++controls_deleted;
  if(question_trial()) controls[c==&controls[0]?0:1]={};
  return 0;
}
extern "C" int audio_codec_delete_gpio_if(const audio_codec_gpio_if_t*){return 0;}
extern "C" int audio_codec_delete_data_if(const audio_codec_data_if_t* h){assert(h==&base && deleted==created);++data_deletes;return 0;}
#ifdef STACKCHAN_TEST_EMBEDDED_MIC_TRIAL
std::string run_mic_trial_with_embedded_model_double(
    std::string_view, std::atomic_bool&, std::atomic_bool&);
#endif
int main(int argc,char** argv) {
  assert(argc==2 || (argc==3 && std::string_view(argv[2])=="--report"));mode=argv[1];
  report_trial=argc==3;
  if (report_trial) {
    K151MicWakeTrial trial{[] {
      if (mode=="mic_only_trial_poll_gap") trial_time_us+=100001;
      if (mode=="mic_only_trial_poll_gap_boundary") trial_time_us+=100000;
    }};
    const auto result=trial.run(local_owner,local_stop,{true,true},std::make_unique<TrialDetector>());
    std::array<char, kK151MicWakeReportBytes> line{};
    assert(format_k151_mic_wake_report(result,trial.diagnostic(),trial.take_input_counts(),line)!=0);
    std::fputs(line.data(),stdout);
    return 0;
  }
#ifdef STACKCHAN_TEST_EMBEDDED_MIC_TRIAL
  if (embedded_trial_chain()) {
    const auto report=run_mic_trial_with_embedded_model_double(mode,local_owner,local_stop);
    const bool bad_hash=mode=="mic_only_trial_chain_bad_hash";
    const bool before_codec=bad_hash || mode=="mic_only_trial_chain_memory";
    const bool short_read=mode=="mic_only_trial_chain_short_read";
    assert(heap_checks==(bad_hash?1:2));
    assert(bus_created==(before_codec?0:1) && bus.deletes==bus_created);
    assert(rx.deletes==bus_created && tx.deletes==0 && legacy_calls==0 && data_deletes==0);
    assert(calls==(before_codec?0:short_read?1:4));
    std::printf("%s",report.c_str());
    return 0;
  }
#endif
  if (mode=="mic_report") {
    using Outcome = K151MicWakeTrialResult;
    using Stage = K151MicWakeStage;
    const K151MicWakeDiagnostic complete{Stage::complete};
    std::array<char, kK151MicWakeReportBytes> json{};
    const K151MicWakeInputCounts observed{4,1,6};
    const K151MicWakeInputCounts impossible{4,3,241};
    assert(format_k151_mic_wake_report(Outcome::detected,complete,impossible,json)==0);
    assert(format_k151_mic_wake_report(Outcome::detected,complete,std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(Outcome::stopped,{},observed,json)==0);
    assert(format_k151_mic_wake_report(Outcome::fault,complete,std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(Outcome::fault,{Stage::codec_release},std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(Outcome::fault,{Stage::model_prepare,true},std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(Outcome::fault,{static_cast<Stage>(90)},std::nullopt,json)==0);
    using ClockReason = K151MicWakeClockReason;
    assert(format_k151_mic_wake_report(Outcome::fault,{Stage::capture_clock},std::nullopt,json)==0);
    K151MicWakeDiagnostic deadline{Stage::capture_clock, false, ClockReason::capture_window_exceeded};
    assert(format_k151_mic_wake_report(Outcome::fault, deadline, std::nullopt, json) == 0);
    deadline.deadline_progress = K151WakeDeadlineProgress{
        500, {NativeWakePollTrace::Step::model_return, 156, NativeWakeResult::detected}};
    assert(format_k151_mic_wake_report(Outcome::fault, deadline, std::nullopt, json) > 0);
    // No partial JSON may escape if the fixed report is truncated.
    assert(format_k151_mic_wake_report(Outcome::fault, deadline, std::nullopt,
                                       std::span(json).first(256)) == 0 && json[0] == '\0');
    deadline.deadline_progress->poll.model_calls = 501;
    assert(format_k151_mic_wake_report(Outcome::fault, deadline, std::nullopt, json) == 0);
    assert(format_k151_mic_wake_report(
        Outcome::fault,{Stage::capture_clock,false,static_cast<ClockReason>(99)},
        std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(
        Outcome::fault,{Stage::capture_read,false,ClockReason::clock_rollback},
        std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(
        Outcome::stopped,{Stage::capture_clock,false,ClockReason::clock_rollback},
        std::nullopt,json)==0);
    assert(format_k151_mic_wake_report(Outcome::detected,complete,observed,
                                      std::span(json).first(8))==0);
    assert(json[0]=='\0');
    for (const auto outcome : {Outcome::detected, Outcome::not_detected, Outcome::stopped,
                                Outcome::fault, Outcome::denied, Outcome::memory_denied}) {
      const bool clean = outcome==Outcome::detected || outcome==Outcome::not_detected;
      const auto counts = clean ? std::optional{observed} : std::nullopt;
      Stage stage = Stage::admission;
      if (clean) stage = Stage::complete;
      else if (outcome==Outcome::stopped) stage = Stage::codec_release;
      else if (outcome==Outcome::fault) stage = Stage::board_power;
      else if (outcome==Outcome::memory_denied) stage = Stage::baseline_memory;
      const auto size = format_k151_mic_wake_report(outcome, {stage}, counts, json);
      assert(size!=0 && json[size-1]=='\n' && json[size]=='\0');
      std::printf("%s", json.data());
    }
    return 0;
  }
  if (direct_question()) {
    using Result = K151QuestionTrialResult;
    const auto test = question_case();
    local_stop = test == "stop_before";
    const auto question = run_k151_question_trial(
        local_owner, local_stop, {test != "deny", true}, announce_question);
    assert(trial_model_drops == 0 && trial_chunks == 0 && trial_resets == 0 && heap_checks == 0);
    assert(!question.codec_cleanup_unverified && tx.deletes == 0 && legacy_calls == 0);
    if (test == "deny" || test == "stop_before") {
      assert(question.result == (test == "deny" ? Result::prepare_failed : Result::stopped));
      assert(question_cues == 0 && question_reads == 0 && !question_allocated && bus_created == 0);
    } else {
      assert(question_freed && bus_created == 1 && bus.deletes == 1 && rx.deletes == 1);
      assert(question_cues == 1 && question_reads_at_cue == 50);
      const auto after_cue = question_reads - question_reads_at_cue;
      if (test == "endpoint") {
        assert(question.result == Result::endpoint && after_cue == 58);
      } else if (test == "silence") {
        assert(question.result == Result::no_endpoint && question_reads == 800);
        assert(std::ranges::all_of(question_pcm, [](int16_t sample) { return sample == 12345; }));
      } else {
        assert(test == "stop_after_speech" && local_stop && question.result == Result::stopped);
        assert(after_cue == 9);
      }
    }
    std::puts("question-only capture verified");
    return 0;
  }
  if(question_trial()) {
    using Result=K151QuestionTrialResult;
    const auto test=question_case();
    if (question_with_gate()) {
      for (const char c : std::string_view{"START 00000001\n"}) question_gate.feed(c,1);
      assert(question_gate.running());
    }
    K151MicWakeTrial trial{[] {
        if (question_case() == "wake_cue_deadline") ++trial_time_us;
      }, announce_question, question_control()
        ? K151QuestionTrialMode::wake_only_control : K151QuestionTrialMode::standard};
    const auto wake=trial.run(local_owner,local_stop,{true,true},std::make_unique<TrialDetector>());
    const auto question=trial.question_diagnostic();
    if(test=="no_wake") {
      assert(wake==K151MicWakeTrialResult::not_detected);
      assert(question.result==Result::not_run && !question_allocated);
      assert(question_cues==0 && question_reads==0 && bus_created==1);
      return 0;
    }
    if (test == "wake_paced_deadline" || test == "wake_cue_deadline" ||
        test == "wake_detect_over_deadline") {
      const bool paced = test == "wake_paced_deadline";
      assert(calls == (paced ? 486 : 500));
      assert(trial_chunks == (paced ? 151 : test == "wake_cue_deadline" ? 155 : 156));
      assert(wake == K151MicWakeTrialResult::fault && !trial.take_input_counts());
      assert(trial.diagnostic().stage == K151MicWakeStage::capture_clock);
      assert(trial.diagnostic().clock_reason == K151MicWakeClockReason::capture_window_exceeded);
      assert(!trial.diagnostic().codec_cleanup_unverified && !rx.alive && !bus.alive);
      assert(trial_model_drops == 1 && channels_created == 1);
      assert(question.result == Result::not_run && !question_allocated);
      assert(question_cues == 0 && question_reads == 0);
      std::array<char, kK151MicWakeReportBytes> report{};
      assert(format_k151_mic_wake_report(wake, trial.diagnostic(), std::nullopt, report) != 0);
      std::fputs(report.data(), stdout);
      return 0;
    }
    const auto counts = trial.take_input_counts();
    const bool detected_at_deadline = test == "wake_detect_at_deadline";
    assert(wake == K151MicWakeTrialResult::detected && counts);
    assert(counts->frames_read == (detected_at_deadline ? 500u : 4u));
    if (detected_at_deadline) assert(trial_chunks == 156);
    assert(trial_model_drops==1 && question_allocated && !bus.alive && !rx.alive);
    assert(tx.deletes==0 && data_deletes==0 && legacy_calls==0);
    if(test=="no_memory" || test=="bad_placement") {
      assert(question.result==Result::memory_denied && question_cues==0 && question_reads==0);
      assert(question_freed==(test=="bad_placement") && bus_created==1);
      return 0;
    }
    assert(question_freed && bus_created==2 && bus.deletes==2 && rx.deletes==2);
    assert(question.codec_cleanup_unverified==(test=="release_fail" || test=="control_release_fail"));
    if(test=="quiet_timeout" || test=="quiet_at_deadline" ||
       test=="handoff_stop" || test=="handoff_short") {
      assert(question_cues==0);
      if(test=="quiet_timeout" || test=="quiet_at_deadline") {
        assert(question_reads==800 && question.result==Result::quiet_timeout);
      } else {
        assert(question_reads==9);
        assert(question.result==(test=="handoff_stop"?Result::stopped:Result::read_failed));
      }
      assert(std::ranges::all_of(question_pcm,[](int16_t sample){return sample==12345;}));
      return 0;
    }

    if(test=="wake_tail" || test=="interrupted_quiet")
      assert(question.result!=Result::endpoint && "post-wake energy was accepted as a new question");
    const int expected_cue=test=="wake_tail" || test=="tail_then_question" ? 58
        : test=="interrupted_quiet" ? 112 : test=="control_local_limit" ? 250 : 50;
    assert(question_cues==1 && question_reads_at_cue==expected_cue);
    const int after_cue=question_reads-question_reads_at_cue;
    if (test == "endpoint" || test == "release_fail" || test == "tail_then_question" ||
        detected_at_deadline) {
      assert(after_cue==58);
      assert(question.result==(test=="release_fail"?Result::release_failed:Result::endpoint));
    } else if(test=="wake_tail" || test=="interrupted_quiet") {
      assert(question.result==Result::no_endpoint && question_reads==800);
      assert(std::ranges::all_of(question_pcm,[](int16_t sample){return sample==12345;}));
    } else if(test=="control_complete") {
      assert(question.result==Result::no_endpoint && "wake-only observation stopped at the combined deadline");
      assert(after_cue==150 && question_gate.running() && trial_time_us==6'001'000);
    } else if(test=="control_gate_stop" || test=="standard_gate_stop") {
      assert(question.result==Result::stopped && question_gate.stopped());
      assert(after_cue==(test=="control_gate_stop"?51:551));
    } else if(test=="control_stop_on_last_read") {
      assert(question.result==Result::stopped && after_cue==150 && question_gate.stopped());
    } else if(test=="control_short_read") {
      assert(question.result==Result::read_failed && after_cue==150);
    } else if(test=="control_endpoint") {
      assert(question.result==Result::endpoint && after_cue==150);
    } else if(test=="control_release_fail") {
      assert(question.result==Result::release_failed && after_cue==150);
    } else if(test=="control_local_limit") {
      assert(question.result==Result::stopped && after_cue<150 && !local_stop);
    } else if(test=="wall") {
      assert(trial_time_us==8'081'000 && question_reads==268);
      assert(question.result==Result::no_endpoint);
    } else if(test=="frame_cap") {
      assert(question_reads==2*static_cast<int>(QuestionCapture::kMaxFrames));
      assert(question.result==Result::no_endpoint);
    } else if(test=="stop_at_cue") {
      assert(question.result==Result::stopped && after_cue==0);
    } else if(test=="revoke") {
      assert(question.result==Result::stopped && after_cue==9);
    } else if(test=="short") {
      assert(question.result==Result::read_failed && after_cue==9);
    } else if(test=="clock") {
      assert(question.result==Result::clock_fault && after_cue==9);
    } else assert(false);
    return 0;
  }
  if(mic_wake_trial()) {
    using Outcome = K151MicWakeTrialResult;
    K151MicWakeTrial trial;
    assert(!trial.take_input_counts());
    const bool missing = mode == "mic_only_trial_evidence";
    const bool no_owner = mode == "mic_only_trial_owner";
    const bool bad_format = mode == "mic_only_trial_format";
    const bool stop_before = mode == "mic_only_trial_stop_before";
    const bool reset_fail = mode == "mic_only_trial_reset_fail";
    const bool stop_on_reset = mode == "mic_only_trial_stop_on_reset";
    const bool stop_on_open = mode == "mic_only_trial_stop_on_open";
    const bool stop_in_read = mode == "mic_only_trial_stop_in_read";
    const bool wall = mode == "mic_only_trial_wall";
    const bool cap = mode == "mic_only_trial_frame_cap";
    local_owner = !no_owner;
    local_stop = stop_before;
    const K151MicOnlyEvidence evidence{true,!missing};
    const auto outcome = trial.run(local_owner,local_stop,evidence,std::make_unique<TrialDetector>());
    if (mode == "mic_only_trial_unread_counts_after_denial") {
      assert(outcome == Outcome::detected && calls == 4);
      assert(trial.run(local_owner,local_stop,evidence,std::make_unique<TrialDetector>()) == Outcome::denied);
      assert(!trial.take_input_counts() && calls == 4 && trial_model_drops == 2);
      return 0;
    }
    const auto counts = trial.take_input_counts();
    const bool completed = outcome == Outcome::detected || outcome == Outcome::not_detected;
    assert(static_cast<bool>(counts) == completed);
    assert(!trial.take_input_counts());
    if (counts) {
      const bool injected = mode == "mic_only_trial_input_counts";
      assert(counts->frames_read == static_cast<unsigned>(calls));
      assert(counts->all_zero_frames == (injected ? 1u : 0u));
      assert(counts->full_scale_samples == (injected ? 6u : 0u));
    }
    if (mode == "mic_only_trial_input_counts" || mode == "mic_only_trial_stop_on_drop") {
      std::array<char, kK151MicWakeReportBytes> json{};
      assert(format_k151_mic_wake_report(outcome,trial.diagnostic(),counts,json) != 0);
      std::printf("%s", json.data());
    }
    assert(trial_model_drops == 1);
    if (missing || no_owner || stop_before || bad_format || reset_fail || stop_on_reset) {
      const auto expected = stop_before || stop_on_reset ? Outcome::stopped :
                            bad_format || reset_fail ? Outcome::fault : Outcome::denied;
      assert(outcome == expected);
      assert(calls == 0 && trial_chunks == 0 && bus_created == 0);
      assert(heap_checks == 0);
      assert(trial_resets == (reset_fail || stop_on_reset ? 1 : 0));
      return 0;
    }
    assert(heap_checks == 1);
    if (mode.starts_with("mic_only_trial_live_") ||
        mode.find("_during_memory_check") != std::string::npos) {
      assert(outcome == (local_owner && !local_stop ? Outcome::memory_denied : Outcome::stopped));
      assert(calls == 0 && trial_chunks == 0 && trial_resets == 1 && bus_created == 0);
      assert(trial.run(local_owner,local_stop,evidence,std::make_unique<TrialDetector>()) == Outcome::denied);
      assert(heap_checks == 1 && trial_resets == 1);
      return 0;
    }
    assert(trial_resets == 1 && bus_created == 1 && rx.deletes == 1 && tx.deletes == 0 && created == 1);
    assert(controls_deleted == 1 && bus.deletes == 1 && deleted == 1 && data_deletes == 0);
    if (wall || cap) {
      assert(outcome == Outcome::not_detected);
      assert(calls == (wall ? 250 : 500));
      assert(trial_chunks == (wall ? 78 : 156));
    } else if (mode == "mic_only_trial_ok" || mode == "mic_only_trial_input_counts") {
      assert(outcome == Outcome::detected && calls == 4 && trial_chunks == 1);
    } else {
      const bool stop_after = mode == "mic_only_trial_stop_in_detect" ||
                              mode == "mic_only_trial_revoke_in_detect" ||
                              mode == "mic_only_trial_stop_on_close" ||
                              mode == "mic_only_trial_stop_on_drop";
      const bool read_error = mode == "mic_only_trial_short" || mode == "mic_only_trial_clock_backwards";
      assert(outcome == (stop_after ? Outcome::stopped : Outcome::fault));
      assert(calls == (stop_on_open ? 0 : stop_in_read || read_error ? 1 : 4));
      assert(trial_chunks == (stop_on_open || stop_in_read || read_error ? 0 : 1));
    }
    assert(trial.run(local_owner,local_stop,evidence,std::make_unique<TrialDetector>()) == Outcome::denied);
    assert(!trial.take_input_counts());
    assert(trial_model_drops == 2 && bus_created == 1 && trial_resets == 1);
    return 0;
  }
  K151CodecPort port;std::array<int16_t,240> pcm;pcm.fill(123);
  if(mic_only()) {
    const K151MicOnlyEvidence verified{true,true};
    if(mode.starts_with("mic_only_board_") && mode!="mic_only_board_already_held") {
      assert(!port.prepare_microphone_only(local_owner,local_stop,verified));
      assert(port.faulted() && !port.shutdown());
      assert(channels_created==0 && calls==0 && bus_created==1 && bus.deletes==1);
      assert(!pmic.open && !expander.open);
      const bool needs_write=mode=="mic_only_board_write_error" ||
          mode=="mic_only_board_bad_readback" || mode=="mic_only_board_stop_on_write" ||
          mode=="mic_only_board_cleanup" || mode=="mic_only_board_cleanup_busy";
      assert(reset_writes==int(needs_write));
      if(mode=="mic_only_board_cleanup_busy")assert(expander_removes==2 && !bus.alive);
      assert(!port.prepare_microphone_only(local_owner,local_stop,verified));
      return 0;
    }
    if(mode=="mic_only_board_already_held") {
      output_latch=0xa3;
      assert(port.prepare_microphone_only(local_owner,local_stop,verified));
      assert(reset_read_back && reset_writes==0 && port.shutdown());
      return 0;
    }
    if(mode=="mic_only_gates") {
      assert(!port.prepare_microphone_only(local_owner,local_stop,{false,true}));
      assert(!port.prepare_microphone_only(local_owner,local_stop,{true,false}));
      local_owner=false;
      assert(!port.prepare_microphone_only(local_owner,local_stop,verified));
      local_owner=true;local_stop=true;
      assert(!port.prepare_microphone_only(local_owner,local_stop,verified));
      assert(bus_created==0 && channels_created==0 && controls_created==0);return 0;
    }
    if(mode=="mic_only_peer") {
      assert(!port.prepare_microphone_only(local_owner,local_stop,verified));
      assert(port.faulted() && !port.shutdown());
      assert(tdm_inits==0 && controls_created==0 && tx.deletes==0 && rx.deletes==1);return 0;
    }
    assert(port.prepare_microphone_only(local_owner,local_stop,verified));
    assert(port.prepared() && !rx.enabled && controls_created==1 && created==1);
    assert(!port.prepare(local_owner,local_stop,{true,true}) &&
           !port.speaker_on_low_volume(local_owner));
    if(mode=="mic_only_stop_open") {
      assert(!port.microphone_on() && port.faulted() && !rx.enabled && gains==0);
      assert(!port.shutdown());return 0;
    }
    assert(port.microphone_on());
    if(mode=="mic_only_wakenet" || mode=="mic_only_wakenet_late_stop") {
      K151MicReader reader{port};
      WakeDetector model;
      NativeWakeInput input;
      assert(input.configure(model.format()));
      bool input_allowed = true;
      const auto allowed = [&] {
        return input_allowed && local_owner.load() && !local_stop.load();
      };
      assert(input.poll(reader, model, allowed) == NativeWakeResult::none);
      assert(input.poll(reader, model, allowed) == NativeWakeResult::none);
      input_allowed = false;
      assert(input.poll(reader, model, allowed) == NativeWakeResult::error);
      assert(calls == 2 && model.chunks == 0);
      input_allowed = true;
      for(int i=0;i<3;++i)assert(input.poll(reader, model, allowed) == NativeWakeResult::none);
      assert(model.chunks==0);
      const auto result=input.poll(reader, model, allowed);
      assert(calls==6 && model.chunks==1);
      assert(result==(local_stop?NativeWakeResult::error:NativeWakeResult::detected));
      assert(port.microphone_off() && !rx.enabled && port.shutdown());
      return 0;
    }
    if(mode=="mic_only_close_failure") {
      assert(!port.microphone_off());
      assert(port.faulted() && !rx.alive && rx.deletes==1);
      local_owner=false;
      K151MicReader reader{port};
      assert(!reader.read_10ms(pcm));zero(pcm);
      assert(calls==0 && !port.shutdown() && rx.deletes==1 && tx.deletes==0);
      return 0;
    }
    if(mode=="mic_only_output") {
      const auto* api=devices[0].data;
      assert(api->write(api,reinterpret_cast<uint8_t*>(pcm.data()),480)!=0);
      for(auto sample:pcm)assert(sample==123);
      assert(calls==0 && port.faulted() && !port.shutdown());return 0;
    }
    if(mode=="mic_only_stop_before_read")local_stop=true;
    if(mode=="mic_only_release_latched")fail_rx_disable=true;
    K151MicReader reader{port};
    const bool ok=reader.read_10ms(pcm);
    if(mode=="mic_only_release_latched") {
      assert(!ok && port.faulted() && rx.enabled && rx.deletes==1);
      zero(pcm);
      const int disables=rx.disables;
      pcm.fill(123);
      assert(!reader.read_10ms(pcm));zero(pcm);
      assert(calls==1 && rx.disables==disables && rx.deletes==1);
      fail_rx_disable=false;
      assert(!port.shutdown() && !rx.alive && rx.deletes==2 && tx.deletes==0);
      return 0;
    }
    if(mode=="mic_only_ok") {
      assert(ok && calls==1);
      for(size_t i=0;i<pcm.size();++i)assert(pcm[i]==static_cast<int16_t>(i-100));
      assert(port.microphone_off() && !rx.enabled && port.shutdown());
    } else {
      assert(!ok && port.faulted() && !rx.enabled);
      zero(pcm);
      assert(calls==(mode=="mic_only_stop_before_read"?0:1));
      local_stop=false;local_owner=true;assert(!port.microphone_on());
      assert(!port.shutdown());
    }
    assert(rx.deletes==1 && tx.deletes==0 && data_deletes==0 && legacy_calls==0);
    return 0;
  }
  if(mode=="reader_denied") {
    K151MicReader reader{port};assert(!reader.read_10ms(pcm));zero(pcm);assert(created==0);return 0;
  }
  if(mode=="denied") {
    local_owner=false;
    assert(!port.prepare(local_owner,local_stop,{true,true}));
    local_owner=true;local_stop=true;
    assert(!port.prepare(local_owner,local_stop,{true,true}));
    local_stop=false;
    assert(!port.prepare(local_owner,local_stop,{false,true}));
    assert(!port.prepare(local_owner,local_stop,{true,false}));
    assert(!port.capture_mono_24k(pcm));zero(pcm);
    assert(created==0 && bus_created==0);return 0;
  }
  if (mode.starts_with("duplex_board_")) {
    assert(!port.prepare(local_owner, local_stop, {true, true}));
    assert(port.faulted() && !port.prepared() && !port.speaker_on_low_volume(local_owner));
    assert(!port.shutdown() && !bus.alive);
    if (mode=="duplex_board_wrong_pmic" || mode=="duplex_board_wrong_mode") {
      assert(reset_writes==0 && channels_created==0 && output_latch==0xa7);
    } else {
      assert(output_latch==0xa3 && reset_read_back);
      assert(reset_writes==(mode=="duplex_board_stop_in_reset" ? 1 : 3));
      assert(!rx.alive && !tx.alive && created==0);
    }
    return 0;
  }
  if (mode == "tx_callback_failed") {
    assert(!port.prepare(local_owner, local_stop, {true, true}) && port.faulted());
    assert(tx_callbacks_registered == 1 && created == 0 && tdm_inits == 0);
    assert(!port.shutdown() && !tx.alive && !rx.alive && !bus.alive);
    assert(tx.deletes == 1 && rx.deletes == 1 && bus.deletes == 1);
    return 0;
  }
  if(mode.starts_with("ctrl_") && mode.find("_init_")!=std::string::npos) {
    assert(!port.prepare(local_owner,local_stop,{true,true}));assert(port.faulted() && !port.prepared());
    assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==0);
    assert(!port.shutdown());assert(controls_deleted==controls_created);return 0;
  }
  assert(port.prepare(local_owner,local_stop,{true,true}));
  assert(reset_writes==2 && output_latch==0xa7);
  assert(tx_callbacks_registered == 1);
  const auto* api=devices[1].data;
  if(mode.starts_with("release_")) {
    const bool bus_error=mode.starts_with("release_bus_");
    assert(!port.shutdown());assert(port.faulted() && !port.prepared());
    assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==0);
    assert(!port.microphone_on());assert(!port.prepare(local_owner,local_stop,{true,true}));
    const bool retained_rx=!bus_error && mode!="release_tx";
    const bool retained_tx=mode=="release_tx" || mode=="release_both";
    assert(rx.alive==retained_rx && tx.alive==retained_tx);
    assert(!port.shutdown()); // Later cleanup cannot clear the original fault.
    assert(!rx.alive && !tx.alive);
    assert(rx.deletes==(retained_rx?2:1));assert(tx.deletes==(retained_tx?2:1));
    assert(!port.shutdown()); // No access to confirmed freed channels/bus.
    assert(rx.deletes==(retained_rx?2:1) && tx.deletes==(retained_tx?2:1));
    assert(bus.deletes==1 && bus.alive==(mode=="release_bus_live_error"));
    assert(data_deletes==1 && deleted==created && controls_deleted==controls_created);return 0;
  }
  if(mode.starts_with("null_")) {
    esp_codec_dev_sample_info_t fs{16,2,3,24000,0};
    if(mode=="null_open")assert(!api->is_open(nullptr));
    if(mode=="null_format")assert(api->set_fmt(nullptr,ESP_CODEC_DEV_TYPE_IN,&fs)==ESP_CODEC_DEV_INVALID_ARG);
    if(mode=="null_enable")assert(api->enable(nullptr,ESP_CODEC_DEV_TYPE_IN,true)==ESP_CODEC_DEV_INVALID_ARG);
    if(mode=="null_read") {
      assert(api->read(nullptr,reinterpret_cast<uint8_t*>(pcm.data()),480)==ESP_CODEC_DEV_INVALID_ARG);zero(pcm);
    }
    if(mode=="null_write") {
      assert(api->write(nullptr,reinterpret_cast<uint8_t*>(pcm.data()),480)==ESP_CODEC_DEV_INVALID_ARG);
      for(auto sample:pcm)assert(sample==123);
    }
    assert(calls==0 && formats==0);assert(!port.faulted());assert(port.shutdown());return 0;
  }
  if(mode=="info_fail") {
    assert(!port.shutdown());assert(port.faulted() && !port.prepared());
    assert(!tx.enabled && !rx.enabled);assert(!port.shutdown());return 0;
  }
  if(mode.starts_with("write_") || mode=="halfduplex") {
    esp_codec_dev_sample_info_t fs{16,1,0,24000,0};
    assert(api->set_fmt(api,ESP_CODEC_DEV_TYPE_OUT,&fs)==0);
    assert(api->enable(api,ESP_CODEC_DEV_TYPE_OUT,true)==0);
    if(mode=="halfduplex") {
      fs={16,2,3,24000,0};
      assert(api->set_fmt(api,ESP_CODEC_DEV_TYPE_IN,&fs)!=0);
      assert(formats==1 && port.faulted());
    } else {
      int rc=api->write(api,reinterpret_cast<uint8_t*>(pcm.data()),480);
      assert((rc==0)==(mode=="write_ok"));assert(calls==1 && legacy_calls==0);
      for(auto sample:pcm)assert(sample==123); // Caller-owned source is not erased.
    }
    assert(api->enable(api,ESP_CODEC_DEV_TYPE_OUT,false)==0);
    assert(port.shutdown()==(mode=="write_ok"));return 0;
  }
  if(mode.starts_with("bad_") || mode=="enable_unformatted" || mode=="read_unopened") {
    if(mode=="enable_unformatted")assert(api->enable(api,ESP_CODEC_DEV_TYPE_IN,true)!=0);
    else if(mode=="read_unopened"){
      assert(api->read(api,reinterpret_cast<uint8_t*>(pcm.data()),480)!=0);
      zero(std::span<const int16_t>(pcm.data(),240));
    } else {
      esp_codec_dev_sample_info_t fs{16,2,3,24000,0};
      if(mode=="bad_rate")fs.sample_rate=16000;
      if(mode=="bad_bits")fs.bits_per_sample=32;
      if(mode=="bad_channel")fs.channel=4;
      if(mode=="bad_mask")fs.channel_mask=1;
      if(mode=="bad_mclk")fs.mclk_multiple=384;
      auto type=mode=="bad_type"?ESP_CODEC_DEV_TYPE_IN_OUT:ESP_CODEC_DEV_TYPE_IN;
      assert(api->set_fmt(api,type,&fs)!=0);
    }
    assert(port.faulted() && calls==0 && formats==0);assert(!port.microphone_on());return 0;
  }
  if(mode=="format_fail" || mode=="enable_fail") {
    assert(!port.microphone_on());assert(port.faulted() && gains==0 && calls==0);port.shutdown();return 0;
  }
  if(mode.starts_with("ctrl_in_open_") || mode.starts_with("ctrl_in_gain_")) {
    assert(!port.microphone_on());assert(port.faulted() && !port.prepared());
    assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==0);
    assert(!port.microphone_on());assert(!port.shutdown());return 0;
  }
  assert(port.microphone_on());
  if(mode.starts_with("ctrl_in_close_")) {
    assert(!port.microphone_off());assert(port.faulted());
    assert(!port.microphone_off());assert(!port.capture_mono_24k(pcm));zero(pcm);
    assert(!port.shutdown());return 0;
  }
  if(mode.starts_with("ctrl_in_delete_") || mode.starts_with("ctrl_out_delete_")) {
    assert(port.microphone_off());assert(!port.shutdown());assert(port.faulted());
    assert(!port.shutdown());return 0;
  }
  if(mode=="reader_bad_size") {
    std::array<int16_t,241> invalid;invalid.fill(123);K151MicReader reader{port};
    assert(!reader.read_10ms(invalid));zero(invalid);assert(calls==0);return 0;
  }
  if(mode=="reformat_active") {
    esp_codec_dev_sample_info_t fs{16,2,3,24000,0};
    assert(api->set_fmt(api,ESP_CODEC_DEV_TYPE_IN,&fs)!=0);
    assert(formats==1 && port.faulted());assert(port.microphone_off());return 0;
  }
  if(mode=="invalid") {
    std::array<int16_t,241> invalid;invalid.fill(123);
    assert(!port.capture_mono_24k(invalid));zero(invalid);assert(calls==0);return 0;
  }
  const bool ok=port.capture_mono_24k(pcm);
  assert(legacy_calls==0);
  if(mode=="ok" || mode=="boundary" || mode=="disable_fail") {
    assert(ok);for(size_t i=0;i<pcm.size();++i)assert(pcm[i]==static_cast<int16_t>(i-100));
    if(mode=="disable_fail"){assert(!port.microphone_off());assert(port.faulted());return 0;}
    assert(port.microphone_off());assert(port.shutdown());
  } else {
    assert(!ok && port.faulted());zero(pcm);
    int previous=calls;pcm.fill(123);assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==previous);
    assert(!port.shutdown());
  }
  assert(data_deletes==1 && deleted==created);
}
