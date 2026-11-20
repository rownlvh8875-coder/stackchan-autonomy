// SPDX-License-Identifier: MIT
// Fake features only; this is NOT a real speech recognition evaluation.
#include "offline_conv_kws.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

using namespace stackchan::standalone;

int main() {
  auto require=[](bool ok) {
    if (!ok) throw std::runtime_error("conv_kws_host_test_failed");
  };
  require(kConvKwsFilters==8 && kConvKwsInputChannels==13);
  LinearKwsExample yes{}, no{};
  yes.features.fill(1.f);
  yes.is_wake=true;
  no.features.fill(-1.f);
  no.is_wake=false;
  std::vector<LinearKwsExample> training;
  for (int i=0; i<8; ++i) training.push_back(yes);
  for (int i=0; i<20; ++i) training.push_back(no);
  const auto model=train_conv_kws(training);
  require(model.has_value());
  require(model->accepts(yes.features));
  require(!model->accepts(no.features));
  const auto binary=encode_conv_kws(*model);
  require(binary && binary->size()==kConvKwsModelBytes);
  const auto loaded=decode_conv_kws(*binary);
  require(loaded && loaded->accepts(yes.features));
  require(!loaded->accepts(no.features));
  auto corrupted=*binary;
  corrupted[8] ^= 1;
  require(!decode_conv_kws(corrupted));
  corrupted=*binary;
  corrupted[0]='X';
  require(!decode_conv_kws(corrupted));
  corrupted=*binary;
  corrupted.pop_back();
  require(!decode_conv_kws(corrupted));
  auto broken=*model;
  broken.output_bias=std::numeric_limits<float>::quiet_NaN();
  require(!encode_conv_kws(broken));
  training.resize(2);
  require(!train_conv_kws(training));
  require(kConvKwsModelBytes==1423);
  std::cout<<"OFFLINE_TINY_CONV_KWS_FAKE_FEATURE_PASS; NO REAL VOICE\n";
}
