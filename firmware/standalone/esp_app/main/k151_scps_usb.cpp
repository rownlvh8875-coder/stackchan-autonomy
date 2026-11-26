// SPDX-License-Identifier: MIT
// Separate SCPS secure pairing, mutually exclusive with the SCFG voice
// enrollment USB driver and the USB console. No boot-time peripheral calls.
#include "k151_scps_usb.hpp"

#include <algorithm>
#include <array>
#include <driver/usb_serial_jtag.h>
#include <freertos/FreeRTOS.h>
#include <sdkconfig.h>
#include <string_view>

namespace stackchan::standalone {
namespace {
constexpr size_t kUsbReadChunk=96;
constexpr uint32_t kTxBuffer=512,kRxBuffer=512;
constexpr uint32_t kTxTicks=0;
constexpr uint32_t kFinalTxMs=250;
constexpr uint64_t kSessionMaxMs=120000;

#if !defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED)
bool open_scps_driver() {
  usb_serial_jtag_driver_config_t cfg{};
  cfg.tx_buffer_size=kTxBuffer;
  cfg.rx_buffer_size=kRxBuffer;
  return usb_serial_jtag_driver_install(&cfg)==ESP_OK;
}
#endif

bool send_scps_frame(scpswire::Op op,std::span<const uint8_t> payload) {
  const auto framed=scpswire::encode(op,payload);
  if(!framed)return false;
  const int count=usb_serial_jtag_write_bytes(framed->data(),framed->size(),kTxTicks);
  // Driver enqueue != proof of physical receipt; never automatically retry.
  return count==static_cast<int>(framed->size());
}
}

#ifdef STACKCHAN_K151_CONVERSATION_SETUP_PROBE
bool k151_probe_scps_tx() {
#if defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED)
  return false;
#else
  if(usb_serial_jtag_is_driver_installed() || !open_scps_driver())return false;
  // The shape and TX path match DEVICE_HELLO. Zero bytes cannot supply a
  // valid key exchange, and this diagnostic never accepts host input.
  const std::array<uint8_t,scpswire::kHelloBytes> fixture{};
  const bool drained=send_scps_frame(scpswire::Op::device_hello,fixture) &&
      usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(kFinalTxMs)+1)==ESP_OK;
  return usb_serial_jtag_driver_uninstall()==ESP_OK && drained;
#endif
}
#endif

const char* K151ScpsUsbPort::compiled_link_marker() {
  return "SCPW encrypted USB setup with local second-touch gate compiled; NOT STARTED";
}

K151ScpsUsbPort::~K151ScpsUsbPort() { (void)shutdown(); }

void K151ScpsUsbPort::scrub_pending() {
  if(!pending_.empty()) {
    wipe_secret(reinterpret_cast<volatile unsigned char*>(pending_.data()),
                pending_.size());
    pending_.clear();
  }
}

bool K151ScpsUsbPort::send(scpswire::Op op,std::span<const uint8_t> payload) {
  return running_ && send_scps_frame(op,payload);
}

bool K151ScpsUsbPort::start(uint64_t now,bool exact_board_verified,
                             bool trusted_lcd_verified,bool uart_console_verified,
                             bool usb_exclusively_owned) {
  if(attempted_ || stop_.load() || !exact_board_verified ||
     !trusted_lcd_verified || !uart_console_verified ||
     !usb_exclusively_owned || !display_.attached() ||
     &stop_!=&touch_.stop_ || &stop_!=&display_.stop_ || &stop_!=&setup_.stop_ ||
     &touch_.owner_mode_!=&setup_.owner_ ||
     !touch_.owner_window_open(now))return false;
#if defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED)
  // Never multiplex console, SCFG and secret setup over the same USB bytes.
  return false;
#else
  attempted_=true;
  if(usb_serial_jtag_is_driver_installed())return fault();
  std::array<uint8_t,K151SecurePcSetup::kHelloBytes> hello{};
  if(!pairing_.device_hello(now,touch_.owner_window_open(now),
                            trusted_lcd_verified,hello))return fault();

  if(!open_scps_driver())return fault();
  running_=true;
  trusted_lcd_=trusted_lcd_verified;
  began_ms_=now;
  state_=State::wait_pc_hello;
  const bool sent=send(scpswire::Op::device_hello,hello);
  std::fill(hello.begin(),hello.end(),uint8_t(0));
  return sent || fault();
#endif
}

