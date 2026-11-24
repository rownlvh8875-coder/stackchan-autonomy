# K151 저음량 합성음 시험 1회와 출고 복구

2026-11-24에 저음량 합성음 진단 1회와 원본 복구를 별도로 승인받았다.
사용자가 현장에 없는 조건에서 로봇의 진단 결과와 복구 검증을 수집했다.
[검토 이미지 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45185617275)

| 항목 | 결과 |
|---|---|
| 진단 이미지 SHA256 | `b0bf5eda193ddf568d6f92705f739f4282c5c47e00c1bc323c9575669a0e2275` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 같은 보드, 16MB 플래시, 보안 상태, 파티션 표와 OTA 선택 데이터 및 기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x551B20)`, 269,088바이트. 영향 섹터는 `[0x510000,0x552000)`. 독립 검증 통과 |
| 진단 결과 | `K151_SPEAKER_V1 / amplifier_start_failed` 1회. 합성 PCM의 전송과 DMA 종료 관찰에 이르기 전 정지 |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시 일치와 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 재부팅 요청 확인. USB Serial/JTAG가 COM3로 복귀. 출고 얼굴 화면과 실제 소리 청취는 현장 확인 전 |

감독 프로세스는 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 진단 시도는 1회였다.
파티션 표·OTA 선택 데이터·NVS·eFuse에는 쓰지 않았다. 실제 음성 수집,
외부 전송, 유료 API 호출은 없었다.

현재 결과 코드는 출력 코덱 열기, I2S TX 상태 확인, 볼륨 설정, 앰프
시작 확인 중 어느 검사에서 실패했는지 구분하지 않는다. 시험 뒤 Windows
오프라인의 스피커·코덱·수집기 관련 시험 31개가 통과했다. 재생 중
물리 STOP에서 전기적 뮤트까지의 실측과 독립 GPT 대화 검증이 남아 있다.

## V2 앰프 클럭 확인과 출고 복구

별도로 승인받은 V2 이미지를 사용했다. 먼저 현지 ROM 도우미에 남은
V1의 검토 ID와 이미지 해시로 인해 포트를 열기 전에 거부됐다.
첫 시도 기록을 보존하고, 같은 V2 승인과 이미지·원본 복구 해시에
도우미를 맞췄다. 이전 도우미의 거부와 고친 도우미의 승인·이미지
대조를 오프라인에서 확인했다. 실물 기록 및 진단 실행은 각각 1회였다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `92b92f83a547ad0a6222d8fe4638e7c3f08fe8e5`, SHA256 `de78636e989226941086da2f403ac54b4005327f260038209a8926243c4cd45e` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일, 같은 보드, 보안 상태, 파티션 표·OTA 선택 데이터·기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x551EE0)` 270,048바이트, 영향 섹터 `[0x510000,0x552000)`. 독립 검증 통과 |
| 기기 결과 | `K151_SPEAKER_V2 / amplifier_start_failed / wait_clock`. 합성 PCM 전송 전, 최종 HOLD |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시와 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 부팅 요청 확인 및 COM3 복귀. 화면은 현장 확인 전 |

실제 기록을 수행한 감독 세션의 결과는 `preflight_exit=0`,
`trial_runner_exit=1`, `factory_restore_verified=true`였다.
오디오 수집, 외부 전송, API 호출은 없었다. NVS, 파티션 표,
OTA 선택 데이터와 eFuse에 쓰지 않았다.

`wait_clock`은 AW88298의 클럭 활성화 설정을 쓰고 읽어 대조한
뒤 시작된다. V2는 이 구간의 상태 읽기 실패, 보호 상태, 비정상 스위칭,
클럭·PLL 미확인과 시간 제한을 한 코드로 보고한다. 드라이버의 TX
활성 상태만 확인했으며, 보드 BCK·WCK의 전기적 상태는 미측정이다.

## V3 보호 상태와 출고 복구

