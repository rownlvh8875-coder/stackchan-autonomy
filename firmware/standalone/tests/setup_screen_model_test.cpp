#include "setup_screen_model.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string_view>

using namespace stackchan::standalone;

static bool ascii(const char* s) {
  if (!s || std::strlen(s)>48) return false;
  for (const unsigned char* p=reinterpret_cast<const unsigned char*>(s); *p; ++p) {
    if (*p < 32 || *p > 126) return false;
  }
  return true;
}
int main() {
  const std::array<TouchConsentPhase,15> touch_phases{
    TouchConsentPhase::hold, TouchConsentPhase::clear_for_arm,
    TouchConsentPhase::wait_arm_press, TouchConsentPhase::arm_press,
    TouchConsentPhase::arm_release, TouchConsentPhase::owner_window,
    TouchConsentPhase::clear_for_confirm, TouchConsentPhase::wait_confirm_press,
    TouchConsentPhase::confirm_press, TouchConsentPhase::confirm_release,
    TouchConsentPhase::confirmed, TouchConsentPhase::consumed,
    TouchConsentPhase::stopped, TouchConsentPhase::fault,
    TouchConsentPhase::hold
  };
  const std::array<OwnerSetupPhase,8> setup_phases{
    OwnerSetupPhase::hold,OwnerSetupPhase::wifi_input,
    OwnerSetupPhase::api_input,OwnerSetupPhase::confirm,
    OwnerSetupPhase::ready,OwnerSetupPhase::stopped,
    OwnerSetupPhase::fault,OwnerSetupPhase::hold
  };
  for (auto tp:touch_phases) for(auto op:setup_phases) for(bool verified:{false,true}) {
    auto frame=setup_screen_frame(tp,op,verified,false,false);
    assert(ascii(frame.title) && ascii(frame.line1) && ascii(frame.line2));
    for (auto literal : {frame.title,frame.line1,frame.line2}) {
      std::string_view s(literal);
      assert(s.find("fake-testing-token")==std::string_view::npos);
      assert(s.find("fake-passphrase")==std::string_view::npos);
      assert(s.find("test-ssid")==std::string_view::npos);
    }
    assert(setup_screen_frame(tp,op,verified,true,false).kind==SetupScreenKind::stopped);
    if(tp!=TouchConsentPhase::stopped && op!=OwnerSetupPhase::stopped)
      assert(setup_screen_frame(tp,op,verified,false,true).kind==SetupScreenKind::fault);
  }
  assert(setup_screen_frame(TouchConsentPhase::hold,OwnerSetupPhase::hold,false,false,false).kind==SetupScreenKind::locked);
  const auto arm = setup_screen_frame(
      TouchConsentPhase::clear_for_arm, OwnerSetupPhase::hold, false, false, false);
  assert(std::string_view(arm.line1) == "Wait for PC instruction");
  assert(std::string_view(arm.line2) == "Touch top for 3 sec, then lift");
  assert(setup_screen_frame(TouchConsentPhase::arm_press,OwnerSetupPhase::hold,false,false,false).kind==SetupScreenKind::hold_to_enter);
  assert(setup_screen_frame(TouchConsentPhase::owner_window,OwnerSetupPhase::hold,false,false,false).kind==SetupScreenKind::trusted_entry_required);
  assert(setup_screen_frame(TouchConsentPhase::owner_window,OwnerSetupPhase::wifi_input,true,false,false).kind==SetupScreenKind::enter_wifi);
  assert(setup_screen_frame(TouchConsentPhase::owner_window,OwnerSetupPhase::api_input,true,false,false).kind==SetupScreenKind::enter_api_key);
  assert(setup_screen_frame(TouchConsentPhase::owner_window,OwnerSetupPhase::confirm,true,false,false).kind==SetupScreenKind::review_on_pc);
  assert(setup_screen_frame(TouchConsentPhase::confirm_press,OwnerSetupPhase::confirm,true,false,false).kind==SetupScreenKind::hold_to_confirm);
  assert(setup_screen_frame(TouchConsentPhase::consumed,OwnerSetupPhase::ready,true,false,false).kind==SetupScreenKind::ready);
  assert(setup_screen_frame(TouchConsentPhase::owner_window,OwnerSetupPhase::ready,true,false,false).kind==SetupScreenKind::fault);
  std::cout<<"privacy-only setup screen state fixture: PASS\n";
}
