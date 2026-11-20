// Host-only, no serial/USB/cryptographic keys.
#include "scps_usb_wire.hpp"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

using namespace stackchan::standalone::scpswire;
static Frame round_trip(Op type,const std::vector<uint8_t>& payload) {
  auto wire=encode(type,payload);assert(wire);
  Reader reader;
  PushResult result;
  for(size_t i=0;i<wire->size();++i){
    result=reader.push((*wire)[i],100+i*2);
    assert(!result.fault);
    if(i+1<wire->size())assert(!result.frame);
  }
  assert(result.frame);
  assert(result.frame->kind==type && result.frame->payload==payload);
  assert(!reader.faulted());
  return *result.frame;
}
int main(){
  std::vector<uint8_t> hello(86,0xab);
  assert(round_trip(Op::device_hello,hello).payload==hello);
  assert(round_trip(Op::pc_hello,hello).payload==hello);
  std::vector<uint8_t> sealed(359,0xcc);
  assert(round_trip(Op::sealed_credentials,sealed).payload==sealed);
  for(Op kind:{Op::display_ready,Op::pending_touch,Op::completed,Op::denied,Op::stop}){
    assert(round_trip(kind,{}).payload.empty());
  }
  assert(!encode(Op::pc_hello,{}));
  assert(!encode(Op::sealed_credentials,std::vector<uint8_t>(34,0x31)));
  assert(!encode(Op::sealed_credentials,std::vector<uint8_t>(360,0x31)));
  assert(!encode(static_cast<Op>(255),{}));
  {
    auto blob=encode(Op::pc_hello,hello);assert(blob);
    (*blob)[12]^=0x01;
    assert(!decode(*blob));
    Reader reader;
    for(size_t i=0;i<blob->size();++i){
      auto r=reader.push((*blob)[i],i);
      if(i+1==blob->size())assert(r.fault&&!r.frame);
    }
    assert(reader.faulted());
    assert(reader.push('S',1000).fault);
  }
  {
    Reader reader;
    assert(reader.push('S',100).frame==std::nullopt);
    assert(!reader.tick(3100));
    assert(reader.faulted());
  }
  {
    Reader reader;
    assert(reader.push('S',100).frame==std::nullopt);
    assert(reader.push('C',99).fault);
  }
  {
    Reader reader;
    assert(reader.push('X',100).fault);
    auto blob=encode(Op::completed);assert(blob);
    for(auto c:*blob)assert(reader.push(c,101).fault);
  }
  {
    auto wire=encode(Op::completed);assert(wire);
    (*wire)[6]=0xff;(*wire)[7]=0xff;
    Reader reader;
    for(size_t i=0;i<8;++i){
      auto r=reader.push((*wire)[i],i);
      if(i==7)assert(r.fault);
    }
  }
  {
    auto wire=encode(Op::device_hello,hello);assert(wire);
    (*wire)[4]=2;
    assert(!decode(*wire));
  }
  std::cout<<"SCPS distinct bounded USB framing: PASS\n";
}
