// SPDX-License-Identifier: MIT
// Complete vendor interface with host C ABI doubles, not neural inference.
#include "k151_wakenet_port.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
using namespace stackchan::standalone;
struct model_iface_data_t {int unused;};
namespace {
std::string_view scenario;
std::string events;
model_iface_data_t data{};
srmodel_list_t list{};
char name[]="wn9l_histackchan_tts3";
char wrong[]="wn9_wrong";
char* names[]={name};
esp_wn_iface_t iface{};
int detects=0,cleans=0,ret=0;
srmodel_list_t* shared=nullptr;
model_iface_data_t* create(const void* n,det_mode_t mode) {
  events+='c';assert(std::strcmp(static_cast<const char*>(n),name)==0);
  assert(mode==DET_MODE_90);return scenario=="create_failure"?nullptr:&data;
}
int rate(model_iface_data_t* d){assert(d==&data);return scenario=="rate"?24000:16000;}
int channel(model_iface_data_t*){return scenario=="channel"?2:1;}
int words(model_iface_data_t*){return scenario=="words"?2:1;}
int chunk(model_iface_data_t*) {
  if(scenario=="chunk_negative")return -1;
  if(scenario=="chunk_small")return 159;
  if(scenario=="chunk_large")return 2049;
  return 480;
}
wakenet_state_t detect(model_iface_data_t* d,int16_t* p) {
  assert(d==&data && p);++detects;
  return static_cast<wakenet_state_t>(ret);
}
void clean(model_iface_data_t* d){assert(d==&data);++cleans;}
void destroy(model_iface_data_t* d){assert(d==&data);events+='d';}
}
extern "C" srmodel_list_t* esp_srmodel_init(const char* partition) {
  assert(std::strcmp(partition,"model")==0);events+='i';
  shared=scenario=="missing_list"?nullptr:&list;return shared;
}
extern "C" void esp_srmodel_deinit(srmodel_list_t* l) {assert(l==&list);events+='l';shared=nullptr;}
extern "C" srmodel_list_t* get_static_srmodels() {return shared;}
extern "C" char* esp_srmodel_filter(srmodel_list_t* l,const char* a,const char* b) {
  assert(l==&list && std::strcmp(a,"wn")==0 && std::strcmp(b,"histackchan_tts3")==0);
  events+='f';if(scenario=="missing_name")return nullptr;
  return scenario=="wrong_name"?wrong:name;
}
extern "C" const esp_wn_iface_t* esp_wn_handle_from_name(const char* n) {
  assert(std::strcmp(n,name)==0);events+='h';return scenario=="missing_iface"?nullptr:&iface;
}
int main(int argc,char** argv) {
  assert(argc==2);scenario=argv[1];
  list.num=scenario=="multiple"?2:1;list.model_name=names;
  iface.create=create;iface.get_samp_rate=rate;iface.get_channel_num=channel;
  iface.get_samp_chunksize=chunk;iface.get_word_num=words;
  iface.detect=detect;iface.clean=clean;iface.destroy=destroy;
  if(scenario=="no_create")iface.create=nullptr;
  if(scenario=="no_rate")iface.get_samp_rate=nullptr;
  if(scenario=="no_channel")iface.get_channel_num=nullptr;
  if(scenario=="no_chunk")iface.get_samp_chunksize=nullptr;
  if(scenario=="no_words")iface.get_word_num=nullptr;
  if(scenario=="no_detect")iface.detect=nullptr;
  if(scenario=="no_clean")iface.clean=nullptr;
  if(scenario=="no_destroy")iface.destroy=nullptr;
  if(scenario=="overlap" || scenario=="preexisting_sdk") {
    if(scenario=="preexisting_sdk") {
      shared=&list;
      K151WakeNetPort denied;assert(!denied.prepare(true,true) && events.empty());
      shared=nullptr;
    }
    K151WakeNetPort first,second;
    assert(first.prepare(true,true));
    const auto before=events;
    assert(!second.prepare(true,true));second.close();
    assert(events==before && first.ready());
    first.close();assert(events=="ifhcdl");
    assert(!second.prepare(true,true)); // Failed lifecycle cannot silently retry.
    {K151WakeNetPort fresh;assert(fresh.prepare(true,true));}
    assert(events=="ifhcdlifhcdl");
    std::cout<<"single SDK owner PASS; no device/inference/API\n";return 0;
  }
  {
    (void)K151WakeNetPort::compiled_link_marker();assert(events.empty());
    K151WakeNetPort p;
    assert(!p.ready() && !p.reset());
    std::array<int16_t,480> samples{};
    if(scenario=="gate") {
      assert(!p.prepare(false,true));assert(!p.prepare(true,false));
      assert(events.empty());assert(p.prepare(true,true));
    } else if(scenario=="valid" || scenario=="closed" || scenario=="unknown" ||
              scenario=="wrong_buffer") {
      assert(p.prepare(true,true));assert(p.ready());
      const auto f=p.format();assert(f.sample_rate_hz==16000 && f.channels==1 &&
          f.bits_per_sample==16 && f.chunk_samples==480);
      assert(!p.prepare(true,true)); // No second SDK allocation.
      assert(events=="ifhc");
      if(scenario=="closed") {
        p.close();p.close();assert(!p.ready() && !p.reset());
        assert(!p.prepare(true,true) && events=="ifhcdl");
        assert(p.detect(samples)==NativeWakeResult::error && detects==0);
      } else if(scenario=="unknown" || scenario=="wrong_buffer") {
        ret=2;
        auto input=scenario=="wrong_buffer"?std::span(samples).first(479):std::span(samples);
        assert(p.detect(input)==NativeWakeResult::error && !p.ready());
        assert(p.detect(samples)==NativeWakeResult::error);
        assert(detects==(scenario=="unknown"?1:0));
        assert(events=="ifhcdl"); // Fault releases speech context before scope ends.
        p.close();assert(events=="ifhcdl");
      } else {
        assert(p.reset() && cleans==1);
        ret=0;assert(p.detect(samples)==NativeWakeResult::none);
        ret=-1;assert(p.detect(samples)==NativeWakeResult::none);
        ret=1;assert(p.detect(samples)==NativeWakeResult::detected);
        assert(detects==3 && p.reset() && cleans==2);
      }
    } else {
      assert(!p.prepare(true,true) && !p.ready());
      const auto after=events;assert(!p.prepare(true,true) && events==after);
      assert(p.detect(samples)==NativeWakeResult::error && detects==0);
      if(scenario=="missing_list")assert(events=="i");
      else if(events.find('c')!=std::string::npos && scenario!="create_failure")
        assert(events.ends_with("dl"));
      else assert(events.ends_with('l') && events.find('d')==std::string::npos);
    }
  }
  if(scenario!="missing_list") {
    assert(events.ends_with('l'));
    assert(events.find('l')==events.rfind('l'));
    if(events.find('d')!=std::string::npos)assert(events.ends_with("dl"));
  }
  std::cout<<"SDK ABI/lifecycle PASS; no device/inference/API\n";
}
