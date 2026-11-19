// SPDX-License-Identifier: MIT
// Portable safety core for a proposed K151 standalone GPT firmware.
// Host-verified only: not an ESP32 application or an installation image.
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <optional>
#include <span>
#include <utility>
#include <vector>

namespace stackchan::standalone {

// CRC is an integrity check, not USB authentication. The physical USB port is
// the trust boundary. Do not log packet contents (Wi-Fi/API secrets).
inline uint32_t crc32(std::span<const uint8_t> bytes) {
  uint32_t crc = 0xffffffffU;
  for (const uint8_t octet : bytes) {
    crc ^= octet;
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1U) ^ ((crc & 1U) ? 0xedb88320U : 0U);
    }
  }
  return ~crc;
}

inline void put16(std::vector<uint8_t>& dst, uint16_t v) {
  dst.push_back(static_cast<uint8_t>(v));
  dst.push_back(static_cast<uint8_t>(v >> 8));
}
inline void put32(std::vector<uint8_t>& dst, uint32_t v) {
  for (unsigned i = 0; i < 4; ++i) dst.push_back(static_cast<uint8_t>(v >> (8U * i)));
}
inline void put64(std::vector<uint8_t>& dst, uint64_t v) {
  for (unsigned i = 0; i < 8; ++i) dst.push_back(static_cast<uint8_t>(v >> (8U * i)));
}
inline uint16_t get16(std::span<const uint8_t> src, size_t i) {
  return static_cast<uint16_t>(src[i] | (static_cast<uint16_t>(src[i + 1]) << 8U));
}
inline uint32_t get32(std::span<const uint8_t> src, size_t i) {
  uint32_t v = 0;
  for (unsigned n = 0; n < 4; ++n) v |= static_cast<uint32_t>(src[i + n]) << (8U * n);
  return v;
}
inline uint64_t get64(std::span<const uint8_t> src, size_t i) {
  uint64_t v = 0;
  for (unsigned n = 0; n < 8; ++n) v |= static_cast<uint64_t>(src[i + n]) << (8U * n);
  return v;
}

enum class Op : uint8_t {
  status = 1, stop = 2, configure = 3, enroll_begin = 4,
  enroll_features = 5, enroll_commit = 6, cloud_enable = 7,
};
inline bool valid_op(uint8_t code) { return code >= 1 && code <= 7; }

struct Frame {
  Op op;
  uint32_t nonce;
  uint16_t sequence;
  std::vector<uint8_t> payload;
};

// SCFG v1: magic(4), version(1), opcode(1), payload_len(2), nonce(4),
// sequence(2), payload, CRC32(4). No raw PCM/upload opcode exists.
inline std::optional<std::vector<uint8_t>> encode_frame(const Frame& f) {
  if (!valid_op(static_cast<uint8_t>(f.op)) || f.nonce == 0 || f.payload.size() > 8192) return std::nullopt;
  if (f.op == Op::enroll_features && f.payload.size() > 4096) return std::nullopt;
  if ((f.op == Op::status || f.op == Op::stop) && !f.payload.empty()) return std::nullopt;
  std::vector<uint8_t> out{'S','C','F','G',1,static_cast<uint8_t>(f.op)};
  put16(out, static_cast<uint16_t>(f.payload.size()));
  put32(out, f.nonce);
  put16(out, f.sequence);
  out.insert(out.end(), f.payload.begin(), f.payload.end());
  put32(out, crc32(out));
  return out;
}
inline std::optional<Frame> decode_frame(std::span<const uint8_t> bytes) {
  if (bytes.size() < 18 || bytes.size() > 8210 || bytes[0] != 'S' ||
      bytes[1] != 'C' || bytes[2] != 'F' || bytes[3] != 'G' ||
      bytes[4] != 1 || !valid_op(bytes[5])) return std::nullopt;
  const size_t payload_size = get16(bytes, 6);
  if (payload_size > 8192 || bytes.size() != 18 + payload_size ||
      get32(bytes, 8) == 0 || get32(bytes, bytes.size() - 4) !=
      crc32(bytes.first(bytes.size() - 4))) return std::nullopt;
  const Op op = static_cast<Op>(bytes[5]);
  if ((op == Op::status || op == Op::stop) && payload_size != 0) return std::nullopt;
  if (op == Op::enroll_features && payload_size > 4096) return std::nullopt;
  return Frame{op, get32(bytes, 8), get16(bytes, 12),
               std::vector<uint8_t>(bytes.begin() + 14, bytes.end() - 4)};
}

