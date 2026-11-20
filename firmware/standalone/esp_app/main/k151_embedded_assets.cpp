// SPDX-License-Identifier: MIT
#include "k151_wakenet_port.hpp"
#include <esp_memory_utils.h>
#include <psa/crypto.h>
#include <array>

namespace stackchan::standalone {
bool K151WakeNetPort::prepare_embedded(const std::atomic_bool& owner,
    const std::atomic_bool& stop,std::span<const uint8_t> pack) {
  const auto allowed=[&] {return owner.load() && !stop.load();};
  if(local_assets_attempted_ || attempted_ || !allowed())return false;
  local_assets_attempted_=true;
  // srmodel_load has no length parameter. Never parse unverified/mutable data.
  if(pack.size()!=292607 || !pack.data() || !esp_ptr_in_drom(pack.data()) ||
     !esp_ptr_in_drom(pack.data()+pack.size()-1) || esp_ptr_external_ram(pack.data()) ||
     esp_ptr_external_ram(pack.data()+pack.size()-1))return false;
  constexpr std::array<uint8_t,32> expected{
    0x02,0x55,0x85,0x5e,0x56,0xbf,0x72,0xd1,0xe0,0x72,0xd2,0xe0,0xcb,0xee,0x4f,0xb3,
    0xce,0x1a,0xc2,0xc4,0x8f,0x7f,0xee,0x6c,0x8c,0xd5,0x91,0xf8,0x3e,0x59,0xed,0x95};
  std::array<uint8_t,32> digest{};
  size_t produced=0;
  // Pinned IDF6.1 uses Mbed TLS4.1 / PSA Crypto, not legacy sha256.h.
  // No keys or persistent-storage operations. Do not free shared PSA globals.
  if(psa_crypto_init()!=PSA_SUCCESS || !allowed() ||
     psa_hash_compute(PSA_ALG_SHA_256,pack.data(),pack.size(),digest.data(),
                      digest.size(),&produced)!=PSA_SUCCESS ||
     produced!=digest.size() || digest!=expected || !allowed())return false;
  if(!prepare_verified(allowed(),true,&owner,&stop,pack.data()))return false;
  if(!allowed()) {close();return false;}
  return ready();
}
} // namespace stackchan::standalone
