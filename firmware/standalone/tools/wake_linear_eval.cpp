// SPDX-License-Identifier: MIT
// Compare a frozen host-only linear model with labeled WAVs; no file writes.
#include "offline_linear_kws_io.hpp"
#include <iostream>
#include <set>

using namespace stackchan::standalone;

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "REJECTED_LINEAR_EVALUATION\n";
    return 2;
  }
  const auto bytes = offline_read_file(argv[1], kLinearKwsModelBytes);
  if (!bytes) return 2;
  const auto model = decode_linear_kws(*bytes);
  if (!model) return 2;
  const auto labeled = offline_labeled_manifest(argv[2]);
  if (!labeled) return 2;
  unsigned positive_total = 0, negative_total = 0;
  unsigned positive_accepts = 0, negative_accepts = 0;
  std::set<uint64_t> fingerprints;
  for (const auto& item : *labeled) {
    uint64_t fingerprint = 0;
    const auto feature = offline_labeled_feature(item.path, fingerprint);
    if (!feature || !fingerprints.insert(fingerprint).second) return 2;
    const bool accepted = model->accepts(*feature);
    if (item.wake) {
      ++positive_total;
      if (accepted) ++positive_accepts;
    } else {
      ++negative_total;
      if (accepted) ++negative_accepts;
    }
  }
  if (!positive_total || !negative_total) return 2;
  std::cout << "UNVERIFIED_LINEAR_MFCC_KWS_EVALUATION\n"
            << "positive_accepted=" << positive_accepts << "/" << positive_total << "\n"
            << "negative_accepted=" << negative_accepts << "/" << negative_total << "\n"
            << "Same synthetic voice is NOT human accuracy or false-wakes/hour.\n"
            << "No robot, network, API, flashing, NVS or install authorization.\n";
  return 0;
}
