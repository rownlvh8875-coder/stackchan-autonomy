// SPDX-License-Identifier: MIT
// Pure fake-feature host tests. No Korean words, real voice, robot or network.
#include "offline_contrastive_wake.hpp"

#include <cassert>
#include <iostream>
#include <stdexcept>
#include <vector>

using namespace stackchan::standalone;

int main() {
  const auto require = [](bool valid) {
    if (!valid) throw std::runtime_error("contrastive_host_policy_test_failed");
  };
  WakeFeature wake{};
  WakeFeature unrelated{};
  unrelated.quantized.fill(100);
  WakeProfile profile{};
  profile.limit_q8 = 25600;
  profile.templates.push_back(wake);
  std::vector<WakeFeature> negatives(10, unrelated);

  // A matching wake with distant negatives is acceptable in this fake model.
  const auto positive = offline_contrastive_wake(profile, negatives, wake);
  require(positive && positive->accepted);
  require(positive->best_wake_distance == 0.f);
  require(positive->nearest_nonwake_distance > 0.f);

  // An exact nonwake feature match must veto a positive profile match.
  negatives[0] = wake;
  const auto vetoed = offline_contrastive_wake(profile, negatives, wake);
  require(vetoed && !vetoed->accepted);
  require(vetoed->nearest_nonwake_distance == 0.f);

  // Missing, oversized and invalid calibration evidence always fails closed.
  negatives.resize(9);
  require(!offline_contrastive_wake(profile, negatives, wake));
  negatives.resize(49, unrelated);
  require(!offline_contrastive_wake(profile, negatives, wake));
  negatives.resize(10, unrelated);
  profile.limit_q8 = 0;
  require(!offline_contrastive_wake(profile, negatives, wake));
  profile.limit_q8 = 25600;
  profile.templates.clear();
  require(!offline_contrastive_wake(profile, negatives, wake));

  require(kContrastiveNonwakeMargin == 2.0f);
  std::cout << "CONTRASTIVE_FAKE_FEATURE_POLICY_PASS; HOST_ONLY\n";
}
