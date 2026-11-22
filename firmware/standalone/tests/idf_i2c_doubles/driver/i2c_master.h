// SPDX-License-Identifier: MIT
// Narrow IDF6.1 I2C C ABI double; no device implementation.
#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int esp_err_t;
typedef int i2c_port_t;
typedef int gpio_num_t;
#define ESP_OK 0
#define ESP_ERR_NOT_FOUND 0x105
#define ESP_FAIL -1
#define I2C_NUM_1 1
#define I2C_CLK_SRC_DEFAULT 0
#define I2C_ADDR_BIT_LEN_7 0
struct i2c_master_bus_t;struct i2c_master_dev_t;
typedef i2c_master_bus_t* i2c_master_bus_handle_t;
typedef i2c_master_dev_t* i2c_master_dev_handle_t;
struct i2c_master_bus_config_t {i2c_port_t i2c_port;gpio_num_t sda_io_num,scl_io_num;int clk_source;uint8_t glitch_ignore_cnt;struct {unsigned enable_internal_pullup:1;} flags;};
struct i2c_device_config_t {int dev_addr_length;uint16_t device_address;uint32_t scl_speed_hz;};
extern "C" {
esp_err_t i2c_new_master_bus(const i2c_master_bus_config_t*,i2c_master_bus_handle_t*);
esp_err_t i2c_master_get_bus_handle(i2c_port_t,i2c_master_bus_handle_t*);
esp_err_t i2c_del_master_bus(i2c_master_bus_handle_t);
esp_err_t i2c_master_probe(i2c_master_bus_handle_t,uint16_t,int);
esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t,const i2c_device_config_t*,i2c_master_dev_handle_t*);
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t);
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t,const uint8_t*,size_t,int);
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t,const uint8_t*,size_t,uint8_t*,size_t,int);
}
