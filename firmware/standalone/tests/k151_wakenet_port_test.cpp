// SPDX-License-Identifier: MIT
// Complete vendor interface with host C ABI doubles, not neural inference.
#include "k151_wakenet_port.hpp"
#include "k151_mic_only_evidence.hpp"
#include "k151_mic_wake_trial.hpp"
#include "k151_model_assets.hpp"
#include "synthetic_wake_probe.hpp"
#include <esp_heap_caps.h>
#include <esp_partition.h>
#include <psa/crypto.h>
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <utility>
using namespace stackchan::standalone;

template<class Owner, class Stop>
concept CanPrepareLocal = requires(K151WakeNetPort& port) {
  port.prepare_local(std::declval<Owner>(), std::declval<Stop>());
};
template<class Owner, class Stop>
concept CanPrepareEmbedded = requires(K151WakeNetPort& port, std::span<const uint8_t> pack) {
  port.prepare_embedded(std::declval<Owner>(), std::declval<Stop>(), pack);
};

using Flag = std::atomic_bool;
static_assert(CanPrepareLocal<const Flag&, Flag&> && CanPrepareEmbedded<Flag&, const Flag&>);
static_assert(!CanPrepareLocal<Flag, Flag&> && !CanPrepareLocal<Flag&, Flag>);
static_assert(!CanPrepareEmbedded<Flag, Flag&> && !CanPrepareEmbedded<Flag&, Flag>);
static_assert(!CanPrepareLocal<bool, Flag&> && !CanPrepareEmbedded<Flag&, bool>);