사용자 발화나 터치 없이 진행하는 V3 진단 1회와 출고 복구를 별도로
승인받았다. Windows 호스트 회귀는 1,386개 통과, 6개 건너뜀을 기록했고,
검토한 V3 이미지의 ESP32-S3 컴파일과 링크를 확인했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `8f2409b18324f36f6b70ab2f1173425dd040e74e`, SHA256 `7f63ea4dcca60e65de45b711db9870c85e093bf0e694df1dbb7323da70612d7c` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일, 동일 보드, 보안 상태, 파티션 표·OTA 선택 데이터·기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x5522C0)` 271,040바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 기기 결과 | `K151_SPEAKER_V3 / amplifier_start_failed / wait_clock`, `clock_wait_exit=protection_active`, `clock_wait_last=stable`. 합성 PCM 전송 전 정지 후 HOLD |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시와 파티션 표·OTA 선택 데이터 일치 |
| 재부팅 | 출고 펌웨어 부팅 요청과 USB Serial/JTAG의 COM3 복귀 확인. 화면은 현장에서 확인하지 않았다. |

감독 세션은 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 실제 진단 실행은 1회였다.
파티션 표, OTA 선택 데이터, NVS와 eFuse는 쓰기 범위에서 제외했다.
실제 음성 수집이나 외부 전송, API 호출은 없었다.

`stable`은 AW88298의 같은 `SYSST` 읽기에서 기준 클럭·PLL·내부 클럭
조건을 만족했다는 뜻이다. 그 읽기에 보호 비트도 설정돼 기존 안전
절차가 시작을 중단했다. 활성 보호 비트의 종류와 BCK·WCK의 전기적
상태는 미확인이다. 실제 재생과 재생 중 물리 STOP 검증이 남아 있다.

## V4 저전압 표시와 출고 복구

승인된 V4 진단을 1회 실행했다. 오프라인 Windows standalone 회귀는
1,395개 통과, 6개 건너뜀을 기록했다. 검토한 ESP32-S3 이미지의 컴파일,
링크와 이미지 검증을 완료했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `1970494417e0e273773eb9638b743bce2afe634f`, SHA256 `45c1081de3308fecff63f356f4c18bfd0edb1219c298817c1046900cf5861373` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 같은 보드, 보안 상태, 파티션 표·OTA 선택 데이터·기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x552450)` 271,440바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 기기 결과 | `K151_SPEAKER_V4 / amplifier_start_failed / wait_clock`, `clock_wait_exit=protection_active`, `clock_wait_last=stable`, `undervoltage=true`. 나머지 보호 비트 5개는 `false`. 합성 PCM을 보내기 전에 정지하고 HOLD에 도달 |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시 및 파티션 표·OTA 선택 데이터 일치 |
| 재부팅 | 출고 펌웨어 부팅 요청 및 USB Serial/JTAG의 COM3 복귀 확인. 화면은 현장에서 확인하지 않았다. |

감독 세션은 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 파티션 표, OTA 선택 데이터,
NVS, assets 및 eFuse는 쓰기 범위에서 제외했다. 마이크 사용, 음성 수집,
외부 전송과 API 호출은 없었다.

