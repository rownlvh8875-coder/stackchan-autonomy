// SPDX-License-Identifier: MIT
// Actual durable-budget policy, in-memory store only. No device/API.
#include "persistent_store.hpp"
#include <cassert>
#include <iostream>
#include <string_view>
#include <vector>
using namespace stackchan::standalone;
struct Store:AtomicKv {
  std::vector<uint8_t> budget;
  int writes=0;
  ReadValue read(std::string_view key,size_t bound) override {
    if(key!="budget" || budget.empty())return {ReadCode::missing,{}};
    if(budget.size()>bound)return {ReadCode::failure,{}};
    return {ReadCode::found,budget};
  }
  bool commit(std::string_view key,std::span<const uint8_t> b) override {
    if(key!="budget")return false;
    ++writes;budget.assign(b.begin(),b.end());return true;
  }
};
int main(int argc,char** argv) {
  assert(argc==2);const std::string_view test=argv[1];
  Store store;PersistentGuard g(store);assert(g.provision_budget(true));
  if(test=="admission_valid") {
    assert(g.admit_builtin_wake(2,true,true));assert(!g.has_profile());
    assert(g.reserve(1800000000,true,true,2));
    assert(g.authorize_step(PaidStage::transcribe,true,true));
    assert(!g.authorize_step(PaidStage::transcribe,true,true));
    assert(g.authorize_step(PaidStage::respond,true,true));
    assert(g.authorize_step(PaidStage::synthesize,true,true));
    assert(!g.authorize_step(PaidStage::synthesize,true,true));
    assert(g.reserved_conversations()==1 && store.writes==2 && !g.has_profile());
    assert(!g.admit_builtin_wake(2,true,true)); // Cannot replay a consumed hit.
  } else if(test=="admission_default_closed") {
    assert(!g.reserve(1800000000,true,true,2));
    assert(!g.authorize_step(PaidStage::transcribe,true,true));
    assert(g.reserved_conversations()==0);
    // Old3-argument API preserves reservation semantics, but not authority.
    assert(g.reserve(1800000000,true,true));
    assert(!g.authorize_step(PaidStage::transcribe,true,true));
  } else if(test=="admission_gates") {
    assert(!g.admit_builtin_wake(2,false,true));
    assert(!g.admit_builtin_wake(2,true,false));
    assert(!g.admit_builtin_wake(0,true,true));
    assert(!g.reserve(1800000000,true,true,2));
  } else if(test=="admission_epoch") {
    assert(g.admit_builtin_wake(2,true,true));
    assert(!g.reserve(1800000000,true,true,3));
    assert(!g.reserve(1800000000,true,true,2));
    assert(g.reserved_conversations()==0);
  } else if(test=="admission_cancel") {
    assert(g.admit_builtin_wake(2,true,true));g.cancel_permit();
    assert(!g.reserve(1800000000,true,true,2));
    assert(g.admit_builtin_wake(3,true,true));
    assert(g.reserve(1800000000,true,true,3));g.cancel_permit();
    assert(!g.authorize_step(PaidStage::transcribe,true,true));
    assert(g.reserved_conversations()==1);
  } else if(test=="admission_reboot") {
    assert(g.admit_builtin_wake(2,true,true));
    assert(g.reserve(1800000000,true,true,2));
    PersistentGuard reboot(store);assert(reboot.restore_budget());
    assert(!reboot.reserve(1800000061,true,true,2));
    assert(!reboot.authorize_step(PaidStage::transcribe,true,true));
    assert(reboot.reserved_conversations()==1);
    assert(reboot.admit_builtin_wake(2,true,true)); // A new local hit in new lifecycle.
    assert(reboot.reserve(1800000061,true,true,2));
    assert(reboot.authorize_step(PaidStage::transcribe,true,true));
  } else if(test=="admission_fatal") {
    store.budget={1,2,3};PersistentGuard broken(store);
    assert(!broken.restore_budget() && broken.fatal());
    assert(!broken.admit_builtin_wake(2,true,true));
    assert(!broken.reserve(1800000000,true,true,2));
  } else assert(false);
  std::cout<<"builtin source admission PASS; no device/API\n";
}
