// SPDX-License-Identifier: MIT
#pragma once
#include "board_evidence.hpp"
#include <cstdint>
#include <optional>

namespace stackchan::standalone {

// Stable numeric codes for the bounded speaker probe report.
enum class K151SpeakerCleanupStage : uint8_t {
  none, standby_request, output_disable, standby_readback, amplifier_reset,
  codec_release, codec_control, interface_release, i2s_disable, i2s_release,
  i2c_release, previous_fault,
};

// First failed checkpoint, with no register values or audio in the report.
enum class K151SpeakerStartupStage : uint8_t {
  none, audio_guard, admission, codec_open, codec_ready, i2s_tx_state, volume,
  muted_admission, clock_origin, standby_readback, i2s_enable, clock_enable, wait_clock,
  mute_readback, pre_amplifier_status, amplifier_enable, wait_switching, attenuation, pre_unmute_status,
  unmute, post_unmute_status,
};

enum class K151ClockWaitExit : uint8_t {
  none, admission_lost, timer_regressed, startup_deadline, poll_limit,
  status_read_failed, protection_active, early_switching,
};

enum class K151ClockWaitSample : uint8_t {
  none, unobserved, reference_missing, pll_unlocked, internal_unstable, stable,
};

// AW88298 SYSST protection indicators. Only these bits may enter the diagnostic.
namespace aw88298_protection {
inline constexpr uint16_t ovp2 = 0x8000;
inline constexpr uint16_t undervoltage = 0x4000;
inline constexpr uint16_t boost_overcurrent = 0x0800;
inline constexpr uint16_t ovp = 0x0400;
inline constexpr uint16_t amplifier_overcurrent = 0x0008;
inline constexpr uint16_t overtemperature = 0x0002;
inline constexpr uint16_t mask =
    ovp2 | undervoltage | boost_overcurrent | ovp | amplifier_overcurrent | overtemperature;
} // namespace aw88298_protection

struct K151SpeakerStartupDiagnostic {
  K151SpeakerStartupStage stage = K151SpeakerStartupStage::none;
  K151ClockWaitExit clock_wait_exit = K151ClockWaitExit::none;
  K151ClockWaitSample clock_wait_last = K151ClockWaitSample::none;
  uint16_t protection_flags = 0;
  int32_t uvls_after_clock_us = -1;
  int32_t vdd_after_uvls_us = -1;
  k151::VoltageReading vdd{};
  std::optional<bool> standby_uvls{};
  std::optional<bool> uvls_after_vdd{};
  int32_t uvls_after_vdd_us = -1;
  int32_t settling_uvls_us = -1;
  int32_t clock_ready_after_uvls_us = -1;
};

struct K151SpeakerResetObservations {
  std::optional<bool> before_tx{};
  std::optional<bool> before_codec_init{};
  std::optional<bool> after_codec_init{};
};

} // namespace stackchan::standalone
