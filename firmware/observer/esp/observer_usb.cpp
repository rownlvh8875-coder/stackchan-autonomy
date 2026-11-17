// SPDX-License-Identifier: MIT
#include "sdkconfig.h"
#include "observer_usb.h"
#if CONFIG_STACKCHAN_PC_OBSERVER
#if !CONFIG_ESP_CONSOLE_UART_DEFAULT || !CONFIG_ESP_CONSOLE_SECONDARY_NONE
#error "Observer requires UART0 console and no USB secondary console"
#endif
#if CONFIG_LOG_MAXIMUM_LEVEL > 3 || CONFIG_XIAOZHI_ENABLE_CAMERA_DEBUG_MODE
#error "Upstream camera debug hexdumps must remain compiled out"
#endif
#include "../core/observer_core.h"
#include "../core/observer_camera.h"
#include "linux/videodev2.h" // before the encoder header's fallback pixel macros
#include "hal/hal.h"
#include "hal/board/hal_bridge.h"
#include "hal/board/stackchan_camera.h"
#include "driver/usb_serial_jtag.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "jpg/image_to_jpeg.h"
#include "psa/crypto.h"
#include <cstdlib>
#include <mutex>
#include <sys/ioctl.h>

// A conditional friend in the pinned EspVideo header grants this narrow adapter
// access to its queue, not ownership of the factory's retained frame_ or encoder.
struct StackChanObserverAccess final : scob::FrameQueue {
    EspVideo& camera;
    uint8_t*& jpeg;
    v4l2_format format{};
    v4l2_buffer leased{};
    bool lease_valid = false;
    StackChanObserverAccess(EspVideo& c, uint8_t*& p) : camera(c), jpeg(p) {}
    uint64_t now_ms() override { return uint64_t(esp_timer_get_time()) / 1000; }
    bool take(scob::RawFrame& out) override {
        leased = {}; leased.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; leased.memory = V4L2_MEMORY_MMAP;
        if (ioctl(camera.video_fd_, VIDIOC_DQBUF, &leased) != 0) return false;
        lease_valid = true;
        if (leased.index >= camera.mmap_buffers_.size() ||
            leased.flags & V4L2_BUF_FLAG_ERROR) { give(); return false; }
        const auto& map = camera.mmap_buffers_[leased.index];
        scob::Pixel pixel = scob::Pixel::Unsupported;
        switch (format.fmt.pix.pixelformat) {
            case V4L2_PIX_FMT_RGB565: case V4L2_PIX_FMT_RGB565X: pixel = scob::Pixel::RGB565; break;
            case V4L2_PIX_FMT_RGB24: pixel = scob::Pixel::RGB888; break;
            case V4L2_PIX_FMT_YUYV: pixel = scob::Pixel::YUYV; break;
            case V4L2_PIX_FMT_UYVY: pixel = scob::Pixel::UYVY; break;
            case V4L2_PIX_FMT_YUV422P: pixel = scob::Pixel::YUV422P; break;
            case V4L2_PIX_FMT_GREY: pixel = scob::Pixel::Grey; break;
            default: break;
        }
        out = {static_cast<const uint8_t*>(map.start), leased.bytesused, map.length,
               format.fmt.pix.width, format.fmt.pix.height, pixel};
        return true;
    }
    bool give() override {
        if (!lease_valid) return false;
        lease_valid = false;
        return ioctl(camera.video_fd_, VIDIOC_QBUF, &leased) == 0;
    }
    scob::Result encode(const scob::RawFrame& f, scob::Capture& out) override {
        // valid_raw has checked the converter's dimensions-derived memory reads.
        size_t bytes = 0;
        if (!image_to_jpeg(const_cast<uint8_t*>(f.data), f.size, f.width, f.height,
                static_cast<v4l2_pix_fmt_t>(format.fmt.pix.pixelformat), 20, &jpeg, &bytes) ||
            !jpeg || !bytes || bytes > 131072) return scob::Result::Unavailable;
        out.data = jpeg; out.size = bytes; out.width = f.width; out.height = f.height;
        return scob::Result::Ok;
    }
    static scob::Result capture(EspVideo& camera, uint8_t*& jpeg, scob::Capture& out) {
#if !CONFIG_ESP_VIDEO_ENABLE_DVP_VIDEO_DEVICE || CONFIG_ESP_VIDEO_ENABLE_MIPI_CSI_VIDEO_DEVICE || CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE || CONFIG_XIAOZHI_ENABLE_ROTATE_CAMERA_IMAGE || CONFIG_XIAOZHI_ENABLE_CAMERA_ENDIANNESS_SWAP
        return scob::Result::Unavailable;
#else
        std::unique_lock<std::recursive_mutex> lock(camera.capture_mutex_, std::try_to_lock);
        if (!lock.owns_lock()) return scob::Result::Busy;
        if (!camera.streaming_on_ || camera.video_fd_ < 0 || camera.mmap_buffers_.size() != 1)
            return scob::Result::Unavailable;
        StackChanObserverAccess q(camera, jpeg);
        q.format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        if (ioctl(camera.video_fd_, VIDIOC_G_FMT, &q.format) != 0 ||
            q.format.fmt.pix.pixelformat != camera.sensor_format_)
            return scob::Result::Unavailable;
        const auto& pix = q.format.fmt.pix;
        const unsigned channels = pix.pixelformat == V4L2_PIX_FMT_GREY ? 1 :
                                  pix.pixelformat == V4L2_PIX_FMT_RGB24 ? 3 : 2;
        if (pix.bytesperline && pix.bytesperline != pix.width * channels)
            return scob::Result::Unavailable;
        // DQBUF remains the original driver API; no shared timeout/stream/encoder
        // configuration is changed. Driver fault recovery is an installation HOLD.
        return scob::capture_fresh(q, out);
#endif
    }
};

