#include "persistent_store.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <span>
#include <string>

using namespace stackchan::standalone;

class TestKv : public AtomicKv {
 public:
  std::map<std::string, std::vector<uint8_t>> data;
  bool commit_fails = false;
  bool next_read_fails = false;
  bool fake_success = false;
  int writes = 0;

  ReadValue read(std::string_view key, size_t max_bytes) override {
    if (next_read_fails) { next_read_fails = false; return {ReadCode::failure, {}}; }
    auto it = data.find(std::string(key));
    if (it == data.end()) return {ReadCode::missing, {}};
    if (it->second.size() > max_bytes) return {ReadCode::failure, {}};
    return {ReadCode::found, it->second};
  }
  bool commit(std::string_view key, std::span<const uint8_t> blob) override {
    ++writes;
    if (commit_fails) return false;
    if (!fake_success) data[std::string(key)] = {blob.begin(), blob.end()};
    return true;
  }
};

static std::vector<uint8_t> make_profile() {
  WakeProfile p;
  p.limit_q8 = 512;
  p.templates.emplace_back();
  auto encoded = encode_wake_profile(p);
  assert(encoded);
  return *encoded;
}

int main() {
  constexpr uint64_t now = 1795100000ULL;
  auto profile = make_profile();
  TestKv kv;
  PersistentGuard no_init(kv);
  assert(no_init.restore_profile() == ProfileLoad::missing);
  assert(!no_init.restore_budget() && no_init.fatal());
  assert(!no_init.provision_budget(true)); // normal boot with absent ledger is HOLD
  assert(kv.writes == 0);

  TestKv fresh;
  PersistentGuard first(fresh);
  assert(!first.provision_budget(false) && fresh.writes == 0);
  assert(first.provision_budget(true) && fresh.writes == 1);
  assert(!first.provision_budget(true));
  assert(!first.save_profile(profile, false));
  assert(first.save_profile(profile, true));
  assert(first.may_transmit(true, true));
  assert(!first.may_transmit(false, true));
  assert(!first.reserve(now, false, true));
  assert(!first.reserve(now, true, false));
  assert(first.reserve(now, true, true));
  assert(first.reserved_conversations() == 1);

  PersistentGuard reboot(fresh);
  assert(reboot.restore_profile() == ProfileLoad::valid);
  assert(reboot.restore_budget());
  assert(reboot.reserved_conversations() == 1);
  assert(reboot.reserve(now + 1, true, true));
  assert(!reboot.reserve(now + 2, true, true)); // 2 conversations per minute
  assert(!reboot.reserve(now - 10, true, true)); // clock rollback, no renewal

  TestKv bad;
  bad.data["budget"] = {1, 2, 3};
  PersistentGuard invalid(bad);
  assert(!invalid.restore_budget() && invalid.fatal());
  assert(!invalid.provision_budget(true));

  TestKv write_fail;
  write_fail.commit_fails = true;
  PersistentGuard broken(write_fail);
  assert(!broken.provision_budget(true) && broken.fatal());
  write_fail.commit_fails = false;
  assert(!broken.provision_budget(true)); // no retry after uncertain write

  TestKv misreport;
  misreport.fake_success = true;
  PersistentGuard fake(misreport);
  assert(!fake.provision_budget(true) && fake.fatal());
  assert(!fake.reserve(now, true, true));

  TestKv profile_failure;
  PersistentGuard guard(profile_failure);
  assert(guard.provision_budget(true));
  profile_failure.next_read_fails = true;
  assert(guard.restore_profile() == ProfileLoad::invalid_or_io && guard.fatal());

  TestKv invalid_profile;
  PersistentGuard profile_guard(invalid_profile);
  assert(profile_guard.provision_budget(true));
  auto bytes = profile;
  bytes[4] = 0; // invalid number of templates
  assert(!profile_guard.save_profile(bytes, true));
  assert(invalid_profile.writes == 1); // budget only, bad features never persist

  std::cout << "persistent store: PASS (first provisioning, NVS-style fail-closed, reboot budget)\n";
}
