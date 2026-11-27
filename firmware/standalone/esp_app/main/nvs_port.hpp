// SPDX-License-Identifier: MIT
#pragma once
#include "persistent_store.hpp"
#include <atomic>

namespace stackchan::standalone {

// Scoped solely to the new 'sc_gpt' namespace. Never imports manufacturer
// namespaces or invokes nvs_flash_erase() under any circumstances.
// NVS writes require an explicit local confirmation; no USB opcode can arm it.
class IsolatedNvs : public AtomicKv {
 public:
  IsolatedNvs() = default;
  // Live device-local latches for budget initialization and durable charging.
  // All flags must outlive this store. The profile approval is separate.
  IsolatedNvs(const std::atomic_bool& owner, const std::atomic_bool& paid_consent,
              const std::atomic_bool& budget_writes, const std::atomic_bool& stop)
      : owner_(&owner), paid_consent_(&paid_consent),
        budget_writes_(&budget_writes), stop_(&stop) {}
  // Called only by the standalone app, after a later installation decision.
  bool init_without_erase();
  ReadValue read(std::string_view key, size_t max_bytes) override;
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override;
  void set_local_write_approval(bool enabled) { approved_ = enabled; }

 private:
  bool write_authorized(std::string_view key) const;
  const std::atomic_bool* owner_ = nullptr;
  const std::atomic_bool* paid_consent_ = nullptr;
  const std::atomic_bool* budget_writes_ = nullptr;
  const std::atomic_bool* stop_ = nullptr;
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

}  // namespace stackchan::standalone
