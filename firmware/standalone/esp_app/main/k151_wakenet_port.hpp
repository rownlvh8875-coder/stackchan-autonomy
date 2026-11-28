// SPDX-License-Identifier: MIT
// Dormant native model adapter. No construction/startup from app_main.
#pragma once
#include "native_wake_port.hpp"
#include <atomic>
#include <esp_wn_iface.h>
#include <model_path.h>
namespace stackchan::standalone {
class K151WakeNetPort final: public NativeWakePort {
 public:
  K151WakeNetPort()=default;
  K151WakeNetPort(const K151WakeNetPort&)=delete;
  K151WakeNetPort& operator=(const K151WakeNetPort&)=delete;
  ~K151WakeNetPort() override {close();}
  // Local bootstrap must verify asset integrity/memory and obtain owner consent.
  // One live port owns the SDK global loader; other SDK users must be absent.
  // These gates never accept SCFG, remote or user-provided network booleans.
  bool prepare(bool local_owner,bool model_assets_verified);
  // Operational bootstrap uses actual local partition SHA and atomic consent.
  // Model allocation is separate from runtime mic/cloud memory admission.
  // No remote wire handler calls this; app_main remains dormant.
  // Atomic consent and STOP flags must outlive the port.
  bool prepare_local(const std::atomic_bool& local_owner,
                     const std::atomic_bool& physical_stop);
  bool prepare_local(const std::atomic_bool&&,const std::atomic_bool&)=delete;
  bool prepare_local(const std::atomic_bool&,const std::atomic_bool&&)=delete;
  // Static read-only ELF data only. Exact length + SHA before SDK parsing.
  // The same flag lifetime contract applies to the embedded source.
  bool prepare_embedded(const std::atomic_bool& local_owner,
                        const std::atomic_bool& physical_stop,
                        std::span<const uint8_t> pack);
  bool prepare_embedded(const std::atomic_bool&&,const std::atomic_bool&,
                        std::span<const uint8_t>)=delete;
  bool prepare_embedded(const std::atomic_bool&,const std::atomic_bool&&,
                        std::span<const uint8_t>)=delete;
  bool ready() const override;
  NativeWakeFormat format() const override {return ready()?format_:NativeWakeFormat{};}
  NativeWakeResult detect(std::span<int16_t> pcm) override;
  bool reset() override;
  void close();
  static const char* compiled_link_marker();
 private:
  bool prepare_verified(bool local_owner,bool assets_verified,
                        const std::atomic_bool* live_owner=nullptr,
                        const std::atomic_bool* physical_stop=nullptr,
                        const void* embedded=nullptr);
  NativeWakeFormat checked_context_format() const;
  bool reset_allowed() const;
  void fault();
  srmodel_list_t* models_=nullptr;
  const esp_wn_iface_t* iface_=nullptr;
  model_iface_data_t* data_=nullptr;
  const char* model_name_=nullptr; // Borrowed from the exclusively owned model list.
  const std::atomic_bool* live_owner_=nullptr;
  const std::atomic_bool* physical_stop_=nullptr;
  NativeWakeFormat format_{};
  bool attempted_=false,faulted_=false,owns_loader_=false,local_assets_attempted_=false;
  bool embedded_=false;
};
} // namespace stackchan::standalone
