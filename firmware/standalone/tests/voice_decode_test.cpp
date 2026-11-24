// Offline cJSON response-schema fixture, no HTTP requests.
#include "k151_voice_decode.hpp"
#include <cJSON.h>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string>
#include <vector>
using stackchan::standalone::K151VoiceDecoder;
using stackchan::standalone::K151RealtimeSpeechExchange;
void test_realtime_transport();
static std::span<const uint8_t> bytes(const std::string& text){
 return {reinterpret_cast<const uint8_t*>(text.data()),text.size()};
}

static void realtime_speech() {
 using Speech = K151RealtimeSpeechExchange;
 constexpr auto session = R"({"type":"session.created","session":{"type":"realtime"}})";
 constexpr auto conversation = R"({"event_id":"event_a","type":"conversation.created","conversation":{}})";
 constexpr auto response = R"({"type":"response.created","response":{"id":"resp_a","status":"in_progress","metadata":{"stackchan":"speech"},"audio":{"output":{"format":{"type":"audio/pcm","rate":24000}}}}})";
 constexpr auto delta = R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"AID/fw=="})";
 constexpr auto audio_done = R"({"type":"response.output_audio.done","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0})";
 constexpr auto done = R"({"type":"response.done","response":{"id":"resp_a","status":"completed","status_details":null}})";
 const auto begin = [&](Speech& speech) {
  assert(speech.take_pcm().empty());
  assert(speech.accept(bytes(session)) && speech.state() == Speech::State::ready);
  assert(speech.begin_response());
  assert(speech.accept(bytes(response)));
 };
 Speech speech;
 const auto request = Speech::response_request("marin", "답변 \"인용\"");
 assert(request && request->find(R"("type":"response.create")") != std::string::npos);
 auto* json = cJSON_Parse(request->c_str());
 assert(json);
 cJSON_Delete(json);
 assert(request->find(R"("conversation":"none")") != std::string::npos);
 assert(request->find(R"("rate":24000)") != std::string::npos);
 assert(request->find(R"(답변 \"인용\")") != std::string::npos);
 assert(request->find(R"("tool_choice":"none")") != std::string::npos);
 assert(!Speech::response_request("", "답변"));
 assert(!Speech::response_request("marin", std::string(301, 'a')));

 begin(speech);
 assert(speech.accept(bytes(R"({"type":"response.output_audio_transcript.delta","delta":"답변"})")));
 assert(speech.accept(bytes(delta)) && speech.take_pcm().empty());
 assert(speech.accept(bytes(audio_done)) && speech.take_pcm().empty());
 assert(speech.accept(bytes(done)) && speech.state() == Speech::State::complete);
 const std::vector<uint8_t> expected{0, 128, 255, 127};
 assert(speech.take_pcm() == expected && speech.take_pcm().empty());

 for (const auto invalid : {
     R"({"type":"response.output_audio.delta","response_id":"resp_b","item_id":"msg_a","output_index":0,"content_index":0,"delta":"AA=="})",
     R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"AB=="})",
     R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":1,"content_index":0,"delta":"AA=="})",
     R"({"type":"response.output_audio.done","response_id":"resp_a","item_id":"msg_b","output_index":0,"content_index":0})",
     R"({"type":"response.done","response":{"id":"resp_a","status":"incomplete"}})",
     R"({"type":"error"})", conversation, response, done}) {
  Speech failed;
  begin(failed);
  assert(failed.accept(bytes(delta)));
  assert(!failed.accept(bytes(invalid)) && failed.state() == Speech::State::failed);
  assert(!failed.accept(bytes(audio_done)) && failed.take_pcm().empty());
 }
 Speech premature;
 assert(!premature.begin_response());
 assert(!premature.accept(bytes(delta)) && premature.take_pcm().empty());
 Speech early_conversation;
 assert(!early_conversation.accept(bytes(conversation)));
 Speech duplicate_conversation;
 assert(duplicate_conversation.accept(bytes(session)));
 assert(duplicate_conversation.accept(bytes(conversation)));
 assert(duplicate_conversation.state() == Speech::State::ready);
 assert(duplicate_conversation.begin_response());
 assert(!duplicate_conversation.accept(bytes(conversation)));
 assert(duplicate_conversation.state() == Speech::State::failed);
 for (const auto invalid : {
     R"({"type":"conversation.created","conversation":[]})",
     R"({"type":"conversation.created","conversation":{"id":5}})",
     R"({"type":"conversation.created","conversation":{"object":"realtime.session"}})",
     R"({"type":"conversation.created","conversation":{"id":"a","id":"b"}})"}) {
  Speech failed;
  assert(failed.accept(bytes(session)) && failed.begin_response());
  assert(!failed.accept(bytes(invalid)) && failed.state() == Speech::State::failed);
  assert(failed.take_pcm().empty());
 }
 Speech too_large;
 begin(too_large);
 assert(!too_large.accept(bytes(std::string(Speech::kMaxEventBytes + 1, ' '))));
 Speech over_cap;
 begin(over_cap);
 const auto large_delta = std::string(
     R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":")")
     + std::string(30'000, 'A') + "\"}";
 for (int i = 0; i < 42; ++i) assert(over_cap.accept(bytes(large_delta)));
 assert(!over_cap.accept(bytes(large_delta)) && over_cap.take_pcm().empty());
 Speech odd;
 begin(odd);
 assert(odd.accept(bytes(R"({"type":"response.output_audio.delta","response_id":"resp_a","item_id":"msg_a","output_index":0,"content_index":0,"delta":"AA=="})")));
 assert(!odd.accept(bytes(audio_done)) && odd.take_pcm().empty());
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
 realtime_speech();
 test_realtime_transport();
 std::cout<<"cJSON response decoding PASS\n";
}
