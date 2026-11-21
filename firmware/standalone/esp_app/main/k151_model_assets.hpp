// SPDX-License-Identifier: MIT
// Draft, read-only native-model placement contract; never installs a partition.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
namespace stackchan::standalone {
inline constexpr uint32_t kNativeModelPartitionOffset = 0x00f00000;
inline constexpr size_t kNativeModelPartitionBytes = 1048576;
// Exact 292607-byte pinned ESP-SR pack followed by 0xff to the partition end.
inline constexpr char kNativeModelPartitionSha256[] =
    "1d04bf6a1f6775d43ab4398bbbac1bc4606f5c4130fe1a853851ec5df7f21d1b";
bool verify_k151_model_assets(const std::atomic_bool& local_owner,
                             const std::atomic_bool& physical_stop);
} // namespace stackchan::standalone
