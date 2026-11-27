// SPDX-License-Identifier: MIT
#pragma once

#include "nvs_port.hpp"
#include "owner_unlock.hpp"
#include <atomic>
#include <psa/crypto.h>

namespace stackchan::standalone {

// One attempt per boot. The instance outlives the asynchronous worker.
class K151OwnerCode final : public OwnerUnlockPort, private OwnerCredentialCipher {
 public:
  explicit K151OwnerCode(const std::atomic_bool& stop) : stop_(stop) {}
  static bool available();
  ReadCode inspect() override { return storage_.inspect(); }
  bool generate(std::span<char, kOwnerCodeLength> output) override;
  bool begin(OwnerCode code) override;
  State state() const override { return state_.load(); }
  SavedOwnerCredentials& credentials() override { return credentials_; }
  void cancel() override;

 private:
  bool seal(Plaintext plaintext, MutableRecord record) override;
  bool open(Record record, MutablePlaintext plaintext) override;
  bool clear_key();
  void derive();
  static void task(void* self);

  const std::atomic_bool& stop_;
  K151OwnerCodeNvs storage_{stop_};
  SavedOwnerCredentials credentials_{storage_, *this};
  std::atomic<State> state_{State::idle};
  std::array<char, kOwnerCodeLength> code_{};
  psa_key_id_t key_ = 0;
};

} // namespace stackchan::standalone
