#pragma once
#include <esp_err.h>
struct esp_transport;
using esp_transport_handle_t = esp_transport*;
extern "C" {
esp_transport_handle_t esp_transport_ssl_init();
void esp_transport_ssl_crt_bundle_attach(esp_transport_handle_t, esp_err_t (*)(void*));
int esp_transport_connect(esp_transport_handle_t, const char*, int, int);
int esp_transport_poll_read(esp_transport_handle_t, int);
int esp_transport_read(esp_transport_handle_t, char*, int, int);
int esp_transport_close(esp_transport_handle_t);
esp_err_t esp_transport_destroy(esp_transport_handle_t);
}
