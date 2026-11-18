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
| 원본 A 읽기 | `factory-a.bin`: 도구가 주소0부터16,777,216바이트 읽기 완료 보고,1301.2초,103.2kbit/s |
| 원본 B 읽기 | `factory-b.bin`: 같은 ROM 설정에서16,777,216바이트 완료 보고,1309.6초,102.5kbit/s |
| 파일시스템 길이 | PowerShell 결과 A/B 모두16,777,216바이트 |
| SHA256 비교 | A/B 동일, `C1241A7C…5019543E`; 전체 값은 [메타데이터 기록](2026-11-18-k151-original-backup.json) |
| 부팅·기존 기능 복귀 | PC GPT 준비 후 짧은 RST 재부팅·앱·ANSWERED·로봇 음성 확인 요청에 사용자가 “잘된다” 응답 |
| 공식 앱 카메라 | Avatar 모드의 Monitoring Camera 영상 표시 확인 요청에 사용자가 “보여” 응답 |
| 현재 판정 | **원본 백업 파일 일치·정상 부팅 복귀·공식 앱 카메라 표시 PASS**, 실제 복구 쓰기 미실행 |

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
만들고 같은 부트로더 세션에서 ROM 방식16MB A 읽기를 수행했으며, 사용자가 다음
완료 출력을 제공했다. 경로는 파일명만 남겼다.

```text
Read 16777216 bytes from 0x00000000 in 1301.2 seconds (103.2 kbit/s) to 'factory-a.bin'.
Staying in bootloader.
```

이어 사용자가 B 읽기 완료와 같은 부트로더 유지 출력을 제공했다.

```text
Read 16777216 bytes from 0x00000000 in 1309.6 seconds (102.5 kbit/s) to 'factory-b.bin'.
Staying in bootloader.
```

별도 PowerShell 조회 결과에서 A/B의 실제 파일 길이가 각각16,777,216바이트였고,
SHA256은 모두 `C1241A7C87145EE8B9569CFBCFBB1F8C289641856F9B9B5DDF2CCD565019543E`였다.
따라서 **원본 백업 파일 일치 PASS**다. 원본은 사용자 노트북에만 있고 클라우드에서
직접 해시를 재계산한 것은 아니다. 전체 MAC·원본 flash·키는 이 기록에 포함하지 않는다.
약21분41초/21분50초는 실제 관측이며 다른 환경의 읽기 시간 보장은 아니다.

두 파일은 같은 로컬 디스크의 A/B 읽기다. **별도 비공개 저장장치 사본·실제 복구 쓰기
성공은 아직 미확인**이다. 파일 일치를 실제 restore 쓰기 성공과 동일하게 취급하지 않는다.

## 정상 부팅과 공식 앱 카메라 기본 동작

PC GPT 연결을 먼저 준비한 뒤 짧은 RST 한 번으로 정상 부팅하고, 기존 공식 앱 연결·
GPT_ANSWERED 표시·로봇 음성을 확인하도록 안내했다. 사용자는 **“잘된다”**고 응답했다.
이 범위는 사용자 보고로 PASS다. 전체 복귀 로그·정확한 GPT 호출 번호·부팅 후 펌웨어
버전은 다시 수집하지 않았고, 신규 이미지를 flash에 쓰거나 복원 쓰기를 수행하지 않았다.

이어서 로봇을 Avatar 모드로 바꾸고 공식 앱의 Monitoring Camera에서 빈 책상을 향한
영상이 보이는지 확인하도록 안내했다. 사용자는 **“보여”**라고 응답했다. 따라서 출고
펌웨어·공식 앱의 카메라 **기본 영상 표시 PASS**다. 카메라 화면을 닫고 로봇을 AI Agent로
돌아오도록 안내했으나, 카메라 확인 이후의 최종 모드 전환은 별도로 재확인하지 않았다.

실제 사진이나 영상은 채팅·GitHub·클라우드에 제공받지 않았다. 이 확인은 PC의 카메라
API 연결이나 GPT 이미지 전송, 센서 측정, 영상 최신성·지연·해상도 측정, 관찰과 음성의
동시 사용 검증을 포함하지 않는다. 기존 이미지 전송 설정을 켜지 않았다.

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
[원본 보존 절차](../K151_BACKUP_RECOVERY.ko.md)의 A/B 읽기·길이·해시 비교는 사용자
증거로 통과했고, 정상 부팅·기존 앱/GPT 기능 복귀와 공식 앱 카메라 기본 영상 표시도
사용자가 확인했다. 별도 비공개 저장장치 사본은 미확인이고 실제 복구 쓰기는 수행하지 않았다.
[커스텀 빌드의 공식 인증 HOLD](2026-11-17-k151-recovery-compatibility.md)는 원본 백업과
별도로 유지한다.
