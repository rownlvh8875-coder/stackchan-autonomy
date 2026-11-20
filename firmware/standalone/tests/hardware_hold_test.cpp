// Synthetic host-only STOP callbacks and no executable hardware activation.
#include "hardware_hold.hpp"

#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;
class MemoryKv final : public AtomicKv {
 public:
  std::vector<uint8_t> budget, profile;
  ReadValue read(std::string_view key, size_t max) override {
    const auto& value = key=="budget" ? budget : profile;
    if (value.empty()) return {ReadCode::missing,{}};
    if (value.size()>max) return {ReadCode::failure,{}};
    return {ReadCode::found,value};
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    if (key=="budget")budget.assign(bytes.begin(),bytes.end());
    else if (key=="wake_profile")profile.assign(bytes.begin(),bytes.end());
    else return false;
    return true;
  }
};
int main() {
  RecoveryReadiness facts{};
  assert(assess_install_hold(facts)==InstallHoldReason::original_missing);
  assert(!can_activate_hardware(facts));
  facts.original_a_b_verified=true;
  assert(assess_install_hold(facts)==InstallHoldReason::offsite_missing);
  facts.separately_preserved_backup=true;
  assert(assess_install_hold(facts)==InstallHoldReason::restore_unproven);
  facts.validated_recovery_path=true;
  facts.live_device_identity_unchanged=true;
  assert(assess_install_hold(facts)==InstallHoldReason::app_slot_unknown);
  facts.active_slot_and_boot_selection_known=true;
  facts.physical_stop_measured=true;
  facts.exact_lcd_variant_verified=true;
  facts.exclusive_i2c_bus_verified=true;
  facts.power_rails_measured=true;
  facts.amp_mute_measured=true;
  assert(assess_install_hold(facts)==InstallHoldReason::new_approval_missing);
  facts.explicit_new_install_authorization=true;
  assert(assess_install_hold(facts)==InstallHoldReason::deliberately_disabled);
  assert(!can_activate_hardware(facts)); // Simulated claims cannot enable GPIO.
  MemoryKv kv;
  PersistentGuard ledger(kv);
  assert(ledger.provision_budget(true));
  WakeProfile profile;
  profile.limit_q8=512;
  WakeFeature feat;
  feat.quantized.fill(1);
  profile.templates.push_back(feat);
  assert(ledger.save_profile(*encode_wake_profile(profile),true));
  assert(ledger.reserve(1800000000,true,true));
  assert(ledger.authorize_step(PaidStage::transcribe,true,true));
  Session session;
  session.boot(1000,true,true);
  session.cloud_enable(true);
  std::atomic_bool stop{false};
  std::array<int,6> invoked{};
  auto make_hooks=[&](bool fail_amp) {
    PeripheralStopHooks h;
    h.microphone_off=[&]() {++invoked[0];return stop.load();};
    h.amplifier_off=[&,fail_amp]() {++invoked[1];return !fail_amp;};
    h.abort_http=[&]() {++invoked[2];return true;};
    h.close_usb=[&]() {++invoked[3];return true;};
    h.remove_display=[&]() {++invoked[4];return true;};
    h.release_i2c=[&]() {++invoked[5];return true;};
    return h;
  };
  {
    PeripheralStopSupervisor supervisor(stop,session,ledger,make_hooks(false));
    assert(supervisor.request_stop());
    assert(supervisor.stopped() && !supervisor.faulted());
    assert(stop.load() && session.state()==State::stopped);
    assert(!ledger.permit_active());
    assert(!ledger.authorize_step(PaidStage::respond,true,true));
    assert(supervisor.request_stop());
    for(int n: invoked) assert(n==1);
  }
  {
    stop.store(false);
    for(auto& v:invoked)v=0;
    PeripheralStopSupervisor supervisor(stop,session,ledger,make_hooks(true));
    assert(!supervisor.request_stop());
    assert(supervisor.stopped() && supervisor.faulted() && stop.load());
    for(int n:invoked)assert(n==1);  // All shutdowns called after amp failure.
    assert(!supervisor.request_stop());
    for(int n:invoked)assert(n==1);  // No repeated driver commands.
  }
  {
    stop.store(false);
    PeripheralStopHooks incomplete;
    incomplete.microphone_off=[](){return true;};
    PeripheralStopSupervisor supervisor(stop,session,ledger,incomplete);
    assert(!supervisor.request_stop());
    assert(supervisor.faulted() && stop.load());
  }
  std::cout<<"install-HOLD and STOP no-retry supervisor: PASS\n";
}
