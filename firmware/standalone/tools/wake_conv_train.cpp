// SPDX-License-Identifier: MIT
// Host-only tiny 1D CNN training from synthetic calibration TSV.
#include "offline_conv_kws.hpp"
#include "offline_linear_kws_io.hpp"

#include <iostream>
#include <set>
#include <vector>

using namespace stackchan::standalone;

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "REJECTED_CNN_TRAINING\n";
    return 2;
  }
  const auto manifest=offline_labeled_manifest(argv[1]);
  if (!manifest) return 2;
  std::vector<LinearKwsExample> data;
  std::set<uint64_t> fingerprints;
  unsigned wakes=0, others=0;
  for (const auto& row : *manifest) {
    uint64_t fingerprint=0;
    const auto feature=offline_labeled_feature(row.path,fingerprint);
    if (!feature || !fingerprints.insert(fingerprint).second) return 2;
    data.push_back({*feature,row.wake});
    if (row.wake) ++wakes;
    else ++others;
  }
  const auto model=train_conv_kws(data);
  if (!model) return 2;
  const auto encoded=encode_conv_kws(*model);
  if (!encoded || !decode_conv_kws(*encoded)) return 2;
  if (!offline_write_exclusive(argv[2],*encoded)) return 2;
  std::cout << "UNVERIFIED_SYNTHETIC_TINY_CNN_TRAINING\n"
            << "wake_training_count=" << wakes << "\n"
            << "nonwake_training_count=" << others << "\n"
            << "model_bytes=" << encoded->size() << "\n"
            << "model_type=1D_TEMPORAL_CONV_RELU_POOLED_MFCC_NOT_ASR\n"
            << "fixed_logit_threshold_zero=true; NO K151/device/API\n";
  return 0;
}