// Feature-blob chunks only; no raw audio support. The caller must validate
// schema/version/template sizes before committing this blob to NVS.
class FeatureAssembly {
 public:
  bool begin(uint32_t nonce, size_t total) {
    abort();
    if (nonce == 0 || total == 0 || total > 4096) return false;
    nonce_ = nonce;
    total_ = total;
    active_ = true;
    return true;
  }
  bool append(uint32_t nonce, uint16_t sequence, std::span<const uint8_t> chunk) {
    if (!active_ || nonce != nonce_ || sequence != sequence_ ||
        chunk.empty() || chunk.size() > 4096 || chunk.size() > total_ - data_.size()) {
      abort();
      return false;
    }
    data_.insert(data_.end(), chunk.begin(), chunk.end());
    ++sequence_;
    return true;
  }
  std::optional<std::vector<uint8_t>> finish(uint32_t nonce, size_t length, uint32_t checksum) {
    if (!active_ || nonce != nonce_ || length != total_ || data_.size() != total_ ||
        crc32(data_) != checksum) {
      abort();
      return std::nullopt;
    }
    active_ = false;
    nonce_ = 0;
    sequence_ = 0;
    total_ = 0;
    return std::exchange(data_, {});
  }
  void abort() {
    std::fill(data_.begin(), data_.end(), 0U);
    data_.clear();
    active_ = false;
    nonce_ = 0;
    sequence_ = 0;
    total_ = 0;
  }
 private:
  uint32_t nonce_ = 0;
  size_t total_ = 0;
  uint16_t sequence_ = 0;
  bool active_ = false;
  std::vector<uint8_t> data_;
};

// Each reservation permanently accounts for one conversation and its three
// potential paid requests. Persistence MUST be atomic and durable before send.
// Never interpret an absent/corrupt NVS ledger as a valid restored ledger.
class BudgetLedger {
 public:
  // Only call fresh() during the explicit first-install provisioning path.
  static BudgetLedger fresh() { return BudgetLedger{}; }

  static std::optional<BudgetLedger> restore(std::span<const uint8_t> bytes) {
    if (bytes.size() < 18 || bytes.size() > 818 || bytes[0] != 'B' ||
        bytes[1] != 'U' || bytes[2] != 'D' || bytes[3] != '1' || bytes[4] != 1) return std::nullopt;
    const size_t count = bytes[5];
    if (count > 100 || bytes.size() != 18 + count * 8 ||
        get32(bytes, bytes.size() - 4) != crc32(bytes.first(bytes.size() - 4))) return std::nullopt;
    BudgetLedger ledger;
    ledger.last_ = get64(bytes, 6);
    uint64_t previous = 0;
    for (size_t i = 0; i < count; ++i) {
      const uint64_t t = get64(bytes, 14 + i * 8);
      if (t == 0 || (i != 0 && t < previous) || t > ledger.last_) return std::nullopt;
      ledger.events_.push_back(t);
      previous = t;
    }
    if (count == 0 && ledger.last_ != 0) return std::nullopt;
    return ledger;
  }

  using Commit = std::function<bool(std::span<const uint8_t>)>;
  bool reserve(uint64_t epoch_seconds, bool trusted_clock, const Commit& persist) {
    // A valid SNTP epoch is a caller precondition; time rollback fails closed.
    if (faulted_ || !trusted_clock || epoch_seconds < 1'600'000'000ULL ||
        epoch_seconds < last_ || !persist) return false;
    std::vector<uint64_t> recent;
    size_t minute = 0, hour = 0;
    for (const uint64_t t : events_) {
      if (t > epoch_seconds) return false;
      const uint64_t age = epoch_seconds - t;
      if (age < 86400) {
        recent.push_back(t);
        if (age < 3600) ++hour;
        if (age < 60) ++minute;
      }
    }
    if (minute >= 2 || hour >= 30 || recent.size() >= 100) return false;
    recent.push_back(epoch_seconds);
    BudgetLedger proposal;
    proposal.events_ = std::move(recent);
    proposal.last_ = epoch_seconds;
    const std::vector<uint8_t> wire = proposal.serialize();
    if (!persist(wire)) {
      faulted_ = true;  // Ambiguous NVS result: block until independent durable reload.
      return false;
    }
    *this = std::move(proposal);
    return true;
  }
  std::vector<uint8_t> serialize() const {
    std::vector<uint8_t> out{'B','U','D','1',1,static_cast<uint8_t>(events_.size())};
    put64(out, last_);
    for (uint64_t t : events_) put64(out, t);
    put32(out, crc32(out));
    return out;
  }
  size_t count() const { return events_.size(); }
  bool faulted() const { return faulted_; }
 private:
  uint64_t last_ = 0;
  std::vector<uint64_t> events_;
  bool faulted_ = false;
};

enum class State : uint8_t {
  setup_required, enroll_required, wake_wait, ready, record, transcribe,
  think, synthesize, play, cooldown, stopped, error,
};

