// SPDX-License-Identifier: MIT
// Train a tiny linear MFCC classifier OFFLINE; fixed SGD hyperparameters.
// This is NOT a phoneme model, user authentication or K151 installation.
#include "offline_linear_kws_io.hpp"
#include <iostream>
#include <set>
#include <vector>

using namespace stackchan::standalone;

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "REJECTED_LINEAR_TRAINING; usage requires private TSV and NEW model\n";
    return 2;
  }
  const auto paths = offline_labeled_manifest(argv[1]);
  if (!paths || paths->size() > kLinearKwsMaxTrainingExamples)
    return 2;
  size_t positive = 0, negative = 0;
  std::vector<LinearKwsExample> training;
  std::set<uint64_t> fingerprints;
  for (const auto& item : *paths) {
    uint64_t fingerprint = 0;
    auto feature = offline_labeled_feature(item.path, fingerprint);
    if (!feature || !fingerprints.insert(fingerprint).second)
      return 2;
    training.push_back({*feature, item.wake});
    if (item.wake) ++positive;
    else ++negative;
  }
  const auto model = train_linear_kws(training);
  if (!model) return 2;
  const auto binary = encode_linear_kws(*model);
  if (!binary || !decode_linear_kws(*binary)) return 2;
  if (!offline_write_exclusive(argv[2], *binary)) return 2;
  std::cout << "UNVERIFIED_SYNTHETIC_LINEAR_KWS_TRAINING\n"
            << "wake_training_count=" << positive << "\n"
            << "nonwake_training_count=" << negative << "\n"
            << "model_bytes=" << binary->size() << "\n"
            << "model_type=MFCC_TEMPORAL_POOLED_LOGISTIC_NOT_PHONEME_MODEL\n"
            << "fixed_zero_logit_threshold=true; no K151/device/API used\n";
  return 0;
}
