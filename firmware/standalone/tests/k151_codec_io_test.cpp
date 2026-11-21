// SPDX-License-Identifier: MIT
// Execute actual port against pinned codec headers + no-hardware C ABI doubles.
#include "k151_codec_port.hpp"
#include "k151_mic_reader.hpp"
#include <algorithm>
#include <cassert>
#include <cstring>
#include <string>
using namespace stackchan::standalone;
struct i2s_channel_obj { bool enabled=false; };
struct i2c_master_bus_t {};
struct Dev { const audio_codec_data_if_t* data{}; esp_codec_dev_type_t type{}; bool open=false; };
namespace {
std::string mode;
i2s_channel_obj tx,rx;
i2c_master_bus_t bus;
audio_codec_data_if_t base{};
audio_codec_ctrl_if_t ctrl{};
audio_codec_gpio_if_t gpio{};
audio_codec_if_t codec{};
Dev devices[2];
int created=0, deleted=0, data_deletes=0, calls=0, legacy_calls=0, timer_calls=0, gains=0, formats=0;
bool base_open=true;
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
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t*,i2c_master_bus_handle_t* h){*h=&bus;return 0;}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t h){assert(h==&bus);return 0;}
extern "C" esp_err_t i2s_new_channel(const i2s_chan_config_t* c,i2s_chan_handle_t* t,i2s_chan_handle_t* r){assert(c->dma_frame_num==240);*t=&tx;*r=&rx;return 0;}
extern "C" esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t,const i2s_std_config_t*){return 0;}
extern "C" esp_err_t i2s_channel_init_tdm_mode(i2s_chan_handle_t,const i2s_tdm_config_t*){return 0;}
extern "C" esp_err_t i2s_channel_enable(i2s_chan_handle_t h){if(h->enabled)return ESP_ERR_INVALID_STATE;h->enabled=true;return 0;}
extern "C" esp_err_t i2s_channel_disable(i2s_chan_handle_t h){if(!h->enabled)return ESP_ERR_INVALID_STATE;h->enabled=false;return 0;}
extern "C" esp_err_t i2s_del_channel(i2s_chan_handle_t h){assert(!h->enabled);return 0;}
extern "C" esp_err_t i2s_channel_get_info(i2s_chan_handle_t h,i2s_chan_info_t* info){info->is_enabled=h->enabled;return 0;}
extern "C" esp_err_t i2s_channel_read(i2s_chan_handle_t h,void* p,size_t n,size_t* bytes,uint32_t ms) {
  assert(h==&rx && n<=960 && ms==20);++calls;
  *bytes=(mode=="short"?n-4:mode=="overcount"?n+4:n);
  auto* pcm=static_cast<int16_t*>(p);
  for(size_t i=0;i<std::min(*bytes,n)/4;++i){pcm[2*i]=static_cast<int16_t>(i-100);pcm[2*i+1]=900;}
  if(mode=="base_lost")base_open=false;
  if(mode=="reentrant") {
    esp_codec_dev_sample_info_t fs{16,2,3,24000,0};
    assert(devices[1].data->set_fmt(devices[1].data,ESP_CODEC_DEV_TYPE_IN,&fs)!=0);
  }
  return mode=="driver_fail"?ESP_ERR_TIMEOUT:ESP_OK;
}
extern "C" esp_err_t i2s_channel_write(i2s_chan_handle_t h,const void*,size_t n,size_t* bytes,uint32_t ms){
  assert(h==&tx && ms==20 && n<=480);++calls;*bytes=mode=="write_short"?n-2:n;
  return mode=="write_fail"?ESP_ERR_TIMEOUT:ESP_OK;
}
extern "C" const audio_codec_data_if_t* audio_codec_new_i2s_data(audio_codec_i2s_cfg_t*) {
  base.is_open=sdk_open;base.enable=sdk_enable;base.set_fmt=sdk_format;base.read=legacy_read;base.write=legacy_write;base.close=sdk_close;return &base;
}
extern "C" const audio_codec_ctrl_if_t* audio_codec_new_i2c_ctrl(audio_codec_i2c_cfg_t*){return &ctrl;}
extern "C" const audio_codec_gpio_if_t* audio_codec_new_gpio(){return &gpio;}
extern "C" const audio_codec_if_t* aw88298_codec_new(aw88298_codec_cfg_t*){return &codec;}
extern "C" const audio_codec_if_t* es7210_codec_new(es7210_codec_cfg_t*){return &codec;}
extern "C" esp_codec_dev_handle_t esp_codec_dev_new(esp_codec_dev_cfg_t* cfg) {
  assert(created<2);devices[created]={cfg->data_if,cfg->dev_type,false};return &devices[created++];
}
extern "C" int esp_codec_dev_open(esp_codec_dev_handle_t h,esp_codec_dev_sample_info_t* fs) {
  auto* d=static_cast<Dev*>(h);d->open=true;
  d->data->set_fmt(d->data,d->type,fs);d->data->enable(d->data,d->type,true);
  return 0; // pinned SDK ignores these two callback errors
}
extern "C" int esp_codec_dev_close(esp_codec_dev_handle_t h) {
  auto* d=static_cast<Dev*>(h);if(d->open){d->data->enable(d->data,d->type,false);d->open=false;}return 0;
}
extern "C" int esp_codec_dev_set_in_channel_gain(esp_codec_dev_handle_t,uint16_t,float){++gains;return 0;}
extern "C" int esp_codec_dev_set_out_vol(esp_codec_dev_handle_t,int){return 0;}
extern "C" int esp_codec_dev_read(esp_codec_dev_handle_t h,void* p,int n){auto* d=static_cast<Dev*>(h);return d->data->read(d->data,static_cast<uint8_t*>(p),n);}
extern "C" int esp_codec_dev_write(esp_codec_dev_handle_t h,void* p,int n){auto* d=static_cast<Dev*>(h);return d->data->write(d->data,static_cast<uint8_t*>(p),n);}
extern "C" void esp_codec_dev_delete(esp_codec_dev_handle_t h){assert(!static_cast<Dev*>(h)->open);++deleted;}
extern "C" int audio_codec_delete_codec_if(const audio_codec_if_t*){return 0;}
extern "C" int audio_codec_delete_ctrl_if(const audio_codec_ctrl_if_t*){return 0;}
extern "C" int audio_codec_delete_gpio_if(const audio_codec_gpio_if_t*){return 0;}
extern "C" int audio_codec_delete_data_if(const audio_codec_data_if_t* h){assert(h==&base && deleted==created);++data_deletes;return 0;}
int main(int argc,char** argv) {
  assert(argc==2);mode=argv[1];
  K151CodecPort port;std::array<int16_t,240> pcm;pcm.fill(123);
  if(mode=="reader_denied") {
    K151MicReader reader{port};assert(!reader.read_10ms(pcm));zero(pcm);assert(created==0);return 0;
  }
  if(mode=="denied") {
    assert(!port.prepare(false,true,true));assert(!port.capture_mono_24k(pcm));zero(pcm);assert(created==0);return 0;
  }
  assert(port.prepare(true,true,true));
  const auto* api=devices[1].data;
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
  assert(port.microphone_on());
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
