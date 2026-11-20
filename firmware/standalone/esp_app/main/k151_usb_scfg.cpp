// SPDX-License-Identifier: MIT
// Dedicated native ESP32-S3 USB Serial/JTAG SCFG framed receiver, dormant.
#include "k151_usb_scfg.hpp"

#include <algorithm>
#include <array>
#include <driver/usb_serial_jtag.h>
#include <freertos/FreeRTOS.h>
#include <sdkconfig.h>

namespace stackchan::standalone {
namespace {
constexpr size_t kReadChunk = 96;
constexpr uint32_t kUsbTxBufferSize = 256;
constexpr uint32_t kUsbRxBufferSize = 512;
constexpr uint32_t kTxBoundedTicks = 0;
}

const char* K151ScfgUsbPort::compiled_link_marker() {
  return "Dedicated SCFG USB/JTAG receiver compiled; disabled at boot";
}

bool K151ScfgUsbPort::start(bool local_owner_mode, bool uart_console_verified,
                            bool durable_profile_store_ready,
                            const std::atomic_bool& stop_latch) {
  if (ever_started_ || running_ || faulted_ || !local_owner_mode ||
      !uart_console_verified || !durable_profile_store_ready ||
      stop_latch.load()) return false;
#if defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED)
  // Never mix SCFG and device console bytes on one stream.
  return false;
#else
  if (usb_serial_jtag_is_driver_installed()) return false;
  usb_serial_jtag_driver_config_t config = {};
  config.tx_buffer_size = kUsbTxBufferSize;
  config.rx_buffer_size = kUsbRxBufferSize;
  ever_started_ = true;  // Prevent silent recovery/reopen on uncertain state.
  if (usb_serial_jtag_driver_install(&config) != ESP_OK) {
    faulted_ = true;
    return false;
  }
  running_ = true;
  enrollment_.arm_enrollment(true);  // Not available through a USB opcode.
  return true;
#endif
}

void K151ScfgUsbPort::latch_local_stop() {
  if (local_stop_latched_) return;
  local_stop_latched_ = true;
  reader_.reset();
  // Physical stop and remote STOP share the non-restartable server latch.
  // This does not send an ACK or expose any personalized payload.
  (void)enrollment_.handle(Frame{Op::stop, 1, 0, {}});
}

void K151ScfgUsbPort::fail() {
  faulted_ = true;
  latch_local_stop();
}

bool K151ScfgUsbPort::poll_once(std::uint64_t monotonic_ms,
                               const std::atomic_bool& stop_latch) {
  if (!running_ || faulted_) return false;
  if (stop_latch.load()) latch_local_stop();
  std::array<uint8_t, kReadChunk> input{};
  const int count = usb_serial_jtag_read_bytes(input.data(), input.size(), 0);
  if (count < 0 || static_cast<size_t>(count) > input.size()) {
    fail();
    return false;
  }
  for (int i = 0; i < count; ++i) {
    if (stop_latch.load()) latch_local_stop();
    auto frame = reader_.push(input[static_cast<size_t>(i)], monotonic_ms);
    if (!frame) continue;
    const Ack answer = enrollment_.handle(*frame);
    std::fill(frame->payload.begin(), frame->payload.end(), 0U);
    const auto reply = encode_ack(answer);
    const int written = usb_serial_jtag_write_bytes(reply.data(), reply.size(),
                                                    kTxBoundedTicks);
    if (written != static_cast<int>(reply.size())) {
      std::fill(input.begin(), input.end(), 0U);
      fail();
      return false;
    }
    // Driver-accepted bytes != physical delivery proof. A future runtime must
    // track bounded TX drain and independently obey physical STOP.
  }
  std::fill(input.begin(), input.end(), 0U);
  return true;
}

bool K151ScfgUsbPort::shutdown() {
  latch_local_stop();
  if (!running_) return !faulted_;
  const esp_err_t result = usb_serial_jtag_driver_uninstall();
  running_ = false;
  if (result != ESP_OK) faulted_ = true;
  return !faulted_;
}

}  // namespace stackchan::standalone
