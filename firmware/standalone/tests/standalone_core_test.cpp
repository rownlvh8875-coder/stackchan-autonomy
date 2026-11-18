// SPDX-License-Identifier: MIT
#include "standalone_core.hpp"
#include <cassert>
#include <iostream>

using namespace stackchan::standalone;

void scfg_tests() {
  Frame original{Op::configure, 12345, 0, {0x00, 0x01, 0xfa, 0xff}};
  const auto encoded = encode_frame(original);
  assert(encoded);
  const auto decoded = decode_frame(*encoded);
  assert(decoded && decoded->op == original.op && decoded->nonce == 12345 &&
         decoded->sequence == 0 && decoded->payload == original.payload);
  auto damaged = *encoded;
  damaged[14] ^= 0x01;
  assert(!decode_frame(damaged));
  damaged = *encoded;
  damaged[6] = 0xff;
  damaged[7] = 0xff;
  assert(!decode_frame(damaged));
  damaged = *encoded;
  damaged[4] = 2;
  assert(!decode_frame(damaged));
  assert(!decode_frame(std::span<const uint8_t>(encoded->data(), 13)));
  assert(!decode_frame(std::span<const uint8_t>(encoded->data(), encoded->size()-1)));
  assert(!encode_frame(Frame{Op::enroll_features,1,0,std::vector<uint8_t>(4097,1)}));
  assert(!encode_frame(Frame{Op::stop,1,0,{1}}));
  assert(!encode_frame(Frame{Op::status,0,0,{}}));
  assert(!encode_frame(Frame{static_cast<Op>(255),1,0,{}}));
  FeatureAssembly a;
  const std::array<uint8_t,4> input{1,2,3,4};
  assert(!a.begin(0,4));
  assert(a.begin(123,4));
  assert(a.append(123,0,std::span<const uint8_t>(input).first(2)));
  assert(!a.append(123,0,std::span<const uint8_t>(input).last(2))); // replay aborts
  assert(!a.finish(123,4,crc32(input)));
  assert(a.begin(123,4));
  assert(a.append(123,0,std::span<const uint8_t>(input).first(2)));
  assert(a.append(123,1,std::span<const uint8_t>(input).last(2)));
  assert(a.finish(123,4,crc32(input)) == std::vector<uint8_t>(input.begin(), input.end()));
  assert(!a.finish(123,4,crc32(input))); // commit only once
  assert(a.begin(124,4));
  assert(a.append(124,0,input));
  assert(!a.finish(124,4,12345));
  assert(a.begin(124,4));
  assert(!a.append(125,0,input)); // nonce swap aborts
}

void budget_tests() {
  constexpr uint64_t t = 1'800'000'000ULL;
  auto ledger = BudgetLedger::fresh();
  std::vector<uint8_t> durable;
  auto save = [&](std::span<const uint8_t> b) {
    durable.assign(b.begin(), b.end());
    return true;
  };
  assert(!ledger.reserve(t,false,save));
  assert(!ledger.reserve(t,true,{}));
  assert(ledger.reserve(t,true,save));
  assert(ledger.reserve(t+1,true,save));
  assert(!ledger.reserve(t+2,true,save)); // two jobs per minute
  assert(ledger.count()==2);
  const auto restored = BudgetLedger::restore(durable);
  assert(restored && restored->count()==2);
  auto recovered = *restored;
  assert(!recovered.reserve(t-1,true,save)); // rollback cannot refund
  assert(recovered.reserve(t+60,true,save));
  const auto before = durable;
  assert(!recovered.reserve(t+120,true,[&](std::span<const uint8_t>) {return false;}));
  assert(durable == before); // failed store -> no send/reclaim
  assert(recovered.reserve(t+120,true,save));
  assert(recovered.count()==4);
  auto corrupted = durable;
  corrupted.back() ^= 1;
  assert(!BudgetLedger::restore(corrupted));
  corrupted = durable;
  corrupted[5] = 101;
  assert(!BudgetLedger::restore(corrupted));
  assert(!BudgetLedger::restore({}));
  assert(BudgetLedger::restore(BudgetLedger::fresh().serialize()));
  for (uint64_t i=4;i<30;++i) {
    assert(recovered.reserve(t + i * 61,true,save));
  }
  assert(!recovered.reserve(t+30*61,true,save)); // per-hour limit
  assert(recovered.reserve(t+3600,true,save)); // old events aged out of hour
}

