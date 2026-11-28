#pragma once

#include <cstdint>
#include <esp_crt_bundle.h>

#define ESP_FAIL -1
#define ESP_ERR_HTTP_EAGAIN 0x7007

struct esp_http_client;
using esp_http_client_handle_t = esp_http_client*;
enum esp_http_client_event_id_t { HTTP_EVENT_ON_HEADER };
enum esp_http_client_method_t { HTTP_METHOD_POST };
enum esp_http_client_transport_t { HTTP_TRANSPORT_OVER_SSL };

struct esp_http_client_event_t {
  esp_http_client_event_id_t event_id;
  void* user_data;
  const char* header_key;
  const char* header_value;
};

struct esp_http_client_config_t {
  const char* host;
  const char* path;
  int port;
  esp_http_client_method_t method;
  esp_http_client_transport_t transport_type;
  esp_err_t (*crt_bundle_attach)(void*);
  bool skip_cert_common_name_check;
  bool disable_auto_redirect;
  int max_authorization_retries;
  bool keep_alive_enable;
  int timeout_ms;
  esp_err_t (*event_handler)(esp_http_client_event_t*);
  void* user_data;
};

extern "C" {
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t*);
esp_err_t esp_http_client_set_header(esp_http_client_handle_t, const char*, const char*);
esp_err_t esp_http_client_open(esp_http_client_handle_t, int);
int esp_http_client_write(esp_http_client_handle_t, const char*, int);
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t);
int esp_http_client_get_status_code(esp_http_client_handle_t);
esp_http_client_transport_t esp_http_client_get_transport_type(esp_http_client_handle_t);
bool esp_http_client_is_chunked_response(esp_http_client_handle_t);
int esp_http_client_read(esp_http_client_handle_t, char*, int);
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t);
esp_err_t esp_http_client_close(esp_http_client_handle_t);
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t);
}
