// SPDX-License-Identifier: MIT
#include "k151_readonly_probe.hpp"
#include <driver/i2c_master.h>
#include <cassert>
#include <cstring>
#include <vector>
using namespace stackchan::standalone;
#include <string>
struct i2c_master_bus_t {};
struct i2c_master_dev_t {};
namespace {
i2c_master_bus_t bus;
i2c_master_dev_t dev;
std::atomic_bool owner{true}, stop{false};
std::string mode;
int inject = -1, calls = 0, deletes = 0, removes = 0, adds = 0;
bool bus_live = false, dev_live = false, triggered = false, absent = false;
uint16_t device_address = 0;
std::vector<uint16_t> addresses;
std::vector<std::pair<uint16_t, uint8_t>> reads;
bool event(bool cleanup = false) {
  // After cancellation/failure only cleanup may run.
  assert(!triggered || cleanup);
  const bool hit = calls++ == inject;
  if (!hit) return false;
  triggered = true;
  if (mode == "stop") stop = true;
  if (mode == "revoke") owner = false;
  return mode == "fail";
}
void cleared(const k151::ReadOnlyEvidence& e) {
  assert(!e.bus_opened && !e.finished_without_bus_error);
  for (bool a : e.acknowledged) assert(!a);
  assert(!e.touch_version_read && !e.pmic_id_read && !e.pmic_ldo_read);
  assert(!e.pmic_aldo12_read && !e.aw9523_p0_mode_read && e.aw9523_p0_mode == 0);
  assert(!e.aw9523_id_read && !e.aw9523_outputs_read && !e.aw9523_directions_read);
  assert(e.pmic_id == 0 && e.aw9523_id == 0);
  for (auto a : e.touch_version) assert(a == 0);
  for (auto a : e.pmic_ldo) assert(a == 0);
  for (auto a : e.pmic_aldo12) assert(a == 0);
  for (auto a : e.aw9523_outputs) assert(a == 0);
  for (auto a : e.aw9523_directions) assert(a == 0);
}
}
extern "C" esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t* c,
                                        i2c_master_bus_handle_t* b) {
  assert(!bus_live && c->i2c_port == 1 && c->sda_io_num == 12 && c->scl_io_num == 11);
  if (event()) return ESP_FAIL;
  bus_live = true; *b = &bus; return ESP_OK;
}
extern "C" esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t b) {
  assert(b == &bus && bus_live); ++deletes;
  if (event(true) || dev_live) return ESP_FAIL;
  bus_live = false; return ESP_OK;
}
extern "C" esp_err_t i2c_master_probe(i2c_master_bus_handle_t b, uint16_t a, int ms) {
  assert(b == &bus && bus_live && ms == 30);
  addresses.push_back(a);
  if (event()) return ESP_FAIL;
  return absent ? ESP_ERR_NOT_FOUND : ESP_OK;
}
extern "C" esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t b,
    const i2c_device_config_t* c, i2c_master_dev_handle_t* d) {
  assert(b == &bus && bus_live && !dev_live && c->dev_addr_length == I2C_ADDR_BIT_LEN_7);
  assert(c->scl_speed_hz == 100000);
  if (event()) return ESP_FAIL;
  ++adds; dev_live = true; device_address = c->device_address; *d = &dev; return ESP_OK;
}
extern "C" esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t d) {
  assert(d == &dev && dev_live); ++removes;
  if (event(true)) return ESP_FAIL;
  dev_live = false; return ESP_OK;
}
extern "C" esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t d,
    const uint8_t* tx, size_t tn, uint8_t* rx, size_t rn, int ms) {
  assert(d == &dev && dev_live && tn == 1 && ms == 30);
  assert((device_address == 0x34 && rn == 1 &&
          (*tx == 0x03 || *tx == 0x90 || *tx == 0x92 || *tx == 0x93 ||
           *tx == 0x94 || *tx == 0x95 || *tx == 0x97 || *tx == 0x99)) ||
         (device_address == 0x58 && (((*tx == 0x10 || *tx == 0x12) && rn == 1) ||
          ((*tx == 0x02 || *tx == 0x04) && rn == 2))) ||
         (device_address == 0x38 && *tx == 0xA3 && rn == 6));
  reads.emplace_back(device_address, *tx);
  for (size_t i = 0; i < rn; ++i) rx[i] = static_cast<uint8_t>(device_address ^ (*tx + i));
  return event() ? ESP_FAIL : ESP_OK;  // Can leave partially filled data on error.
}
int main(int argc, char** argv) {
  mode = argc > 1 ? argv[1] : "ok";
  if (argc > 2) inject = std::stoi(argv[2]);
  if (mode == "denied") owner = false;
  if (mode == "stopped") stop = true;
  absent = mode == "absent";
  K151ReadOnlyProbe p;
  k151::ReadOnlyEvidence e;
  e.bus_opened = e.pmic_id_read = e.finished_without_bus_error = true;
  e.pmic_id = 255; e.touch_version.fill(255);
  e.pmic_aldo12_read = e.aw9523_p0_mode_read = true;
  e.pmic_aldo12.fill(255); e.aw9523_p0_mode = 255;
  const bool ok = p.observe_once(owner, stop, e);
  if (mode == "denied" || mode == "stopped") {
    assert(!ok && calls == 0); cleared(e); return 0;
  }
  if (inject >= 0) {
    assert(triggered && !ok); cleared(e);
    assert(deletes == (inject == 0 && mode == "fail" ? 0 : 1));
    assert(removes == adds); return 0;
  }
  assert(ok && !bus_live && !dev_live && deletes == 1);
  assert((addresses == std::vector<uint16_t>{0x34, 0x58, 0x38, 0x40, 0x36}));
  assert(e.bus_opened && e.finished_without_bus_error);
  if (absent) {
    assert(reads.empty() && adds == 0 && !e.pmic_id_read && !e.touch_version_read);
    assert(!e.pmic_aldo12_read && !e.aw9523_p0_mode_read);
    for (bool a : e.acknowledged) assert(!a);
    return 0;
  }
  assert(calls == 26 && adds == 3 && removes == 3);
  assert((reads == std::vector<std::pair<uint16_t, uint8_t>>{
      {0x34, 0x03}, {0x34, 0x90}, {0x34, 0x94}, {0x34, 0x95}, {0x34, 0x97},
      {0x34, 0x99}, {0x34, 0x92}, {0x34, 0x93}, {0x58, 0x10}, {0x58, 0x02},
      {0x58, 0x04}, {0x58, 0x12}, {0x38, 0xA3}}));
  assert(e.pmic_id_read && e.pmic_ldo_read && e.aw9523_id_read &&
         e.aw9523_outputs_read && e.aw9523_directions_read && e.touch_version_read);
  assert(e.pmic_id == (0x34 ^ 0x03) && e.aw9523_id == (0x58 ^ 0x10));
  assert((e.pmic_ldo == std::array<uint8_t, 5>{0xA4, 0xA0, 0xA1, 0xA3, 0xAD}));
  assert((e.pmic_aldo12_read && e.pmic_aldo12 == std::array<uint8_t, 2>{0xA6, 0xA7}));
  assert((e.aw9523_outputs == std::array<uint8_t, 2>{0x5A, 0x5B}));
  assert((e.aw9523_directions == std::array<uint8_t, 2>{0x5C, 0x5D}));
  assert(e.aw9523_p0_mode_read && e.aw9523_p0_mode == 0x4A);
  assert((e.touch_version == std::array<uint8_t, 6>{0x9B, 0x9C, 0x9D, 0x9E, 0x9F, 0x90}));
}
