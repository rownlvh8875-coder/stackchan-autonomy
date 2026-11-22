// SPDX-License-Identifier: MIT
#pragma once
#include <esp_err.h>
enum spi_host_device_t { SPI3_HOST = 2 };
enum spi_dma_chan_t { SPI_DMA_CH_AUTO = 3 };
struct spi_bus_config_t {
  int mosi_io_num, miso_io_num, sclk_io_num, quadwp_io_num, quadhd_io_num;
  int data4_io_num, data5_io_num, data6_io_num, data7_io_num, max_transfer_sz;
};
extern "C" esp_err_t spi_bus_initialize(spi_host_device_t, const spi_bus_config_t*, spi_dma_chan_t);
extern "C" esp_err_t spi_bus_free(spi_host_device_t);
