// SPDX-License-Identifier: MIT
// Offline voice schema compile marker ONLY. No transport object is constructed.
#include "offline_voice_cycle.hpp"

namespace stackchan::standalone {
const char* offline_voice_cycle_compiled_marker() {
  return "Offline STT->Responses->PCM-TTS contract compiled; no API calls";
}
}  // namespace stackchan::standalone
