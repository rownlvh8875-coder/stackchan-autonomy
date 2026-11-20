// SPDX-License-Identifier: MIT
// Host-only, deterministic tiny 1D temporal-convolution MFCC experiment.
// Not an acoustic phoneme recognizer and NOT compiled into K151 firmware.
#pragma once

#include "offline_linear_kws.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

inline constexpr size_t kConvKwsFilters = 8;
inline constexpr size_t kConvKwsKernel = 3;
inline constexpr size_t kConvKwsPoolRegions = 4;
inline constexpr size_t kConvKwsTimeBins = 16;
inline constexpr size_t kConvKwsInputChannels = kWakeCoefficients;
inline constexpr size_t kConvKwsKernelWeights =
    kConvKwsFilters*kConvKwsKernel*kConvKwsInputChannels;
inline constexpr size_t kConvKwsOutputWeights =
    kConvKwsFilters*kConvKwsPoolRegions;
inline constexpr size_t kConvKwsFloatCount =
    kConvKwsKernelWeights+kConvKwsFilters+kConvKwsOutputWeights+1;
inline constexpr size_t kConvKwsModelBytes = 5+2+kConvKwsFloatCount*4+4;
inline constexpr int kConvKwsEpochs = 650;
inline constexpr float kConvKwsStep = 0.30f;
inline constexpr float kConvKwsL2 = 0.004f;

struct ConvKwsModel {
  std::array<float, kConvKwsKernelWeights> kernel{};
  std::array<float, kConvKwsFilters> hidden_bias{};
  std::array<float, kConvKwsOutputWeights> output{};
  float output_bias = 0.f;

  static constexpr size_t kernel_index(
      size_t filter, size_t tap, size_t channel) {
    return (filter*kConvKwsKernel+tap)*kConvKwsInputChannels+channel;
  }
  static constexpr size_t output_index(size_t region, size_t filter) {
    return region*kConvKwsFilters+filter;
  }

  struct Forward {
    std::array<float, kConvKwsTimeBins*kConvKwsFilters> z{};
    std::array<float, kConvKwsOutputWeights> pooled{};
    float logit = 0.f;
  };

  Forward forward(const LinearKwsVector& input) const {
    Forward result{};
    for (size_t t=0; t<kConvKwsTimeBins; ++t) {
      for (size_t f=0; f<kConvKwsFilters; ++f) {
        float value = hidden_bias[f];
        for (size_t k=0; k<kConvKwsKernel; ++k) {
          const int ti = static_cast<int>(t)+static_cast<int>(k)-1;
          if (ti < 0 || ti >= static_cast<int>(kConvKwsTimeBins))
            continue;
          for (size_t c=0; c<kConvKwsInputChannels; ++c) {
            value += kernel[kernel_index(f,k,c)] *
                input[static_cast<size_t>(ti)*kConvKwsInputChannels+c];
          }
        }
        result.z[t*kConvKwsFilters+f] = value;
        result.pooled[output_index(t/4,f)] += std::max(value,0.f)*0.25f;
      }
    }
    float total = output_bias;
    for (size_t i=0; i<output.size(); ++i)
      total += output[i]*result.pooled[i];
    result.logit = total;
    return result;
  }
  bool accepts(const LinearKwsVector& input) const {
    return forward(input).logit > 0.f;
  }
};

