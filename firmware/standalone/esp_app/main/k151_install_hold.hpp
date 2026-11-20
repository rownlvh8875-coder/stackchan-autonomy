// SPDX-License-Identifier: MIT
// Never construct or run hardware controls from HOLD firmware.
#pragma once
namespace stackchan::standalone {
class K151InstallHold final {
 public:
  static const char* compiled_link_marker();
  static constexpr bool kDeviceActivationEnabled = false;
};
}  // namespace stackchan::standalone
