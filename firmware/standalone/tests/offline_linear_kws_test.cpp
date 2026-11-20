// SPDX-License-Identifier: MIT
// Host-only fake-feature safety tests for tiny linear keyword classifier.
#include "offline_linear_kws.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

using namespace stackchan::standalone;

int main() {
  auto require = [](bool valid) {
    if (!valid) throw std::runtime_error("offline_linear_kws_test_failed");
  };
  require(kLinearKwsInputDim == 208);
  require(kLinearKwsModelBytes == 847);
  WakeFeature a{}, b{};
  a.quantized.fill(64);
  b.quantized.fill(-64);
  const auto positive = linear_kws_pool(a);
  const auto negative = linear_kws_pool(b);
  for (auto val : positive) require(val == 1.f);
  for (auto val : negative) require(val == -1.f);

  std::vector<LinearKwsExample> examples;
  for (size_t i = 0; i < 8; ++i) examples.push_back({positive, true});
  for (size_t i = 0; i < 20; ++i) examples.push_back({negative, false});
  const auto trained = train_linear_kws(examples);
  require(trained.has_value());
  require(trained->accepts(positive));
  require(!trained->accepts(negative));
  require(trained->score(positive) > trained->score(negative));
  const auto trained_again = train_linear_kws(examples);
  require(trained_again && trained_again->weights == trained->weights);
  require(trained_again->bias == trained->bias);

  auto wire = encode_linear_kws(*trained);
  require(wire && wire->size() == kLinearKwsModelBytes);
  const auto restored = decode_linear_kws(*wire);
  require(restored && restored->weights == trained->weights);
  require(restored->bias == trained->bias);
  require(restored->accepts(positive) && !restored->accepts(negative));

  auto corrupted = *wire;
  corrupted[10] ^= 1;
  require(!decode_linear_kws(corrupted));
  corrupted = *wire;
  corrupted[0] = 'Z';
  require(!decode_linear_kws(corrupted));
  corrupted = *wire;
  corrupted[5] = 0;
  require(!decode_linear_kws(corrupted));
  corrupted = *wire;
  corrupted.pop_back();
  require(!decode_linear_kws(corrupted));

  LinearKwsModel unsafe = *trained;
  unsafe.bias = std::numeric_limits<float>::quiet_NaN();
  require(!encode_linear_kws(unsafe));
  unsafe = *trained;
  unsafe.weights[0] = std::numeric_limits<float>::infinity();
  require(!encode_linear_kws(unsafe));

  require(!train_linear_kws(std::span<const LinearKwsExample>()));
  examples.resize(3);
  require(!train_linear_kws(examples));
  std::cout << "OFFLINE_LINEAR_KWS_FAKE_FEATURE_TEST_PASS; NOT HUMAN SPEECH\n";
}