inline std::optional<ConvKwsModel> train_conv_kws(
    std::span<const LinearKwsExample> cases) {
  if (cases.size() < 20 || cases.size() > kLinearKwsMaxTrainingExamples)
    return std::nullopt;
  size_t positive = 0;
  for (const auto& item : cases) {
    if (item.is_wake) ++positive;
    for (float value : item.features)
      if (!std::isfinite(value) || std::abs(value) > 2.f)
        return std::nullopt;
  }
  const size_t negative = cases.size()-positive;
  if (positive < 5 || negative < 10) return std::nullopt;

  ConvKwsModel model{};
  // Deterministic asymmetric initialization avoids all-zero ReLU dead state.
  for (size_t i=0; i<model.kernel.size(); ++i)
    model.kernel[i] = 0.035f*std::sin((static_cast<float>(i)+1.f)*0.71f);
  for (size_t i=0; i<model.output.size(); ++i)
    model.output[i] = 0.07f*std::cos((static_cast<float>(i)+1.f)*0.43f);

  for (int epoch=0; epoch<kConvKwsEpochs; ++epoch) {
    std::array<float,kConvKwsKernelWeights> grad_kernel{};
    std::array<float,kConvKwsFilters> grad_hidden{};
    std::array<float,kConvKwsOutputWeights> grad_output{};
    float grad_bias = 0.f;

    for (const auto& example : cases) {
      const auto forward = model.forward(example.features);
      const float logistic = std::clamp(forward.logit,-30.f,30.f);
      const float probability = 1.f/(1.f+std::exp(-logistic));
      const float balanced = example.is_wake
          ? 0.5f/static_cast<float>(positive)
          : 0.5f/static_cast<float>(negative);
      const float delta =
          balanced*(probability-(example.is_wake?1.f:0.f));
      grad_bias += delta;
      for (size_t j=0; j<grad_output.size(); ++j)
        grad_output[j] += delta*forward.pooled[j];
      for (size_t t=0; t<kConvKwsTimeBins; ++t) {
        for (size_t f=0; f<kConvKwsFilters; ++f) {
          if (forward.z[t*kConvKwsFilters+f] <= 0.f)
            continue;
          const float chain =
              delta*model.output[ConvKwsModel::output_index(t/4,f)]*0.25f;
          grad_hidden[f] += chain;
          for (size_t k=0; k<kConvKwsKernel; ++k) {
            const int ti = static_cast<int>(t)+static_cast<int>(k)-1;
            if (ti < 0 || ti >= static_cast<int>(kConvKwsTimeBins))
              continue;
            for (size_t c=0; c<kConvKwsInputChannels; ++c) {
              grad_kernel[ConvKwsModel::kernel_index(f,k,c)] +=
                  chain*example.features[
                      static_cast<size_t>(ti)*kConvKwsInputChannels+c];
            }
          }
        }
      }
    }
    for (size_t j=0; j<model.kernel.size(); ++j)
      model.kernel[j] -= kConvKwsStep*
          (grad_kernel[j]+kConvKwsL2*model.kernel[j]);
    for (size_t j=0; j<model.hidden_bias.size(); ++j)
      model.hidden_bias[j] -= kConvKwsStep*grad_hidden[j];
    for (size_t j=0; j<model.output.size(); ++j)
      model.output[j] -= kConvKwsStep*
          (grad_output[j]+kConvKwsL2*model.output[j]);
    model.output_bias -= kConvKwsStep*grad_bias;
  }
  const auto finite = [](float x) {
    return std::isfinite(x) && std::abs(x) <= 16.f;
  };
  for (float value : model.kernel) if (!finite(value)) return std::nullopt;
  for (float value : model.hidden_bias) if (!finite(value)) return std::nullopt;
  for (float value : model.output) if (!finite(value)) return std::nullopt;
  if (!finite(model.output_bias)) return std::nullopt;
  return model;
}

inline std::optional<std::vector<uint8_t>> encode_conv_kws(
    const ConvKwsModel& model) {
  std::vector<uint8_t> bytes{'S','K','W','C','1'};
  put16(bytes,static_cast<uint16_t>(kConvKwsFloatCount));
  auto append = [&](float value) {
    if (!std::isfinite(value) || std::abs(value) > 16.f) return false;
    put_f32_le(bytes,value);
    return true;
  };
  for (float x : model.kernel) if (!append(x)) return std::nullopt;
  for (float x : model.hidden_bias) if (!append(x)) return std::nullopt;
  for (float x : model.output) if (!append(x)) return std::nullopt;
  if (!append(model.output_bias)) return std::nullopt;
  put32(bytes,crc32(bytes));
  if (bytes.size() != kConvKwsModelBytes) return std::nullopt;
  return bytes;
}
inline std::optional<ConvKwsModel> decode_conv_kws(
    std::span<const uint8_t> bytes) {
  if (bytes.size() != kConvKwsModelBytes ||
      bytes[0]!='S' || bytes[1]!='K' || bytes[2]!='W' ||
      bytes[3]!='C' || bytes[4]!='1' ||
      get16(bytes,5) != kConvKwsFloatCount ||
      crc32(bytes.first(bytes.size()-4)) != get32(bytes,bytes.size()-4))
    return std::nullopt;
  ConvKwsModel result{};
  size_t offset=7;
  const auto take = [&](float& out) {
    out=get_f32_le(bytes,offset);
    offset+=4;
    return std::isfinite(out) && std::abs(out) <= 16.f;
  };
  for (auto& x : result.kernel) if (!take(x)) return std::nullopt;
  for (auto& x : result.hidden_bias) if (!take(x)) return std::nullopt;
  for (auto& x : result.output) if (!take(x)) return std::nullopt;
  if (!take(result.output_bias)) return std::nullopt;
  return result;
}

} // namespace stackchan::standalone
