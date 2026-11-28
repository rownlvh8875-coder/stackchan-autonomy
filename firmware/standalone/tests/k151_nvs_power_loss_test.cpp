// SPDX-License-Identifier: MIT
// The pinned SDK's NVS storage against a four-sector RAM flash.
#include "nvs_storage.hpp"
#include "persistent_store.hpp"
#include "standalone_core.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <span>
#include <stdexcept>
#include <vector>

using stackchan::standalone::AtomicKv;
using stackchan::standalone::BudgetLedger;
using stackchan::standalone::PaidStage;
using stackchan::standalone::PersistentGuard;
using stackchan::standalone::ReadCode;
using stackchan::standalone::ReadValue;
using stackchan::standalone::RebootTrialBoot;
using stackchan::standalone::RebootTrialScope;

namespace {
constexpr size_t kSector = 4096;
constexpr size_t kSectors = 4;
using FlashBytes = std::array<uint8_t, kSectors * kSector>;
using SetupRecord = std::array<uint8_t, 371>;
enum class CutPattern { completed, first_half, interleaved_bits };
struct PowerLoss {
  bool incomplete;
  bool erase;
};

void require(bool ok, const char* step) {
  if (!ok) throw std::runtime_error(step);
}

class RamFlash final : public nvs::Partition {
 public:
  explicit RamFlash(const FlashBytes& input) : bytes(input) {}
  const char* get_partition_name() override { return "nvs"; }
  uint32_t get_address() override { return 0; }
  uint32_t get_size() override { return bytes.size(); }
  bool get_readonly() override { return false; }

  esp_err_t read_raw(size_t offset, void* dest, size_t size) override {
    if (!fits(offset, size)) return ESP_ERR_INVALID_SIZE;
    std::memcpy(dest, bytes.data() + offset, size);
    return ESP_OK;
  }
  esp_err_t read(size_t offset, void* dest, size_t size) override {
    return read_raw(offset, dest, size);
  }
  esp_err_t write_raw(size_t offset, const void* source, size_t size) override {
    if (!fits(offset, size)) return ESP_ERR_INVALID_SIZE;
    return flash_operation(offset, static_cast<const uint8_t*>(source), size);
  }
  esp_err_t write(size_t offset, const void* source, size_t size) override {
    return write_raw(offset, source, size);
  }
  esp_err_t erase_range(size_t offset, size_t size) override {
    if (offset % kSector || size % kSector || !fits(offset, size)) return ESP_ERR_INVALID_SIZE;
    return flash_operation(offset, nullptr, size);
  }

  FlashBytes bytes;
  size_t operations = 0;
  size_t cut_after = 0;
  CutPattern pattern = CutPattern::completed;

 private:
  bool fits(size_t offset, size_t size) const {
    return offset <= bytes.size() && size <= bytes.size() - offset;
  }
  esp_err_t flash_operation(size_t offset, const uint8_t* data, size_t size) {
    const bool interrupted = ++operations == cut_after;
    bool changed = false;
    bool changes_missing = false;
    for (size_t i = 0; i < size; ++i) {
      const uint8_t before = bytes[offset + i];
      const uint8_t intended = data ? before & data[i] : 0xff;
      uint8_t mask = 0xff;
      // Apply a subset of the requested NOR bit transitions on the interrupted operation.
      if (interrupted && pattern == CutPattern::first_half && i >= size / 2) mask = 0;
      if (interrupted && pattern == CutPattern::interleaved_bits) mask = i % 2 ? 0xaa : 0x55;
      const auto after = static_cast<uint8_t>(before ^ ((before ^ intended) & mask));
      changed |= after != before;
      changes_missing |= after != intended;
      bytes[offset + i] = after;
    }
    if (interrupted) throw PowerLoss{changed && changes_missing, data == nullptr};
    return ESP_OK;
  }
};

uint8_t ns(nvs::Storage& storage, const char* name, bool create = false) {
  uint8_t index{};
  require(storage.createOrOpenNamespace(name, create, index) == ESP_OK, "open namespace");
  return index;
}

bool write_blob(nvs::Storage& storage, uint8_t index, const char* key,
                std::span<const uint8_t> wire) {
  // NVS_READWRITE uses purgeAfterErase=false. The pinned SDK commits synchronously.
  return storage.writeItem(index, nvs::ItemType::BLOB, key, wire.data(), wire.size(), false) ==
         ESP_OK;
}

ReadValue read_blob(nvs::Storage& storage, const char* name, const char* key, size_t bound) {
  uint8_t index{};
  auto result = storage.createOrOpenNamespace(name, false, index);
  if (result == ESP_ERR_NVS_NOT_FOUND) return {ReadCode::missing, {}};
  if (result != ESP_OK) return {};
  size_t size{};
  result = storage.getItemDataSize(index, nvs::ItemType::BLOB, key, size);
  if (result == ESP_ERR_NVS_NOT_FOUND) return {ReadCode::missing, {}};
  if (result != ESP_OK || size > bound) return {};
  std::vector<uint8_t> wire(size);
  if (storage.readItem(index, nvs::ItemType::BLOB, key, wire.data(), wire.size()) != ESP_OK)
    return {};
  return {ReadCode::found, std::move(wire)};
}

class RebootBudget final : public AtomicKv {
 public:
  explicit RebootBudget(const ReadValue& budget) : budget_(budget) {}
  ReadValue read(std::string_view key, size_t max_bytes) override {
    if (key != "budget" || budget_.bytes.size() > max_bytes) return {};
    return budget_;
  }
  bool commit(std::string_view, std::span<const uint8_t>) override {
    require(false, "normal restart attempted to create or update a budget");
    return false;
  }

