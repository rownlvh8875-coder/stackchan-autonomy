// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <optional>

namespace stackchan::standalone {
// The GPIO timer's sampled time is later than the electrical edge. These
// software timestamps do not measure the amplifier output or its mute time.
constexpr std::optional<uint32_t> sampled_stop_elapsed_us(
    int64_t first_write, int64_t stop_sampled, int64_t transfer_returned, int64_t verified_at) {
  if (first_write < 0 || stop_sampled < first_write || transfer_returned < stop_sampled ||
      verified_at < transfer_returned || verified_at - stop_sampled > 10'000'000)
    return std::nullopt;
  return static_cast<uint32_t>(verified_at - stop_sampled);
}
} // namespace stackchan::standalone
