// SPDX-License-Identifier: MIT
// SCPS USB framing, deliberately distinct from SCFG voice-feature enrollment.
// No raw credentials, sockets, serial device, display or hardware dependencies.
// CRC32 is error detection only, NOT authentication. SAS + AEAD are separate.
#pragma once
#include "standalone_core.hpp"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone::scpswire {
enum class Op : uint8_t {
  device_hello=1, pc_hello=2, sealed_credentials=3,
  display_ready=4, pending_touch=5, completed=6, denied=7, stop=8, local_setup_fault=9
};
// Advice from the device before credentials. These codes never advance setup.
enum class SetupFailure : uint8_t {
  clock_invalid=1, clock_backwards=2, sample_gap=3, sensor_read=4,
  head_input=5, usb_start=6, pairing_display=7
};
constexpr size_t kHeaderBytes=8, kCrcBytes=4;
constexpr size_t kHelloBytes=86, kMaxSealedBytes=359;
constexpr size_t kMaxPayload=kMaxSealedBytes;
constexpr size_t kMaxFrame=kHeaderBytes+kMaxPayload+kCrcBytes;
constexpr uint64_t kPartialTimeoutMs=3000;
constexpr std::array<uint8_t,4> kMagic{'S','C','P','W'};
inline bool valid(Op kind, size_t length) {
  switch(kind) {
    case Op::device_hello: case Op::pc_hello: return length==kHelloBytes;
    case Op::sealed_credentials: return length>=35 && length<=kMaxSealedBytes;
    case Op::local_setup_fault: return length==1;
    case Op::display_ready: case Op::pending_touch:
    case Op::completed: case Op::denied: case Op::stop: return length==0;
  }
  return false;
}
inline bool valid_setup_failure(uint8_t code) {
  return code>=static_cast<uint8_t>(SetupFailure::clock_invalid) &&
         code<=static_cast<uint8_t>(SetupFailure::pairing_display);
}
struct Frame { Op kind; std::vector<uint8_t> payload; };

inline std::optional<std::vector<uint8_t>> encode(
    Op kind,std::span<const uint8_t> payload={}) {
  if(!valid(kind,payload.size()))return std::nullopt;
  if(kind==Op::local_setup_fault && !valid_setup_failure(payload.front()))return std::nullopt;
  std::vector<uint8_t> wire{kMagic.begin(),kMagic.end()};
  wire.push_back(1);
  wire.push_back(static_cast<uint8_t>(kind));
  put16(wire,static_cast<uint16_t>(payload.size()));
  wire.insert(wire.end(),payload.begin(),payload.end());
  put32(wire,crc32(wire));
  return wire;
}
inline std::optional<Frame> decode(std::span<const uint8_t> wire) {
  if(wire.size()<kHeaderBytes+kCrcBytes||wire.size()>kMaxFrame ||
     !std::equal(kMagic.begin(),kMagic.end(),wire.begin()) ||
     wire[4]!=1 || wire[5]<1 || wire[5]>static_cast<uint8_t>(Op::local_setup_fault))return std::nullopt;
  const auto kind=static_cast<Op>(wire[5]);
  const size_t length=get16(wire,6);
  if(!valid(kind,length)||wire.size()!=kHeaderBytes+length+kCrcBytes ||
     get32(wire,kHeaderBytes+length)!=crc32(wire.first(kHeaderBytes+length)))
    return std::nullopt;
  if(kind==Op::local_setup_fault && !valid_setup_failure(wire[kHeaderBytes]))return std::nullopt;
  return Frame{kind,{wire.begin()+kHeaderBytes,wire.begin()+kHeaderBytes+length}};
}
struct PushResult {
  std::optional<Frame> frame;
  bool fault=false;
};

class Reader final {
 public:
  bool tick(uint64_t now) {
    if(fault_)return false;
    if(used_ && (now<start_ms_||now-start_ms_>=kPartialTimeoutMs))
      return fail();
    return true;
  }
  PushResult push(uint8_t octet,uint64_t now) {
    if(!tick(now))return {{},true};
    if(!used_)start_ms_=now;
    if(used_>=buffer_.size())return {{},!fail()};
    buffer_[used_++]=octet;
    if(used_<=kMagic.size() && octet!=kMagic[used_-1])
      return {{},!fail()};
    if(used_==5 && buffer_[4]!=1)return {{},!fail()};
    if(used_==6 && (buffer_[5]<1 || buffer_[5]>static_cast<uint8_t>(Op::local_setup_fault)))
      return {{},!fail()};
    if(used_==kHeaderBytes) {
      const size_t length=get16(buffer_,6);
      const auto op=static_cast<Op>(buffer_[5]);
      if(!valid(op,length))return {{},!fail()};
      expected_=kHeaderBytes+length+kCrcBytes;
      if(expected_>buffer_.size())return {{},!fail()};
    }
    if(expected_ && used_==expected_) {
      auto decoded=decode({buffer_.data(),used_});
      clear_buffer();
      if(!decoded)return {{},!fail()};
      return {std::move(decoded),false};
    }
    return {};
  }
  bool faulted() const { return fault_; }
  void invalidate() { (void)fail(); }
  ~Reader(){clear_buffer();}
 private:
  bool fail() {
    fault_=true;
    clear_buffer();
    return false;
  }
  void clear_buffer() {
    volatile uint8_t* ptr=buffer_.data();
    for(size_t i=0;i<buffer_.size();++i)ptr[i]=0;
    used_=expected_=0;
    start_ms_=0;
  }
  std::array<uint8_t,kMaxFrame> buffer_{};
  size_t used_=0,expected_=0;
  uint64_t start_ms_=0;
  bool fault_=false;
};
} // namespace stackchan::standalone::scpswire