`undervoltage`는 AW88298 `SYSST.UVLS`의 상태다. 데이터시트는 이 비트의
기준을 VDD 2.8V로 명시한다. 이번 시험은 앰프의 상태만 읽었으므로 실제
전압, 발생 시점의 전원 경로 상태와 원인은 미확인이다. M5Stack이 K151에
공개한 호스트 회로도에서 앰프 VDD는 `AXP_PS`에 연결돼 있다. 다음
오프라인 조사에서는 출고 코드와 진단 코드의 전원 초기화 순서를 대조한다.
[AW88298 데이터시트의 SYSST 표](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=31)
[M5Stack StackChan 호스트 회로도](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/490/Sch_M5_CoreS3_v1.0.pdf#page=4)

## 전원 전용 실물 결과와 출고 복구

검토한 전원 전용 이미지를 한 번 실행했다. Windows standalone
오프라인 회귀 1,455개 통과, 6개 건너뜀과 ESP32-S3 빌드·링크를
확인한 이미지다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `6ac1ed8a25a27b1b2e68400ae0e9d0ea3556d0d9`, SHA256 `d8e6fa2e660f8d7f202711f0bdd29aec79fae5c053b22592c83de9f996142b15` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 같은 보드, 보안 상태, 기존 파티션 표·OTA 선택 데이터·OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x53D630)` 185,904바이트, 영향 섹터 `[0x510000,0x53E000)`. 독립 검증 통과 |
| AXP2101 | `pmic_vsys=sampled`, `pmic_vsys_mv=4443` |
| AW88298 | `amp_vdd=powered_down`, `amp_uvls=null`. VDD 표본 없음 |
| 종료 | START 1회, `K151_POWER_READBACK_V1` 보고와 HOLD 확인. `operating_admission=false` |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시 및 파티션 표·OTA 선택 데이터 일치 |
| 재부팅 | 출고 펌웨어 부팅 요청과 USB Serial/JTAG의 COM3 복귀 확인. 화면은 현장에서 확인하지 않았다. |

감독 세션은 `preflight_exit=0`, `trial_runner_exit=0`,
`factory_restore_verified=true`를 기록했다. 전원 설정, 앰프 리셋,
스피커·마이크 구동, 외부 전송과 API 호출은 없었다. 파티션 표,
OTA 선택 데이터, NVS, assets와 eFuse는 쓰기 범위에서 제외했다.

VSYS 4.443V는 이 부팅에서 AXP2101의 내부 ADC가 보고한 대기 표본이다.
V4가 클럭 활성화 단계에서 멈춘 순간의 앰프 VDD와 동시 전원 상태는
미확인이다.

## 동일 소스의 CI와 Windows 모의 재현

소스 `6ac1ed8`의 PR PC 검사 4개와 ESP32-S3 검사 1개는 통과했다.
push PC 검사 4개 중 Windows/Python 3.12의 가속 Mock soak만 실패해
전체는 8/9였다. cycle 744에서 `engine_failure / renew_timeout`으로
안전 정지했다. 중단 당시 `lease_renew/sqlite_commit` 경과 시간은
6.627초였다. 전체 기록에서 실행기 대기는 최대 약 4.4ms, 저장소 직렬
대기는 약 21.6ms, 이벤트 루프 지연은 약 53.9ms였다.
[실패한 push 작업](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45318478426/job/138190969753)

로컬 Windows에선 임시 SQLite 파일과 가짜 로봇으로 갱신 한 번의
커밋 진입부에만 지연을 주입했다. 기본 기한에서 `renew_timeout`과
`lease_renew/sqlite_commit` 중단(6.666초)을 재현했다. 실행기 대기
최대 5.0ms, 이벤트 루프 지연 최대 12.6ms였고, 갱신은 한 번만
시도했으며 로봇 명령은 없었다. 관련 회귀 24개 통과를 확인했다.
GitHub 환경에서 SQLite 커밋이 지연된 원인은 미확인이다.

## V5 시작 시 VDD 표본과 출고 복구

검토한 V5 진단을 승인 범위에 따라 1회 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `6cef0c92e80dc3245f85801df16e710a559c01c5`, SHA256 `b2b2cbbc609565287ba14d4d0d94384748116dd9407ed155bd0a4be487c01aa9` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 동일 보드, 16MB 플래시, 보안 상태, 파티션 표·OTA 선택 데이터·기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x5528B0)` 272,560바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 기기 결과 | `K151_SPEAKER_V5 / amplifier_start_failed / wait_clock`, `clock_wait_exit=protection_active`, `clock_wait_last=stable`. `undervoltage`만 활성화됐고 합성 PCM 전송 전에 정지했다. |
| 저전압 표시와 VDD | 클럭 활성화 설정 읽기 확인 556µs 뒤 `SYSST.UVLS` 관측. 그 관측 572µs 뒤 `startup_vdd=sampled`, `startup_vdd_mv=4370`. |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시 및 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 펌웨어 부팅 요청과 USB Serial/JTAG의 COM3 재연결 확인. 출고 화면은 현장 확인 전. |

감독 세션에서 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 확인했다. 파티션 표, OTA 선택 데이터,
NVS, assets 및 eFuse에는 쓰지 않았다. 마이크 사용, 음성 수집, 외부
전송 및 유료 API 호출은 없었다.

데이터시트의 `SYSST.UVLS` 기준은 2.8V다. 4.370V는 표시를 읽은 뒤
다른 레지스터에서 얻은 내부 ADC 표본이다. 표시 시점의 VDD와 그
사이의 파형은 미측정이므로 순간 전압 강하나 시작 시퀀스의 영향을
구분할 수 없다. 출력 보호와 운영 승인 조건을 유지한다.
[AW88298의 저전압 상태 비트](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=31) · [VDD ADC 설명](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=23)
