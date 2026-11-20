// Host-only synthetic SWK1 enrollment + NVS-like fake, never USB or device.
#include "consent_profile_store.hpp"
#include "usb_enrollment.hpp"

#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <span>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;
struct FakeKv final : AtomicKv {
  bool allow = false;
  bool fail_commit = false;
  bool corrupt_on_read = false;
  int writes = 0;
  std::vector<uint8_t> value;
  std::atomic_bool* stop_during_commit = nullptr;

  ReadValue read(std::string_view key, size_t max) override {
    if (key != "wake_profile") return {ReadCode::failure, {}};
    if (value.empty()) return {ReadCode::missing, {}};
    if (value.size() > max) return {ReadCode::failure, {}};
    auto out = value;
    if (corrupt_on_read && !out.empty()) out[0] ^= 0xff;
    return {ReadCode::found, out};
  }
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override {
    if (key != "wake_profile" || !allow || fail_commit) return false;
    ++writes;
    value.assign(bytes.begin(), bytes.end());
    if (stop_during_commit) stop_during_commit->store(true);
    return true;
  }
};

std::vector<uint8_t> profile() {
  WakeProfile p;
  p.limit_q8 = 512;
  WakeFeature f;
  f.quantized.fill(1);
  p.templates.push_back(f);
  const auto wire = encode_wake_profile(p);
  assert(wire);
  return *wire;
}
Ack send_profile(EnrollmentServer& server, const std::vector<uint8_t>& blob,
                 uint32_t nonce) {
  std::vector<uint8_t> begin_data;
  put16(begin_data, static_cast<uint16_t>(blob.size()));
  put32(begin_data, crc32(blob));
  assert(server.handle(Frame{Op::enroll_begin, nonce, 0, begin_data}).code == AckCode::ok);
  assert(server.handle(Frame{Op::enroll_features, nonce, 0, blob}).code == AckCode::ok);
  return server.handle(Frame{Op::enroll_commit, nonce, 1, {}});
}

int main() {
  const auto bytes = profile();

  { // Only trusted local mode can permit a write.
    FakeKv db;
    PersistentGuard guard(db);
    std::atomic_bool owner{false}, stop{false};
    ConsentProfileStore gate(guard, owner, stop, [&](bool on){ db.allow=on; });
    EnrollmentServer server([&](std::span<const uint8_t> p){return gate.persist(p);});
    server.arm_enrollment(true); // server arm ALONE is not ownership.
    assert(send_profile(server, bytes, 111).code == AckCode::store_failed);
    assert(db.writes==0 && !db.allow);
  }
  { // Full valid enrollment commits exactly once and verifies readback.
    FakeKv db;
    PersistentGuard guard(db);
    std::atomic_bool owner{true}, stop{false};
    ConsentProfileStore gate(guard, owner, stop, [&](bool on){db.allow=on;});
    EnrollmentServer server([&](std::span<const uint8_t> p){return gate.persist(p);});
    server.arm_enrollment(true);
    assert(send_profile(server, bytes, 112).code == AckCode::ok);
    assert(db.value == bytes && db.writes==1 && !db.allow && guard.has_profile());
    assert(server.handle(Frame{Op::enroll_commit,112,1,{}}).code != AckCode::ok);
    assert(db.writes==1);
  }
  { // Local mode revoked between begin and commit.
    FakeKv db;
    PersistentGuard guard(db);
    std::atomic_bool owner{true}, stop{false};
    ConsentProfileStore gate(guard, owner, stop, [&](bool on){db.allow=on;});
    EnrollmentServer server([&](std::span<const uint8_t> p){return gate.persist(p);});
    server.arm_enrollment(true);
    std::vector<uint8_t> header;
    put16(header, static_cast<uint16_t>(bytes.size())); put32(header, crc32(bytes));
    assert(server.handle(Frame{Op::enroll_begin,113,0,header}).code == AckCode::ok);
    assert(server.handle(Frame{Op::enroll_features,113,0,bytes}).code == AckCode::ok);
    owner.store(false);
    assert(server.handle(Frame{Op::enroll_commit,113,1,{}}).code == AckCode::store_failed);
    assert(db.writes==0 && !db.allow);
  }
  { // Corrupt readback is fatal and cannot be accepted as durable enrollment.
    FakeKv db; db.corrupt_on_read=true;
    PersistentGuard guard(db);
    std::atomic_bool owner{true}, stop{false};
    ConsentProfileStore gate(guard, owner, stop, [&](bool on){db.allow=on;});
    EnrollmentServer server([&](std::span<const uint8_t> p){return gate.persist(p);});
    server.arm_enrollment(true);
    assert(send_profile(server, bytes,114).code == AckCode::store_failed);
    assert(db.writes==1 && !db.allow && guard.fatal());
    assert(!gate.persist(bytes));
  }
  { // If STOP occurs while the commit is in-flight, success is never ACKed.
    FakeKv db;
    PersistentGuard guard(db);
    std::atomic_bool owner{true}, stop{false};
    db.stop_during_commit=&stop;
    ConsentProfileStore gate(guard, owner, stop, [&](bool on){db.allow=on;});
    EnrollmentServer server([&](std::span<const uint8_t> p){return gate.persist(p);});
    server.arm_enrollment(true);
    assert(send_profile(server, bytes,115).code == AckCode::store_failed);
    assert(db.writes==1 && stop.load() && !db.allow);
    // Already committed bytes cannot be rolled back by USB STOP.
  }
  std::cout << "consent profile/NVS bridge host scenarios: PASS\n";
}