bool K151ScpsUsbPort::process(const scpswire::Frame& f,uint64_t now,
                                bool lvgl_lock_held) {
  if(stop_.load() || !touch_.owner_window_open(now))return fault();
  if(f.kind==scpswire::Op::stop)return fault();
  if(state_==State::wait_pc_hello && f.kind==scpswire::Op::pc_hello) {
    std::array<char,9> sas{};
    const bool accepted=pairing_.accept_pc_hello(
        now,true,f.payload,sas);
    const bool shown=accepted && display_.present_pairing_sas(
        std::string_view(sas.data(),8),trusted_lcd_,true,lvgl_lock_held);
    wipe_secret(reinterpret_cast<volatile unsigned char*>(sas.data()),
                sas.size());
    if(!shown)return fault();
    state_=State::wait_sealed;
    return send(scpswire::Op::display_ready) || fault();
  }
  if(state_==State::wait_sealed && f.kind==scpswire::Op::sealed_credentials) {
    if(!pending_.empty() || f.payload.size()>K151SecurePcSetup::kMaxSealedBytes)
      return fault();
    if(!display_.begin_pairing_review(now,lvgl_lock_held))return fault();
    pending_=f.payload; // ciphertext only; validated later via AES-GCM.
    state_=State::pending_local_review;
    return send(scpswire::Op::pending_touch) || fault();
  }
  // Any replay, out-of-order packet or spurious SCFG header is terminal.
  return fault();
}

bool K151ScpsUsbPort::poll_once(uint64_t now,bool lvgl_lock_held) {
  if(!running_ || faulted_)return false;
  if(stop_.load())return fault();
  // A successful second-touch ticket is CONSUMED, which means the sensor's
  // owner_window_open() becomes false. Never treat that as a fresh failure.
  if(state_==State::complete)return true;
  if(now<began_ms_ || now-began_ms_>=kSessionMaxMs ||
     !touch_.owner_window_open(now) ||
     !frames_.tick(now))return fault();
  std::array<uint8_t,kUsbReadChunk> data{};
  const int count=usb_serial_jtag_read_bytes(data.data(),data.size(),0);
  if(count<0 || static_cast<size_t>(count)>data.size())return fault();
  for(int i=0;i<count;++i) {
    if(stop_.load())return fault();
    auto received=frames_.push(data[static_cast<size_t>(i)],now);
    if(received.fault)return fault();
    if(received.frame) {
      const bool accepted=process(*received.frame,now,lvgl_lock_held);
      std::fill(received.frame->payload.begin(),
                received.frame->payload.end(),uint8_t(0));
      if(!accepted)return false;
    }
  }
  if(state_==State::pending_local_review) {
    const auto review=display_.poll_pairing_review(now,lvgl_lock_held);
    if(review==K151SetupLvgl::ReviewResult::fault)return fault();
    if(review==K151SetupLvgl::ReviewResult::approved) {
      if(!touch_.start_scps_final_touch(true,now))return fault();
      state_=State::waiting_touch;
    }
  }
  return true;
}

bool K151ScpsUsbPort::finalize_after_touch(uint64_t now) {
  if(!running_ || state_!=State::waiting_touch || stop_.load() ||
     now<began_ms_ || now-began_ms_>=kSessionMaxMs)
    return false;
  if(!touch_.owner_window_open(now))return false;
  if(!touch_.take_scps_final_touch(now))return false;
  // One physical touch token has now been irrevocably consumed.
  PairingCredentials credentials;
  const bool opened=pairing_.open_sealed(
      now,true,true,pending_,credentials);
  scrub_pending();
  if(!opened || !credentials.valid())return fault();
  const bool started=setup_.arm(now);
  const bool wifi=started && setup_.submit_wifi(
      credentials.ssid(),
      std::string_view(credentials.password().data(),
                       credentials.password().size()),now);
  const bool key=wifi && setup_.submit_api_key(
      std::string_view(credentials.api_key().data(),
                       credentials.api_key().size()),now);
  const bool confirmed=key && setup_.confirm(now,true);
  credentials.clear();
  if(!confirmed || !setup_.ready())return fault();
  state_=State::complete;
  return true;
}

bool K151ScpsUsbPort::close_completed_transport() {
  if (!running_ || state_ != State::complete || !setup_.ready() || stop_.load())
    return fault();
  if (!send(scpswire::Op::completed) ||
      usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(kFinalTxMs) + 1) != ESP_OK ||
      stop_.load() || !shutdown()) return fault();
  return true;
}

bool K151ScpsUsbPort::fault() {
  faulted_=true;
  // Even a post-success physical STOP cancels the still-in-RAM setup.
  setup_.stop();
  touch_.revoke();
  (void)shutdown();
  state_=State::fault;
  return false;
}

bool K151ScpsUsbPort::shutdown() {
  frames_.invalidate();
  scrub_pending();
  pairing_.stop();
  if(state_!=State::complete || stop_.load())setup_.stop();
  if(state_!=State::complete || stop_.load())touch_.revoke();
  state_=state_==State::complete?State::complete:State::stopped;
  if(running_ && usb_serial_jtag_driver_uninstall()!=ESP_OK) {
    faulted_=true;
    return false;
  }
  running_=false;
  return true;
}

} // namespace stackchan::standalone
