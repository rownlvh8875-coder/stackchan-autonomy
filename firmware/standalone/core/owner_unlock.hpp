// SPDX-License-Identifier: MIT
#pragma once

#include "saved_owner_credentials.hpp"
#include <array>
#include <span>
#include <string_view>

namespace stackchan::standalone {

inline constexpr std::string_view kOwnerCodeAlphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
inline constexpr size_t kOwnerCodeLength = 16;
using OwnerCode = std::span<const char, kOwnerCodeLength>;

class OwnerUnlockPort {
 public:
  enum class State { idle, deriving, ready, failed };
  virtual ~OwnerUnlockPort() = default;
  virtual ReadCode inspect() = 0;
  virtual bool generate(std::span<char, kOwnerCodeLength> output) = 0;
  virtual bool begin(OwnerCode code) = 0;
  virtual State state() const = 0;
  virtual SavedOwnerCredentials& credentials() = 0;
  virtual void cancel() = 0;
};

// Single-contact entry. No selected symbol is echoed. Presses must be released
// from the same key, and a pre-existing hold needs a fresh release first.
class OwnerCodeInput final {
 public:
  static constexpr int kLeft = 8, kTop = 51, kCellWidth = 38, kCellHeight = 37;
  static constexpr int kControlsY = 204;
  static constexpr int kBack = 32, kCancel = 33, kConfirm = 34;
  ~OwnerCodeInput() { clear(); }
  OwnerCodeInput() = default;
  OwnerCodeInput(const OwnerCodeInput&) = delete;
  OwnerCodeInput& operator=(const OwnerCodeInput&) = delete;

  static int key_at(int x, int y, bool keypad, bool pending) {
    if (x < 0 || x >= 320 || y < 0 || y >= 240) return -1;
    if (y >= kControlsY) {
      if (x < 104) return keypad ? kBack : -1;
      if (x < 216) return kCancel;
      return pending ? -1 : kConfirm;
    }
    if (!keypad || x < kLeft || x >= kLeft + 8 * kCellWidth ||
        y < kTop || y >= kTop + 4 * kCellHeight) return -1;
    return 8 * ((y - kTop) / kCellHeight) + (x - kLeft) / kCellWidth;
  }

  int sample(unsigned count, int key) {
    if (count == 0) {
      const int released = selected_;
      reset_gesture(true);
      return released;
    }
    if (count != 1 || key < 0 || !armed_ || (selected_ >= 0 && selected_ != key)) {
      reset_gesture(false);
      return -1;
    }
    selected_ = key;
    return -1;
  }

  void edit(int key) {
    if (key == kBack && size_) text_[--size_] = '\0';
    if (key >= 0 && key < static_cast<int>(kOwnerCodeAlphabet.size()) && size_ < kOwnerCodeLength)
      text_[size_++] = kOwnerCodeAlphabet[static_cast<size_t>(key)];
  }
  void set_generated(OwnerCode code) {
    clear();
    std::copy(code.begin(), code.end(), text_.begin());
    size_ = kOwnerCodeLength;
  }
  bool full() const { return size_ == kOwnerCodeLength; }
  size_t size() const { return size_; }
  const char* text() const { return text_.data(); }
  OwnerCode code() const { return OwnerCode(text_.data(), kOwnerCodeLength); }
  void clear() {
    wipe_secret(reinterpret_cast<volatile unsigned char*>(text_.data()), text_.size());
    size_ = 0;
    reset_gesture(false);
  }

 private:
  void reset_gesture(bool armed) { armed_ = armed; selected_ = -1; }
  std::array<char, kOwnerCodeLength + 1> text_{};
  size_t size_ = 0;
  bool armed_ = false;
  int selected_ = -1;
};

} // namespace stackchan::standalone
