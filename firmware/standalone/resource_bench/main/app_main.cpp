// SPDX-License-Identifier: MIT
// Silent finite laboratory diagnostic. No codec, GPIO, NVS, Wi-Fi or cloud init.
#include "bench_gate.hpp"
#include "k151_wakenet_port.hpp"
#include "audio_wipe.hpp"
#include "audio_memory_admission.hpp"
#include "local_tls_probe.hpp"
#include "wire_memory_probe.hpp"
#include <driver/usb_serial_jtag.h>
#include <esp_heap_caps.h>
#include <esp_memory_utils.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <new>
#include <vector>
using namespace stackchan::standalone;
extern const uint8_t model_start[] asm("_binary_srmodels_bin_start");
extern const uint8_t model_end[] asm("_binary_srmodels_bin_end");
namespace {
std::atomic_bool owner{false},stop{false},reader_done{false};
constexpr auto internal_caps=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT;
constexpr auto external_caps=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
bool allowed() {return owner.load() && !stop.load();}
void snapshot(const char* stage) {
  std::printf("{\"stage\":\"%s\",\"internal_free\":%u,\"internal_largest\":%u,"
      "\"psram_free\":%u,\"psram_largest\":%u,\"internal_min\":%u,\"psram_min\":%u}\n",
      stage,static_cast<unsigned>(heap_caps_get_free_size(internal_caps)),
      static_cast<unsigned>(heap_caps_get_largest_free_block(internal_caps)),
      static_cast<unsigned>(heap_caps_get_free_size(external_caps)),
      static_cast<unsigned>(heap_caps_get_largest_free_block(external_caps)),
      static_cast<unsigned>(heap_caps_get_minimum_free_size(internal_caps)),
      static_cast<unsigned>(heap_caps_get_minimum_free_size(external_caps)));
}
void reader(void*) {
  const uint32_t nonce=esp_random();
  BenchGate gate{nonce,esp_timer_get_time()/1000};
  std::printf("{\"bench\":\"WAIT_LOCAL_START\",\"nonce\":\"%08lX\",\"wait_ms\":60000}\n",
              static_cast<unsigned long>(nonce));
  while(!gate.stopped() && !reader_done.load()) {
    char c{};
    const int count=usb_serial_jtag_read_bytes(&c,1,pdMS_TO_TICKS(20));
    const auto now=esp_timer_get_time()/1000;
    if(count==1)gate.feed(c,now);
    else if(count<0) {stop=true;break;}
    else gate.tick(now);
    if(gate.running())owner=true;
  }
  owner=false;stop=true;
  vTaskDelete(nullptr);
}
struct Pcm {
  std::vector<int16_t> samples;
  explicit Pcm(size_t n):samples(n,0) {}
  ~Pcm() {wipe_pcm(samples);}
};
void measure() {
  K151WakeNetPort wake;
  if(!wake.prepare_embedded(owner,stop,{model_start,static_cast<size_t>(model_end-model_start)})) {
    std::puts("{\"result\":\"MODEL_PREPARE_DENIED\"}");return;
  }
  snapshot("model_resident");
  if(!allowed())return;
  try {
    Pcm question{OfflineVoiceCycle::kMaxRecordedFrames};
    if(!allowed())return;
    Pcm tts{0};
    const bool q_external=esp_ptr_external_ram(question.samples.data());
    if(!q_external) {
      std::puts("{\"result\":\"ALLOCATOR_PLACEMENT_DENIED\"}");return;
    }
    if (!allowed()) return;
    {
      LocalTlsProbe tls;
      snapshot("model_question_before_local_tls");
      if (!tls.run(allowed)) {
        std::printf("{\"result\":\"%s\",\"local_tls_stage\":\"%s\","
                    "\"local_tls_handshake_error\":%d}\n",
                    allowed() ? "LOCAL_TLS_DENIED" : "BENCH_STOPPED",
                    tls.stage(), tls.handshake_error());
        return;
      }
      if (!allowed()) return;
      snapshot("model_question_local_tls_established");
      const bool wire_ok = probe_wire_memory(
        tts.samples, allowed, [&](httpwire::Endpoint endpoint, const auto& raw, const auto& pcm) {
          const bool speech = endpoint == httpwire::Endpoint::speech;
          const bool raw_external = esp_ptr_external_ram(raw.data());
          const bool pcm_external = speech && esp_ptr_external_ram(pcm.data());
          snapshot(speech ? "model_question_tls_wire_and_decoded_pcm"
                          : "model_question_tls_json_decoded");
          std::printf("{\"wire_probe\":\"%s\",\"body_bytes\":%u,\"body_capacity_bytes\":%u,"
                      "\"body_in_psram\":%s,\"decoded_pcm_capacity_bytes\":%u,"
                      "\"decoded_pcm_in_psram\":%s}\n",
                      speech ? "speech" : "json", static_cast<unsigned>(raw.size()),
                      static_cast<unsigned>(raw.capacity()), raw_external ? "true" : "false",
                      static_cast<unsigned>(pcm.capacity() * sizeof(int16_t)),
                      pcm_external ? "true" : "false");
          return raw.capacity() <= httpwire::response_cap(endpoint) &&
                 (!speech || (raw_external && pcm_external));
        });
      if (!wire_ok) {
        std::puts(allowed() ? "{\"result\":\"WIRE_PROBE_DENIED\"}" : "{\"result\":\"BENCH_STOPPED\"}");
        return;
      }
    }
    if(!allowed())return;
    Pcm chunk{wake.format().chunk_samples};
    snapshot("model_question_tts");
    std::printf("{\"question_bytes\":384000,\"tts_bytes\":960000,"
        "\"question_in_psram\":true,\"tts_in_psram\":true,\"chunk_samples\":%u}\n",
        static_cast<unsigned>(chunk.samples.size()));
    int64_t max_us=0;unsigned completed=0,over100ms=0,matches=0;
    bool failed=false;
    for(unsigned i=0;i<64 && allowed();++i) {
      const auto before=esp_timer_get_time();
      const auto r=wake.detect(chunk.samples); // Synthetic silence only.
      const auto elapsed=esp_timer_get_time()-before;
      wipe_pcm(chunk.samples);
      if(elapsed<0 || r==NativeWakeResult::error) {failed=true;break;}
      max_us=std::max(max_us,elapsed);++completed;
      if(elapsed>100000)++over100ms;
      if(r==NativeWakeResult::detected)++matches;
      vTaskDelay(1);
    }
    snapshot("synthetic_inference");
    std::printf("{\"result\":\"%s\",\"chunks\":%u,\"max_detect_us\":%lld,"
        "\"over_100ms\":%u,\"synthetic_matches\":%u,\"wire_decoders_exercised\":true,"
        "\"local_tls12_peer_verified\":true,\"tls_measured\":false,"
        "\"operating_admission\":false}\n",
        !failed && allowed() && completed==64?"FINITE_BENCH_COMPLETED":"BENCH_STOPPED",
        completed,static_cast<long long>(max_us),over100ms,matches);
  } catch(const std::bad_alloc&) {
    std::puts("{\"result\":\"BENCH_ALLOCATION_DENIED\"}");
  }
}
}
extern "C" void app_main() {
  std::puts("K151_SILENT_RESOURCE_BENCH_NOT_OPERATIONAL");
  usb_serial_jtag_driver_config_t cfg{};cfg.rx_buffer_size=128;cfg.tx_buffer_size=1024;
  if(usb_serial_jtag_driver_install(&cfg)!=ESP_OK)return;
  if(xTaskCreate(reader,"local_bench",4096,nullptr,6,nullptr)!=pdPASS)return;
  while(!owner.load() && !stop.load())vTaskDelay(pdMS_TO_TICKS(10));
  if(!allowed()) {reader_done=true;return;}
  snapshot("baseline");
  // Do not start the SDK monitor if its small internal allocation lacks room.
  if(heap_caps_get_largest_free_block(internal_caps)<32768 ||
     heap_caps_get_free_size(internal_caps)<131072) {
    reader_done=true;owner=false;stop=true;return;
  }
  const bool monitoring=heap_caps_monitor_local_minimum_free_size_start()==ESP_OK;
  if(monitoring) {
    measure();snapshot("after_cleanup");
    heap_caps_monitor_local_minimum_free_size_stop();
  } else std::puts("{\"result\":\"HEAP_MONITOR_BUSY\"}");
  owner=false;stop=true;reader_done=true;
  std::puts("{\"bench\":\"HOLD_UNTIL_RESET\",\"operating_admission\":false}");
}
