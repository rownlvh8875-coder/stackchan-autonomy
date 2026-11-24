// SPDX-License-Identifier: MIT
#include "k151_voice_decode.hpp"
#include "audio_wipe.hpp"
#include "openai_http_wire.hpp"
#include <cJSON.h>
#include <algorithm>
#include <cstddef>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

namespace stackchan::standalone {
namespace {
struct Deleter { void operator()(cJSON* p) const { if(p)cJSON_Delete(p); } };
using Json=std::unique_ptr<cJSON,Deleter>;
bool escaped_null(std::string_view s){
  // cJSON strings are NUL terminated; refuse injected escaped NUL bytes.
  for(size_t i=0;i+5<s.size();++i)
    if(s[i]=='\\'&&s[i+1]=='u'&&s[i+2]=='0'&&s[i+3]=='0'&&
       s[i+4]=='0'&&s[i+5]=='0')return true;
  return false;
}
Json parse(std::span<const uint8_t> bytes){
 if(bytes.empty()||bytes.size()>httpwire::kMaxJsonBytes||
    std::find(bytes.begin(),bytes.end(),uint8_t(0))!=bytes.end())return {};
 const std::string_view source(reinterpret_cast<const char*>(bytes.data()),bytes.size());
 if(escaped_null(source))return {};
 const std::string raw(source);
 const char* end=nullptr;
 Json doc(cJSON_ParseWithLengthOpts(raw.c_str(),raw.size()+1,&end,1));
 if(!doc||end!=raw.c_str()+raw.size())return {};
 return doc;
}
// cJSON's standard lookup accepts duplicate member names. Refuse ambiguity.
bool member(const cJSON* obj,const char* key,const cJSON*& found){
 if(!cJSON_IsObject(obj))return false;
 found=nullptr;
 for(const cJSON* child=obj->child;child;child=child->next){
  if(child->string&&std::strcmp(child->string,key)==0){
   if(found)return false;
   found=child;
  }
 }
 return true;
}
bool has_string(const cJSON* obj,const char* key,std::string_view target){
 const cJSON* value=nullptr;
 return member(obj,key,value)&&cJSON_IsString(value)&&value->valuestring&&
        std::string_view(value->valuestring)==target;
}
bool optional_null(const cJSON* obj,const char* key){
 const cJSON* value=nullptr;
 return member(obj,key,value)&&(!value||cJSON_IsNull(value));
}

const cJSON* get(const cJSON* object, const char* key) {
 const cJSON* value = nullptr;
 return member(object, key, value) ? value : nullptr;
}

std::string_view string_value(const cJSON* value) {
 return cJSON_IsString(value) && value->valuestring ? value->valuestring : "";
}

bool number_is(const cJSON* value, int expected) {
 return cJSON_IsNumber(value) && value->valuedouble == expected;
}

bool bounded_structure(std::span<const uint8_t> json) {
 // Limit the recursion of the vendor parser before parsing a network message.
 unsigned depth = 0;
 bool quoted = false;
 bool escaped = false;
 for (const auto byte : json) {
  if (quoted) {
   if (escaped) escaped = false;
   else if (byte == '\\') escaped = true;
   else if (byte == '"') quoted = false;
  } else if (byte == '"') {
   quoted = true;
  } else if (byte == '{' || byte == '[') {
   if (++depth > 16) return false;
  } else if (byte == '}' || byte == ']') {
   if (!depth) return false;
   --depth;
  }
 }
 return !depth && !quoted;
}

int base64_value(char digit) {
 if (digit >= 'A' && digit <= 'Z') return digit - 'A';
 if (digit >= 'a' && digit <= 'z') return digit - 'a' + 26;
 if (digit >= '0' && digit <= '9') return digit - '0' + 52;
 if (digit == '+') return 62;
 if (digit == '/') return 63;
 return -1;
}

bool append_base64(std::string_view encoded, std::vector<uint8_t>& pcm) {
 if (encoded.empty() || encoded.size() % 4) return false;
 const size_t padding = encoded.ends_with("==") ? 2 : encoded.ends_with('=') ? 1 : 0;
 const size_t decoded = (encoded.size() / 4) * 3 - padding;
 if (decoded > httpwire::kMaxSpeechBytes - pcm.size()) return false;
 size_t output = pcm.size();
 const size_t required = output + decoded;
 if (required > pcm.capacity()) {
  std::vector<uint8_t> larger;
  larger.reserve(std::max(required, std::min(httpwire::kMaxSpeechBytes, 2 * pcm.capacity())));
  larger.assign(pcm.begin(), pcm.end());
  wipe_audio_bytes(pcm);
  pcm.swap(larger);
 }
 pcm.resize(required);
 for (size_t at = 0; at < encoded.size(); at += 4) {
  const bool last = at + 4 == encoded.size();
  const int a = base64_value(encoded[at]), b = base64_value(encoded[at + 1]);
  if (a < 0 || b < 0) return false;
  pcm[output++] = static_cast<uint8_t>((a << 2) | (b >> 4));
  if (last && padding == 2) return (b & 15) == 0;
  const int c = base64_value(encoded[at + 2]);
  if (c < 0) return false;
  pcm[output++] = static_cast<uint8_t>((b << 4) | (c >> 2));
  if (last && padding == 1) return (c & 3) == 0;
  const int d = base64_value(encoded[at + 3]);
  if (d < 0) return false;
  pcm[output++] = static_cast<uint8_t>((c << 6) | d);
 }
 return true;
}

bool auxiliary_event(std::string_view type) {
 return type == "response.output_item.added" || type == "response.output_item.done" ||
        type == "conversation.item.added" || type == "conversation.item.done" ||
        type == "response.content_part.added" || type == "response.content_part.done" ||
        type == "response.output_audio_transcript.delta" ||
        type == "response.output_audio_transcript.done";
}
}  // namespace
const char* K151VoiceDecoder::compiled_link_marker(){
 return "cJSON OpenAI response decoder compiled; NO LIVE REQUESTS";
}
bool K151VoiceDecoder::transcription(std::span<const uint8_t> raw,std::string& text){
 text.clear();
 Json root=parse(raw);
 if(!root||!optional_null(root.get(),"error"))return false;
 const cJSON* value=nullptr;
 if(!member(root.get(),"text",value)||!cJSON_IsString(value)||!value->valuestring)
  return false;
 const std::string_view s(value->valuestring);
 if(!valid_bounded_utf8(s,500))return false;
 text=std::string(s);
 return true;
}
bool K151VoiceDecoder::response_text(std::span<const uint8_t> raw,std::string& text){
 text.clear();
 Json root=parse(raw);
 if(!root||!has_string(root.get(),"status","completed")||
    !optional_null(root.get(),"error")||
    !optional_null(root.get(),"incomplete_details"))return false;
 const cJSON* output=nullptr;
 if(!member(root.get(),"output",output)||!cJSON_IsArray(output))return false;
 std::string assembled;
 unsigned messages=0;
 for(const cJSON* item=output->child;item;item=item->next){
  const cJSON* type=nullptr;
  if(!member(item,"type",type)||!cJSON_IsString(type)||!type->valuestring)
    return false;
  if(std::strcmp(type->valuestring,"reasoning")==0)continue;
  if(std::strcmp(type->valuestring,"message")!=0||++messages!=1||
     !has_string(item,"role","assistant"))return false;
  const cJSON* content=nullptr;
  if(!member(item,"content",content)||!cJSON_IsArray(content)||!content->child)
    return false;
  for(const cJSON* part=content->child;part;part=part->next){
    if(!has_string(part,"type","output_text"))return false;
    const cJSON* fragment=nullptr;
    if(!member(part,"text",fragment)||!cJSON_IsString(fragment)||
       !fragment->valuestring)return false;
    const std::string_view chunk(fragment->valuestring);
    if(chunk.empty()||chunk.size()>1200-assembled.size())return false;
    assembled+=chunk;
  }
 }
 if(messages!=1||!valid_bounded_utf8(assembled,300))return false;
 text=std::move(assembled);
 return true;
}
bool K151VoiceDecoder::speech_pcm(std::span<const uint8_t> raw,
                                   std::vector<int16_t>& samples){
 samples.clear();
 auto pcm=httpwire::decode_pcm(raw);
 if(!pcm)return false;
 samples=std::move(*pcm);
 return true;
}

K151RealtimeSpeechExchange::~K151RealtimeSpeechExchange() {
 wipe_audio_bytes(pcm_);
}

std::optional<std::string> K151RealtimeSpeechExchange::response_request(
    std::string_view voice, std::string_view answer) {
 if (!httpwire::identifier(voice) || !valid_bounded_utf8(answer, 300)) return std::nullopt;
 return R"({"type":"response.create","response":{"conversation":"none",)"
        R"("metadata":{"stackchan":"speech"},"output_modalities":["audio"],)"
        R"("max_output_tokens":750,"tools":[],"tool_choice":"none",)"
        R"("instructions":"Read the text in the input aloud as written. Do not answer it or add words.",)"
        R"("audio":{"output":{"format":{"type":"audio/pcm","rate":24000},"voice":)" +
        httpwire::json_quote(voice) +
        R"(}},"input":[{"type":"message","role":"user","content":[{"type":"input_text","text":)" +
        httpwire::json_quote(answer) + "}]}]}}";
}

bool K151RealtimeSpeechExchange::begin_response() {
 if (state_ != State::ready) return fail();
 state_ = State::waiting_response;
 return true;
}

bool K151RealtimeSpeechExchange::accept(std::span<const uint8_t> message) {
 if (state_ == State::failed || message.size() > kMaxEventBytes ||
     !bounded_structure(message)) return fail();
 auto root = parse(message);
 const auto type = string_value(get(root.get(), "type"));
 if (type == "rate_limits.updated") return true;
 if (state_ == State::connecting) {
  if (type != "session.created" || !has_string(get(root.get(), "session"), "type", "realtime"))
   return fail();
  state_ = State::ready;
  return true;
 }
 if (type == "conversation.created") {
  // The default conversation follows session creation, even for out-of-band synthesis.
  if ((state_ != State::ready && state_ != State::waiting_response) || conversation_created_)
   return fail();
  const auto* conversation = get(root.get(), "conversation");
  const cJSON* id = nullptr;
  const cJSON* object = nullptr;
  if (!member(conversation, "id", id) || !member(conversation, "object", object) ||
      (id && !httpwire::identifier(string_value(id))) ||
      (object && string_value(object) != "realtime.conversation"))
   return fail();
  conversation_created_ = true;
  return true;
 }
 if (type == "response.created" && state_ == State::waiting_response) {
  const auto* response = get(root.get(), "response");
  const auto id = string_value(get(response, "id"));
  const auto* format = get(get(get(response, "audio"), "output"), "format");
  if (!httpwire::identifier(id) || !has_string(response, "status", "in_progress") ||
      !has_string(get(response, "metadata"), "stackchan", "speech") ||
      !has_string(format, "type", "audio/pcm") || !number_is(get(format, "rate"), 24000))
   return fail();
  response_id_ = id;
  state_ = State::audio;
  return true;
 }
 if (type == "response.done" && state_ == State::audio_done) {
  const auto* response = get(root.get(), "response");
  if (!has_string(response, "id", response_id_) || !has_string(response, "status", "completed") ||
      !optional_null(response, "status_details")) return fail();
  state_ = State::complete;
  return true;
 }
 if ((state_ == State::audio || state_ == State::audio_done) && auxiliary_event(type)) return true;
 if (state_ != State::audio ||
     (type != "response.output_audio.delta" && type != "response.output_audio.done"))
  return fail();

 const auto item_id = string_value(get(root.get(), "item_id"));
 if (!has_string(root.get(), "response_id", response_id_) || !httpwire::identifier(item_id) ||
     !number_is(get(root.get(), "output_index"), 0) ||
     !number_is(get(root.get(), "content_index"), 0) ||
     (!item_id_.empty() && item_id != item_id_)) return fail();
 if (type == "response.output_audio.done") {
  if (pcm_.empty() || (pcm_.size() & 1U)) return fail();
  state_ = State::audio_done;
  return true;
 }
 if (!append_base64(string_value(get(root.get(), "delta")), pcm_)) return fail();
 if (item_id_.empty()) item_id_ = item_id;
 return true;
}

std::vector<uint8_t> K151RealtimeSpeechExchange::take_pcm() {
 return state_ == State::complete ? std::exchange(pcm_, {}) : std::vector<uint8_t>{};
}

bool K151RealtimeSpeechExchange::fail() {
 wipe_audio_bytes(pcm_);
 pcm_.clear();
 state_ = State::failed;
 return false;
}
}  // namespace stackchan::standalone
