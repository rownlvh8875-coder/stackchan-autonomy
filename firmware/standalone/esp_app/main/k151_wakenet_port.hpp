// SPDX-License-Identifier: MIT
// Dormant native model adapter. No construction/startup from app_main.
#pragma once
#include "native_wake_port.hpp"
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
  // These gates never accept SCFG, remote or user-provided network booleans.
  bool prepare(bool local_owner,bool model_assets_verified);
  bool ready() const override;
  NativeWakeFormat format() const override {return ready()?format_:NativeWakeFormat{};}
  NativeWakeResult detect(std::span<int16_t> pcm) override;
  bool reset() override;
  void close();
  static const char* compiled_link_marker();
 private:
  srmodel_list_t* models_=nullptr;
  const esp_wn_iface_t* iface_=nullptr;
  model_iface_data_t* data_=nullptr;
  NativeWakeFormat format_{};
  bool attempted_=false,faulted_=false;
};
} // namespace stackchan::standalone
