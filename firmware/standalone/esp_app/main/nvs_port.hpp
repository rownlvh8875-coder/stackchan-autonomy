// SPDX-License-Identifier: MIT
#pragma once
#include "persistent_store.hpp"
#include <array>
#include <atomic>

namespace stackchan::standalone {

// Scoped solely to the new 'sc_gpt' namespace. Never imports manufacturer
// namespaces or invokes nvs_flash_erase() under any circumstances.
// NVS writes require an explicit local confirmation; no USB opcode can arm it.
class IsolatedNvs : public AtomicKv {
 public:
  static constexpr std::string_view kTrialCheckpointKey = "trial_ckpt";
  IsolatedNvs() = default;
  // Live device-local latches for budget initialization and durable charging.
  // All flags must outlive this store. The profile approval is separate.
  IsolatedNvs(const std::atomic_bool& owner, const std::atomic_bool& paid_consent,
              const std::atomic_bool& budget_writes, const std::atomic_bool& stop,
              bool reboot_trial = false)
      : owner_(&owner), paid_consent_(&paid_consent),
        budget_writes_(&budget_writes), stop_(&stop), reboot_trial_(reboot_trial) {}
  // Called only by the standalone app, after a later installation decision.
  bool init_without_erase();
  ReadValue read(std::string_view key, size_t max_bytes) override;
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override;
  void set_local_write_approval(bool enabled) { approved_ = enabled; }

 private:
  bool write_authorized(std::string_view key) const;
  bool trial_checkpoint(std::string_view key) const {
    return reboot_trial_ && key == kTrialCheckpointKey;
  }
  const std::atomic_bool* owner_ = nullptr;
  const std::atomic_bool* paid_consent_ = nullptr;
  const std::atomic_bool* budget_writes_ = nullptr;
  const std::atomic_bool* stop_ = nullptr;
  bool reboot_trial_ = false;
  bool initialized_ = false;
  bool approved_ = false;
};

// Owner-task-only store for the single authenticated ciphertext envelope.
// The caller admits writes after local setup and budget review.
class K151SavedOwnerNvs final : public AtomicKv {
 public:
  explicit K151SavedOwnerNvs(const std::atomic_bool& stop) : stop_(stop) {}
  ReadValue read(std::string_view key, size_t max_bytes) override;
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override;

 private:
  const std::atomic_bool& stop_;
  bool initialized_ = false;
};

class K151OwnerCodeNvs final : public AtomicKv {
 public:
  using Salt = std::array<uint8_t, 16>;
  explicit K151OwnerCodeNvs(const std::atomic_bool& stop) : stop_(stop) {}
  ReadCode inspect();
  bool prepare_salt(const Salt& salt);
  const Salt& salt() const { return salt_; }
  bool has_salt() const { return salt_ready_; }
  ReadValue read(std::string_view key, size_t max_bytes) override;
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override;

 private:
  ReadValue envelope();
  const std::atomic_bool& stop_;
  Salt salt_{};
  ReadCode initial_ = ReadCode::failure;
  bool initialized_ = false;
  bool salt_ready_ = false;
};

}  // namespace stackchan::standalone
