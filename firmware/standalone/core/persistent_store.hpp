// SPDX-License-Identifier: MIT
// Storage boundary for K151 standalone enrollment and pre-charged API budgets.
// This layer contains no ESP-IDF, network, USB, erase or motor operations.
#pragma once

#include "wake_features.hpp"

#include <algorithm>
#include <cstdint>
#include <optional>
#include <span>
#include <string_view>
#include <utility>
#include <vector>

namespace stackchan::standalone {

enum class ReadCode { found, missing, failure };
struct ReadValue {
  ReadCode code = ReadCode::failure;
  std::vector<uint8_t> bytes;
};

// A commit is one key-value replacement in an isolated namespace. Its
// implementation must report uncertainty as failure; it must NEVER erase or
// format NVS to recover from an error.
class AtomicKv {
 public:
  virtual ~AtomicKv() = default;
  virtual ReadValue read(std::string_view key, size_t max_bytes) = 0;
  virtual bool commit(std::string_view key, std::span<const uint8_t> bytes) = 0;
};

enum class ProfileLoad { valid, missing, invalid_or_io };

class PersistentGuard {
 public:
  explicit PersistentGuard(AtomicKv& store) : store_(store) {}

  // A corrupt/missing ledger is never silently treated as an empty ledger.
  // An explicit, separately authorized FIRST provisioning operation may set
  // up the ledger. A missing profile merely means enrollment is needed.
  ProfileLoad restore_profile() {
    const auto result = store_.read(kProfileKey, 2507);
    if (result.code == ReadCode::missing) { profile_.reset(); return ProfileLoad::missing; }
    if (result.code != ReadCode::found ||
        !decode_wake_profile(result.bytes).has_value()) {
      fatal_ = true;
      profile_.reset();
      return ProfileLoad::invalid_or_io;
    }
    profile_ = std::move(result.bytes);
    return ProfileLoad::valid;
  }

  bool restore_budget() {
    auto result = store_.read(kBudgetKey, 818);
    if (result.code != ReadCode::found) { fatal_ = true; return false; }
    auto restored = BudgetLedger::restore(result.bytes);
    if (!restored) { fatal_ = true; return false; }
    budget_ = std::move(*restored);
    return true;
  }

  // Not a normal boot operation. Must only be reached by verified, explicitly
  // approved local provisioning and only once while the ledger is ABSENT.
  bool provision_budget(bool local_owner_consent) {
    if (fatal_ || !local_owner_consent || budget_) return false;
    const ReadValue existing = store_.read(kBudgetKey, 818);
    if (existing.code != ReadCode::missing) {
      if (existing.code == ReadCode::failure) fatal_ = true;
      return false;
    }
    BudgetLedger fresh = BudgetLedger::fresh();
    auto wire = fresh.serialize();
    if (!verified_commit(kBudgetKey, wire)) return false;
    budget_ = std::move(fresh);
    return true;
  }

  // Always checked against the profile schema before NVS writes. The sole
  // authorization source is the local owner UI/controller, NOT a USB opcode.
  bool save_profile(std::span<const uint8_t> bytes, bool local_owner_consent) {
    if (fatal_ || !local_owner_consent || !decode_wake_profile(bytes)) return false;
    if (!verified_commit(kProfileKey, bytes)) return false;
    profile_ = std::vector<uint8_t>(bytes.begin(), bytes.end());
    return true;
  }

  // Caller must check SNTP, trusted epoch and paid-request owner consent.
  // The first remote request is forbidden until NVS commit and read-back pass.
  bool reserve(uint64_t epoch, bool trusted_clock, bool paid_owner_consent) {
    if (fatal_ || !paid_owner_consent || !budget_) return false;
    const bool ok = budget_->reserve(epoch, trusted_clock, [this](std::span<const uint8_t> wire) {
      return verified_commit(kBudgetKey, wire);
    });
    if (budget_->faulted()) fatal_ = true;
    return ok && !fatal_;
  }

  bool has_profile() const { return profile_.has_value(); }
  bool has_budget() const { return budget_.has_value(); }
  bool fatal() const { return fatal_; }
  size_t reserved_conversations() const { return budget_ ? budget_->count() : 0; }
  bool may_transmit(bool paid_owner_consent, bool trusted_clock) const {
    return !fatal_ && budget_ && profile_ && paid_owner_consent && trusted_clock;
  }

 private:
  bool verified_commit(std::string_view key, std::span<const uint8_t> wire) {
    if (fatal_) return false;
    // Any write/commit/read-back ambiguity permanently latches failure.
    if (!store_.commit(key, wire)) { fatal_ = true; return false; }
    ReadValue check = store_.read(key, wire.size());
    if (check.code != ReadCode::found ||
        !std::equal(check.bytes.begin(), check.bytes.end(), wire.begin(), wire.end())) {
      fatal_ = true;
      return false;
    }
    return true;
  }
  static constexpr std::string_view kProfileKey = "wake_profile";
  static constexpr std::string_view kBudgetKey = "budget";
  AtomicKv& store_;
  std::optional<std::vector<uint8_t>> profile_;
  std::optional<BudgetLedger> budget_;
  bool fatal_ = false;
};

}  // namespace stackchan::standalone
