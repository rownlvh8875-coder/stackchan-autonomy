// SPDX-License-Identifier: MIT
// Portable, host-only SCFG USB enrollment receiver. No device, flash, or API I/O.
#pragma once

#include "wake_features.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

constexpr size_t kScfgFrameMax = 8210;
constexpr uint64_t kScfgFrameTimeoutMs = 2000;

enum class AckCode : uint8_t {
  ok = 0, invalid = 1, denied = 2, busy = 3,
  invalid_profile = 4, store_failed = 5, not_supported = 6,
};

struct Ack {
  Op op;
  AckCode code;
  State state;
  uint32_t nonce;
  uint16_t sequence;
};

// Fixed 18-byte SACK v1 reply, no payload, credentials, features, or raw audio.
inline std::array<uint8_t, 18> encode_ack(const Ack& reply) {
  std::array<uint8_t, 18> out{'S','A','C','K',1,static_cast<uint8_t>(reply.op),
      static_cast<uint8_t>(reply.code),static_cast<uint8_t>(reply.state)};
  for (size_t i = 0; i < 4; ++i) {
    out[8+i] = static_cast<uint8_t>(reply.nonce >> (i*8U));
  }
  out[12] = static_cast<uint8_t>(reply.sequence);
  out[13] = static_cast<uint8_t>(reply.sequence >> 8U);
  const uint32_t checksum = crc32(std::span<const uint8_t>(out).first(14));
  for (size_t i = 0; i < 4; ++i) {
    out[14+i] = static_cast<uint8_t>(checksum >> (i*8U));
  }
  return out;
}

inline std::optional<Ack> decode_ack(std::span<const uint8_t> data) {
  if (data.size()!=18 || data[0]!='S' || data[1]!='A' || data[2]!='C' ||
      data[3]!='K' || data[4]!=1 || !valid_op(data[5]) || data[6]>6 ||
      data[7]>static_cast<uint8_t>(State::error) ||
      crc32(data.first(14))!=get32(data,14)) return std::nullopt;
  return Ack{static_cast<Op>(data[5]),static_cast<AckCode>(data[6]),
             static_cast<State>(data[7]),get32(data,8),get16(data,12)};
}

// Bounded, fragmented USB stream decoder. Never guesses a complete packet.
// An unfinished packet expires; callers must process physical STOP separately.
class ScfgStreamReader {
 public:
  std::optional<Frame> push(uint8_t byte, uint64_t now_ms) {
    if (used_ && (now_ms < start_ms_ || now_ms-start_ms_ > kScfgFrameTimeoutMs)) reset();
    if (!used_) {
      if (byte != 'S') return std::nullopt;
      start_ms_ = now_ms;
    }
    buffer_[used_++] = byte;
    constexpr std::array<uint8_t,4> magic{'S','C','F','G'};
    if (used_<=4 && byte!=magic[used_-1]) { reset(); return std::nullopt; }
    if (used_==6 && (buffer_[4]!=1 || !valid_op(buffer_[5]))) {
      reset(); return std::nullopt;
    }
    if (used_==8) {
      const uint16_t payload_size = get16(std::span<const uint8_t>(buffer_),6);
      if (payload_size>8192 || (buffer_[5]==static_cast<uint8_t>(Op::enroll_features) &&
          payload_size>4096) ||
          ((buffer_[5]==static_cast<uint8_t>(Op::status) ||
            buffer_[5]==static_cast<uint8_t>(Op::stop)) && payload_size!=0)) {
        reset(); return std::nullopt;
      }
      expected_=18U+payload_size;
    }
    if (expected_ && used_==expected_) {
      const auto f = decode_frame(std::span<const uint8_t>(buffer_).first(used_));
      reset();
      return f;
    }
    return std::nullopt;
  }
  void reset() {
    std::fill(buffer_.begin(),buffer_.begin()+static_cast<std::ptrdiff_t>(used_),0U);
    used_=0; expected_=0; start_ms_=0;
  }
  size_t buffered() const { return used_; }
 private:
  std::array<uint8_t,kScfgFrameMax> buffer_{};
  size_t used_=0;
  size_t expected_=0;
  uint64_t start_ms_=0;
};