namespace {
uint64_t now_ms() { return uint64_t(esp_timer_get_time()) / 1000; }
struct Cached { bool known = false; unsigned kind = 0; uint64_t at = 0; };
portMUX_TYPE cache_mux = portMUX_INITIALIZER_UNLOCKED;
Cached touch, motion;
void cache(Cached& item, unsigned kind) {
    const auto now = now_ms();
    portENTER_CRITICAL(&cache_mux);
    item = {true, kind, now};
    portEXIT_CRITICAL(&cache_mux);
}
class HalBackend final : public scob::Backend {
    scob::Id boot_{};
    uint8_t* jpeg_ = nullptr;
public:
    HalBackend() { esp_fill_random(boot_.data(), boot_.size()); }
    scob::Id boot_id() const override { return boot_; }
    std::array<uint8_t, 6> device_id() const override { return GetHAL().getFactoryMac(); }
    scob::State status() override {
        const auto now = now_ms();
        portENTER_CRITICAL(&cache_mux);
        const auto t = touch, m = motion;
        portEXIT_CRITICAL(&cache_mux);
        scob::State state; state.uptime_ms = now;
        state.touch = {t.known, t.kind, t.known && now >= t.at ? now - t.at : 0};
        state.imu = {m.known, m.kind, m.known && now >= m.at ? now - m.at : 0};
        return state;
    }
    scob::Result capture(scob::Capture& output) override {
        auto* camera = hal_bridge::board_get_camera();
        if (!camera) return scob::Result::Unavailable;
        const auto result = StackChanObserverAccess::capture(*camera, jpeg_, output);
        if (result != scob::Result::Ok) return result;
        size_t hash_bytes = 0;
        if (psa_crypto_init() != PSA_SUCCESS ||
            psa_hash_compute(PSA_ALG_SHA_256, jpeg_, output.size, output.sha.data(), output.sha.size(),
                             &hash_bytes) != PSA_SUCCESS || hash_bytes != output.sha.size())
            return scob::Result::Unavailable;
        return scob::Result::Ok;
    }
    void release() override { free(jpeg_); jpeg_ = nullptr; }
};
class UsbSink final : public scob::Sink {
public:
    bool write(const uint8_t* data, size_t n) override {
        const auto deadline = now_ms() + 2000;
        while (n && now_ms() < deadline) {
            const size_t chunk = n > 1024 ? 1024 : n;
            const int wrote = usb_serial_jtag_write_bytes(data, chunk, pdMS_TO_TICKS(50));
            if (wrote <= 0) return false;
            data += wrote; n -= size_t(wrote);
        }
        return n == 0;
    }
};
void worker(void*) {
    HalBackend backend;
    scob::Dispatcher dispatcher(backend);
    UsbSink sink;
    uint8_t input[128];
    uint64_t last = now_ms();
    for (;;) {
        const int n = usb_serial_jtag_read_bytes(input, sizeof(input), pdMS_TO_TICKS(50));
        const auto now = now_ms();
        if (now - last > 1000) dispatcher.reset(); // abandon partial requests
        if (n > 0) { dispatcher.feed(input, size_t(n), sink); last = now; }
    }
}
} // namespace
void start_pc_observer() {
    static bool started = false;
    if (started) return;
    usb_serial_jtag_driver_config_t config{};
    config.rx_buffer_size = 256; config.tx_buffer_size = 2048;
    if (usb_serial_jtag_driver_install(&config) != ESP_OK) return;
    GetHAL().onHeadPetGesture.connect([](HeadPetGesture g) { cache(touch, unsigned(g)); });
    GetHAL().onImuMotionEvent.connect([](ImuMotionEvent e) { cache(motion, unsigned(e)); });
    if (xTaskCreate(worker, "pc-observer", 8192, nullptr, 2, nullptr) != pdPASS) {
        usb_serial_jtag_driver_uninstall();
        return;
    }
    started = true;
}
#else
void start_pc_observer() {}
#endif
