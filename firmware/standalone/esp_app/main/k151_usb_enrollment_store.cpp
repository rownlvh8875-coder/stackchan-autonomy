// SPDX-License-Identifier: MIT
// Never instantiated from the HOLD application entrypoint.
#include "k151_usb_enrollment_store.hpp"

namespace stackchan::standalone {
const char* K151UsbEnrollmentStorage::compiled_link_marker() {
  return "SWK1 SCFG -> owner-gated verified sc_gpt NVS bridge compiled; NOT STARTED";
}
}  // namespace stackchan::standalone
