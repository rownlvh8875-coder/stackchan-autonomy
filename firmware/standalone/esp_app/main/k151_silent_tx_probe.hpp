// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>

namespace stackchan::standalone {

enum class K151SilentTxResult {
  denied, stopped, channel_failed, preload_failed, callback_failed, enable_failed,
  timeout, invalid_event, clock_fault, cleanup_failed, observed,
};

// One shot in a dedicated diagnostic app. Creates internal DMA only and routes
// no pins. Observed means two DMA descriptors completed and the channel closed.
K151SilentTxResult run_k151_silent_tx_probe(const std::atomic_bool& owner,
                                           const std::atomic_bool& stop);

}  // namespace stackchan::standalone
