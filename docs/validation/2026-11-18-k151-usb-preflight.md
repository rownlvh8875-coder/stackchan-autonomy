# K151 USB 사전 확인과 출고 연결 경로 검토 — 2026-11-18

사용자 시간대 Asia/Seoul 기준. 사용자의 Windows cmd 출력과 공개 공식 소스
검토를 구분한다. 클라우드에서 실제 USB·Bluetooth·LAN 장치에 접속하지 않았다.

## 사용자 PC에서 확인한 항목

| 항목 | 사용자 출력 / 판정 |
|---|---|
| 일반 부팅 중 USB 포트 | `OK USB 직렬 장치(COM3)` |
| 다른 포트 | `COM7`은 표준 Bluetooth 직렬 링크; USB 대상으로 사용하지 않음 |
| COM3 하드웨어 ID | `USB\VID_303A&PID_1001&REV_0101&MI_00`, `USB\VID_303A&PID_1001&MI_00` |
| USB 계열 | Espressif USB Serial/JTAG 식별자와 일치; 이 값만으로 정확한 칩·보호 상태·용량은 확정하지 않음 |
| 준비 도구 | 별도 uv 도구 환경의 `esptool v5.6.0`, `5.6.0` 출력 확인 |
| ROM 연결 | `--before usb-reset --no-stub`의 보호 상태 조회 성공, `Staying in bootloader` |
| 실제 칩 | ESP32-S3 (QFN56), revision v0.2, USB-Serial/JTAG |
| 보호 상태 | Flags0, Secure Boot Disabled, Flash Encryption Disabled, SPI_BOOT_CRYPT_CNT0 |
| flash 용량 | 후속 `--before no-reset --no-stub flash-id`: 제조사46, Device4018,16MB, quad,3.3V |
| 원본 보관 | 새 `k151-original-20261118-01` 폴더 생성 확인; 첫 A 읽기 안내, 완료 결과 대기 |

버전 확인에서 처음 입력된 uv 경로에는 사용자 폴더 뒤의 역슬래시가 빠져 있었다.
실제 전체 경로를 코드 블록으로 안내한 뒤 정상 버전을 확인했다. Windows 명령은
역슬래시가 유지되도록 코드 블록으로 전달하고 한 번에 한 줄씩 실행한다.

Download Mode 진입 안내 후 처음에는 COM7 Bluetooth만 보였으나, 후속 Espressif
장치 조회에서 복합 USB·USB JTAG/serial debug unit·COM3이 다시 확인됐다.
수동 상태의 `--before no-reset` 보호 조회는 Write timeout으로 실패했고,
PC 쪽 USB 재연결 후 동일 조회를 한 번 반복해도 같은 오류였다. 사용자는 화면 꺼짐과
녹색 LED 계속 켜짐을 보고했다. 열거 상태나 LED만으로 ROM 연결 성공을 판정하지 않았다.

확인된 Espressif USB Serial/JTAG에 맞는 esptool5.6.0의 `--before usb-reset`을
명시해 칩을 리셋한 뒤 보호 조회가 성공했다. 이어 같은 부트로더에서 no-reset
flash-id도 성공했다. 이는 관측한 연결 복구 절차이며, Windows 드라이버 자체 결함이나
수동 버튼 동작 실패의 정확한 원인을 확정한 것은 아니다. 보호 설정을 변경하지 않았다.

원본 읽기 조건인 ESP32-S3·16MB·보호 해제 상태를 조회로 확인했다. 새 로컬 폴더를
만들고 같은 부트로더 세션에서 ROM 방식16MB A 읽기를 안내했다. **백업 파일 길이·
A/B 해시·출고 부팅 복귀·복구 성공은 아직 미확인**이다. 전체 MAC·원본 flash·키는
이 기록에 포함하지 않는다.

## 펌웨어 교체 없는 관찰 경로의 공개 소스 검토

고정 공식 소스: `m5stack/StackChan`의
`28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400`.
아래는 소스 확인이며 사용자 기기에서의 프로토콜 실행 성공은 아니다.

| 경로 | 확인한 구조 | 현재 프로젝트에 적용할 때 남은 조건 |
|---|---|---|
| 공식 MCP | 공식 AI가 PC에 등록된 도구를 호출 | 카메라·모터를 PC가 요청하는 장치 API로 취급하지 않음 |
| Avatar LAN | 휴대폰이 WebSocket 서버를 열고, 원격 채널의 `AppLanAddress`를 받은 로봇이 접속 | 주소 전달 채널과 제품의 RSA 핸드셰이크 검증 경로 필요 |
| 휴대폰 LAN 수명 | Avatar/Motion/Monitoring Camera 페이지 유지·앱 전경·대상 지정에 종속 | 휴대폰 화면을 닫아도 유지되는 PC 상시 API라고 가정하지 않음 |
| BLE GATT | motion/avatar/config/RGB 특성과 battery 서비스; 읽기는 해당 버퍼 반환 | 센서·카메라의 최신 측정 API로 간주하지 않음. `hal_ble.cpp`의 공개 battery 콜백은 상수96이므로 실제 배터리 측정 근거로 사용하지 않음 |
| App Center | `firmwareUrl`을 `launchApp`에 전달하고 `start_ota_update` 실행 | 출고 펌웨어를 그대로 둔 동적 플러그인 설치 경로로 취급하지 않음 |

LAN 서버는 요청의 Authorization을 `decryptStackChanBlue`로 해독하고 대상 MAC을
검증한다. 이는 앱의 `ValueConstant.stackChanBluePrivateKey` 배포 입력에 의존한다.
인증을 생략하거나 제조사 키를 추출하는 방식으로 PC 연결을 만들지 않는다.
공식 앱이 정당하게 지원하는 기능이 있다는 사실만으로 PC 재구현·기존 음성 기능과의
동시 사용이 확인된 것은 아니다. BLE 동작 명령이나 카메라 스트림도 실행하지 않았다.

## 근거 파일

- [휴대폰 LAN 서비스·수명·인증](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/local_area_network_service.dart)
- [LAN 주소 발표](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/lan_endpoint_announcer.dart)
- [제품 핸드셰이크 해독](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/util/rsa_util.dart)
- [펌웨어 LAN 주소·카메라/동작 처리](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/hal_ws_avatar.cpp)
- [BLE 콜백](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/hal_ble.cpp)
- [GATT 버퍼 읽기](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/utils/bleprph/gatt_svr.c)
- [App Center 선택](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/apps/app_app_center/app_app_center.cpp)
- [App Center의 OTA 경로](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/hal_app_center.cpp)

## 현재 판정

USB 열거·도구 준비·ROM 연결·칩/보호/16MB 조회는 사용자 출력으로 확인했다.
출고 상태의 완전한 PC 관찰·제어 경로가 확보됐다는 판정은 하지 않는다.
[원본 보존 절차](../K151_BACKUP_RECOVERY.ko.md)에 따라 A/B 읽기와 길이·해시 비교를
진행한다. [커스텀 빌드의 공식 인증 HOLD](2026-11-17-k151-recovery-compatibility.md)는
원본 백업과 별도로 유지한다.
