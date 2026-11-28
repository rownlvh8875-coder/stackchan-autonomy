#pragma once
#include "esp_transport_ssl.h"
enum ws_transport_opcodes_t {
  WS_TRANSPORT_OPCODES_CONT = 0,
  WS_TRANSPORT_OPCODES_TEXT = 1,
  WS_TRANSPORT_OPCODES_BINARY = 2,
  WS_TRANSPORT_OPCODES_CLOSE = 8,
  WS_TRANSPORT_OPCODES_PING = 9,
  WS_TRANSPORT_OPCODES_PONG = 10,
  WS_TRANSPORT_OPCODES_FIN = 128,
  WS_TRANSPORT_OPCODES_NONE = 256,
};
struct esp_transport_ws_config_t {
  const char* ws_path;
  const char* auth;
  bool propagate_control_frames;
};
extern "C" {
esp_transport_handle_t esp_transport_ws_init(esp_transport_handle_t);
esp_err_t esp_transport_ws_set_config(esp_transport_handle_t, const esp_transport_ws_config_t*);
esp_err_t esp_transport_ws_set_auth(esp_transport_handle_t, const char*);
int esp_transport_ws_get_upgrade_request_status(esp_transport_handle_t);
ws_transport_opcodes_t esp_transport_ws_get_read_opcode(esp_transport_handle_t);
int esp_transport_ws_get_read_payload_len(esp_transport_handle_t);
bool esp_transport_ws_get_fin_flag(esp_transport_handle_t);
int esp_transport_ws_send_raw(esp_transport_handle_t, ws_transport_opcodes_t, const char*, int, int);
}
