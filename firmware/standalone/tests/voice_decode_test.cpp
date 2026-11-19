// Offline cJSON response-schema fixture, no HTTP requests.
#include "k151_voice_decode.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <vector>
using stackchan::standalone::K151VoiceDecoder;
static std::span<const uint8_t> bytes(const std::string& text){
 return {reinterpret_cast<const uint8_t*>(text.data()),text.size()};
}
int main(){
 std::string answer;
 assert(K151VoiceDecoder::transcription(bytes(R"({"text":"안녕하세요"})"),answer));
 assert(answer=="안녕하세요");
 assert(!K151VoiceDecoder::transcription(bytes(R"({"text":"a","text":"b"})"),answer));
 assert(!K151VoiceDecoder::transcription(bytes(R"({"text":"abc\u0000bad"})"),answer));
 assert(!K151VoiceDecoder::transcription(bytes(R"({"text":5})"),answer));
 assert(!K151VoiceDecoder::transcription(bytes(R"({"text":"ok","error":{"code":"bad"}})"),answer));
 assert(K151VoiceDecoder::response_text(bytes(R"({"status":"completed","error":null,"output":[{"type":"reasoning","summary":[]},{"type":"message","role":"assistant","content":[{"type":"output_text","text":"안녕"},{"type":"output_text","text":"하세요"}]}]})"),answer));
 assert(answer=="안녕하세요");
 assert(!K151VoiceDecoder::response_text(bytes(R"({"status":"incomplete","output":[]})"),answer));
 assert(!K151VoiceDecoder::response_text(bytes(R"({"status":"completed","output":[{"type":"function_call","name":"danger"}]})"),answer));
 assert(!K151VoiceDecoder::response_text(bytes(R"({"status":"completed","status":"completed","output":[]})"),answer));
 assert(!K151VoiceDecoder::response_text(bytes(R"({"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"refusal","refusal":"no"}]}]})"),answer));
 std::vector<int16_t> pcm;
 std::array<uint8_t,4> sample{0,128,255,127};
 assert(K151VoiceDecoder::speech_pcm(sample,pcm));
 assert(pcm.size()==2&&pcm[0]==-32768&&pcm[1]==32767);
 const std::array<uint8_t,3> odd{1,2,3};
 assert(!K151VoiceDecoder::speech_pcm(odd,pcm)&&pcm.empty());
 std::cout<<"cJSON response decoding PASS\n";
}
