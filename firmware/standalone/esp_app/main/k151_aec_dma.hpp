// SPDX-License-Identifier: MIT
#pragma once

#include <driver/i2s_common.h>
#include <span>

namespace stackchan::standalone {

// The diagnostic has one static RX owner. The ISR copies only slot 1 and
// wipes the completed DMA buffer. The task never consumes the IDF RX queue.
bool attach_k151_aec_dma(i2s_chan_handle_t rx);
bool begin_k151_aec_dma();
void end_k151_aec_dma();
bool k151_aec_dma_faulted();
bool take_k151_aec_block(std::span<int16_t> destination, uint32_t& first_frame, int64_t& eof_us);

}  // namespace stackchan::standalone
