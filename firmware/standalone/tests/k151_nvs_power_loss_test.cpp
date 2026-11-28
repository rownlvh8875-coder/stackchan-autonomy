// SPDX-License-Identifier: MIT
// The pinned SDK's NVS storage against a four-sector RAM flash.
#include "nvs_storage.hpp"
#include "standalone_core.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <span>
#include <stdexcept>
#include <vector>

using stackchan::standalone::BudgetLedger;

namespace {
constexpr size_t kSector = 4096;
constexpr size_t kSectors = 4;
using FlashBytes = std::array<uint8_t, kSectors * kSector>;
using SetupRecord = std::array<uint8_t, 371>;
struct PowerLoss {};

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
    const auto* data = static_cast<const uint8_t*>(source);
    for (size_t i = 0; i < size; ++i) bytes[offset + i] &= data[i];
    return completed_flash_operation();
  }
  esp_err_t write(size_t offset, const void* source, size_t size) override {
    return write_raw(offset, source, size);
  }
  esp_err_t erase_range(size_t offset, size_t size) override {
    if (offset % kSector || size % kSector || !fits(offset, size)) return ESP_ERR_INVALID_SIZE;
    std::fill_n(bytes.begin() + offset, size, 0xff);
    return completed_flash_operation();
  }

  FlashBytes bytes;
  size_t operations = 0;
  size_t cut_after = 0;

 private:
  bool fits(size_t offset, size_t size) const {
    return offset <= bytes.size() && size <= bytes.size() - offset;
  }
  esp_err_t completed_flash_operation() {
    if (++operations == cut_after) throw PowerLoss{};
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

std::vector<uint8_t> read_blob(nvs::Storage& storage, uint8_t index, const char* key, size_t bound) {
  size_t size{};
  if (storage.getItemDataSize(index, nvs::ItemType::BLOB, key, size) != ESP_OK) return {};
  require(size <= bound, "stored blob length");
  std::vector<uint8_t> bytes(size);
  require(storage.readItem(index, nvs::ItemType::BLOB, key, bytes.data(), bytes.size()) == ESP_OK,
          "read complete blob");
  return bytes;
}

void check_cut(const FlashBytes& start, size_t cut, const std::vector<uint8_t>& previous,
               const std::vector<uint8_t>& proposed, const SetupRecord& setup) {
  RamFlash flash(start);
  try {
    nvs::Storage storage(&flash);
    require(storage.init(0, kSectors) == ESP_OK, "mount before budget update");
    flash.cut_after = flash.operations + cut;
    (void)write_blob(storage, ns(storage, "sc_gpt"), "budget", proposed);
    require(false, "simulated power loss was not reached");
  } catch (const PowerLoss&) {
    flash.cut_after = 0;
  }
  nvs::Storage reboot(&flash);
  require(reboot.init(0, kSectors) == ESP_OK, "mount after simulated power loss");
  const auto observed = read_blob(reboot, ns(reboot, "sc_gpt"), "budget", 818);
  require(BudgetLedger::restore(observed).has_value() &&
              (observed == previous || observed == proposed),
          "reboot lost the prior and proposed budgets");
  require(std::ranges::equal(read_blob(reboot, ns(reboot, "sc_owner"), "owner_cfg_v2", setup.size()),
                             setup),
          "reboot changed stored setup");
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
  size_t cuts = 0;
  for (size_t i = 0; i < 300; ++i) {
    const auto previous = ledger.serialize();
    FlashBytes start;
    size_t operations;
    {
      nvs::Storage storage(&flash);
      require(storage.init(0, kSectors) == ESP_OK, "reopen NVS");
      const auto index = ns(storage, "sc_gpt");
      require(read_blob(storage, index, "budget", 818) == previous, "read prior committed budget");
      start = flash.bytes;
      const size_t before = flash.operations;
      require(ledger.reserve(1'700'000'000 + 864 * i, true, [&](auto wire) {
        return write_blob(storage, index, "budget", wire);
      }), "commit maximum-rate rolling ledger");
      operations = flash.operations - before;
    }
    const auto proposed = ledger.serialize();
    for (size_t cut = 1; cut <= operations; ++cut) {
      try {
        check_cut(start, cut, previous, proposed, setup);
        ++cuts;
      } catch (const std::runtime_error& error) {
        std::fprintf(stderr, "Budget update %zu, cut %zu: %s\n", i + 1, cut, error.what());
        return 1;
      }
    }
  }
  require(ledger.serialize().size() == 818 && cuts > 3'000, "exercise full ledger and page reuse");
  std::printf("K151 NVS power-loss regression: %zu write/erase boundaries passed\n", cuts);
  return 0;
} catch (const std::runtime_error& error) {
  std::fprintf(stderr, "%s\n", error.what());
  return 1;
}
