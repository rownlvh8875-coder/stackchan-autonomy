// SPDX-License-Identifier: MIT
#include "pcm_chunk_guard.hpp"
#include <atomic>
#include <cassert>
#include <iostream>
#include <optional>
#include <vector>

using namespace stackchan::standalone;

int main() {
  {
    const std::vector<int16_t> pcm(481, 2);
    std::atomic_bool stop{false}, consent{true};
    std::vector<size_t> sizes;
    uint64_t now = 1000;
    const auto result = stream_pcm_chunks_guarded(
        pcm, 1000, stop, consent,
        [&](std::span<const int16_t> chunk) {
          sizes.push_back(chunk.size());
          return true;
        },
        [&]() -> std::optional<uint64_t> { return ++now; });
    assert(result && *result == 1006);
    assert((sizes == std::vector<size_t>{240, 240, 1}));
  }
  {
    std::atomic_bool stop{true}, consent{true};
    const std::vector<int16_t> pcm(240, 1);
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) { ++calls; return true; },
        []() -> std::optional<uint64_t> { return 100; }));
    assert(calls == 0);
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(500, 1);
    int calls = 0;
    const auto ended = stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) {
          ++calls;
          if (calls == 2) stop.store(true);
          return true;
        },
        []() -> std::optional<uint64_t> { return 101; });
    assert(!ended && calls == 2);
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(500, 1);
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) { ++calls; return calls < 2; },
        []() -> std::optional<uint64_t> { return 101; }));
    assert(calls == 2); // No retry after failed write.
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(480, 1);
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) { ++calls; return true; },
        []() -> std::optional<uint64_t> { return std::nullopt; }));
    assert(calls == 0);
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(480, 1);
    uint64_t now = 100;
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) { ++calls; return true; },
        [&]() -> std::optional<uint64_t> {
          now += 14000;
          return now;
        }));
    assert(calls == 1); // Reject overrun after a write.
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(480, 1);
    int calls = 0;
    const auto result = stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) { ++calls; return true; },
        [now = uint64_t{101}]() mutable -> std::optional<uint64_t> {
          return now--;
        });
    assert(!result && calls == 1); // Reject backward time after a write.
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> large(kPcmOutputMaxSamples + 1, 1);
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        large, 100, stop, consent,
        [&](auto) { ++calls; return true; },
        []() -> std::optional<uint64_t> { return 100; }));
    assert(calls == 0);
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(240, 1);
    assert(!stream_pcm_chunks_guarded(
        pcm, UINT64_MAX - 1000, stop, consent,
        [](auto) { return true; },
        []() -> std::optional<uint64_t> { return 0; }));
  }
  {
    std::atomic_bool stop{false}, consent{true};
    const std::vector<int16_t> pcm(480, 1);
    int calls = 0;
    assert(!stream_pcm_chunks_guarded(
        pcm, 100, stop, consent,
        [&](auto) {
          ++calls;
          consent.store(false);
          return true;
        },
        []() -> std::optional<uint64_t> { return 101; }));
    assert(calls == 1);
  }
  std::cout << "bounded PCM chunk streaming: PASS (offline fake writer)\n";
}
