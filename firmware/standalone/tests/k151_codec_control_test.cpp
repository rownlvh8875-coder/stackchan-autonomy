// SPDX-License-Identifier: MIT
// Real unmodified ES7210 SDK C; only the underlying register I/O is doubled.
#include "k151_codec_control.hpp"
#include <esp_codec_dev_defaults.h>
#include <es7210_adc.h>
#include <array>
#include <cassert>
#include <cstdlib>
#include <string>
using namespace stackchan::standalone;
namespace {
audio_codec_ctrl_if_t base{};
std::array<uint8_t,256> regs{};
bool opened=true, inject=false, write_error=false;
int reads=0,writes=0;
bool is_open(const audio_codec_ctrl_if_t* h){assert(h==&base);return opened;}
int read(const audio_codec_ctrl_if_t* h,int reg,int len,void* data,int n){
  assert(h==&base && len==1 && n==1);++reads;
  if(inject && !write_error)return ESP_CODEC_DEV_DRV_ERR;
  *static_cast<uint8_t*>(data)=regs.at(reg);return 0;
}
int write(const audio_codec_ctrl_if_t* h,int reg,int len,void* data,int n){
  assert(h==&base && len==1 && n==1);++writes;
  if(inject && write_error)return ESP_CODEC_DEV_DRV_ERR;
  regs.at(reg)=*static_cast<uint8_t*>(data);return 0;
}
int info(const audio_codec_ctrl_if_t* h,audio_codec_ctrl_info_t* out){
  assert(h==&base);out->type=AUDIO_CODEC_CTRL_I2C;return inject?ESP_CODEC_DEV_DRV_ERR:0;
}
}
int main(int argc,char** argv){
  assert(argc==2);const std::string mode=argv[1];
  base.is_open=is_open;base.read_reg=read;base.write_reg=write;base.get_info=info;
  K151CodecControl guard;assert(guard.attach(&base));const auto* c=guard.interface();
  if(mode=="boundaries") {
    uint8_t byte=0;audio_codec_ctrl_info_t details{};
    assert(!c->is_open(nullptr));
    assert(c->read_reg(nullptr,1,1,&byte,1)==ESP_CODEC_DEV_INVALID_ARG);
    assert(c->write_reg(nullptr,1,1,&byte,1)==ESP_CODEC_DEV_INVALID_ARG);
    assert(c->get_info(nullptr,&details)==ESP_CODEC_DEV_INVALID_ARG);
    assert(!guard.faulted() && reads==0 && writes==0);
    inject=true;assert(c->get_info(c,&details)!=0);assert(guard.faulted());
    inject=false;assert(c->read_reg(c,1,1,&byte,1)==0);assert(guard.faulted());
    guard.detach();assert(guard.faulted());assert(!guard.attach(&base));return 0;
  }
  if(mode=="lost") {
    opened=false;assert(!guard.healthy() && guard.faulted());
    uint8_t byte=0;assert(c->read_reg(c,1,1,&byte,1)==ESP_CODEC_DEV_WRONG_STATE);
    assert(reads==0);return 0;
  }
  es7210_codec_cfg_t cfg{};
  cfg.ctrl_if=mode=="raw_read"?&base:c;
  cfg.mic_selected=ES7210_SEL_MIC1|ES7210_SEL_MIC2|ES7210_SEL_MIC3;
  auto* codec=es7210_codec_new(&cfg);assert(codec && guard.healthy());
  const int old_reads=reads,old_writes=writes;
  inject=true;write_error=mode=="guard_write";
  const int rc=codec->set_mic_channel_gain(codec,1,30.0f);
  assert(reads>old_reads && writes>old_writes);
  // Real ES7210 update_reg_bit swallows read failure and still returns success.
  assert((rc==ESP_CODEC_DEV_OK)==!write_error);
  assert(guard.faulted()==(mode!="raw_read"));
  inject=false;(void)codec->close(codec);
  assert(guard.faulted()==(mode!="raw_read"));
  std::free(const_cast<audio_codec_if_t*>(codec));
}
