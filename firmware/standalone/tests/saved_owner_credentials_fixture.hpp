// Host fixture. This transform must never be used as a cipher on device.
#pragma once

#include "saved_owner_credentials.hpp"
#include <cassert>
#include <functional>

struct MockOwnerRecords final : stackchan::standalone::AtomicKv {
  using ReadValue = stackchan::standalone::ReadValue;
  using ReadCode = stackchan::standalone::ReadCode;
  std::vector<uint8_t> data;
  bool fail_read = false, fail_commit = false, disagree_on_readback = false;
  unsigned reads = 0, commits = 0;
  std::function<void()> before_commit;

  ReadValue read(std::string_view key, size_t max) override {
    assert(key == stackchan::standalone::SavedOwnerCredentials::kKey);
    ++reads;
    if (fail_read || data.size() > max) return {};
    if (data.empty()) return {ReadCode::missing, {}};
    auto observed = data;
    if (disagree_on_readback) observed.back() ^= 1;
    return {ReadCode::found, std::move(observed)};
  }

  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    assert(key == stackchan::standalone::SavedOwnerCredentials::kKey);
    ++commits;
    if (before_commit) before_commit();
    if (fail_commit) return false;
    data.assign(bytes.begin(), bytes.end());
    return true;
  }
};

struct MockOwnerCipher final : stackchan::standalone::OwnerCredentialCipher {
  bool reject = false;
  std::atomic_bool* stop_on_open = nullptr;
  unsigned opens = 0, seals = 0;

  bool seal(Plaintext plaintext, MutableRecord record) override {
    ++seals;
    for (size_t i = 0; i < plaintext.size(); ++i)
      record[kNonceBytes + i] = plaintext[i] ^ 0xD3;
    record.back() = 0xA6;
    return !reject;
  }

  bool open(Record record, MutablePlaintext plaintext) override {
    ++opens;
    if (stop_on_open) stop_on_open->store(true);
    if (reject || record.back() != 0xA6) return false;
    for (size_t i = 0; i < plaintext.size(); ++i)
      plaintext[i] = record[kNonceBytes + i] ^ 0xD3;
    return true;
  }
};
