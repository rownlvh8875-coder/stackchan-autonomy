// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <optional>

namespace stackchan::standalone {
// The GPIO timer's sampled time is later than the electrical edge. These
// software timestamps do not measure the amplifier output or its mute time.
constexpr std::optional<uint32_t> sampled_stop_to_standby_us(
    int64_t first_write, int64_t stop_sampled, int64_t transfer_returned, int64_t standby_verified) {
  if (first_write < 0 || stop_sampled < first_write || transfer_returned < stop_sampled ||
      standby_verified < transfer_returned || standby_verified - stop_sampled > 10'000'000)
    return std::nullopt;
  return static_cast<uint32_t>(standby_verified - stop_sampled);
}
} // namespace stackchan::standalone
