# K151 읽기 전용 보드 진단 준비

2026-11-21 후속: 사용자 승인으로 검토한 보드 조회를1회 실행했고7142µs에 완료했다.
원본 slot1 복구·독립 verify·표/OTA 세 시점 일치와 **사용자의 얼굴/메뉴 복귀 확인**까지
완료했다. [실물 결과](validation/2026-11-21-k151-board-readback-live.md)를 우선한다.
아래는 이 실제 실행 전 준비 범위와 제한이다. 추가 설치/조회 권한을 부여하지 않는다.

기존 `K151ReadOnlyProbe`를 확장한 작은 `board_probe` 앱이다. 운영 `esp_app`은
계속 HOLD다. 새 마이크·스피커 드라이버를 시작하기 전에 PMIC 설정과 IO 출력
래치/방향을 관찰할 수 있게 준비한다. 이 값은 실제 전압·앰프 mute·reset 파형,
물리 STOP, DMA drain 또는 오디오 배선의 정상 동작을 증명하지 않는다.

## 진단 범위

부팅 시 실제 실행 파티션과 칩 모델/리비전을 조회한다. 실행 위치가
`0x510000`, 크기가 `0x4f0000`, ESP32-S3 rev0.2인 경우만 USB START 대기를 연다.
임의 슬롯을 빈 공간으로 간주하지 않는다. 현재 원본 slot1은 점유되어 있다.

기존 `BenchGate`를 재사용한다. 부팅별 nonce가 포함된 START를 60초 안에 한 번
받아야 GPIO12/11의 I2C1 버스를 연다. START 뒤 10초의 소프트 기한과 USB STOP을
별도 reader task에서 관찰한다. 잘못된 입력·시간 역행·기한 만료는 중지로 잠긴다.
각 probe/read는 SDK timeout 30ms이며 호출 전후에 동의/STOP을 확인한다.
이는 하드 실시간 STOP 보장이 아니다. SDK 내부 버스 생성/해제·스케줄링의
최악 지연과 GPIO mux의 해제 후 전기 상태는 아직 실물에서 측정하지 않았다.

| 장치 / 7비트 주소 | 읽는 레지스터 |
|---|---|
| AXP2101 / `0x34` | ID `0x03`, 설정 `0x90/94/95/97/99` 각 1byte |
| AW9523 / `0x58` | ID `0x10` 1byte, output latch `0x02..03`, direction `0x04..05` |
| FT6336 / `0x38` | 기존 version `0xa3..a8` 6byte; work-mode 설정 없음 |
| ES7210 / `0x40`, AW88298 / `0x36` | ACK 조회만 |

마이크 전기 확인 후속은 PMIC `0x92/0x93`과 AW9523B `0x12`를 각각
한 바이트씩 더 읽고, 기존 보고 필드와 함께 별도 유효성 및 값을 출력한다.
읽은 값의 해석과 실제 측정 범위는 [마이크 전기 확인 기록](validation/2026-11-21-k151-mic-electrical-preflight.md)에 있다.
위 표와 앞선 실물 기록은 그때 실행한 이미지의 범위를 나타낸다.

전송은 1byte register pointer와 repeated-start read뿐이다. 레지스터 설정값,
PMIC 전원 변경, AW9523 reset/출력 변경, touch mode 설정은 보내지 않는다.
마이크/I2S·스피커/코덱·모델·NVS·Wi-Fi·TLS·유료 API는 시작하지 않는다.
GPIO mux와 버스 신호는 실제 하드웨어 동작이므로 이 앱의 설치/실행에 새 승인이 필요하다.

SDK 호출 실패·동의 철회·STOP·cleanup 오류가 있으면 이전/부분 결과까지 전부
무효화한다. NACK은 별도 유효 관찰이며 해당 레지스터 그룹의 valid는 false다.
완료 JSON의 각 valid와 ACK를 함께 해석해야 한다. 읽기 성공만으로 장치를
정확히 식별하거나 오디오 사용 권한을 부여하지 않는다. 완료/실패 후 재시험 없이 HOLD한다.

## 소스에서 확인한 수정과 제한

기존 probe는 코덱의 8비트 기본 주소를 IDF7비트 주소로 전달했다. 실제 C++ 코드를
C ABI double로 실행해 잘못된 주소를 재현한 뒤 `0x40/0x36`으로 수정했다.
물리 주소는 공통 보드 증거에 두고 실제 codec 빌드에서 SDK 상수와 shift 관계를
static_assert한다. 별도 보드 앱은 코덱 SDK를 주소 때문에 링크하지 않는다.
근거는 고정 [ES7210 헤더](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/device/include/es7210_adc.h),
[AW88298 헤더](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/device/include/aw88298_dac.h),
[동일 SDK의 I2C 변환](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/platform/audio_codec_ctrl_i2c.c)이다.

