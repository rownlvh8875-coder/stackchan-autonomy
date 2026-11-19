#include "board_evidence.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>

using stackchan::standalone::k151::Device;
using stackchan::standalone::k151::PanelHint;
using stackchan::standalone::k151::ReadOnlyEvidence;
using stackchan::standalone::k151::ReferenceAction;
using stackchan::standalone::k151::expected_devices_acknowledged;
using stackchan::standalone::k151::index;
using stackchan::standalone::k151::kAw88298ResetReference;
using stackchan::standalone::k151::panel_hint;

int main() {
  ReadOnlyEvidence e;
  assert(panel_hint(e) == PanelHint::unknown);
  assert(!expected_devices_acknowledged(e));
  e.bus_opened = true;
  e.finished_without_bus_error = true;
  e.acknowledged.fill(true);
  assert(expected_devices_acknowledged(e));
  assert(panel_hint(e) == PanelHint::unknown);
  e.touch_version_read = true;
  e.touch_version = {0x51, 0x22, 0, 0x12, 0, 0x11};
  assert(panel_hint(e) == PanelHint::ili9342e_candidate);
  e.touch_version[0] = 0;
  assert(panel_hint(e) == PanelHint::unknown);
  e.touch_version[0] = 0x51;
  e.touch_version[3] = 0x10;
  assert(panel_hint(e) == PanelHint::unknown);  // Never call this ILI9342C.
  e.touch_version[3] = 0x12;
  e.acknowledged[index(Device::touch_ft6336)] = false;
  assert(panel_hint(e) == PanelHint::unknown);
  assert(!expected_devices_acknowledged(e));
  e.acknowledged.fill(true);
  e.finished_without_bus_error = false;
  assert(panel_hint(e) == PanelHint::unknown);
  assert(!expected_devices_acknowledged(e));
  static_assert(kAw88298ResetReference.size() == 4);
  assert(kAw88298ResetReference[0].action == ReferenceAction::write_register);
  assert(kAw88298ResetReference[0].reg == 0x02);
  assert(kAw88298ResetReference[0].value == 0x03);
  assert(kAw88298ResetReference[1].delay_ms == 10);
  assert(kAw88298ResetReference[2].value == 0x07);
  assert(kAw88298ResetReference[3].delay_ms == 50);
  std::cout << "board evidence: PASS (no false C panel or reset arming)\n";
}
