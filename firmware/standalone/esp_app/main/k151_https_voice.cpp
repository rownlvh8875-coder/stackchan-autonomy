// SPDX-License-Identifier: MIT
// Fixed-host TLS, no redirect/retry, per-stage deadline and capped reply.
// Compile-only: app_main never calls post_once or starts a network stack.
#include "k151_https_voice.hpp"
#include "live_io_gate.hpp"
#include <algorithm>
#include <array>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
#include <esp_timer.h>
#include <optional>
#include <string>
#include <utility>

namespace stackchan::standalone {
namespace {
constexpr char kHost[]="api.openai.com";
constexpr int64_t kStageMs=30000;
constexpr int kIoTimeoutMs=1500;
constexpr std::time_t kEarliestTrustedEpoch=1700000000;

struct Headers { std::string media; bool duplicate=false; };
bool iequals(const char* a,const char* b){
 if(!a||!b)return false;
 for(size_t i=0;;++i){
  char x=a[i],y=b[i];
  if(x>='A'&&x<='Z')x=static_cast<char>(x-'A'+'a');
  if(y>='A'&&y<='Z')y=static_cast<char>(y-'A'+'a');
  if(x!=y)return false;
  if(x==0)return true;
 }
}
esp_err_t on_header(esp_http_client_event_t* e){
 if(!e||e->event_id!=HTTP_EVENT_ON_HEADER||!e->user_data||
    !iequals(e->header_key,"content-type"))return ESP_OK;
 auto* h=static_cast<Headers*>(e->user_data);
 if(!h->media.empty()||!e->header_value||
    std::strlen(e->header_value)>128){h->duplicate=true;return ESP_OK;}
 h->media=e->header_value;
 return ESP_OK;
}
bool secret_safe(std::string_view s){
 if(s.empty()||s.size()>220)return false;
 for(unsigned char c:s)if(c<=0x20||c>=0x7f)return false;
 return true;
}
int64_t monotonic_ms(){return esp_timer_get_time()/1000;}
struct Client {
 esp_http_client_handle_t ptr=nullptr;
 ~Client(){if(ptr){(void)esp_http_client_close(ptr);(void)esp_http_client_cleanup(ptr);}}
};
bool send_exact(esp_http_client_handle_t c,const char* buf,size_t n,
                LiveIoGate& gate){
 size_t at=0;
 while(at<n){
  if(!gate.allowed(static_cast<uint64_t>(monotonic_ms())))return false;
  const int want=static_cast<int>(std::min(n-at,size_t(1024)));
  const int sent=esp_http_client_write(c,buf+at,want);
  if(sent<=0||sent>want)return false;
  at+=static_cast<size_t>(sent);
 }
 return true;
}
bool send_pcm(esp_http_client_handle_t c,std::span<const int16_t> samples,
              LiveIoGate& gate){
 std::array<char,1024> block{};
 size_t at=0;
 while(at<samples.size()){
  if(!gate.allowed(static_cast<uint64_t>(monotonic_ms())))return false;
  const size_t count=std::min(block.size()/2,samples.size()-at);
  for(size_t i=0;i<count;++i){
   const auto v=static_cast<uint16_t>(samples[at+i]);
   block[2*i]=static_cast<char>(v&0xffU);
   block[2*i+1]=static_cast<char>(v>>8);
  }
  const bool success=send_exact(c,block.data(),count*2,gate);
  std::fill(block.begin(),block.end(),'\0');
  if(!success)return false;
  at+=count;
 }
 return true;
}
}  // namespace
const char* K151HttpsVoicePort::compiled_link_marker(){
 return "OpenAI fixed-host TLS/HTTP adapter linked; no connection at startup";
}
bool K151HttpsVoicePort::post_once(
 const Request& req,std::string_view api_key,
 const std::function<bool()>& live_network_ready,
 const std::atomic_bool& owner,const std::atomic_bool& stop,
 const std::function<bool()>& paid_stage_permit, Reply& out) const {
 out={};
 if(!live_network_ready||!live_network_ready()||!owner.load()||stop.load()||
    !secret_safe(api_key)||!paid_stage_permit||
    std::time(nullptr)<kEarliestTrustedEpoch)return false;
 std::string body;
 std::optional<httpwire::MultipartPlan> multipart;
 switch(req.endpoint){
  case httpwire::Endpoint::transcription:
   if(!req.text.empty()||!req.voice.empty())return false;
   multipart=httpwire::transcription_body(req.model,req.pcm24k.size());
   if(!multipart)return false;
   break;
  case httpwire::Endpoint::responses:{
   if(!req.pcm24k.empty()||!req.voice.empty())return false;
   auto json=httpwire::responses_body(req.model,req.text);
   if(!json)return false;
   body=std::move(*json);break;
  }
  case httpwire::Endpoint::speech:{
   if(!req.pcm24k.empty())return false;
   auto json=httpwire::speech_body(req.model,req.voice,req.text);
   if(!json)return false;
   body=std::move(*json);break;
  }
  default:return false;
 }
 const size_t size=multipart?multipart->length:body.size();
 if(size==0||size>INT_MAX)return false;
 const int64_t start=monotonic_ms();
 if(start<0||start>INT64_MAX-kStageMs)return false;
 const int64_t until=start+kStageMs;
 LiveIoGate gate(live_network_ready,owner,stop,static_cast<uint64_t>(until));
 if(!gate.allowed(static_cast<uint64_t>(start)))return false;
 // A stage may have reached the server even if later I/O fails:
 // consume exactly once BEFORE opening a socket, never retry or refund.
 if(!paid_stage_permit())return false;
 Headers headers;
 esp_http_client_config_t cfg={};
 cfg.host=kHost;
 cfg.path=httpwire::path(req.endpoint);
 cfg.port=443;
 cfg.method=HTTP_METHOD_POST;
 cfg.transport_type=HTTP_TRANSPORT_OVER_SSL;
 cfg.crt_bundle_attach=esp_crt_bundle_attach;
 cfg.skip_cert_common_name_check=false;
 cfg.disable_auto_redirect=true;
 cfg.max_authorization_retries=-1;
 cfg.keep_alive_enable=false;
 cfg.timeout_ms=kIoTimeoutMs;
 cfg.event_handler=on_header;
 cfg.user_data=&headers;
 Client c{esp_http_client_init(&cfg)};
 if(!c.ptr)return false;
 std::array<char,230> auth{};
 constexpr std::string_view prefix="Bearer ";
 std::copy(prefix.begin(),prefix.end(),auth.begin());
 std::copy(api_key.begin(),api_key.end(),auth.begin()+prefix.size());
 const bool authorized=esp_http_client_set_header(c.ptr,"Authorization",auth.data())==ESP_OK;
 std::fill(auth.begin(),auth.end(),'\0');
 if(!authorized||esp_http_client_set_header(c.ptr,"Content-Type",
      multipart?multipart->content_type.c_str():"application/json")!=ESP_OK||
    esp_http_client_set_header(c.ptr,"Accept",
      req.endpoint==httpwire::Endpoint::speech?
        "application/octet-stream":"application/json")!=ESP_OK)return false;
 if(!gate.allowed(static_cast<uint64_t>(monotonic_ms()))||
    esp_http_client_open(c.ptr,static_cast<int>(size))!=ESP_OK)return false;
 if(multipart){
  if(!send_exact(c.ptr,multipart->prefix.data(),multipart->prefix.size(),gate)||
     !send_exact(c.ptr,reinterpret_cast<const char*>(multipart->wav.data()),
                 multipart->wav.size(),gate)||
     !send_pcm(c.ptr,req.pcm24k,gate)||
     !send_exact(c.ptr,multipart->suffix.data(),multipart->suffix.size(),gate))
    return false;
 }else if(!send_exact(c.ptr,body.data(),body.size(),gate))return false;
 int64_t declared;
 do {
  if(!gate.allowed(static_cast<uint64_t>(monotonic_ms())))return false;
  // ESP-IDF retains the parser and connection after a receive timeout.
  declared=esp_http_client_fetch_headers(c.ptr);
 } while(declared==-ESP_ERR_HTTP_EAGAIN);
 if(declared<0||headers.duplicate||esp_http_client_get_status_code(c.ptr)!=200||
    esp_http_client_get_transport_type(c.ptr)!=HTTP_TRANSPORT_OVER_SSL)return false;
 const bool chunked=esp_http_client_is_chunked_response(c.ptr);
 std::optional<size_t> length;
 if(!chunked&&declared>0)length=static_cast<size_t>(declared);
 httpwire::BoundedReply receiver(req.endpoint);
 if(!receiver.begin(200,headers.media,length,chunked))return false;
 std::array<char,1024> chunk{};
 for(;;){
  if(!gate.allowed(static_cast<uint64_t>(monotonic_ms())))return false;
  const int count=esp_http_client_read(c.ptr,chunk.data(),chunk.size());
  if(count==-ESP_ERR_HTTP_EAGAIN)continue;
  if(count<0||count>static_cast<int>(chunk.size()))return false;
  if(count==0)break;
  if(!receiver.append(std::span<const uint8_t>(
        reinterpret_cast<const uint8_t*>(chunk.data()),static_cast<size_t>(count))))return false;
 }
 if(!gate.allowed(static_cast<uint64_t>(monotonic_ms()))||
    !receiver.finish(esp_http_client_is_complete_data_received(c.ptr)))return false;
 out.body=receiver.take_bytes();
 out.received_ms=static_cast<uint64_t>(monotonic_ms());
 return true;
}
}  // namespace stackchan::standalone