// All callbacks carry the wake epoch. STOP, timeout and error advance the
// epoch to make late HTTP/audio responses inert. No implicit retry/restart.
class Session {
 public:
  void boot(uint64_t now, bool configured, bool enrolled) {
    configured_ = configured;
    enrolled_ = enrolled;
    cloud_enabled_ = false;  // Paid calls require explicit owner enable.
    ++epoch_;
    last_ms_ = now;
    state_ = !configured_ ? State::setup_required :
             !enrolled_ ? State::enroll_required : State::wake_wait;
  }
  void cloud_enable(bool enabled) { cloud_enabled_ = enabled; }
  State state() const { return state_; }
  uint64_t epoch() const { return epoch_; }

  std::optional<uint64_t> wake(uint64_t now) {
    if (!check(now) || state_ != State::wake_wait) return std::nullopt;
    ++epoch_;
    state_ = State::ready;
    deadline_ = safe_add(now, 5000);
    return epoch_;
  }
  bool speech_started(uint64_t now, uint64_t epoch) {
    if (!check(now) || !matches(epoch, State::ready)) return false;
    state_ = State::record;
    deadline_ = safe_add(now, 8000);
    return true;
  }
  bool recorded(uint64_t now, uint64_t epoch, bool valid_audio,
                bool budget_committed, bool trusted_clock) {
    if (!check(now) || !matches(epoch, State::record)) return false;
    if (!valid_audio) { cooldown(now); return false; }
    if (!cloud_enabled_ || !budget_committed || !trusted_clock) { fail(); return false; }
    overall_deadline_ = safe_add(now, 90000);
    stage(State::transcribe, now);
    return true;
  }
  bool transcribed(uint64_t now, uint64_t epoch, bool valid_response) {
    return advance(now, epoch, State::transcribe, State::think, valid_response);
  }
  bool thought(uint64_t now, uint64_t epoch, bool valid_response) {
    return advance(now, epoch, State::think, State::synthesize, valid_response);
  }
  bool synthesized(uint64_t now, uint64_t epoch, bool valid_pcm) {
    return advance(now, epoch, State::synthesize, State::play, valid_pcm);
  }
  bool played(uint64_t now, uint64_t epoch, bool fully_played) {
    if (!check(now) || !matches(epoch, State::play)) return false;
    if (!fully_played) { fail(); return false; }
    cooldown(now);
    return true;
  }
  void stop() { ++epoch_; state_ = State::stopped; deadline_ = 0; }
  bool resume(uint64_t now) {
    if (state_ != State::stopped || now < last_ms_) return false;
    ++epoch_;
    last_ms_ = now;
    state_ = !configured_ ? State::setup_required :
             !enrolled_ ? State::enroll_required : State::wake_wait;
    return true;
  }
  void tick(uint64_t now) { (void)check(now); }
 private:
  static uint64_t safe_add(uint64_t now, uint64_t duration) {
    return now > std::numeric_limits<uint64_t>::max() - duration ?
           std::numeric_limits<uint64_t>::max() : now + duration;
  }
  bool matches(uint64_t epoch, State expected) const { return epoch == epoch_ && state_ == expected; }
  bool check(uint64_t now) {
    if (now < last_ms_) { fail(); return false; }
    last_ms_ = now;
    if (state_ == State::ready && now >= deadline_) { cooldown(now); return false; }
    if ((state_ == State::record || state_ == State::transcribe ||
         state_ == State::think || state_ == State::synthesize ||
         state_ == State::play) && now >= deadline_) { fail(); return false; }
    if (state_ == State::cooldown && now >= deadline_) state_ = State::wake_wait;
    return true;
  }
  void fail() { ++epoch_; state_ = State::error; deadline_ = 0; }
  void cooldown(uint64_t now) { state_ = State::cooldown; deadline_ = safe_add(now, 500); }
  void stage(State new_state, uint64_t now) {
    state_ = new_state;
    const uint64_t stage_limit = new_state == State::play ? 25000 : 30000;
    deadline_ = std::min(safe_add(now, stage_limit), overall_deadline_);
  }
  bool advance(uint64_t now, uint64_t epoch, State from, State to, bool okay) {
    if (!check(now) || !matches(epoch, from)) return false;
    if (!okay) { fail(); return false; }
    stage(to, now);
    return true;
  }
  State state_ = State::setup_required;
  bool configured_ = false;
  bool enrolled_ = false;
  bool cloud_enabled_ = false;
  uint64_t epoch_ = 0;
  uint64_t last_ms_ = 0;
  uint64_t deadline_ = 0;
  uint64_t overall_deadline_ = 0;
};

}  // namespace stackchan::standalone
