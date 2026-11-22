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

  TestKv setup_store;
  PersistentGuard setup(setup_store);
  assert(!setup.restore_budget_for_setup(false) && setup_store.writes == 0);
  assert(setup.restore_budget_for_setup(true) && setup_store.writes == 1);
  assert(setup.admit_builtin_wake(1, true, true) && setup.reserve(now, true, true, 1));
  const auto reserved_budget = setup_store.data["budget"];
  PersistentGuard configured(setup_store);
  assert(configured.restore_budget_for_setup(true));
  assert(configured.reserved_conversations() == 1);
  assert(setup_store.writes == 2 && setup_store.data["budget"] == reserved_budget);
  PersistentGuard one_turn(setup_store, true);
  assert(one_turn.restore_budget() && !one_turn.paid_trial_spent());
  assert(one_turn.admit_builtin_wake(1, true, true) && one_turn.reserve(now + 1, true, true, 1));
  assert(one_turn.paid_trial_spent() && setup_store.writes == 3);
  assert(one_turn.authorize_step(PaidStage::transcribe, true, true));
  one_turn.cancel_permit();
  assert(one_turn.admit_builtin_wake(2, true, true));
  assert(!one_turn.reserve(now + 86401, true, true, 2)); // Ledger window has rolled over.
  assert(!one_turn.authorize_step(PaidStage::transcribe, true, true) && setup_store.writes == 3);
  TestKv corrupt_setup;
  corrupt_setup.data["budget"] = {1, 2, 3};
  PersistentGuard corrupt(corrupt_setup);
  assert(!corrupt.restore_budget_for_setup(true) && corrupt.fatal());
  assert(corrupt_setup.writes == 0);
  TestKv failed_setup;
  failed_setup.next_read_fails = true;
  PersistentGuard unreadable(failed_setup);
  assert(!unreadable.restore_budget_for_setup(true) && unreadable.fatal());
  assert(failed_setup.writes == 0);

  TestKv fresh;
  PersistentGuard first(fresh);
  assert(!first.provision_budget(false) && fresh.writes == 0);
  assert(first.provision_budget(true) && fresh.writes == 1);
  assert(!first.provision_budget(true));
  assert(!first.save_profile(profile, false));
  assert(first.save_profile(profile, true));
  // A loaded ledger/profile WITHOUT a new reservation must not send requests.
  assert(!first.authorize_step(PaidStage::transcribe, true, true));
  assert(!first.reserve(now, false, true));
  assert(!first.reserve(now, true, false));
  assert(first.reserve(now, true, true));
  assert(first.reserved_conversations() == 1);
  assert(!first.reserve(now + 1, true, true)); // no overlapping reservations
  assert(!first.authorize_step(PaidStage::respond, true, true)); // no phase skipping
  assert(!first.authorize_step(PaidStage::transcribe, false, true)); // owner opt-in
  assert(first.authorize_step(PaidStage::transcribe, true, true));
  assert(!first.authorize_step(PaidStage::transcribe, true, true)); // no retry
  assert(first.authorize_step(PaidStage::respond, true, true));
  assert(first.authorize_step(PaidStage::synthesize, true, true));
  assert(!first.permit_active());
  assert(!first.authorize_step(PaidStage::synthesize, true, true));

  PersistentGuard reboot(fresh);
  assert(reboot.restore_profile() == ProfileLoad::valid);
  assert(reboot.restore_budget());
  assert(reboot.reserved_conversations() == 1);
  assert(!reboot.authorize_step(PaidStage::transcribe, true, true));
  assert(reboot.reserve(now + 1, true, true));
  assert(reboot.authorize_step(PaidStage::transcribe, true, true));
  reboot.cancel_permit(); // STOP: no refund and no delayed next stage
  assert(!reboot.authorize_step(PaidStage::respond, true, true));
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
