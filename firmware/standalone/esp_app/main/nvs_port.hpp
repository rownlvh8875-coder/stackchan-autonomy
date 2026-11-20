// SPDX-License-Identifier: MIT
#pragma once
#include "persistent_store.hpp"

namespace stackchan::standalone {

// Scoped solely to the new 'sc_gpt' namespace. Never imports manufacturer
// namespaces or invokes nvs_flash_erase() under any circumstances.
// NVS writes require an explicit local confirmation; no USB opcode can arm it.
class IsolatedNvs : public AtomicKv {
 public:
  // Called only by the standalone app, after a later installation decision.
  bool init_without_erase();
  ReadValue read(std::string_view key, size_t max_bytes) override;
  bool commit(std::string_view key, std::span<const uint8_t> bytes) override;
  void set_local_write_approval(bool enabled) { approved_ = enabled; }

 private:
  bool initialized_ = false;
  bool approved_ = false;
};

}  // namespace stackchan::standalone
