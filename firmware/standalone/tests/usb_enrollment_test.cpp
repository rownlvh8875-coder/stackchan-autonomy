// SPDX-License-Identifier: MIT
#include "usb_enrollment.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

std::vector<uint8_t> start_payload(std::span<const uint8_t> blob) {
  std::vector<uint8_t> p;
  put16(p,static_cast<uint16_t>(blob.size()));
  put32(p,crc32(blob));
  return p;
}

int main() {
  WakeProfile profile;
  profile.limit_q8=512;
  profile.templates.emplace_back();
  for (size_t i=0;i<kWakeBytes;++i) {
    profile.templates[0].quantized[i]=static_cast<int8_t>(i%70);
  }
  auto profile_blob=encode_wake_profile(profile);
  assert(profile_blob && decode_wake_profile(*profile_blob));
  auto ack=encode_ack(Ack{Op::enroll_begin,AckCode::busy,State::enroll_required,0x1234,7});
  assert(decode_ack(ack) && decode_ack(ack)->code==AckCode::busy);
  ack[9]^=1;
  assert(!decode_ack(ack));

  ScfgStreamReader reader;
  const auto packet=encode_frame(Frame{Op::enroll_begin,123,0,start_payload(*profile_blob)});
  assert(packet);
  std::optional<Frame> decoded;
  for (size_t i=0;i<packet->size();++i) {
    decoded=reader.push((*packet)[i],100+i);
    if (i+1<packet->size()) assert(!decoded);
  }
  assert(decoded && decoded->op==Op::enroll_begin && reader.buffered()==0);
  const auto golden=encode_frame(Frame{Op::enroll_begin,0x01020304,0,{1,0,2,0,0,0}});
  const std::array<uint8_t,24> expected_golden{
      0x53,0x43,0x46,0x47,0x01,0x04,0x06,0x00,0x04,0x03,0x02,0x01,
      0x00,0x00,0x01,0x00,0x02,0x00,0x00,0x00,0xc5,0x5f,0xd0,0x66};
  assert(golden && std::equal(golden->begin(),golden->end(),expected_golden.begin()));
  assert(!reader.push('S',1000));
  assert(reader.buffered()==1);
  assert(!reader.push('C',4001)); // expired half frame
  assert(reader.buffered()==0);
  for (uint8_t byte : *packet) decoded=reader.push(byte,5000);
  assert(decoded && reader.buffered()==0);
  const Frame valid_begin=*decoded;
  auto malformed=*packet;
  malformed.back()^=1;
  for (uint8_t byte : malformed) decoded=reader.push(byte,5500);
  assert(!decoded && reader.buffered()==0);

  std::vector<uint8_t> saved;
  size_t store_calls=0;
  EnrollmentServer server([&](std::span<const uint8_t> blob) {
    ++store_calls;
    saved.assign(blob.begin(),blob.end());
    return true;
  });
  assert(server.handle(valid_begin).code==AckCode::denied); // not armed
  server.arm_enrollment(true);
  assert(server.handle(valid_begin).code==AckCode::ok);
  assert(server.handle(valid_begin).code==AckCode::busy); // no restart of live registration
  assert(server.handle(Frame{Op::status,777,0,{}}).code==AckCode::ok);
  assert(server.active());
  assert(!server.enrolled());
  const auto first=std::span<const uint8_t>(*profile_blob).first(400);
  const auto rest=std::span<const uint8_t>(*profile_blob).subspan(400);
  assert(server.handle(Frame{Op::enroll_features,123,0,{first.begin(),first.end()}}).code==AckCode::ok);
  assert(server.handle(Frame{Op::enroll_features,123,1,{rest.begin(),rest.end()}}).code==AckCode::ok);
  assert(server.handle(Frame{Op::enroll_commit,123,2,{}}).code==AckCode::ok);
  assert(server.enrolled() && !server.active() && saved==*profile_blob && store_calls==1);
  assert(server.handle(Frame{Op::enroll_begin,123,0,start_payload(*profile_blob)}).code==AckCode::invalid);
  assert(server.handle(Frame{Op::cloud_enable,124,0,{1}}).code==AckCode::not_supported);
  assert(server.handle(Frame{Op::configure,125,0,{0x31}}).code==AckCode::not_supported);
  assert(server.handle(Frame{Op::stop,126,0,{}}).state==State::stopped);
  assert(server.handle(Frame{Op::enroll_begin,127,0,start_payload(*profile_blob)}).code==AckCode::denied);
  assert(server.handle(Frame{Op::status,128,0,{}}).state==State::stopped);

  EnrollmentServer wrong([](std::span<const uint8_t>){return true;});
  wrong.arm_enrollment(true);
  std::vector<uint8_t> raw(320,0);
  assert(wrong.handle(Frame{Op::enroll_begin,999,0,start_payload(raw)}).code==AckCode::ok);
  assert(wrong.handle(Frame{Op::enroll_features,999,0,raw}).code==AckCode::ok);
  assert(wrong.handle(Frame{Op::enroll_commit,999,1,{}}).code==AckCode::invalid_profile);
  assert(!wrong.enrolled()); // never store raw PCM as a valid wake profile
  assert(wrong.handle(Frame{Op::enroll_begin,1000,0,start_payload(*profile_blob)}).code==AckCode::ok);
  assert(wrong.handle(Frame{Op::enroll_features,1000,1,{1}}).code==AckCode::invalid); // sequence gap
  assert(!wrong.active());
  assert(wrong.handle(Frame{Op::enroll_begin,1002,0,start_payload(*profile_blob)}).code==AckCode::ok);
  assert(wrong.handle(Frame{Op::stop,1003,0,{}}).code==AckCode::ok);
  assert(!wrong.active() && !wrong.enrolled());

  EnrollmentServer failing([](std::span<const uint8_t>){return false;});
  failing.arm_enrollment(true);
  assert(failing.handle(Frame{Op::enroll_begin,2000,0,start_payload(*profile_blob)}).code==AckCode::ok);
  assert(failing.handle(Frame{Op::enroll_features,2000,0,*profile_blob}).code==AckCode::ok);
  assert(failing.handle(Frame{Op::enroll_commit,2000,1,{}}).code==AckCode::store_failed);
  assert(failing.faulted() && !failing.enrolled());
  assert(failing.handle(Frame{Op::enroll_begin,2001,0,start_payload(*profile_blob)}).code==AckCode::denied);
  assert(failing.handle(Frame{Op::stop,2002,0,{}}).code==AckCode::ok);

  std::cout << "usb enrollment: PASS (fragmented SCFG, status/STOP, profile validation, durable fail-closed)\n";
}
