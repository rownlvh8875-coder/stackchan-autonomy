// SPDX-License-Identifier: MIT
// Host-only driver for the actual K151 pairing code. Use synthetic inputs only.
#include "k151_secure_pc_setup.hpp"

#include <algorithm>
#include <charconv>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

using namespace stackchan::standalone;

namespace {
void write_hex(std::span<const uint8_t> data) {
  constexpr std::string_view digits = "0123456789abcdef";
  for (const auto byte : data) std::cout << digits[byte >> 4] << digits[byte & 15];
  std::cout << std::endl;
}

std::vector<uint8_t> read_hex(size_t max_bytes) {
  std::string line;
  if (!std::getline(std::cin, line) || line.empty() || line.size() % 2 ||
      line.size() / 2 > max_bytes)
    return {};
  std::vector<uint8_t> result(line.size() / 2);
  for (size_t i = 0; i < result.size(); ++i) {
    const auto* at = line.data() + 2 * i;
    unsigned byte = 0;
    const auto parsed = std::from_chars(at, at + 2, byte, 16);
    if (parsed.ec != std::errc{} || parsed.ptr != at + 2) return {};
    result[i] = static_cast<uint8_t>(byte);
  }
  return result;
}

bool fixture_matches(const PairingCredentials& credentials, bool maximum) {
  const std::string ssid = maximum ? std::string(32, 'Z') : "scps-test-network";
  const std::string password = maximum ? std::string(64, 'A') : "scps-test-passphrase";
  const std::string key = maximum ? std::string(220, 'z') : "scps-test-token-only";
  return credentials.valid() && std::ranges::equal(credentials.ssid(), ssid) &&
         std::ranges::equal(credentials.password(), password) &&
         std::ranges::equal(credentials.api_key(), key);
}
}

int main(int argc, char** argv) {
  if (argc != 2) return 1;
  const std::string_view mode = argv[1];
  std::atomic_bool stop{false};
  K151SecurePcSetup device(stop);
  std::array<uint8_t, K151SecurePcSetup::kHelloBytes> device_hello{};
  if (!device.device_hello(100, true, true, device_hello)) return 2;
  write_hex(device_hello);

  const auto pc_hello = read_hex(K151SecurePcSetup::kHelloBytes);
  std::array<char, 9> sas{};
  if (!device.accept_pc_hello(200, true, pc_hello, sas)) return 3;
  std::cout << sas.data() << std::endl;

  const auto sealed = read_hex(K151SecurePcSetup::kMaxSealedBytes);
  PairingCredentials credentials;
  const auto now = mode == "expired" ? 100 + K151SecurePcSetup::kSessionMs : 300;
  stop = mode == "stop";
  const bool opened = device.open_sealed(now, true, mode != "unconfirmed", sealed, credentials);
  const bool expect_success = mode == "normal" || mode == "maximum";
  if (opened != expect_success || credentials.valid() != expect_success) return 4;
  if (opened && !fixture_matches(credentials, mode == "maximum")) return 5;
  if (device.open_sealed(now, true, true, sealed, credentials) || credentials.valid()) return 6;

  std::cout << (opened ? "accepted once" : "rejected") << '\n';
}
