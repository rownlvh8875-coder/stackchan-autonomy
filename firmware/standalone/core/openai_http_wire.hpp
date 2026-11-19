// SPDX-License-Identifier: MIT
// Fixed-host OpenAI wire framing; portable, offline-testable, no sockets.
#pragma once
#include "offline_voice_cycle.hpp"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace stackchan::standalone::httpwire {
constexpr size_t kMaxRecordFrames = 8U*24000U;
constexpr size_t kMaxSpeechBytes = 20U*24000U*2U;
constexpr size_t kMaxJsonBytes = 256U*1024U;
constexpr std::string_view kBoundary = "K151SpeechBoundary20261119";
enum class Endpoint { transcription, responses, speech };
constexpr const char* path(Endpoint e) {
  switch(e) {
    case Endpoint::transcription: return "/v1/audio/transcriptions";
    case Endpoint::responses: return "/v1/responses";
    case Endpoint::speech: return "/v1/audio/speech";
  }
  return "";
}
constexpr size_t response_cap(Endpoint e) {
  return e==Endpoint::speech ? kMaxSpeechBytes : kMaxJsonBytes;
}
inline bool identifier(std::string_view s) {
  if(s.empty()||s.size()>64) return false;
  for(unsigned char c:s) {
    const bool letter=(c>='a'&&c<='z')||(c>='A'&&c<='Z');
    if(!letter && !(c>='0'&&c<='9') && c!='_' && c!='-' && c!='.')return false;
  }
  return true;
}
inline std::string json_quote(std::string_view s) {
  std::string out="\"";
  constexpr char hex[]="0123456789abcdef";
  for(unsigned char c:s) {
    switch(c) {
      case '"': out+="\\\""; break;
      case '\\': out+="\\\\"; break;
      case '\n': out+="\\n"; break;
      case '\r': out+="\\r"; break;
      case '\t': out+="\\t"; break;
      default:
        if(c<0x20){out+="\\u00";out.push_back(hex[c>>4]);out.push_back(hex[c&15]);}
        else out.push_back(static_cast<char>(c));
    }
  }
  out.push_back('"');
  return out;
}
inline std::optional<std::string> responses_body(std::string_view model,
                                                  std::string_view transcript) {
  if(!identifier(model)||!valid_bounded_utf8(transcript,500))return std::nullopt;
  const std::string body="{\"model\":"+json_quote(model)+
    ",\"input\":"+json_quote(transcript)+
    ",\"instructions\":"+json_quote("한국어로 짧고 정확하게 답해 주세요.")+
    ",\"max_output_tokens\":400,\"store\":false,\"stream\":false}";
  return body.size()<=4096 ? std::optional<std::string>(body) : std::nullopt;
}
inline std::optional<std::string> speech_body(std::string_view model,
                                                std::string_view voice,
                                                std::string_view text) {
  if(!identifier(model)||!identifier(voice)||!valid_bounded_utf8(text,300))
    return std::nullopt;
  const std::string body="{\"model\":"+json_quote(model)+
    ",\"voice\":"+json_quote(voice)+",\"input\":"+json_quote(text)+
    ",\"response_format\":\"pcm\",\"stream_format\":\"audio\"}";
  return body.size()<=4096 ? std::optional<std::string>(body) : std::nullopt;
}
inline void put16(std::array<uint8_t,44>& b,size_t at,uint16_t x){
  b[at]=static_cast<uint8_t>(x); b[at+1]=static_cast<uint8_t>(x>>8);
}
inline void put32(std::array<uint8_t,44>& b,size_t at,uint32_t x){
  for(size_t i=0;i<4;++i)b[at+i]=static_cast<uint8_t>(x>>(i*8));
}
inline std::array<uint8_t,44> wav_header(size_t frames){
  std::array<uint8_t,44> b{};
  auto tag=[&](size_t at, const char* s){for(size_t i=0;i<4;++i)b[at+i]=static_cast<uint8_t>(s[i]);};
  const auto data_bytes=static_cast<uint32_t>(frames*2);
  tag(0,"RIFF");put32(b,4,data_bytes+36);tag(8,"WAVE");
  tag(12,"fmt ");put32(b,16,16);put16(b,20,1);put16(b,22,1);
  put32(b,24,24000);put32(b,28,48000);put16(b,32,2);put16(b,34,16);
  tag(36,"data");put32(b,40,data_bytes);return b;
}
struct MultipartPlan {
  std::string prefix;
  std::string suffix;
  std::string content_type;
  std::array<uint8_t,44> wav{};
  size_t pcm_bytes=0;
  size_t length=0;
};
inline std::optional<MultipartPlan> transcription_body(std::string_view model,size_t frames){
  if(!identifier(model)||frames==0||frames>kMaxRecordFrames)return std::nullopt;
  MultipartPlan p;
  const std::string b(kBoundary);
  p.content_type="multipart/form-data; boundary="+b;
  p.prefix="--"+b+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"question.wav\"\r\nContent-Type: audio/wav\r\n\r\n";
  p.suffix="\r\n--"+b+"\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n"+
    std::string(model)+"\r\n--"+b+"\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nko\r\n--"+
    b+"\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n--"+b+"--\r\n";
  p.wav=wav_header(frames);
  p.pcm_bytes=frames*2;
  p.length=p.prefix.size()+p.wav.size()+p.pcm_bytes+p.suffix.size();
  return p;
}
inline bool media_prefix(std::string_view s, std::string_view type){
  if(s.size()<type.size())return false;
  for(size_t i=0;i<type.size();++i){
    char ch=s[i];if(ch>='A'&&ch<='Z')ch=static_cast<char>(ch-'A'+'a');
    if(ch!=type[i])return false;
  }
  return s.size()==type.size() || s[type.size()]==';';
}
class BoundedReply {
 public:
  explicit BoundedReply(Endpoint e):endpoint_(e){}
  bool begin(int status,std::string_view content_type,
             std::optional<size_t> declared,bool chunked){
    if(started_||status!=200||(!declared&&!chunked)||
       (declared&&(*declared==0||*declared>response_cap(endpoint_)))||
       !media_ok(content_type))return false;
    declared_=declared;started_=true;return true;
  }
  bool append(std::span<const uint8_t> part){
    if(!started_||failed_||finished_||part.size()>response_cap(endpoint_)-bytes_.size()||
      (declared_&&part.size()>*declared_-bytes_.size())){failed_=true;return false;}
    bytes_.insert(bytes_.end(),part.begin(),part.end());return true;
  }
  bool finish(bool complete_transport){
    if(!started_||failed_||finished_||!complete_transport||bytes_.empty()||
      (declared_&&bytes_.size()!=*declared_)||
      (endpoint_==Endpoint::speech&&(bytes_.size()&1U))){failed_=true;return false;}
    finished_=true;return true;
  }
  const std::vector<uint8_t>& data()const{return bytes_;}
  std::vector<uint8_t> take_bytes(){return finished_?std::move(bytes_):std::vector<uint8_t>{};}
 private:
  bool media_ok(std::string_view s)const{
    if(endpoint_!=Endpoint::speech)return media_prefix(s,"application/json");
    return media_prefix(s,"application/octet-stream")||media_prefix(s,"audio/pcm")||
           media_prefix(s,"audio/x-pcm");
  }
  Endpoint endpoint_;
  std::optional<size_t> declared_;
  std::vector<uint8_t> bytes_;
  bool started_=false,failed_=false,finished_=false;
};
inline std::optional<std::vector<int16_t>> decode_pcm(std::span<const uint8_t> b){
  if(b.empty()||b.size()>kMaxSpeechBytes||(b.size()&1U))return std::nullopt;
  std::vector<int16_t> out;out.reserve(b.size()/2);
  for(size_t i=0;i<b.size();i+=2){
    const uint16_t v=static_cast<uint16_t>(b[i])|
      (static_cast<uint16_t>(b[i+1])<<8);
    out.push_back(static_cast<int16_t>(v));
  }
  return out;
}
}  // namespace stackchan::standalone::httpwire
