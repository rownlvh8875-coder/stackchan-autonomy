// SPDX-License-Identifier: MIT
// Interpretation-only source evidence; NEVER grants permission to power a K151.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace stackchan::standalone::k151 {

enum class Device : std::size_t {
  pmic_axp2101 = 0,
  io_aw9523 = 1,
  touch_ft6336 = 2,
  mic_es7210 = 3,
  amp_aw88298 = 4,
  count = 5,
};

enum class PanelHint { unknown, ili9342e_candidate };

// IDF uses seven-bit addresses. esp_codec_dev 1.6.2's ES7210 (0x80)
// and AW88298 (0x6c) constants are eight-bit and its own adapter shifts them.
constexpr std::array<std::uint16_t, 5> kProbeAddresses{0x34, 0x58, 0x38, 0x40, 0x36};
// Only known configuration registers, not interrupt/input/clear-on-read state.
constexpr std::array<std::uint8_t, 5> kPmicLdoRegisters{0x90, 0x94, 0x95, 0x97, 0x99};
// The CoreS3 drawing routes ALDO1/2 to VDD_1V8/VDDA_3V3.
constexpr std::array<std::uint8_t, 2> kPmicAldo12Registers{0x92, 0x93};
constexpr std::uint8_t kAw9523P0ModeRegister = 0x12;

// Dedicated diagnostic scope, never a board identity or audio authorization.
constexpr bool board_probe_location_allowed(std::uint32_t address, std::size_t bytes,
                                            bool esp32s3, std::uint16_t revision) {
  return address == 0x510000 && bytes == 0x4f0000 && esp32s3 && revision == 2;
}

struct ReadOnlyEvidence {
  bool bus_opened = false;
  std::array<bool, static_cast<std::size_t>(Device::count)> acknowledged{};
  bool touch_version_read = false;
  std::array<std::uint8_t, 6> touch_version{};
  bool pmic_id_read = false;
  std::uint8_t pmic_id = 0;
  bool pmic_ldo_read = false;
  std::array<std::uint8_t, 5> pmic_ldo{};
  bool pmic_aldo12_read = false;
  std::array<std::uint8_t, 2> pmic_aldo12{};
  bool aw9523_id_read = false;
  std::uint8_t aw9523_id = 0;
  bool aw9523_outputs_read = false;
  std::array<std::uint8_t, 2> aw9523_outputs{};
  bool aw9523_directions_read = false;
  std::array<std::uint8_t, 2> aw9523_directions{};
  bool aw9523_p0_mode_read = false;
  std::uint8_t aw9523_p0_mode = 0;
  bool finished_without_bus_error = false;
};

enum class PowerSample : std::uint8_t {
  not_seen, id_mismatch, disabled, powered_down, reset_value, invalid, sampled,
};

struct PowerReadback {
  PowerSample pmic_vsys = PowerSample::not_seen;
  std::uint16_t pmic_vsys_mv = 0;
  PowerSample amp_vdd = PowerSample::not_seen;
  std::uint16_t amp_vdd_mv = 0;
  bool amp_uvls_valid = false;
  bool amp_uvls = false;
};

constexpr std::size_t index(Device device) {
  return static_cast<std::size_t>(device);
}

constexpr bool ft6336_9342e_signature(const std::array<std::uint8_t, 6>& version) {
  return version[0] != 0 && version[3] == 0x12 && version[5] == 0x11;
}

// M5Stack official source reads FT6336 at register 0xA3 (six bytes).
// It uses a separate write to enter work mode; this observer NEVER sends it.
// It consequently cannot claim to have definitively identified an LCD.
constexpr PanelHint panel_hint(const ReadOnlyEvidence& evidence) {
  if (!evidence.finished_without_bus_error ||
      !evidence.acknowledged[index(Device::touch_ft6336)] ||
      !evidence.touch_version_read) {
    return PanelHint::unknown;
  }
  if (ft6336_9342e_signature(evidence.touch_version)) {
    return PanelHint::ili9342e_candidate;
  }
  // Never infer ILI9342C from a failed/mismatched read.
  return PanelHint::unknown;
}

constexpr bool expected_devices_acknowledged(const ReadOnlyEvidence& evidence) {
  if (!evidence.bus_opened || !evidence.finished_without_bus_error) return false;
  for (const bool seen : evidence.acknowledged) {
    if (!seen) return false;
  }
  return true;
}

// The manufacturer code toggles AW9523 P0 register 0x02 to reset AW88298.
// Reference sequence ONLY. There is deliberately no executor or I2C writer.
enum class ReferenceAction { write_register, delay_ms };
struct ReferenceStep {
  ReferenceAction action;
  std::uint8_t reg;
  std::uint8_t value;
  std::uint16_t delay_ms;
};
constexpr std::array<ReferenceStep, 4> kAw88298ResetReference{{
    {ReferenceAction::write_register, 0x02, 0x03, 0},
    {ReferenceAction::delay_ms, 0, 0, 10},
    {ReferenceAction::write_register, 0x02, 0x07, 0},
    {ReferenceAction::delay_ms, 0, 0, 50},
}};

}  // namespace stackchan::standalone::k151
