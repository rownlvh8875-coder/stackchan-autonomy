// SPDX-License-Identifier: MIT
// Host-only research: a deterministic, regularized linear classifier over
// temporally pooled wake MFCC features. NOT an acoustic phoneme recognizer.
// No K151 firmware, paid API, GPIO, NVS or microphone integration.
#pragma once

#include "wake_features.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

inline constexpr size_t kLinearKwsTimeBins = 16;
inline constexpr size_t kLinearKwsInputDim = kLinearKwsTimeBins * kWakeCoefficients;
inline constexpr size_t kLinearKwsMaxTrainingExamples = 256;
inline constexpr size_t kLinearKwsModelBytes = 5 + 2 + (kLinearKwsInputDim + 1) * 4 + 4;
inline constexpr float kLinearKwsRegularization = 0.012f;
inline constexpr float kLinearKwsStep = 0.20f;
inline constexpr int kLinearKwsEpochs = 650;

using LinearKwsVector = std::array<float, kLinearKwsInputDim>;

inline LinearKwsVector linear_kws_pool(const WakeFeature& feature) {
  LinearKwsVector result{};
  for (size_t t = 0; t < kLinearKwsTimeBins; ++t) {
    for (size_t c = 0; c < kWakeCoefficients; ++c) {
      int total = 0;
      for (size_t j = 0; j < 4; ++j)
        total += feature.quantized[(t*4+j)*kWakeCoefficients+c];
      result[t*kWakeCoefficients+c] = static_cast<float>(total) / (4.f * 64.f);
    }
  }
  return result;
}

struct LinearKwsExample {
  LinearKwsVector features{};
  bool is_wake = false;
};

struct LinearKwsModel {
  LinearKwsVector weights{};
  float bias = 0.f;
  float score(const LinearKwsVector& input) const {
    float value = bias;
    for (size_t i = 0; i < weights.size(); ++i)
      value += weights[i] * input[i];
    return value;
  }
  // Fixed zero logit threshold. NOT tuned on any final evaluation set.
  bool accepts(const LinearKwsVector& input) const {
    return score(input) > 0.f;
  }
};

inline std::optional<LinearKwsModel> train_linear_kws(
    std::span<const LinearKwsExample> examples) {
  if (examples.size() < 20 || examples.size() > kLinearKwsMaxTrainingExamples)
    return std::nullopt;
  size_t wake_count = 0;
  for (const auto& ex : examples) {
    if (ex.is_wake) ++wake_count;
    for (const float feature : ex.features)
      if (!std::isfinite(feature) || std::abs(feature) > 2.f)
        return std::nullopt;
  }
  const size_t nonwake_count = examples.size() - wake_count;
  if (wake_count < 5 || nonwake_count < 10)
    return std::nullopt;

  LinearKwsModel model{};
  // Class-balanced full-batch gradient descent; deterministic order and fixed
  // training schedule. Fixed L2 regularization, no holdout-dependent tuning.
  for (int epoch = 0; epoch < kLinearKwsEpochs; ++epoch) {
    LinearKwsVector gradient{};
    float bias_gradient = 0.f;
    for (const auto& ex : examples) {
      const float z = std::clamp(model.score(ex.features), -30.f, 30.f);
      const float p = 1.f / (1.f + std::exp(-z));
      const float balance = ex.is_wake
          ? 0.5f / static_cast<float>(wake_count)
          : 0.5f / static_cast<float>(nonwake_count);
      const float error = balance * (p - (ex.is_wake ? 1.f : 0.f));
      bias_gradient += error;
      for (size_t i = 0; i < gradient.size(); ++i)
        gradient[i] += error * ex.features[i];
    }
    for (size_t i = 0; i < gradient.size(); ++i)
      model.weights[i] -= kLinearKwsStep *
          (gradient[i] + kLinearKwsRegularization * model.weights[i]);
    model.bias -= kLinearKwsStep * bias_gradient;
  }
  for (const float weight : model.weights)
    if (!std::isfinite(weight) || std::abs(weight) > 16.f)
      return std::nullopt;
  if (!std::isfinite(model.bias) || std::abs(model.bias) > 16.f)
    return std::nullopt;
  return model;
}

inline void put_f32_le(std::vector<uint8_t>& buffer, float number) {
  static_assert(sizeof(float) == sizeof(uint32_t));
  uint32_t bits = 0;
  std::memcpy(&bits, &number, sizeof(bits));
  put32(buffer, bits);
}
inline float get_f32_le(std::span<const uint8_t> bytes, size_t position) {
  const uint32_t bits = get32(bytes, position);
  float value = 0.f;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}
inline std::optional<std::vector<uint8_t>> encode_linear_kws(
    const LinearKwsModel& model) {
  std::vector<uint8_t> bytes{'S','K','W','L','1'};
  put16(bytes, static_cast<uint16_t>(kLinearKwsInputDim));
  for (const float value : model.weights) {
    if (!std::isfinite(value) || std::abs(value) > 16.f) return std::nullopt;
    put_f32_le(bytes, value);
  }
  if (!std::isfinite(model.bias) || std::abs(model.bias) > 16.f)
    return std::nullopt;
  put_f32_le(bytes, model.bias);
  put32(bytes, crc32(bytes));
  if (bytes.size() != kLinearKwsModelBytes) return std::nullopt;
  return bytes;
}
inline std::optional<LinearKwsModel> decode_linear_kws(
    std::span<const uint8_t> bytes) {
  if (bytes.size() != kLinearKwsModelBytes ||
      bytes[0]!='S' || bytes[1]!='K' || bytes[2]!='W' ||
      bytes[3]!='L' || bytes[4]!='1' ||
      get16(bytes, 5) != kLinearKwsInputDim ||
      crc32(bytes.first(bytes.size()-4)) != get32(bytes, bytes.size()-4))
    return std::nullopt;
  LinearKwsModel model{};
  for (size_t i = 0; i < model.weights.size(); ++i) {
    const float value = get_f32_le(bytes, 7 + i*4);
    if (!std::isfinite(value) || std::abs(value) > 16.f) return std::nullopt;
    model.weights[i] = value;
  }
  model.bias = get_f32_le(bytes, 7 + kLinearKwsInputDim*4);
  if (!std::isfinite(model.bias) || std::abs(model.bias) > 16.f)
    return std::nullopt;
  return model;
}

} // namespace stackchan::standalone
