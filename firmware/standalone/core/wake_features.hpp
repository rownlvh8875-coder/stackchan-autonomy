// SPDX-License-Identifier: MIT
// Experimental 24kHz mono -> 16kHz anti-aliased MFCC/DTW wake feature core.
// Synthetic/host verification is NOT proof of Korean word recognition accuracy.
#pragma once

#include "standalone_core.hpp"
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <vector>

namespace stackchan::standalone {

inline constexpr size_t kWakeBins = 64;
inline constexpr size_t kWakeCoefficients = 13;
inline constexpr size_t kWakeBytes = kWakeBins * kWakeCoefficients;
inline constexpr size_t kWakeMaxSamples24k = 72000; // <=3sec per utterance
inline constexpr float kPi = 3.14159265358979323846f;

struct WakeFeature {
  std::array<int8_t, kWakeBytes> quantized{};
  bool operator==(const WakeFeature&) const = default;
};

inline float sinc(float x) {
  return std::abs(x) < 1.e-6f ? 1.f : std::sin(kPi * x) / (kPi * x);
}

// Windowed-sinc fractional 3:2 SRC; 0.30 cycles/input cutoff (<16k Nyquist).
// In a deployed application the caller must supply real 24kHz PCM16 mono.
inline std::optional<std::vector<float>> resample_24k_to_16k(std::span<const int16_t> pcm) {
  if (pcm.size() < 2400 || pcm.size() > kWakeMaxSamples24k) return std::nullopt;
  constexpr int radius = 16;
  constexpr float cutoff2 = 0.60f;
  std::array<std::array<float, 33>, 2> kernels{};
  for (int phase = 0; phase < 2; ++phase) {
    float sum = 0;
    for (int j = -radius; j <= radius; ++j) {
      const float x = static_cast<float>(j) - phase * 0.5f;
      const float window = 0.5f * (1.f + std::cos(kPi * x / (radius + 0.5f)));
      const float w = cutoff2 * sinc(cutoff2 * x) * window;
      kernels[phase][j + radius] = w;
      sum += w;
    }
    if (sum == 0) return std::nullopt;
    for (float& v : kernels[phase]) v /= sum;
  }
  const size_t output_samples = pcm.size() * 2 / 3;
  std::vector<float> out(output_samples, 0.f);
  for (size_t n = 0; n < output_samples; ++n) {
    const int center = static_cast<int>((3 * n) / 2);
    const int phase = static_cast<int>(n & 1U);
    float acc = 0;
    for (int j = -radius; j <= radius; ++j) {
      const int index = center + j;
      if (index >= 0 && static_cast<size_t>(index) < pcm.size()) {
        acc += kernels[phase][j + radius] * pcm[static_cast<size_t>(index)];
      }
    }
    out[n] = acc / 32768.f;
  }
  return out;
}

// Non-recursive radix-2 FFT, N=512. No device-specific DSP dependency.
inline void fft512(std::array<std::complex<float>, 512>& a) {
  constexpr size_t n = 512;
  for (size_t i = 1, j = 0; i < n; ++i) {
    size_t bit = n >> 1;
    while (j & bit) { j ^= bit; bit >>= 1; }
    j ^= bit;
    if (i < j) std::swap(a[i], a[j]);
  }
  for (size_t len = 2; len <= n; len <<= 1) {
    const float angle = -2.f * kPi / static_cast<float>(len);
    const std::complex<float> multiplier{std::cos(angle), std::sin(angle)};
    for (size_t i = 0; i < n; i += len) {
      std::complex<float> w{1, 0};
      for (size_t j = 0; j < len / 2; ++j) {
        const auto u = a[i + j], v = a[i + j + len / 2] * w;
        a[i + j] = u + v;
        a[i + j + len / 2] = u - v;
        w *= multiplier;
      }
    }
  }
}

inline std::optional<WakeFeature> wake_mfcc_from_24k(std::span<const int16_t> pcm) {
  const auto samples16 = resample_24k_to_16k(pcm);
  if (!samples16 || samples16->size() < 400) return std::nullopt;
  float peak = 0, energy = 0;
  for (float s : *samples16) { peak = std::max(peak, std::abs(s)); energy += s*s; }
  if (peak < 0.003f || energy / static_cast<float>(samples16->size()) < 1.e-6f) {
    return std::nullopt; // silence / digital zero, not a calibrated VAD
  }
  constexpr size_t frame = 400, hop = 160, mel_channels = 26;
  const size_t frames = 1 + (samples16->size() - frame) / hop;
  if (frames < 1 || frames > 300) return std::nullopt;
  const auto hz_to_mel = [](float hz) { return 2595.f * std::log10(1.f + hz/700.f); };
  const auto mel_to_hz = [](float mel) { return 700.f * (std::pow(10.f, mel/2595.f) - 1.f); };
  std::array<float, mel_channels + 2> edges{};
  const float mel_top = hz_to_mel(8000.f);
  for (size_t i = 0; i < edges.size(); ++i) {
    edges[i] = mel_to_hz(mel_top * static_cast<float>(i) / (mel_channels + 1));
  }
  std::vector<std::array<float, kWakeCoefficients>> spectrum(frames);
  for (size_t t = 0; t < frames; ++t) {
    std::array<std::complex<float>, 512> bins{};
    for (size_t j = 0; j < frame; ++j) {
      const size_t i = t * hop + j;
      const float previous = i > 0 ? (*samples16)[i-1] : 0.f;
      const float value = (*samples16)[i] - 0.97f * previous;
      const float hamming = 0.54f - 0.46f * std::cos(2.f * kPi * j / (frame-1));
      bins[j] = {value * hamming, 0.f};
    }
    fft512(bins);
    std::array<float, 257> power{};
    for (size_t i = 0; i < power.size(); ++i) power[i] = std::norm(bins[i]);
    std::array<float, mel_channels> logged{};
    for (size_t b = 0; b < mel_channels; ++b) {
      float sum = 0;
      for (size_t k = 0; k < power.size(); ++k) {
        const float hz = k * 16000.f / 512.f;
        float weight = 0;
        if (hz > edges[b] && hz <= edges[b+1]) {
          weight = (hz - edges[b]) / (edges[b+1] - edges[b]);
        } else if (hz > edges[b+1] && hz < edges[b+2]) {
          weight = (edges[b+2] - hz) / (edges[b+2] - edges[b+1]);
        }
        sum += power[k] * weight;
      }
      logged[b] = std::log(std::max(sum, 1.e-9f));
    }
    for (size_t c = 0; c < kWakeCoefficients; ++c) {
      float dct = 0;
      for (size_t b = 0; b < mel_channels; ++b) {
        dct += logged[b] * std::cos(kPi * c * (b + 0.5f) / mel_channels);
      }
      const float scale = c == 0 ? std::sqrt(1.f / mel_channels) :
                                   std::sqrt(2.f / mel_channels);
      spectrum[t][c] = dct * scale;
    }
  }
  // Cepstral-mean normalization reduces fixed microphone frequency response.
  std::array<float, kWakeCoefficients> mean{};
  for (const auto& f : spectrum) {
    for (size_t c=0; c<kWakeCoefficients; ++c) mean[c] += f[c];
  }
  for (float& m : mean) m /= static_cast<float>(frames);
  WakeFeature result;
  for (size_t t=0; t<kWakeBins; ++t) {
    const float position = frames == 1 ? 0.f :
        static_cast<float>(t) * (frames-1) / (kWakeBins-1);
    const size_t left = static_cast<size_t>(position);
    const size_t right = std::min(left+1,frames-1);
    const float blend = position-left;
    for (size_t c=0; c<kWakeCoefficients; ++c) {
      const float value = ((1.f-blend)*spectrum[left][c] +
                           blend*spectrum[right][c] - mean[c])*8.f;
      result.quantized[t*kWakeCoefficients+c] = static_cast<int8_t>(
          std::clamp(std::lround(value), -127L, 127L));
    }
  }
  return result;
}

// Fixed 64x13 features; DTW allows local time warping, 13-bin Manhattan cost.
inline float wake_dtw_distance(const WakeFeature& a, const WakeFeature& b) {
  constexpr float infinity = std::numeric_limits<float>::infinity();
  std::array<float, kWakeBins+1> previous{}, current{};
  previous.fill(infinity);
  previous[0] = 0;
  for (size_t i=1; i<=kWakeBins; ++i) {
    current.fill(infinity);
    for (size_t j=std::max<size_t>(1, i>12 ? i-12 : 1);
         j<=std::min(kWakeBins,i+12); ++j) {
      float distance = 0;
      for (size_t c=0; c<kWakeCoefficients; ++c) {
        const int delta = static_cast<int>(a.quantized[(i-1)*kWakeCoefficients+c]) -
                          static_cast<int>(b.quantized[(j-1)*kWakeCoefficients+c]);
        distance += std::abs(delta);
      }
      current[j] = distance + std::min({previous[j], current[j-1], previous[j-1]});
    }
    previous = current;
  }
  return previous[kWakeBins] / (kWakeBins*kWakeCoefficients);
}

struct WakeProfile {
  uint16_t limit_q8 = 0; // normalized DTW threshold * 256
  std::vector<WakeFeature> templates;
  bool accepts(const WakeFeature& probe) const {
    if (limit_q8 == 0 || templates.empty() || templates.size() > 3) return false;
    for (const auto& tmpl : templates) {
      if (wake_dtw_distance(tmpl,probe) * 256.f < limit_q8) return true;
    }
    return false;
  }
};

inline std::optional<std::vector<uint8_t>> encode_wake_profile(const WakeProfile& p) {
  if (p.limit_q8 == 0 || p.templates.empty() || p.templates.size() > 3) return std::nullopt;
  std::vector<uint8_t> wire{'S','W','K','1',static_cast<uint8_t>(p.templates.size())};
  put16(wire,p.limit_q8);
  for (const auto& template_feature : p.templates) {
    for (int8_t value : template_feature.quantized) wire.push_back(static_cast<uint8_t>(value));
  }
  put32(wire,crc32(wire));
  return wire; // <=2507 bytes. Store only after explicit NVS commit.
}

inline std::optional<WakeProfile> decode_wake_profile(std::span<const uint8_t> bytes) {
  if (bytes.size() < 11 || bytes.size() > 2507 || bytes[0]!='S' || bytes[1]!='W' ||
      bytes[2]!='K' || bytes[3]!='1') return std::nullopt;
  const size_t count=bytes[4];
  if (count < 1 || count > 3 || bytes.size()!=11+count*kWakeBytes ||
      get16(bytes,5)==0 || crc32(bytes.first(bytes.size()-4))!=
      get32(bytes,bytes.size()-4)) return std::nullopt;
  WakeProfile p;
  p.limit_q8=get16(bytes,5);
  for (size_t t=0; t<count; ++t) {
    WakeFeature f;
    for (size_t i=0; i<kWakeBytes; ++i) {
      f.quantized[i]=static_cast<int8_t>(bytes[7+t*kWakeBytes+i]);
    }
    p.templates.push_back(f);
  }
  return p;
}

// Explicit split: up to 3 enrollment templates; positive holdouts and negatives
// must be distinct captured utterances, never the same training recording.
// Reject calibration when holdouts and negatives cannot be separated.
inline std::optional<WakeProfile> calibrate_wake(
    std::span<const WakeFeature> templates,
    std::span<const WakeFeature> held_out_positive,
    std::span<const WakeFeature> negative) {
  if (templates.empty() || templates.size()>3 || held_out_positive.size()<5 ||
      negative.size()<10) return std::nullopt;
  WakeProfile p;
  p.templates.assign(templates.begin(),templates.end());
  auto best = [&](const WakeFeature& sample) {
    float distance=std::numeric_limits<float>::infinity();
    for (const auto& tmpl : p.templates) {
      distance=std::min(distance,wake_dtw_distance(tmpl,sample));
    }
    return distance;
  };
  float worst_pos=0, best_neg=std::numeric_limits<float>::infinity();
  for (const auto& sample : held_out_positive) worst_pos=std::max(worst_pos,best(sample));
  for (const auto& sample : negative) best_neg=std::min(best_neg,best(sample));
  if (!std::isfinite(best_neg) || worst_pos >= best_neg || best_neg <= 0) {
    return std::nullopt;
  }
  const float threshold=(worst_pos+best_neg)*0.5f*256.f;
  if (threshold < 1.f || threshold > 65535.f) return std::nullopt;
  p.limit_q8=static_cast<uint16_t>(threshold);
  return p;
}

} // namespace stackchan::standalone
