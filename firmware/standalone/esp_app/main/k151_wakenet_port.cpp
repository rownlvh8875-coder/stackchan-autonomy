// SPDX-License-Identifier: MIT
#include "k151_wakenet_port.hpp"
#include <esp_wn_models.h>
#include <cstring>
namespace stackchan::standalone {
bool K151WakeNetPort::prepare(bool owner,bool verified) {
  if(!owner || !verified || attempted_)return false;
  attempted_=true;
  models_=esp_srmodel_init("model");
  if(!models_ || models_->num!=1) {close();return false;}
  const char* name=esp_srmodel_filter(models_,ESP_WN_PREFIX,"histackchan_tts3");
  if(!name || std::strcmp(name,"wn9l_histackchan_tts3")!=0) {close();return false;}
  iface_=esp_wn_handle_from_name(name);
  if(!iface_ || !iface_->create || !iface_->destroy || !iface_->get_samp_rate ||
     !iface_->get_samp_chunksize || !iface_->get_channel_num ||
     !iface_->get_word_num || !iface_->clean || !iface_->detect) {
    close();return false;
  }
  data_=iface_->create(name,DET_MODE_90);
  if(!data_) {close();return false;}
  const int chunk=iface_->get_samp_chunksize(data_);
  if(iface_->get_samp_rate(data_)!=16000 || iface_->get_channel_num(data_)!=1 ||
     iface_->get_word_num(data_)!=1 || chunk<160 || chunk>2048) {
    close();return false;
  }
  format_={16000,static_cast<size_t>(chunk),1,16};
  return true;
}
bool K151WakeNetPort::ready() const {
  return data_ && iface_ && models_ && !faulted_;
}
NativeWakeResult K151WakeNetPort::detect(std::span<int16_t> pcm) {
  if(!ready())return NativeWakeResult::error;
  if(pcm.size()!=format_.chunk_samples) {faulted_=true;return NativeWakeResult::error;}
  const auto r=iface_->detect(data_,pcm.data());
  if(r==WAKENET_NO_DETECT || r==WAKENET_CHANNEL_VERIFIED)return NativeWakeResult::none;
  if(r==WAKENET_DETECTED)return NativeWakeResult::detected;
  faulted_=true;return NativeWakeResult::error;
}
bool K151WakeNetPort::reset() {
  if(!ready())return false;
  iface_->clean(data_);return true;
}
void K151WakeNetPort::close() {
  if(data_)iface_->destroy(data_);
  data_=nullptr;iface_=nullptr;
  if(models_)esp_srmodel_deinit(models_);
  models_=nullptr;format_={};
}
const char* K151WakeNetPort::compiled_link_marker() {
  // Retain SDK bindings under linker GC without executing/constructing them.
  bool (K151WakeNetPort::* volatile prepare_anchor)(bool,bool)=&K151WakeNetPort::prepare;
  // A virtual member pointer encodes a vtable slot and can be GC'd without
  // retaining detect. A non-dispatched thunk forces its SDK call into the ELF.
  NativeWakeResult (* volatile detect_anchor)(K151WakeNetPort&,std::span<int16_t>)=
      +[](K151WakeNetPort& port,std::span<int16_t> pcm) {
        return port.K151WakeNetPort::detect(pcm);
      };
  (void)prepare_anchor;(void)detect_anchor;
  return "ESP_SR_2_4_7_HISTACKCHAN_DORMANT_NOT_STARTED";
}
} // namespace stackchan::standalone
