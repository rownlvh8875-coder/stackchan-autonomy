// SPDX-License-Identifier: MIT
// Execute actual port against pinned codec headers + no-hardware C ABI doubles.
#include "k151_codec_port.hpp"
#include "k151_mic_reader.hpp"
#include "native_wake_input.hpp"
#include <algorithm>
#include <cassert>
#include <cstring>
#include <string>
using namespace stackchan::standalone;
struct i2s_channel_obj { bool enabled=false; bool alive=true; int disables=0,deletes=0; };
struct i2c_master_bus_t { bool alive=true; int deletes=0; };
struct Dev { const audio_codec_data_if_t* data{}; esp_codec_dev_type_t type{}; bool open=false; };
namespace {
std::string mode;
i2s_channel_obj tx,rx;
i2c_master_bus_t bus;
audio_codec_data_if_t base{};
audio_codec_ctrl_if_t controls[2]{};
const audio_codec_ctrl_if_t* codec_controls[2]{};
audio_codec_gpio_if_t gpio{};
audio_codec_if_t codecs[2]{};
Dev devices[2];
int created=0, deleted=0, data_deletes=0, calls=0, legacy_calls=0, timer_calls=0, gains=0, formats=0;
int controls_created=0, controls_deleted=0;
std::string phase;
bool base_open=true;
bool mic_only() { return mode.starts_with("mic_only_"); }
std::atomic_bool local_owner{true}, local_stop{false};
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
int bus_created=0, channels_created=0, tdm_inits=0;
bool fail_rx_disable=false;
bool ctrl_open(const audio_codec_ctrl_if_t* h) {assert(h==&controls[0] || h==&controls[1]);return true;}
int ctrl_io(const audio_codec_ctrl_if_t* h,int reg,int reg_len,void* data,int n,bool write) {
  assert(h==&controls[0] || h==&controls[1]);const bool out=h==&controls[0];
  assert(reg_len==1 && data && n==(out?2:1) && reg==(out?0x06:0x43));
  auto* bytes=static_cast<uint8_t*>(data);
  if(!write){bytes[0]=out?0x12:0;if(out)bytes[1]=0x34;}
  else if(out){assert(bytes[0]==0xb7 && bytes[1]==0x6e);}
  const std::string path=out?"ctrl_out_":"ctrl_in_";
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
  if(mode=="mic_only_stop_open" && phase=="open")local_stop=true;
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
  if(mode=="clock_negative")return -1;
  if(timer_calls==1)return 1000;
  if(mode=="clock_backwards")return 999;
  return mode=="deadline" || mode=="write_deadline" ? 41001 : mode=="boundary" ? 41000 : 2000;
}
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t*,i2c_master_bus_handle_t* h){++bus_created;*h=&bus;return 0;}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t h){
  assert(h==&bus && h->alive);++h->deletes;
  if(mode=="release_bus_live_error")return ESP_ERR_INVALID_STATE;
  h->alive=false;return mode=="release_bus_freed_error"?ESP_FAIL:ESP_OK;
}
extern "C" esp_err_t i2s_new_channel(const i2s_chan_config_t* c,i2s_chan_handle_t* t,i2s_chan_handle_t* r){
  assert(c->dma_frame_num==240 && r);assert((t==nullptr)==mic_only());
  ++channels_created;
  if(t)*t=&tx;
  *r=&rx;return 0;
}
extern "C" esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t*){assert(!mic_only());return 0;}
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
                               mode=="release_rx_info" || mode=="mic_only_close_failure");
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
  *bytes=(mode=="short" || mode=="mic_only_short"?n-4:mode=="overcount"?n+4:n);
  auto* pcm=static_cast<int16_t*>(p);
  for(size_t i=0;i<std::min(*bytes,n)/4;++i){pcm[2*i]=static_cast<int16_t>(i-100);pcm[2*i+1]=900;}
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
  auto* c=&controls[out?0:1];
  assert(!c->is_open);
  ++controls_created;
  c->is_open=ctrl_open;c->read_reg=ctrl_read;c->write_reg=ctrl_write;c->get_info=ctrl_info;return c;
}
extern "C" const audio_codec_gpio_if_t* audio_codec_new_gpio(){assert(!mic_only());return &gpio;}
extern "C" const audio_codec_if_t* aw88298_codec_new(aw88298_codec_cfg_t* cfg){assert(!mic_only());codec_controls[0]=cfg->ctrl_if;codec_operation(0,"init");return &codecs[0];}
extern "C" const audio_codec_if_t* es7210_codec_new(es7210_codec_cfg_t* cfg){codec_controls[1]=cfg->ctrl_if;codec_operation(1,"init");return &codecs[1];}
extern "C" esp_codec_dev_handle_t esp_codec_dev_new(esp_codec_dev_cfg_t* cfg) {
  assert(created<2);devices[created]={cfg->data_if,cfg->dev_type,false};return &devices[created++];
}
extern "C" int esp_codec_dev_open(esp_codec_dev_handle_t h,esp_codec_dev_sample_info_t* fs) {
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
extern "C" int audio_codec_delete_codec_if(const audio_codec_if_t* c){assert(deleted==created);codec_operation(c==&codecs[0]?0:1,"delete");return 0;}
extern "C" int audio_codec_delete_ctrl_if(const audio_codec_ctrl_if_t* c){assert(c==&controls[0] || c==&controls[1]);++controls_deleted;return 0;}
extern "C" int audio_codec_delete_gpio_if(const audio_codec_gpio_if_t*){return 0;}
extern "C" int audio_codec_delete_data_if(const audio_codec_data_if_t* h){assert(h==&base && deleted==created);++data_deletes;return 0;}
int main(int argc,char** argv) {
  assert(argc==2);mode=argv[1];
  K151CodecPort port;std::array<int16_t,240> pcm;pcm.fill(123);
  if(mic_only()) {
    const K151MicOnlyEvidence verified{true,true,true,true};
    if(mode=="mic_only_gates") {
      assert(!port.prepare_microphone_only(local_owner,local_stop,{false,true,true,true}));
      assert(!port.prepare_microphone_only(local_owner,local_stop,{true,false,true,true}));
      assert(!port.prepare_microphone_only(local_owner,local_stop,{true,true,false,true}));
      assert(!port.prepare_microphone_only(local_owner,local_stop,{true,true,true,false}));
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
    assert(!port.prepare(true,true,true) && !port.speaker_on_low_volume());
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
    assert(!port.prepare(false,true,true));assert(!port.capture_mono_24k(pcm));zero(pcm);assert(created==0);return 0;
  }
  if(mode.starts_with("ctrl_") && mode.find("_init_")!=std::string::npos) {
    assert(!port.prepare(true,true,true));assert(port.faulted() && !port.prepared());
    assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==0);
    assert(!port.shutdown());assert(controls_deleted==controls_created);return 0;
  }
  assert(port.prepare(true,true,true));
  const auto* api=devices[1].data;
  if(mode.starts_with("release_")) {
    const bool bus_error=mode.starts_with("release_bus_");
    assert(!port.shutdown());assert(port.faulted() && !port.prepared());
    assert(!port.capture_mono_24k(pcm));zero(pcm);assert(calls==0);
    assert(!port.microphone_on());assert(!port.prepare(true,true,true));
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
