// SPDX-License-Identifier: MIT
#include "k151_model_assets.hpp"
#include "k151_wakenet_port.hpp"
#include <esp_flash.h>
#include <esp_partition.h>
#include <array>
#include <cstring>

namespace stackchan::standalone {
namespace {
bool allowed(const std::atomic_bool& owner,const std::atomic_bool& stop) {
  return owner.load() && !stop.load();
}
uint8_t nibble(char c) {
  return static_cast<uint8_t>(c<='9'?c-'0':c-'a'+10);
}
}
bool verify_k151_model_assets(const std::atomic_bool& owner,
                             const std::atomic_bool& stop) {
  if(!allowed(owner,stop))return false;
  const auto* p=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                        ESP_PARTITION_SUBTYPE_ANY,"model");
  if(!allowed(owner,stop) || !p || p->flash_chip!=esp_flash_default_chip ||
     p->type!=ESP_PARTITION_TYPE_DATA || std::memcmp(p->label,"model",6)!=0 ||
     p->address!=kNativeModelPartitionOffset || p->size!=kNativeModelPartitionBytes ||
     p->encrypted || !p->readonly)return false;
  std::array<uint8_t,32> digest{};
  // IDF hashes the ENTIRE data partition, including padding. No app-image hash
  // shortcut, temporary mmap lifecycle, new crypto, or caller-supplied digest.
  if(esp_partition_get_sha256(p,digest.data())!=ESP_OK || !allowed(owner,stop))
    return false;
  for(size_t i=0;i<digest.size();++i) {
    const auto expected=static_cast<uint8_t>((nibble(kNativeModelPartitionSha256[i*2])<<4)|
                                            nibble(kNativeModelPartitionSha256[i*2+1]));
    if(digest[i]!=expected)return false;
  }
  return allowed(owner,stop);
}
bool K151WakeNetPort::prepare_local(const std::atomic_bool& owner,
                                   const std::atomic_bool& stop) {
  if(local_assets_attempted_ || attempted_ || !allowed(owner,stop))return false;
  local_assets_attempted_=true; // Failed verification needs a new local lifecycle.
  const bool verified=verify_k151_model_assets(owner,stop);
  const bool owner_now=allowed(owner,stop);
  if(!prepare_verified(owner_now,verified,&owner,&stop))return false;
  if(!allowed(owner,stop)) {close();return false;}
  return ready();
}
} // namespace stackchan::standalone
