// No device I/O, serial, flash or paid requests. Credentials are fake.
#include "owner_setup.hpp"
#include "saved_owner_credentials_fixture.hpp"

#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string_view>

using namespace stackchan::standalone;
constexpr std::array<uint8_t,4> ssid{'t','e','s','t'};
constexpr std::string_view password="fake-passphrase";
constexpr std::string_view key="fake-testing-token-0123456789";

void exercise_saved_setup() {
  MockOwnerRecords records;
  MockOwnerCipher cipher;
  SavedOwnerCredentials store(records, cipher);
  std::atomic_bool owner{true}, surface{true}, stop{false};
  {
    RuntimeSecrets secrets;
    OwnerSetupController first(secrets, owner, surface, stop);
    assert(first.restore_saved(store, 100) == SavedSetupLoad::missing);
    assert(first.phase() == OwnerSetupPhase::hold && !first.ready() && !cipher.opens);
    assert(first.arm(120) && first.submit_wifi(ssid, password, 121) &&
           first.submit_api_key(key, 122) && first.confirm(123, true));
    assert(!first.save_first(store, false) && records.commits == 0);
    assert(first.save_first(store, true) && records.commits == 1 && cipher.seals == 1);
    assert(!first.save_first(store, true) && records.commits == 1);
    assert(std::search(records.data.begin(), records.data.end(), key.begin(), key.end()) ==
           records.data.end());
  }
  {
    RuntimeSecrets fresh;
    OwnerSetupController rebooted(fresh, owner, surface, stop);
    const auto reads = records.reads;
    owner = false;
    assert(rebooted.restore_saved(store, 5) == SavedSetupLoad::unusable);
    assert(records.reads == reads && !fresh.valid());
    owner = true;
    assert(rebooted.restore_saved(store, 8) == SavedSetupLoad::restored);
    assert(rebooted.ready() && fresh.api_key() == key && fresh.passphrase() == password);
    assert(std::ranges::equal(fresh.ssid(), ssid));
    assert(!rebooted.arm(9) && rebooted.tick(10));
    rebooted.cancel();
    assert(!fresh.valid());
  }
  {
    RuntimeSecrets fresh;
    OwnerSetupController rebooted(fresh, owner, surface, stop);
    cipher.stop_on_open = &stop;
    assert(rebooted.restore_saved(store, 5) == SavedSetupLoad::unusable);
    assert(!fresh.valid() && !rebooted.ready() && !rebooted.arm(8));
    cipher.stop_on_open = nullptr;
    stop = false;
  }
  {
    RuntimeSecrets fresh;
    OwnerSetupController rebooted(fresh, owner, surface, stop);
    records.data.back() ^= 1;
    assert(rebooted.restore_saved(store, 5) == SavedSetupLoad::unusable);
    assert(!fresh.valid() && !rebooted.arm(9) && records.commits == 1);
  }
}

int main() {
  exercise_saved_setup();
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{false}, surface{true}, stop{false};
    OwnerSetupController ui(secrets, owner,surface,stop);
    assert(!ui.arm(100));
    assert(ui.phase()==OwnerSetupPhase::hold && !secrets.valid());
    owner.store(true); surface.store(false);
    assert(!ui.arm(100));
    surface.store(true);
    assert(ui.arm(100));
    assert(ui.phase()==OwnerSetupPhase::wifi_input);
    assert(ui.submit_wifi(ssid,password,120));
    assert(ui.submit_api_key(key,130));
    assert(!ui.ready() && !secrets.valid());
    assert(ui.confirm(140,true) && ui.ready() && secrets.valid());
    assert(secrets.ssid().size()==4 && secrets.api_key()==key);
    assert(!ui.arm(150));
    assert(!ui.submit_wifi(ssid,password,151));
    assert(ui.tick(152));
    ui.cancel();
    assert(!ui.ready() && !secrets.valid());
    assert(secrets.passphrase().empty() && secrets.api_key().empty());
    assert(!ui.arm(200)); // One boot / one setup cycle, no implicit replay.
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(0));
    assert(!ui.submit_api_key(key,10)); // Wrong order is terminal.
    assert(ui.phase()==OwnerSetupPhase::fault && !secrets.valid());
    assert(!ui.submit_wifi(ssid,password,20));
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(0));
    assert(!ui.submit_wifi(ssid,"short",100));
    assert(ui.phase()==OwnerSetupPhase::fault);
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    assert(!ui.submit_api_key("short",102));
    assert(ui.phase()==OwnerSetupPhase::fault && !secrets.valid());
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    assert(ui.submit_api_key(key,102));
    assert(!ui.confirm(103,false));
    assert(ui.phase()==OwnerSetupPhase::fault && !secrets.valid());
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    assert(ui.submit_api_key(key,102));
    assert(!ui.tick(120100)); // At exactly 2 minutes, fail closed.
    assert(!ui.confirm(120101,true));
    assert(ui.phase()==OwnerSetupPhase::fault && !secrets.valid());
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    assert(!ui.submit_api_key(key,99)); // Monotonic rollback.
    assert(ui.phase()==OwnerSetupPhase::fault);
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    stop.store(true);
    assert(!ui.submit_api_key(key,102));
    assert(ui.phase()==OwnerSetupPhase::stopped && !secrets.valid());
    stop.store(false);
    assert(!ui.confirm(103,true)); // STOP cannot be resumed.
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    surface.store(false);
    assert(!ui.submit_api_key(key,102));
    assert(ui.phase()==OwnerSetupPhase::stopped && !secrets.valid());
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    assert(ui.arm(100));
    assert(ui.submit_wifi(ssid,password,101));
    assert(ui.submit_api_key(key,102));
    assert(ui.confirm(103,true));
    owner.store(false);
    assert(!ui.tick(104));
    assert(!secrets.valid() && ui.phase()==OwnerSetupPhase::stopped);
  }
  {
    // Never mutate a valid credential owner we did not create.
    RuntimeSecrets preexisting;
    std::atomic_bool owner{true},surface{true},stop{false};
    assert(preexisting.provision(ssid,password,key,true));
    OwnerSetupController ui(preexisting,owner,surface,stop);
    assert(!ui.arm(100));
    assert(preexisting.valid());
  }
  {
    RuntimeSecrets secrets;
    std::atomic_bool owner{true},surface{true},stop{false};
    OwnerSetupController ui(secrets,owner,surface,stop);
    std::array<uint8_t,3> bad_ssid{'n',0,'x'};
    assert(ui.arm(10));
    assert(!ui.submit_wifi(bad_ssid,password,11));
    assert(ui.phase()==OwnerSetupPhase::fault);
  }
  std::cout << "one-time owner setup/stop/timeout/RAM-only: PASS\n";
}