PMIC 설정은 [고정 제조사 board 소스](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc)의
사용 레지스터만 읽는다. AW9523의 output/config/ID 주소는
[Linux v6.12 드라이버](https://github.com/torvalds/linux/blob/v6.12/drivers/pinctrl/pinctrl-aw9523.c)와 대조했다.
해당 구현 코드는 복사하지 않았다. 입력/인터럽트 상태나 soft reset은 읽거나 쓰지 않는다.

별도 감사에서 [codec1.6.2의 I2S data 구현](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/platform/audio_codec_data_i2s.c)이
1000ms 기본 대기와 short byte count 미검사를 사용함을 확인했다. 현재 주석의
10ms는 PCM 길이이며 호출 지연 보장이 아니다. 실제 마이크를 시작하기 전에
bounded I/O·partial read·오류 후 non-elidable PCM wipe를 별도 회귀 시험으로
강화해야 한다. 이번 조회 준비가 그 문제를 해결했다고 보고하지 않는다.

## 검증과 설치 전 조건

최적화된 실제 observer C++에서 정상/NACK/초기 거부/STOP과 23개 SDK 경계의
오류·STOP·동의 철회 총 73case를 실행했다. 칩/실행 슬롯 범위도 호스트에서 검증한다.
공통 ESP image parser를 재사용해 project·Xtensa ELF SHA·source version·S3 revision·
checksum·app SHA·점유 슬롯 크기/erase 범위를 검사한다. 모델 진단 검증기도 같은
parser를 쓰며 기존 모델 SHA/DROM 검사를 유지한다. 이들은 Mock/오프라인 증거다.

실제 S3 compile/link·artifact SHA/길이와 코드36c4e98의 CI **8/9** 결과는
[후속 검증 기록](validation/2026-11-21-k151-board-readback-preflight.md)에 작성했다.
빌드/업로드 자체가 설치 승인은 아니다. 새 이미지를
검토할 때는 정확한 쓰기/erase 범위, 원본 A/B·별도 저장장치 사본·slot1 복구 slice
재검증, 실행·검증·복구 명령, 중단 조건이 있는 로컬 검토 묶음을 먼저 준비한다.
생성된 bootloader/partition table은 설치 대상이 아니다. 장치 상태를 다시 확인하고
승인된 진단을 한 번 실행한 뒤 같은 slot1 전체 원본을 복구하는 범위를 검토한다.
원본 백업·설정·토큰은 업로드하지 않는다.

독립 검토 후 선택한 write offset과 실제 빌드 table.bin에서 IDF 도구로 생성한 CSV의
OTA subtype/크기/erase 범위를 결합했다. 잘못된 슬롯/overlap/암호화 flags는 거부한다.
실행 위치가 다르거나 partition 조회가 없을 때도 실제 숫자/null을 먼저 기록하고
USB START·I2C 전에 거부한다. actual app_main을 C ABI double로 실행해 확인했다.
프로젝트 MIT·IDF·FreeRTOS copyright/permission과 보충 IDF component notice를
SHA inventory와 함께 패킹한다. 3개 Important는 RED→GREEN으로 수정했으며,
Minor인 부분 NACK 조합 fixture는 후속으로 남긴다 (전체 ACK/전체 NACK은 검증).
Root 로컬 495PASS2SKIP, 짧은 Windows Mock120cycle PASS3.297s/cloud0/잔류task0.
COMMIT max3.3571ms, executor queue max7.6132ms, loop lag max37.2925ms로 과거 CI의
수초 stall을 재현하지 못했다. 기존 root engine·timeout·lease·내구성은 변경하지 않았다.

최종 로컬 standalone은 선택 NumPy/cryptography와 최적화/assertions ON 컴파일러를
포함해 **550PASS5SKIP**(92.09s), root **495PASS2SKIP**(99.41s)이다.
Ruff/format350files와 diff 검사를 통과했다. 실제 target 빌드/새 이미지의 실물 실행과
혼동하지 않는다. CI/이미지 최종 검토는 위 기록을 따른다. S3 target은 통과했고,
PR Windows3.11 root heartbeat 시험의 StateUnavailable는 미해결이다.
