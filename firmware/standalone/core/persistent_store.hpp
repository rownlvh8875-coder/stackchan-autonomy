// SPDX-License-Identifier: MIT
// Storage boundary for K151 standalone enrollment and pre-charged API budgets.
// This layer contains no ESP-IDF, network, USB, erase or motor operations.
#pragma once

#include "wake_features.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
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
// Calls are one-shot, ordered, and RAM-only. Reboot cannot resurrect a permit.
enum class PaidStage : uint8_t { transcribe = 0, respond = 1, synthesize = 2 };

enum class RebootTrialBoot { before_reboot, after_reboot };
struct RebootTrialScope {
  std::array<uint8_t, 32> id{};
  RebootTrialBoot boot = RebootTrialBoot::before_reboot;
};

class PersistentGuard {
 public:
  explicit PersistentGuard(AtomicKv& store, bool limit_to_one_paid_turn = false)
      : store_(store), limit_to_one_paid_turn_(limit_to_one_paid_turn) {}
  PersistentGuard(AtomicKv& store, RebootTrialScope scope)
      : store_(store), reboot_trial_(std::move(scope)) {}

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
    if (reboot_trial_) return false;
    if (load_budget() == ReadCode::found) return true;
    fatal_ = true;
    return false;
  }

  using BudgetBaselineCheck = std::function<bool(const ReadValue&)>;

  // Match the reviewed durable starting record before restoring or provisioning
  // a trial budget. A different record may mean the trial has already charged.
  bool restore_budget_for_setup(bool allow_first_provision,
                                const BudgetBaselineCheck& baseline = {}) {
    if (fatal_) return false;
    if (reboot_trial_) return restore_reboot_trial(allow_first_provision, baseline);
    if (budget_) return !baseline;
    const auto loaded = load_budget(baseline);
    return loaded == ReadCode::found ||
           (loaded == ReadCode::missing && provision_budget(allow_first_provision));
  }

  // Not a normal boot operation. Must only be reached by verified, explicitly
  // approved local provisioning and only once while the ledger is ABSENT.
  bool provision_budget(bool local_owner_consent) {
    if (fatal_ || reboot_trial_ || !local_owner_consent || budget_) return false;
    const ReadValue existing = store_.read(kBudgetKey, kBudgetMax);
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

  // Trusted local detector only; never a wire/cloud operation. This RAM-only
  // grant proves one builtin hit, not enrollment or a paid-request permit.
  bool admit_builtin_wake(uint64_t wake_epoch, bool local_owner, bool model_ready) {
    if (fatal_ || trial_stopped_ || !budget_ || !local_owner || !model_ready || !wake_epoch ||
        wake_epoch <= last_builtin_epoch_ || permit_active_) {
      cancel_permit();
      return false;
    }
    builtin_wake_epoch_ = wake_epoch;
    last_builtin_epoch_ = wake_epoch;
    return true;
  }

  // Caller must check SNTP, trusted epoch and paid-request owner consent.
  // The first remote request is forbidden until NVS commit and read-back pass.
  bool reserve(uint64_t epoch, bool trusted_clock, bool paid_owner_consent,
               uint64_t wake_epoch = 0) {
    const bool builtin = builtin_wake_epoch_ && *builtin_wake_epoch_ == wake_epoch;
    const bool mismatch = builtin_wake_epoch_ && !builtin;
    builtin_wake_epoch_.reset(); // Consumed even if a later gate refuses.
    if (mismatch || (wake_epoch && !profile_ && !builtin) || fatal_ ||
        !paid_owner_consent || !budget_ || permit_active_ || paid_trial_spent() ||
        (reboot_trial_ && (!builtin || trial_stopped_))) return false;
    const bool ok = budget_->reserve(epoch, trusted_clock, [this](std::span<const uint8_t> wire) {
      if (reboot_trial_) return write_trial_budget(claimed_phase(), trial_used_ + 1, wire);
      return verified_commit(kBudgetKey, wire);
    });
    if (budget_->faulted()) fatal_ = true;
    if (ok && !fatal_) {
      paid_trial_spent_ = limit_to_one_paid_turn_;
      if (reboot_trial_) ++trial_used_;
      permit_active_ = true;
      builtin_permit_ = builtin;
      next_step_ = 0;
    }
    return ok && !fatal_;
  }

  bool has_profile() const { return profile_.has_value(); }
  bool has_budget() const { return budget_.has_value(); }
  bool fatal() const { return fatal_; }
  // Independent of the rolling ledger window and not cleared by cancellation.
  bool paid_trial_spent() const {
    return reboot_trial_ ? trial_used_ >= (before_reboot() ? 1 : 3) : paid_trial_spent_;
  }
  // The caller observes the completed playback, standby and live consent.
  // The next boot still needs its own review of the exact prior budget.
  bool prepare_trial_reboot(bool verified_local_standby) {
    if (!reboot_trial_ || !before_reboot() || !verified_local_standby || fatal_ ||
        trial_stopped_ || reboot_prepared_ || trial_used_ != 1 ||
        !trial_stages_dispatched_ || permit_active_ || !budget_) return false;
    reboot_prepared_ = write_trial_budget(TrialPhase::reboot_ready, trial_used_,
                                         budget_->serialize());
    return reboot_prepared_;
  }
  size_t reserved_conversations() const { return budget_ ? budget_->count() : 0; }
  // Consume the permit BEFORE each outbound API send. Even if the HTTP
  // request times out, the same step cannot be authorized twice.
  bool authorize_step(PaidStage step, bool paid_owner_consent, bool trusted_clock) {
    if (fatal_ || !permit_active_ || !budget_ || (!profile_ && !builtin_permit_) ||
        !paid_owner_consent || !trusted_clock ||
        static_cast<unsigned>(step) != next_step_ || next_step_ >= 3) return false;
    ++next_step_;
    if (next_step_ == 3) {
      trial_stages_dispatched_ = reboot_trial_.has_value();
      permit_active_ = false;
      builtin_permit_ = false;
    }
    return true;
  }

  // STOP, error or timeout discards unused tokens without refund. The durable
  // conversation/3-request reservation remains charged after cancellation.
  void cancel_permit() {
    permit_active_ = false; next_step_ = 0;
    builtin_permit_ = false; builtin_wake_epoch_.reset();
  }
  void stop() {
    cancel_permit();
    if (reboot_trial_) trial_stopped_ = true;
  }
  bool permit_active() const { return permit_active_; }

 private:
  enum class TrialPhase : uint8_t { before_claimed = 1, reboot_ready, after_claimed };
  static constexpr std::array<uint8_t, 4> kTrialMagic{'B', 'T', 'R', '1'};
  static constexpr size_t kBudgetMax = 818;
  static constexpr size_t kTrialHeader = kTrialMagic.size() + 2 + RebootTrialScope{}.id.size();
  static constexpr size_t kTrialCrcBytes = 4;

  bool before_reboot() const { return reboot_trial_->boot == RebootTrialBoot::before_reboot; }
  TrialPhase claimed_phase() const {
    return before_reboot() ? TrialPhase::before_claimed : TrialPhase::after_claimed;
  }

  bool restore_reboot_trial(bool allow_first_provision, const BudgetBaselineCheck& baseline) {
    if (budget_ || trial_stopped_ || !baseline ||
        std::ranges::none_of(reboot_trial_->id, [](auto byte) { return byte != 0; })) return false;
    const ReadValue saved = store_.read(kBudgetKey, kTrialHeader + kBudgetMax + kTrialCrcBytes);
    std::optional<BudgetLedger> ledger;
    if (before_reboot()) {
      if (baseline(saved)) {
        if (saved.code == ReadCode::found) ledger = BudgetLedger::restore(saved.bytes);
        else if (allow_first_provision && saved.code == ReadCode::missing && saved.bytes.empty())
          ledger = BudgetLedger::fresh();
      }
    } else if (reboot_trial_->boot == RebootTrialBoot::after_reboot && !allow_first_provision) {
      ledger = read_trial_checkpoint(saved, baseline);
      if (ledger) trial_used_ = 1;
    }
    if (!ledger) {
      fatal_ = true;
      return false;
    }
    if (!write_trial_budget(claimed_phase(), trial_used_, ledger->serialize())) return false;
    budget_ = std::move(ledger);
    return true;
  }

  std::optional<BudgetLedger> read_trial_checkpoint(const ReadValue& saved,
                                                   const BudgetBaselineCheck& baseline) const {
    const std::span<const uint8_t> bytes = saved.bytes;
    if (saved.code != ReadCode::found || bytes.size() < kTrialHeader + kTrialCrcBytes ||
        bytes.size() > kTrialHeader + kBudgetMax + kTrialCrcBytes ||
        !std::ranges::equal(kTrialMagic, bytes.first(kTrialMagic.size())) ||
        bytes[4] != static_cast<uint8_t>(TrialPhase::reboot_ready) || bytes[5] != 1 ||
        !std::ranges::equal(reboot_trial_->id, bytes.subspan(6, reboot_trial_->id.size())) ||
        crc32(bytes.first(bytes.size() - kTrialCrcBytes)) !=
            get32(bytes, bytes.size() - kTrialCrcBytes)) return std::nullopt;
    const auto budget = bytes.subspan(kTrialHeader, bytes.size() - kTrialHeader - kTrialCrcBytes);
    const auto ledger = BudgetLedger::restore(budget);
    if (!ledger || !ledger->count() ||
        !baseline({ReadCode::found, {budget.begin(), budget.end()}})) return std::nullopt;
    return ledger;
  }

  bool write_trial_budget(TrialPhase phase, uint8_t used, std::span<const uint8_t> budget) {
    std::vector<uint8_t> record;
    record.reserve(kTrialHeader + budget.size() + kTrialCrcBytes);
    record.insert(record.end(), kTrialMagic.begin(), kTrialMagic.end());
    record.push_back(static_cast<uint8_t>(phase));
    record.push_back(used);
    record.insert(record.end(), reboot_trial_->id.begin(), reboot_trial_->id.end());
    record.insert(record.end(), budget.begin(), budget.end());
    put32(record, crc32(record));
    return verified_commit(kBudgetKey, record);
  }

  ReadCode load_budget(const BudgetBaselineCheck& baseline = {}) {
    const auto result = store_.read(kBudgetKey, kBudgetMax);
    if (baseline && !baseline(result)) {
      fatal_ = true;
      return ReadCode::failure;
    }
    if (result.code == ReadCode::missing) return ReadCode::missing;
    if (result.code == ReadCode::found) {
      if (auto restored = BudgetLedger::restore(result.bytes)) {
        budget_ = std::move(*restored);
        return ReadCode::found;
      }
    }
    fatal_ = true;
    return ReadCode::failure;
  }

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
  const bool limit_to_one_paid_turn_ = false;
  const std::optional<RebootTrialScope> reboot_trial_;
  std::optional<std::vector<uint8_t>> profile_;
  std::optional<BudgetLedger> budget_;
  bool fatal_ = false;
  bool paid_trial_spent_ = false;
  uint8_t trial_used_ = 0;
  bool reboot_prepared_ = false;
  bool trial_stopped_ = false;
  bool trial_stages_dispatched_ = false;
  bool permit_active_ = false;
  unsigned next_step_ = 0;
  std::optional<uint64_t> builtin_wake_epoch_;
  uint64_t last_builtin_epoch_ = 0;
  bool builtin_permit_ = false;
};

}  // namespace stackchan::standalone