// The only supported write is an explicit *feature-profile* store. The NVS
// adapter is deliberately absent. The caller must commit the entire blob
// atomically to its isolated namespace and return false on any uncertainty.
class EnrollmentServer {
 public:
  using ProfileStore = std::function<bool(std::span<const uint8_t>)>;
  explicit EnrollmentServer(ProfileStore store) : store_(std::move(store)) {}

  // Invoked by a trusted local device-mode controller, NEVER by an SCFG opcode.
  void arm_enrollment(bool allowed) {
    if (stopped_ || fault_) return;
    if (!allowed) { assembly_.abort(); active_=false; }
    armed_=allowed;
  }
  bool enrolled() const { return enrolled_; }
  bool faulted() const { return fault_; }
  bool active() const { return active_; }

  Ack handle(const Frame& f) {
    Ack reply{f.op,AckCode::invalid,view_state(),f.nonce,f.sequence};
    if (!encode_frame(f)) return reply;
    if (f.op==Op::status) { reply.code=AckCode::ok; return reply; }
    if (f.op==Op::stop) {
      assembly_.abort();
      active_=false;
      stopped_=true;
      armed_=false;
      reply.code=AckCode::ok;
      reply.state=State::stopped;
      return reply;
    }
    if (stopped_ || fault_ || !armed_) {
      reply.code=AckCode::denied;
      reply.state=view_state();
      return reply;
    }
    switch (f.op) {
      case Op::enroll_begin: {
        if (active_) { reply.code=AckCode::busy; break; }
        if (f.sequence!=0 || f.payload.size()!=6 || f.nonce==completed_nonce_) break;
        const size_t total=get16(f.payload,0);
        if (!assembly_.begin(f.nonce,total)) break;
        expected_crc_=get32(f.payload,2);
        expected_len_=total;
        expected_seq_=0;
        active_=true;
        reply.code=AckCode::ok;
        break;
      }
      case Op::enroll_features: {
        if (!active_ || f.sequence!=expected_seq_ ||
            !assembly_.append(f.nonce,f.sequence,f.payload)) {
          assembly_.abort();
          active_=false;
          break;
        }
        ++expected_seq_;
        reply.code=AckCode::ok;
        break;
      }
      case Op::enroll_commit: {
        if (!active_ || f.sequence!=expected_seq_ || !f.payload.empty()) break;
        active_=false;
        auto blob=assembly_.finish(f.nonce,expected_len_,expected_crc_);
        if (!blob) break;
        const bool valid=decode_wake_profile(*blob).has_value();
        if (!valid) {
          reply.code=AckCode::invalid_profile;
        } else if (!store_ || !store_(*blob)) {
          fault_=true;
          reply.code=AckCode::store_failed;
        } else {
          enrolled_=true;
          completed_nonce_=f.nonce;
          reply.code=AckCode::ok;
        }
        std::fill(blob->begin(),blob->end(),0U);
        break;
      }
      default:
        reply.code=AckCode::not_supported; // configure/cloud never enabled here
        break;
    }
    reply.state=view_state();
    return reply;
  }

 private:
  State view_state() const {
    if (stopped_) return State::stopped;
    if (fault_) return State::error;
    return enrolled_ ? State::setup_required : State::enroll_required;
  }
  ProfileStore store_;
  FeatureAssembly assembly_;
  size_t expected_len_=0;
  uint32_t expected_crc_=0;
  uint32_t completed_nonce_=0;
  uint16_t expected_seq_=0;
  bool active_=false;
  bool armed_=false;
  bool enrolled_=false;
  bool stopped_=false;
  bool fault_=false;
};

} // namespace stackchan::standalone
