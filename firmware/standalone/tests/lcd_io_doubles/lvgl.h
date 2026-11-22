// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>

struct lv_obj_t;
struct lv_display_t;
struct lv_event_t;
struct lv_area_t { int32_t x1, y1, x2, y2; };
enum lv_color_format_t { LV_COLOR_FORMAT_RGB565 };
enum lv_display_render_mode_t { LV_DISPLAY_RENDER_MODE_PARTIAL };
enum lv_event_code_t { LV_EVENT_INVALIDATE_AREA };
enum lv_align_t { LV_ALIGN_TOP_MID, LV_ALIGN_CENTER, LV_ALIGN_BOTTOM_MID };
extern "C" {
bool lv_is_initialized();
lv_display_t* lv_display_create(int32_t, int32_t);
void lv_display_set_user_data(lv_display_t*, void*);
void* lv_display_get_user_data(lv_display_t*);
void lv_display_set_color_format(lv_display_t*, lv_color_format_t);
void lv_display_set_buffers_with_stride(lv_display_t*, void*, void*, uint32_t, uint32_t,
                                        lv_display_render_mode_t);
void lv_display_set_flush_cb(lv_display_t*, void (*)(lv_display_t*, const lv_area_t*, uint8_t*));
void lv_display_add_event_cb(lv_display_t*, void (*)(lv_event_t*), lv_event_code_t, void*);
uint32_t lv_display_get_event_count(lv_display_t*);
void* lv_event_get_param(lv_event_t*);
lv_obj_t* lv_display_get_screen_active(lv_display_t*);
void lv_obj_invalidate(lv_obj_t*);
void lv_refr_now(lv_display_t*);
void lv_draw_sw_rgb565_swap(void*, uint32_t);
void lv_display_flush_ready(lv_display_t*);
void lv_display_delete(lv_display_t*);
lv_obj_t* lv_obj_create(lv_obj_t*);
lv_obj_t* lv_label_create(lv_obj_t*);
void lv_obj_delete(lv_obj_t*);
void lv_obj_set_size(lv_obj_t*, int32_t, int32_t);
void lv_obj_center(lv_obj_t*);
void lv_obj_align(lv_obj_t*, lv_align_t, int32_t, int32_t);
void lv_label_set_text(lv_obj_t*, const char*);
}
