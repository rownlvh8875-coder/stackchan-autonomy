// Compile and execute a fully offline wire contract fixture.
#include "openai_http_wire.hpp"
#include <array>
#include <cassert>
#include <iostream>
#include <limits>
#include <string>
using namespace stackchan::standalone::httpwire;
static uint32_t le32(const std::array<uint8_t,44>& b,size_t p){
 return uint32_t(b[p])|(uint32_t(b[p+1])<<8)|(uint32_t(b[p+2])<<16)|(uint32_t(b[p+3])<<24);
}
int main(){
 auto x=transcription_body("gpt-4o-transcribe",2400);
 assert(x&&x->length==x->prefix.size()+44+4800+x->suffix.size());
 assert(le32(x->wav,24)==24000&&le32(x->wav,40)==4800&&le32(x->wav,4)==4836);
 assert(x->prefix.find("audio/wav")!=std::string::npos);
 assert(!transcription_body("bad\r\nHeader",2400));
 assert(!transcription_body("valid",0));
 assert(!transcription_body("valid",kMaxRecordFrames+1));
 auto r=responses_body("gpt-test","안녕 \"친구\"");
 assert(r&&r->find("\"store\":false")!=std::string::npos);
 assert(r->find("\\\"친구\\\"")!=std::string::npos);
 assert(!responses_body("bad\nmodel","valid"));
 assert(!responses_body("valid",std::string("\xed\xa0\x80",3)));
 auto s=speech_body("tts-1","alloy","반가워요");
 assert(s&&s->find("\"response_format\":\"pcm\"")!=std::string::npos);
 assert(!speech_body("tts-1","alloy",std::string(301,'a')));
 BoundedReply good(Endpoint::speech);
 assert(good.begin(200,"application/octet-stream",4,false));
 std::array<uint8_t,4> pcm{0,128,255,127};
 assert(good.append(pcm)&&good.finish(true));
 const auto decoded=decode_pcm(good.data());
 assert(decoded&&decoded->size()==2&&(*decoded)[0]==std::numeric_limits<int16_t>::min()&&(*decoded)[1]==32767);
 BoundedReply bad_status(Endpoint::speech);
 assert(!bad_status.begin(302,"application/octet-stream",4,false));
 BoundedReply wrong(Endpoint::speech);
 assert(!wrong.begin(200,"text/html",4,false));
 BoundedReply truncated(Endpoint::responses);
 assert(truncated.begin(200,"application/json; charset=utf-8",6,false));
 assert(truncated.append(pcm)&&!truncated.finish(true));
 BoundedReply chunked(Endpoint::responses);
 assert(chunked.begin(200,"application/json",std::nullopt,true));
 std::array<uint8_t,2> json{'{','}'};
 assert(chunked.append(json)&&!chunked.finish(false));
 BoundedReply complete(Endpoint::responses);
 assert(complete.begin(200,"application/json",std::nullopt,true));
 assert(complete.append(json)&&complete.finish(true));
 BoundedReply unknown(Endpoint::responses);
 assert(!unknown.begin(200,"application/json",std::nullopt,false));
 BoundedReply overrun(Endpoint::responses);
 assert(overrun.begin(200,"application/json",2,false));
 assert(!overrun.append(pcm));
 std::array<uint8_t,3> odd{1,2,3};
 assert(!decode_pcm(odd));
 std::cout<<"HTTP/WAV/JSON/PCM offline wire PASS\n";
}