void session_tests() {
  Session s;
  s.boot(1000,false,false);
  assert(s.state()==State::setup_required);
  assert(!s.wake(1001));
  s.boot(2000,true,false);
  assert(s.state()==State::enroll_required);
  s.boot(3000,true,true);
  assert(s.state()==State::wake_wait);
  const auto e=s.wake(3100);
  assert(e && s.state()==State::ready);
  assert(!s.wake(3200));
  s.tick(8100);
  assert(s.state()==State::cooldown);
  assert(!s.speech_started(8101,*e));
  s.boot(10000,true,true);
  auto epoch=s.wake(11000);
  assert(epoch && s.speech_started(12000,*epoch));
  assert(!s.recorded(12001,*epoch,true,true,true)); // cloud opt-in absent
  assert(s.state()==State::error);
  s.boot(20000,true,true);
  s.cloud_enable(true);
  epoch=s.wake(21000);
  assert(epoch && s.speech_started(21100,*epoch));
  assert(!s.recorded(21200,*epoch,false,true,true));
  assert(s.state()==State::cooldown);
  assert(!s.wake(21699));
  assert(s.wake(21700));
  s.stop();
  assert(s.state()==State::stopped);
  assert(!s.speech_started(22000,*epoch));
  assert(!s.wake(23000));
  assert(s.resume(23000));
  assert(s.state()==State::wake_wait);
  s.cloud_enable(true);
  epoch=s.wake(24000);
  assert(epoch && s.speech_started(24100,*epoch));
  assert(s.recorded(24200,*epoch,true,true,true));
  assert(s.state()==State::transcribe);
  assert(!s.transcribed(24250,*epoch+1,true));
  assert(s.transcribed(24250,*epoch,true));
  assert(!s.thought(24251,*epoch,false));
  assert(s.state()==State::error);
  s.boot(60000,true,true);
  s.cloud_enable(true);
  epoch=s.wake(61000);
  assert(epoch && s.speech_started(62000,*epoch));
  assert(s.recorded(63000,*epoch,true,true,true));
  assert(!s.transcribed(93000,*epoch,true)); // exact stage timeout
  assert(s.state()==State::error);
  assert(!s.thought(93001,*epoch,true)); // late response must be inert
  s.boot(100000,true,true);
  s.cloud_enable(true);
  epoch=s.wake(101000);
  assert(epoch && s.speech_started(101100,*epoch));
  assert(s.recorded(101200,*epoch,true,true,true));
  assert(s.transcribed(101300,*epoch,true));
  assert(s.thought(101400,*epoch,true));
  assert(s.synthesized(101500,*epoch,true));
  assert(!s.wake(101600)); // no self wake on playback
  assert(s.played(101700,*epoch,true));
  assert(s.state()==State::cooldown);
  assert(!s.wake(102199));
  assert(s.wake(102200));
  s.stop();
  assert(!s.resume(100000)); // monotonic rollback
  assert(s.resume(102200));
  assert(s.state()==State::wake_wait);
  auto e2=s.wake(103000);
  assert(e2 && s.speech_started(103100,*e2));
  assert(!s.recorded(111100,*e2,true,true,true)); // recording timeout
  assert(s.state()==State::error);
}

int main() {
  scfg_tests();
  budget_tests();
  session_tests();
  std::cout << "standalone core: PASS (SCFG, feature assembly, durable budget, state/STOP/deadline)\n";
}
