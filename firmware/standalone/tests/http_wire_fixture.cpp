// Generate actual wire requests for a 127.0.0.1-only fake HTTP service.
#include "openai_http_wire.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <string>
using namespace stackchan::standalone::httpwire;
int main(int argc,char** argv){
 if(argc!=2)return 2;
 const std::string prefix(argv[1]);
 auto multipart=transcription_body("gpt-4o-transcribe",2400);
 auto response=responses_body("gpt-test","안녕하세요, 테스트");
 auto speech=speech_body("tts-1","alloy","로컬 테스트 답변");
 if(!multipart||!response||!speech)return 1;
 std::ofstream stt(prefix+"/stt.bin",std::ios::binary);
 stt.write(multipart->prefix.data(),multipart->prefix.size());
 stt.write(reinterpret_cast<const char*>(multipart->wav.data()),multipart->wav.size());
 std::array<char,4800> audio{};
 for(size_t i=0;i<audio.size();i+=2){audio[i]=static_cast<char>(0x80);audio[i+1]=0;}
 stt.write(audio.data(),audio.size());
 stt.write(multipart->suffix.data(),multipart->suffix.size());
 std::ofstream a(prefix+"/responses.json",std::ios::binary);
 std::ofstream b(prefix+"/speech.json",std::ios::binary);
 a.write(response->data(),response->size());
 b.write(speech->data(),speech->size());
 if(!stt||!a||!b)return 3;
 std::cout<<multipart->content_type<<"\n"<<multipart->length<<"\n";
}
