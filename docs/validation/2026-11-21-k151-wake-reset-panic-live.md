# K151 무음 진단의 WakeNet reset 경계 panic과 원본 복구

2026-11-21 KST. 검토한 계측 이미지의 무음 시험 1회 및 같은 슬롯 복구를
사용자가 승인했다. COM3 독점 접근, 동일 ESP32-S3 rev0.2, 16MB,
Secure Boot 및 Flash Encryption OFF를 쓰기 전에 확인했다. 현재 표와
OTA 구간, 원본 슬롯 전체 digest가 원본과 일치했다. 로컬 원본 A/B와
복구 슬라이스 길이·SHA256도 다시 검증했다.

실행 코드는 `14b5f6393e9cb6ea91815a584a68d8fe818b4da5`, 실제 빌드
checkout은 `757e1c017f8c977ebef7b4e6b88fbf055b5675d5`다.
이미지 SHA256은 `e935257acf271b9b8d473aedbd161a31af5f8ba2445837f6238a69c789b980a4`다.
[ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44898221648)

| 실행 | 범위 | 결과 |
|---|---|---|
| 임시 진단 쓰기 | `[0x510000,0x5D1280)`, 791,168 B | 13.664초, 쓰기 digest 일치 |
| 진단 쓰기의 erase | `[0x510000,0x5D2000)`, 794,624 B | 실제 도구 보고 일치 |
| 독립 진단 verify | `[0x510000,0x5D1280)` | 2.073초, digest 일치 |
| 원본 슬롯 복구 | `[0x510000,0xA00000)`, 5,177,344 B | 85.687초, 쓰기 digest 일치 |
| 독립 원본 verify | `[0x510000,0xA00000)` | 9.586초, digest 일치 |
| 파티션 표·OTA | 각 4,096 B·8,192 B | 쓰기 전·진단 뒤·복구 뒤 모두 원본 일치 |

복구 SHA256은 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`다.
복구와 독립 verify 뒤 RTS hard reset으로 출고 부팅을 요청했고 COM3이
PnP에 다시 나타났다. 사용자가 이 재부팅 뒤 출고 얼굴·메뉴를 확인했다.

## 한 번의 실행에서 관측한 결과

1. 최초 시작 대기에서 reset reason `11`(`ESP_RST_USB`)을 받았다.
   START를 한 번 보냈고 로컬 직렬 flush를 확인했다.
2. 모델 준비, 로컬 TLS 및 합성 JSON·speech 처리에 이어
   `synthetic_inference`와 `model_reset_begin`을 받았다.
   코드상 마지막 경계는 64개 직접 합성 chunk 완료 조건 뒤 출력된다.
   직접 추론 시간과 결과를 담은 최종 보고는 수신되지 않았다.
3. `model_reset_return` 없이 바뀐 nonce의 시작 대기 메시지가 들어왔고
   reset reason은 `4`(`ESP_RST_PANIC`)였다. 수신기는
   `DUPLICATE_BOOT_OR_NONCE`로 중단하고 STOP을 한 번 전송했다. 수신기
   실행 총 시간은 5.506초였다. 추가 START와 시험 재시도는 없었다.
   [고정 ESP-IDF의 reset reason](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_system/include/esp_system.h)

관측 경계 바로 뒤의 모델 `reset()`은 ESP-SR의 `clean()`을 호출한다.
이 구간으로 좁혔지만 보고에는 panic의 예외 종류나 명령 주소, backtrace가
없다. `input_allocate_begin`, 첫 poll, 새 합성 32프레임 완료 및 HOLD는
수신되지 않았다. 원시 직렬 내용과 nonce는 저장하지 않았다.
[호출 경계 코드](https://github.com/rownlvh8875-coder/stackchan-autonomy/blob/14b5f6393e9cb6ea91815a584a68d8fe818b4da5/firmware/standalone/resource_bench/main/synthetic_wake_probe.hpp#L50)
[WakeNet 포트 reset](https://github.com/rownlvh8875-coder/stackchan-autonomy/blob/14b5f6393e9cb6ea91815a584a68d8fe818b4da5/firmware/standalone/esp_app/main/k151_wakenet_port.cpp#L59)
[고정 ESP-SR의 상태 정리 인터페이스](https://github.com/espressif/esp-sr/blob/2f8c4b0459db5bbb39abd77adae27962d6d94bcb/include/esp32s3/esp_wn_iface.h)

실행 코드의 Windows 로컬 root 500 PASS / 2 SKIP, standalone 661
PASS / 5 SKIP, 집중 142 PASS 및 GitHub CI 9/9는 기존 검증 기록을
따른다. 이번 실물에는 새 음성 수집 및 유료 API 호출이 없었다. 실제
호출어 인식·물리 STOP·독립 GPT 대화는 계속 검증 대기다.
[PR과 CI 이력](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)