 private:
  const ReadValue& budget_;
};

struct CutTotals {
  size_t tested{};
  size_t partial_writes{};
  size_t partial_erases{};
};

struct Scenario {
  CutPattern pattern;
  const char* label;
  CutTotals totals{};
};

bool check_restart_guard(const ReadValue& observed) {
  RebootBudget store(observed);
  PersistentGuard guard(store);
  const bool restored = guard.restore_budget_for_setup(false);
  if (!restored)
    require(!guard.has_budget() && !guard.admit_builtin_wake(1, true, true) &&
                !guard.reserve(1'700'300'000, true, true),
            "unreadable budget admitted a new charge");
  require(!guard.authorize_step(PaidStage::transcribe, true, true),
          "reboot revived a paid request permit");
  return restored;
}

void check_cut(const FlashBytes& start, size_t cut, CutPattern pattern,
               const std::vector<uint8_t>& previous, const std::vector<uint8_t>& proposed,
               const SetupRecord& setup, CutTotals& totals) {
  RamFlash flash(start);
  flash.pattern = pattern;
  try {
    nvs::Storage storage(&flash);
    require(storage.init(0, kSectors) == ESP_OK, "mount before budget update");
    flash.cut_after = flash.operations + cut;
    (void)write_blob(storage, ns(storage, "sc_gpt"), "budget", proposed);
    require(false, "simulated power loss was not reached");
  } catch (const PowerLoss& loss) {
    flash.cut_after = 0;
    if (loss.incomplete && loss.erase) ++totals.partial_erases;
    if (loss.incomplete && !loss.erase) ++totals.partial_writes;
  }
  nvs::Storage reboot(&flash);
  require(reboot.init(0, kSectors) == ESP_OK, "mount after simulated power loss");
  const auto settings = read_blob(reboot, "sc_owner", "owner_cfg_v2", setup.size());
  require(settings.code == ReadCode::found && std::ranges::equal(settings.bytes, setup),
          "reboot changed stored setup");
  const auto observed = read_blob(reboot, "sc_gpt", "budget", 818);
  require(check_restart_guard(observed) &&
              (observed.bytes == previous || observed.bytes == proposed),
          "reboot failed to recover the prior or proposed budget");
  ++totals.tested;
}

void check_damaged_budget(const FlashBytes& start, std::vector<uint8_t> corrupt) {
  corrupt.back() ^= 1;  // NVS-level CRC stays valid, while the budget checksum fails.
  for (bool missing : {false, true}) {
    RamFlash flash(start);
    {
      nvs::Storage storage(&flash);
      require(storage.init(0, kSectors) == ESP_OK, "mount to prepare damaged budget");
      const auto index = ns(storage, "sc_gpt");
      if (missing)
        require(storage.eraseItem(index, "budget", false) == ESP_OK, "remove fixture budget");
      else
        require(write_blob(storage, index, "budget", corrupt), "write corrupt fixture budget");
    }
    nvs::Storage reboot(&flash);
    require(reboot.init(0, kSectors) == ESP_OK, "mount damaged budget fixture");
    const auto observed = read_blob(reboot, "sc_gpt", "budget", 818);
    require(observed.code == (missing ? ReadCode::missing : ReadCode::found),
            "unexpected damaged fixture read result");
    require(!check_restart_guard(observed), "normal boot accepted a damaged budget");
  }
  require(!check_restart_guard({ReadCode::failure, {}}), "normal boot accepted a read error");
}

class TrialStorage final : public AtomicKv {
 public:
  explicit TrialStorage(RamFlash& flash) : storage_(&flash) {
    require(storage_.init(0, kSectors) == ESP_OK, "mount reboot trial storage");
    index_ = ns(storage_, "sc_gpt");
  }

  ReadValue read(std::string_view key, size_t max_bytes) override {
    return read_blob(storage_, "sc_gpt", name(key), max_bytes);
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    return write_blob(storage_, index_, name(key), bytes);
  }

 private:
  static const char* name(std::string_view key) {
    require(key == "budget" || key == "trial_ckpt", "unexpected reboot trial key");
    return key == "budget" ? "budget" : "trial_ckpt";
  }
  nvs::Storage storage_;
  uint8_t index_{};
};

void check_trial_reboot_cuts(const FlashBytes& start, const BudgetLedger& ledger) {
  constexpr uint64_t epoch = 1'700'000'000 + 864 * 300;
  constexpr size_t record_bound = 1024;
  const RebootTrialScope before{{0x31}, RebootTrialBoot::before_reboot};
  const RebootTrialScope after{before.id, RebootTrialBoot::after_reboot};
  const auto baseline = ledger.serialize();
  auto charged = ledger;
  require(charged.reserve(epoch, true, [](auto) { return true; }), "compute trial reservation");
  const auto expected = charged.serialize();
  require(expected.size() == 818, "exercise maximum size wrapped trial budget");
  std::vector<uint8_t> checkpoint(before.id.begin(), before.id.end());
  checkpoint.insert(checkpoint.end(), expected.begin(), expected.end());
  std::vector<uint8_t> claimed_budget;

  const auto prepare = [&](RamFlash& flash, size_t cut) {
    TrialStorage store(flash);
    PersistentGuard guard(store, before);
    require(guard.restore_budget_for_setup(false, [&](const ReadValue& read) {
              return read.code == ReadCode::found && read.bytes == baseline;
            }) && guard.admit_builtin_wake(1, true, true) && guard.reserve(epoch, true, true, 1),
            "claim before reboot and reserve a trial turn");
    for (const auto stage : {PaidStage::transcribe, PaidStage::respond, PaidStage::synthesize})
      require(guard.authorize_step(stage, true, true), "dispatch mocked paid stage");
    claimed_budget = store.read("budget", record_bound).bytes;
    const auto began = flash.operations;
    flash.cut_after = cut ? began + cut : 0;
    require(guard.prepare_trial_reboot(true, [&](auto wire) {
              return std::ranges::equal(wire, expected) &&
                     store.read("trial_ckpt", record_bound).code == ReadCode::missing &&
                     store.commit("trial_ckpt", checkpoint) &&
                     store.read("trial_ckpt", record_bound).bytes == checkpoint;
            }), "prepare durable reboot checkpoint");
    return flash.operations - began;
  };
  const auto resume = [&](TrialStorage& store, bool eligible) {
    PersistentGuard guard(store, after);
    const bool restored = guard.restore_budget_for_setup(false, [&](const ReadValue& read) {
      const auto durable = store.read("trial_ckpt", record_bound);
      return read.code == ReadCode::found && read.bytes == expected &&
             durable.code == ReadCode::found && durable.bytes == checkpoint;
    });
    require(restored == eligible, "reboot admission does not match durable trial phase");
    require(!guard.authorize_step(PaidStage::transcribe, true, true), "reboot revived a paid permit");
    if (restored)
      require(guard.reserved_conversations() == charged.count(), "reboot changed reserved budget");
    else
      require(!guard.admit_builtin_wake(1, true, true) && !guard.reserve(epoch + 60, true, true),
              "unverified reboot admitted a new charge");
  };

  RamFlash ready(start);
  const auto prepare_ops = prepare(ready, 0);
  RamFlash claimed(ready.bytes);
  std::vector<uint8_t> ready_budget;
  std::vector<uint8_t> after_budget;
  size_t claim_ops;
  {
    TrialStorage store(claimed);
    ready_budget = store.read("budget", record_bound).bytes;
    const auto began = claimed.operations;
    resume(store, true);
    claim_ops = claimed.operations - began;
    after_budget = store.read("budget", record_bound).bytes;
    resume(store, false);
  }
  require(prepare_ops && claim_ops && !claimed_budget.empty() && !ready_budget.empty() &&
              !after_budget.empty() && claimed_budget != ready_budget && ready_budget != after_budget,
          "establish all three distinct durable trial phases");

  size_t cuts = 0;
  for (const auto pattern : {CutPattern::completed, CutPattern::first_half,
                             CutPattern::interleaved_bits}) {
    for (const bool preparing : {true, false}) {
      for (size_t cut = 1; cut <= (preparing ? prepare_ops : claim_ops); ++cut) {
        RamFlash flash(preparing ? start : ready.bytes);
        flash.pattern = pattern;
        try {
          if (preparing) {
            (void)prepare(flash, cut);
          } else {
            TrialStorage store(flash);
            flash.cut_after = flash.operations + cut;
            resume(store, true);
          }
          require(false, "reboot trial write interruption was not reached");
        } catch (const PowerLoss&) {
          flash.cut_after = 0;
        }
        TrialStorage reboot(flash);
        const auto budget = reboot.read("budget", record_bound);
        const auto durable = reboot.read("trial_ckpt", record_bound);
        require(budget.code == ReadCode::found &&
                    (budget.bytes == ready_budget ||
                     budget.bytes == (preparing ? claimed_budget : after_budget)),
                "power cut changed or lost a reserved trial budget");
        if (budget.bytes == ready_budget || !preparing)
          require(durable.code == ReadCode::found && durable.bytes == checkpoint,
                  "verified reboot phase lost its checkpoint");
        resume(reboot, budget.bytes == ready_budget);
        resume(reboot, false);
        ++cuts;
      }
    }
  }

  RamFlash mismatched(ready.bytes);
  TrialStorage bad_checkpoint(mismatched);
  auto incorrect = checkpoint;
  incorrect.back() ^= 1;
  require(bad_checkpoint.commit("trial_ckpt", incorrect), "write mismatched checkpoint fixture");
  resume(bad_checkpoint, false);
  require(bad_checkpoint.read("budget", record_bound).bytes == ready_budget,
          "checkpoint denial modified the trial budget");
  std::printf("K151 reboot trial: %zu modeled cuts in checkpoint publication and boot claim passed\n",
              cuts);
}
}  // namespace

int main() try {
  FlashBytes empty;
  empty.fill(0xff);
  RamFlash flash(empty);
  SetupRecord setup;
  setup.fill(0x5a);
  auto ledger = BudgetLedger::fresh();
  {
    nvs::Storage storage(&flash);
    require(storage.init(0, kSectors) == ESP_OK, "initialize NVS");
    require(write_blob(storage, ns(storage, "sc_gpt", true), "budget", ledger.serialize()),
            "write initial ledger");
    require(write_blob(storage, ns(storage, "sc_owner", true), "owner_cfg_v2", setup),
            "write synthetic setup");
  }
  std::array scenarios{
      Scenario{CutPattern::completed, "completed operation"},
      Scenario{CutPattern::first_half, "first half"},
      Scenario{CutPattern::interleaved_bits, "interleaved bits"},
  };
  for (size_t i = 0; i < 300; ++i) {
    const auto previous = ledger.serialize();
    FlashBytes start;
    size_t operations;
    {
      nvs::Storage storage(&flash);
      require(storage.init(0, kSectors) == ESP_OK, "reopen NVS");
      const auto index = ns(storage, "sc_gpt");
      require(read_blob(storage, "sc_gpt", "budget", 818).bytes == previous,
              "read prior committed budget");
      start = flash.bytes;
      const size_t before = flash.operations;
      require(ledger.reserve(1'700'000'000 + 864 * i, true, [&](auto wire) {
        return write_blob(storage, index, "budget", wire);
      }), "commit maximum-rate rolling ledger");
      operations = flash.operations - before;
    }
    const auto proposed = ledger.serialize();
    for (size_t cut = 1; cut <= operations; ++cut) {
      for (auto& scenario : scenarios) {
        try {
          check_cut(start, cut, scenario.pattern, previous, proposed, setup, scenario.totals);
        } catch (const std::runtime_error& error) {
          std::fprintf(stderr, "Budget update %zu, cut %zu, %s: %s\n",
                       i + 1, cut, scenario.label, error.what());
          return 1;
        }
      }
    }
  }
  const auto boundaries = scenarios.front().totals.tested;
  require(ledger.serialize().size() == 818 && boundaries > 3'000,
          "exercise full ledger and page reuse");
  check_damaged_budget(flash.bytes, ledger.serialize());
  check_trial_reboot_cuts(flash.bytes, ledger);
  std::printf("K151 NVS power-loss regression: %zu write/erase boundaries passed\n", boundaries);
  for (const auto& [pattern, label, totals] : scenarios) {
    if (pattern == CutPattern::completed) continue;
    require(totals.tested == boundaries && totals.partial_writes && totals.partial_erases,
            "exercise genuinely partial writes and erases for each pattern");
    std::printf("K151 NVS %s: %zu recovered, %zu partial writes, %zu partial erases\n",
                label, totals.tested, totals.partial_writes, totals.partial_erases);
  }
  std::printf("K151 NVS restart guard: missing, corrupt and read-error budgets denied\n");
  return 0;
} catch (const std::runtime_error& error) {
  std::fprintf(stderr, "%s\n", error.what());
  return 1;
}
