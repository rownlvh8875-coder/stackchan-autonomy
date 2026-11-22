// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <esp_err.h>

struct esp_timer;
using esp_timer_handle_t = esp_timer*;
enum esp_timer_dispatch_t { ESP_TIMER_TASK, ESP_TIMER_ISR };
struct esp_timer_create_args_t {
  void (*callback)(void*);
  void* arg;
  esp_timer_dispatch_t dispatch_method;
  const char* name;
  bool skip_unhandled_events;
};
extern "C" {
int64_t esp_timer_get_time();
esp_err_t esp_timer_create(const esp_timer_create_args_t* args, esp_timer_handle_t* out);
esp_err_t esp_timer_start_periodic(esp_timer_handle_t timer, uint64_t period_us);
esp_err_t esp_timer_stop(esp_timer_handle_t timer);
esp_err_t esp_timer_delete(esp_timer_handle_t timer);
}
