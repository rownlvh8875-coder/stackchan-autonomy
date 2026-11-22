// SPDX-License-Identifier: MIT
#pragma once
#include <cassert>
#define pdMS_TO_TICKS(ms) (ms)

struct portMUX_TYPE { bool held; };
#define portMUX_INITIALIZER_UNLOCKED {false}
inline void portENTER_CRITICAL(portMUX_TYPE* mux) { assert(!mux->held); mux->held = true; }
inline void portEXIT_CRITICAL(portMUX_TYPE* mux) { assert(mux->held); mux->held = false; }
#define portENTER_CRITICAL_ISR(mux) portENTER_CRITICAL(mux)
#define portEXIT_CRITICAL_ISR(mux) portEXIT_CRITICAL(mux)