struct esp_flash_t {int unused;};
esp_flash_t chip{},external_chip{};
extern "C" { esp_flash_t* esp_flash_default_chip=&chip; }
struct model_iface_data_t {int consumed;};
namespace {
std::string_view scenario;
std::string events;
std::array<model_iface_data_t,2> contexts{};
model_iface_data_t* active_data=nullptr;
srmodel_list_t list{};
char name[]="wn9l_histackchan_tts3";
char wrong[]="wn9_wrong";
char* names[]={name};
esp_wn_iface_t iface{};
int detects=0,cleans=0,creates=0,ret=0;
srmodel_list_t* shared=nullptr;
std::atomic_bool owner{true},stop{false};
int finds=0,hashes=0;
int mic_trial_handoffs=0, heap_checks=0;
std::array<uint8_t,292607> embedded{};
esp_partition_t partition{};
model_iface_data_t* create(const void* n,det_mode_t mode) {
  events+='c';assert(std::strcmp(static_cast<const char*>(n),name)==0);
  assert(mode==DET_MODE_90 && !active_data);
  ++creates;
  if(scenario=="local_revoke_create")owner=false;
  if(scenario=="embedded_stop_create" || scenario=="mic_trial_stop_create")stop=true;
  if(scenario=="reset_stop_create" && creates==2)stop=true;
  if(scenario=="create_failure" || (scenario=="reset_create_failure" && creates==2))return nullptr;
  auto& fresh=contexts[static_cast<size_t>(creates-1)%contexts.size()];
  fresh.consumed=0;active_data=&fresh;
  return active_data;
}
extern "C" const esp_partition_t* esp_partition_find_first(
    esp_partition_type_t type,esp_partition_subtype_t subtype,const char* label) {
  ++finds;assert(type==ESP_PARTITION_TYPE_DATA && subtype==ESP_PARTITION_SUBTYPE_ANY);
  assert(std::strcmp(label,"model")==0);
  if(scenario=="local_revoke_find")owner=false;
  return scenario=="local_missing"?nullptr:&partition;
}
extern "C" esp_err_t esp_partition_get_sha256(const esp_partition_t* p,uint8_t* hash) {
  ++hashes;assert(p==&partition && p->size==1048576);
  constexpr std::array<uint8_t,32> expected{
    0x1d,0x04,0xbf,0x6a,0x1f,0x67,0x75,0xd4,0x3a,0xb4,0x39,0x8b,0xbb,0xac,0x1b,0xc4,
    0x60,0x6f,0x5c,0x41,0x30,0xfe,0x1a,0x85,0x38,0x51,0xec,0x5d,0xf7,0xf2,0x1d,0x1b};
  std::copy(expected.begin(),expected.end(),hash);
  if(scenario=="local_bad_hash")hash[0]^=1;
  if(scenario=="local_revoke_hash")owner=false;
  if(scenario=="local_stop_hash")stop=true;
  return scenario=="local_hash_error"?-1:ESP_OK;
}
int rate(model_iface_data_t* d) {
  assert(d==active_data);
  if(scenario=="reset_revoke_format" && creates==2)owner=false;
  return scenario=="rate" || (scenario=="reset_bad_rate" && creates==2)?24000:16000;
}
int channel(model_iface_data_t*){return scenario=="channel"?2:1;}
int words(model_iface_data_t*){return scenario=="words"?2:1;}
int chunk(model_iface_data_t*) {
  if(scenario=="chunk_negative")return -1;
  if(scenario=="chunk_small")return 159;
  if(scenario=="chunk_large")return 2049;
  if(scenario=="bench_reset_bridge")return 512;
  if(scenario=="reset_changed_chunk" && creates==2)return 512;
  return 480;
}
wakenet_state_t detect(model_iface_data_t* d,int16_t* p) {
  assert(d==active_data && p);++detects;++d->consumed;
  return static_cast<wakenet_state_t>(ret);
}
void clean(model_iface_data_t* d){assert(d==active_data);++cleans;}
void destroy(model_iface_data_t* d) {
  assert(d==active_data && active_data);
  active_data=nullptr;events+='d';
  if(scenario=="reset_revoke_destroy" && creates==1)owner=false;
}
}
extern "C" bool esp_ptr_external_ram(const void*) {return scenario=="embedded_psram";}
extern "C" bool esp_ptr_in_drom(const void*) {return scenario!="embedded_mutable";}
extern "C" void heap_caps_get_info(multi_heap_info_t* info, uint32_t caps) {
  assert(caps==(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  assert(++heap_checks==1 && hashes==0 && events.empty());
  *info={128*1024,32*1024};
  if (scenario=="mic_trial_low_memory") --info->total_free_bytes;
  if (scenario=="mic_trial_fragmented") --info->largest_free_block;
  if (scenario=="mic_trial_stop_during_memory_check") stop=true;
}
extern "C" psa_status_t psa_crypto_init() {
  if(scenario=="embedded_crypto_revoke_init")owner=false;
  return scenario=="embedded_crypto_init_error"?-1:PSA_SUCCESS;
}
extern "C" psa_status_t psa_hash_compute(psa_algorithm_t alg,const uint8_t* p,size_t n,
                                        uint8_t* hash,size_t capacity,size_t* used) {
  assert(p==embedded.data() && n==embedded.size() && alg==PSA_ALG_SHA_256 && capacity==32);
  ++hashes;*used=scenario=="embedded_bad_digest_length"?31:32;
  constexpr std::array<uint8_t,32> expected{
    0x02,0x55,0x85,0x5e,0x56,0xbf,0x72,0xd1,0xe0,0x72,0xd2,0xe0,0xcb,0xee,0x4f,0xb3,
    0xce,0x1a,0xc2,0xc4,0x8f,0x7f,0xee,0x6c,0x8c,0xd5,0x91,0xf8,0x3e,0x59,0xed,0x95};
  std::copy(expected.begin(),expected.end(),hash);
  if(scenario=="embedded_bad_hash" || scenario=="mic_trial_bad_hash")hash[31]^=1;
  if(scenario=="embedded_revoke_hash" || scenario=="mic_trial_revoke_hash")owner=false;
  return scenario=="embedded_hash_error"?-1:0;
}
extern "C" srmodel_list_t* srmodel_load(const void* p) {
  assert(p==embedded.data());events+='e';shared=&list;
  if(scenario=="embedded_revoke_load")owner=false;
  return shared;
}
extern "C" void srmodel_host_deinit(srmodel_list_t* l) {
  assert(l==&list);events+='b';shared=nullptr;
}
extern "C" srmodel_list_t* esp_srmodel_init(const char* partition) {
  assert(std::strcmp(partition,"model")==0);events+='i';
  if(scenario=="local_revoke_init")owner=false;
  shared=scenario=="missing_list"?nullptr:&list;return shared;
}
extern "C" void esp_srmodel_deinit(srmodel_list_t* l) {assert(l==&list);events+='l';shared=nullptr;}
extern "C" srmodel_list_t* get_static_srmodels() {return shared;}
extern "C" char* esp_srmodel_filter(srmodel_list_t* l,const char* a,const char* b) {
  assert(l==&list && std::strcmp(a,"wn")==0 && std::strcmp(b,"histackchan_tts3")==0);
  if(scenario=="local_stop_filter")stop=true;
  events+='f';if(scenario=="missing_name")return nullptr;
  return scenario=="wrong_name"?wrong:name;
}
extern "C" const esp_wn_iface_t* esp_wn_handle_from_name(const char* n) {
  assert(std::strcmp(n,name)==0);events+='h';return scenario=="missing_iface"?nullptr:&iface;
}

// The codec suite executes the real consumer. This seam observes the handoff
// after the concrete WakeNet port's DROM/SHA/SDK preparation on this side.
K151MicWakeTrialResult K151MicWakeTrial::run_prepared(
    const std::atomic_bool& supplied_owner, const std::atomic_bool& supplied_stop,
    const K151MicOnlyEvidence& evidence, std::unique_ptr<NativeWakePort> model) {
  ++mic_trial_handoffs;
  assert(&supplied_owner==&owner && &supplied_stop==&stop && owner && !stop);
  assert(evidence.verified() && model && model->ready());
  assert((model->format()==NativeWakeFormat{16000,480,1,16}));
  assert(events=="efhc" && active_data && shared==&list && hashes==1 && finds==0);
  return K151MicWakeTrialResult::detected;
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
  if(scenario.starts_with("mic_trial_")) {
    using Result = K151MicWakeTrialResult;
    owner=scenario!="mic_trial_no_owner";
    stop=scenario=="mic_trial_stopped";
    const K151MicOnlyEvidence evidence{true,true,scenario!="mic_trial_no_evidence",true};
    const auto input=scenario=="mic_trial_bad_size"?std::span(embedded).first(10):std::span(embedded);
    K151MicWakeTrial trial;
    const auto r=trial.run_embedded(owner,stop,evidence,input);
    const bool denied_before_memory=scenario=="mic_trial_no_owner" ||
        scenario=="mic_trial_stopped" || scenario=="mic_trial_no_evidence";
    assert(heap_checks==(denied_before_memory?0:1));
    if (scenario=="mic_trial_ok") {
      assert(r==Result::detected && mic_trial_handoffs==1 && hashes==1 && events=="efhcdb");
    } else {
      assert(mic_trial_handoffs==0);
      if(scenario=="mic_trial_bad_hash" || scenario=="mic_trial_bad_size")assert(r==Result::fault);
      else if(scenario=="mic_trial_low_memory" || scenario=="mic_trial_fragmented")
        assert(r==Result::memory_denied);
      else if(scenario=="mic_trial_stopped" || scenario=="mic_trial_revoke_hash" ||
              scenario=="mic_trial_stop_create" || scenario=="mic_trial_stop_during_memory_check")
        assert(r==Result::stopped);
      else assert(r==Result::denied);
      assert(hashes==(scenario=="mic_trial_bad_hash" || scenario=="mic_trial_revoke_hash" ||
                      scenario=="mic_trial_stop_create"?1:0));
      assert(events==(scenario=="mic_trial_stop_create"?"efhcdb":""));
    }
    const auto before=events;
    const auto hash_count=hashes;
    owner=true;stop=false;
    assert(trial.run_embedded(owner,stop,{true,true,true,true},embedded)==Result::denied);
    assert(hashes==hash_count && events==before && !active_data && !shared && finds==0);
    assert(heap_checks==(denied_before_memory?0:1));
    return 0;
  }
  if(scenario=="bench_reset_bridge") {
    K151WakeNetPort p;
    assert(p.prepare_embedded(owner,stop,embedded));
    std::array<int16_t,512> samples{};
    for(int i=0;i<64;++i)assert(p.detect(samples)==NativeWakeResult::none);
    assert(active_data->consumed==64);
    int64_t clock=0;
    unsigned checkpoints=0;
    const auto result=probe_synthetic_wake_input(
        p,[] {return owner.load() && !stop.load();},[&] {return ++clock;},[] {},
        [&](std::string_view checkpoint) {
          if(checkpoint=="model_reset_return" || checkpoint=="final_model_reset_return")
            assert(active_data && active_data->consumed==0);
          ++checkpoints;return true;
        });
    assert(result==1 && checkpoints==11 && creates==3 && detects==74 && cleans==0);
    assert(events=="efhcdcdc" && shared==&list && hashes==1);
    p.close();assert(events=="efhcdcdcdb" && !active_data && !shared);
    return 0;
  }
  if(scenario.starts_with("reset_")) {
    K151WakeNetPort p;
    assert(p.prepare_embedded(owner,stop,embedded) && events=="efhc");
    std::array<int16_t,480> samples{};
    assert(p.detect(samples)==NativeWakeResult::none && active_data->consumed==1);
    const auto* old_data=active_data;
    const auto before=p.format();
    if(scenario=="reset_stop_before")stop=true;
    if(scenario=="reset_valid") {
      assert(p.reset() && events=="efhcdc" && cleans==0 && shared==&list);
      assert(p.ready() && p.format()==before && active_data!=old_data && active_data->consumed==0);
      assert(p.detect(samples)==NativeWakeResult::none && active_data->consumed==1);
      p.close();assert(events=="efhcdcdb");
    } else {
      assert(!p.reset() && !p.ready() && !p.reset());
      assert(!p.prepare_embedded(owner,stop,embedded) && !p.prepare(true,true));
      assert(p.detect(samples)==NativeWakeResult::error && detects==1);
      if(scenario=="reset_stop_before" || scenario=="reset_revoke_destroy")
        assert(events=="efhcdb");
      else if(scenario=="reset_create_failure")assert(events=="efhcdcb");
      else assert(events=="efhcdcdb");
      const auto after=events;
      p.close();assert(events==after);
    }
    assert(cleans==0 && hashes==1 && finds==0 && !active_data && !shared);
    return 0;
  }
  if(scenario.starts_with("embedded_")) {
    if(scenario=="embedded_no_owner")owner=false;
    if(scenario=="embedded_stopped")stop=true;
    K151WakeNetPort p;
    const auto input=scenario=="embedded_bad_size"?std::span(embedded).first(10):std::span(embedded);
    const bool accepted=p.prepare_embedded(owner,stop,input);
    if(scenario=="embedded_valid" || scenario=="embedded_overlap") {
      assert(accepted && p.ready() && events=="efhc");
      if(scenario=="embedded_overlap") {
        K151WakeNetPort other;
        assert(!other.prepare_embedded(owner,stop,embedded) && finds==0);
        assert(!other.prepare(true,true));
      }
      p.close();assert(events=="efhcdb" && shared==nullptr);
    } else {
      assert(!accepted && !p.ready());
      if(scenario=="embedded_revoke_load")assert(events=="eb");
      else if(scenario=="embedded_stop_create")assert(events=="efhcdb");
      else assert(events.empty());
    }
    if(scenario!="embedded_no_owner" && scenario!="embedded_stopped") {
      owner=true;stop=false;
      p.close();const auto before=events;
      assert(!p.prepare_embedded(owner,stop,embedded));
      assert(!p.prepare(true,true) && events==before);
    }
    assert(finds==0);return 0;
  }
  if(scenario.starts_with("local_")) {
    partition.flash_chip=&chip;partition.type=ESP_PARTITION_TYPE_DATA;
    partition.address=0xf00000;partition.size=1048576;
    std::strcpy(partition.label,"model");partition.readonly=true;
    if(scenario=="local_no_owner")owner=false;
    if(scenario=="local_stopped")stop=true;
    if(scenario=="local_bad_size")--partition.size;
    if(scenario=="local_bad_address")partition.address=0xa00000;
    if(scenario=="local_bad_type")partition.type=ESP_PARTITION_TYPE_APP;
    if(scenario=="local_bad_label")std::strcpy(partition.label,"assets");
    if(scenario=="local_writable")partition.readonly=false;
    if(scenario=="local_encrypted")partition.encrypted=true;
    if(scenario=="local_external")partition.flash_chip=&external_chip;
    K151WakeNetPort p;
    const bool accepted=p.prepare_local(owner,stop);
    if(scenario=="local_valid") {
      assert(accepted && p.ready() && events=="ifhc");
      assert(finds==1 && hashes==1);
      assert(p.reset() && p.ready() && events=="ifhcdc" && cleans==0);
    } else {
      assert(!accepted && !p.ready());
      if(scenario=="local_revoke_create")assert(events=="ifhcdl");
      else if(scenario=="local_revoke_init")assert(events=="il");
      else if(scenario=="local_stop_filter")assert(events=="ifl");
      else assert(events.empty());
      if(scenario=="local_no_owner" || scenario=="local_stopped")assert(finds==0 && hashes==0);
    }
    const auto before=events;
    const auto old_finds=finds,old_hashes=hashes;
    if(scenario!="local_no_owner" && scenario!="local_stopped") {
      owner=true;stop=false;
      assert(!p.prepare_local(owner,stop));
      assert(events==before && finds==old_finds && hashes==old_hashes);
      if(!accepted) {
        p.close();
        assert(!p.prepare(true,true) && !p.ready());
        assert(events==before); // Legacy bool entry cannot bypass a failed local attempt.
      }
    }
    std::cout<<"local asset/owner gate PASS; SHA API doubled, no device\n";return 0;
  }
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
    } else if(scenario=="valid" || scenario=="no_clean" || scenario=="closed" || scenario=="unknown" ||
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
        assert(p.reset() && events=="ifhcdc" && cleans==0);
        ret=0;assert(p.detect(samples)==NativeWakeResult::none);
        ret=-1;assert(p.detect(samples)==NativeWakeResult::none);
        ret=1;assert(p.detect(samples)==NativeWakeResult::detected);
        assert(detects==3 && p.reset() && events=="ifhcdcdc" && cleans==0);
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
