// SPDX-License-Identifier: MIT
// Read-only source audit, NOT tested electrical routing or an audio driver.
// Origin: m5stack/StackChan@28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400
// firmware/main/hal/board/config.h. Observe board identity before enabling.
#pragma once

namespace stackchan::standalone::k151 {
constexpr int kInputHz = 24000;
constexpr int kOutputHz = 24000;
constexpr bool kHasInputReferenceChannel = true;
constexpr int kI2sMclk = 0;
constexpr int kI2sWs = 33;
constexpr int kI2sBclk = 34;
constexpr int kI2sDin = 14;
constexpr int kI2sDout = 13;
constexpr int kI2cSda = 12;
constexpr int kI2cScl = 11;
// MCLK and boot button share GPIO0 in the upstream board config.
constexpr int kBootButton = 0;
constexpr int kScreenWidth = 320;
constexpr int kScreenHeight = 240;
// Do not choose ILI9342C or ILI9342E without read-back detection.
constexpr bool kScreenTypeConfirmed = false;
// Real ES7210/AW88298 power-up and TDM format are NOT implemented.
constexpr bool kAudioCodecVerified = false;
static_assert(kI2sMclk == kBootButton);
}  // namespace stackchan::standalone::k151
