// SPDX-License-Identifier: MIT
#include "k151_voice_decode.hpp"
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
}  // namespace stackchan::standalone
