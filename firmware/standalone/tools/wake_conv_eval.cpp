// SPDX-License-Identifier: MIT
// Host-only 1D CNN MFCC inference; never opens microphone, GPIO or network.
#include "offline_conv_kws.hpp"
#include "offline_linear_kws_io.hpp"

#include <iostream>
#include <set>

using namespace stackchan::standalone;

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  const auto bytes=offline_read_file(argv[1],kConvKwsModelBytes);
  if (!bytes) return 2;
  const auto model=decode_conv_kws(*bytes);
  if (!model) return 2;
  const auto trials=offline_labeled_manifest(argv[2]);
  if (!trials) return 2;
  unsigned wake_total=0,wake_accepted=0;
  unsigned nonwake_total=0,nonwake_accepted=0;
  std::set<uint64_t> fingerprints;
  for (const auto& item : *trials) {
    uint64_t fingerprint=0;
    auto feature=offline_labeled_feature(item.path,fingerprint);
    if (!feature || !fingerprints.insert(fingerprint).second) return 2;
    const bool accepted=model->accepts(*feature);
    if (item.wake) {
      ++wake_total;
      if (accepted) ++wake_accepted;
    } else {
      ++nonwake_total;
      if (accepted) ++nonwake_accepted;
    }
  }
  if (!wake_total || !nonwake_total) return 2;
  std::cout << "UNVERIFIED_TINY_CNN_MFCC_EVALUATION\n"
            << "positive_accepted=" << wake_accepted << "/" << wake_total << "\n"
            << "negative_accepted=" << nonwake_accepted << "/" << nonwake_total << "\n"
            << "Synthetic only; NOT human speech or safe K151 wake\n";
  return 0;
}
