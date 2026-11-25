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

## 리셋 순서 수정 이미지의 실물 결과와 출고 복구

I²S 송신 시작을 AW88298 리셋 해제와 기존 50ms 대기 뒤로 옮긴
이미지를 별도 승인 범위에서 1회 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `dc65da37dd0e7efc07a4391532c7ae18b5464c23`, SHA256 `f397e6ed2c243e862d7b85d146d2453f77454e07a2b353745185ffe2e550dfec` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 동일 보드, 16MB 플래시, 보안 상태, 파티션 표·OTA 선택 데이터·기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x5528B0)` 272,560바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 기기 결과 | `amplifier_start_failed / wait_clock`. `clock_wait_last=stable`, `clock_wait_exit=protection_active`, `undervoltage=true`. 나머지 보호 비트는 꺼져 있었고, 합성 PCM 전송 전에 정지했다. |
| 저전압 표시와 VDD | 클럭 활성화 설정 읽기 확인 562µs 뒤 `SYSST.UVLS` 관측. 그 관측 568µs 뒤 `startup_vdd=sampled`, `startup_vdd_mv=4382`. |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 해시 및 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 부팅 요청과 USB Serial/JTAG의 COM3 재연결 확인. 출고 화면은 현장 확인 전. |

이전 V5는 556µs에 저전압 표시를 읽었고, 572µs 뒤 4.370V를 얻었다.
수정 이미지에서도 같은 단계에서 같은 보호 비트가 관측됐다. 두 시험
모두 VDD 표본은 저전압 표시를 읽은 뒤 얻었다. 표시 당시의 전압이나
두 읽기 사이의 파형은 미측정이다. 실제 재생과 독립 대화가 남아 있다.

감독 세션은 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 파티션 표, OTA 선택 데이터,
NVS, assets 및 eFuse에는 쓰지 않았다. 마이크 사용, 음성 수집, 외부
전송 및 유료 API 호출은 없었다. 오프라인 스피커·수집기 시험 36개가
통과했다.

## V6 대기 상태 저전압과 출고 복구

`I2SEN` 활성화와 `PWDN` 해제를 분리한 합성음 진단을 별도 승인
범위에서 1회 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `4f695588aa8c6382da33fdd96ef285f888f5284d`, SHA256 `e4f5ee2f6a553b809471c7ce68ea0e56277bc3327651cf5b8cdb9cd0c1654894` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 동일 보드, 16MB 플래시, 보안 상태, 파티션 표·OTA 선택 데이터 및 기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x552930)` 272,688바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 기기 결과 | `K151_SPEAKER_V6 / amplifier_start_failed / wait_clock`, `clock_wait_last=stable`, `clock_wait_exit=protection_active`. `undervoltage`만 활성화됐고 합성 PCM 전송 전에 정지했다. |
| 대기 상태 | `standby_uvls=true`. AW88298의 `I2SEN` 설정과 `PWDN` 해제 전의 읽기이며, ESP32의 I²S 송신 클럭은 이미 시작한 상태였다. |
| 전환 이후 | `PWDN` 해제 읽기 확인 558µs 뒤 `UVLS` 관측. 그로부터 570µs 뒤 `startup_vdd=sampled`, `startup_vdd_mv=4476`. |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 플래시 해시와 원본 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 부팅 요청과 USB Serial/JTAG의 COM3 재연결 확인. 출고 화면은 현장 확인 전. |

Codex Desktop 업데이트로 원본 쓰기 완료 후 독립 검증이 중단됐다.
완료된 원본 쓰기 로그를 확인하고, 동일 보드와 보안 상태를 확인한 뒤
원본 해시 검증과 메타데이터 읽기부터 이어서 수행했다. 원본은 한 번
썼으며 이후 출고 재부팅을 요청했다. 파티션 표, OTA 선택 데이터,
NVS, assets 및 eFuse에는 쓰지 않았다. 마이크 사용, 음성 수집이나
유료 API 호출은 없었다.

이 시험에서 저전압 표시는 준비 단계에서 한 번, `PWDN` 해제 이후에
다시 읽혔다. 두 읽기 사이의 비트 상태와 전압 파형은 미측정이다.
데이터시트의 `UVLS` 기준은 2.8V이며, 4.476V는 다른 시점에 읽은
내부 ADC 표본이다. 저전압 표시의 원인과 실제 스피커 재생은 미확인이다.
[AW88298 상태 비트](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=31)

### V6 소스의 오프라인 검증과 CI

Windows standalone 회귀는 1,476개 통과, 8개 건너뜀을 기록했고
ESP32-S3용 V6 컴파일·링크 및 이미지 검사가 통과했다. GitHub의
`4f69558`은 8/9다. PR CI 네 조합과 타깃 빌드는 통과했다.
Push Windows/Python 3.12의 기본 시험은 502개 통과, 2개 건너뜀,
1개 실패였다. `test_subprocess_lease_acquisition_has_exactly_one_winner`
자식 프로세스가 `StateUnavailable`로 종료됐다. 해당 작업의 가상
soak는 시작하지 않았다. 로컬 Windows/Python 3.12에서 같은 시험을
한 번 실행해 통과했고, GitHub 실패 시의 저장소 단계는 확인되지 않았다.
[PR CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45362286359)
· [타깃 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45362286456)
· [실패 작업](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45362270298/job/138335024294)

## V7 TX 시작 전 저전압과 출고 복구

리셋 해제 대기 후의 상태와 SDK 초기화 구간을 나눈 V7 합성음 진단을
별도 승인 범위에서 1회 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `f50d1a93806fc82df197823079eb3187c3369cc9`, SHA256 `9ec14c287ed5016da601af272bc749b2f284ce7ec349b4cc00900c3cb11c53b6` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 동일 보드, 16MB 플래시, 보안 상태, 파티션 표·OTA 선택 데이터 및 기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x552AC0)` 273,088바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 초기화 구간 | `reset_uvls=[true,true,true]`. 순서대로 하드웨어 리셋 해제 대기 후 TX 시작 전, TX 시작 후 SDK 초기화 전, SDK 초기화 직후 |
| 대기 후 전환 | `standby_uvls=true`. `PWDN` 해제 읽기 확인 554µs 뒤 `SYSST.UVLS` 관측. 584µs 뒤 내부 ADC는 `startup_vdd=sampled`, `startup_vdd_mv=4370` 보고 |
| 기기 결과 | `amplifier_start_failed / wait_clock`, `clock_wait_last=stable`, `clock_wait_exit=protection_active`. `undervoltage`만 활성화됐고 합성 PCM 전송 전에 정지 |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 플래시 해시와 원본 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 부팅 요청과 USB Serial/JTAG의 COM3 재연결 확인. 출고 화면은 현장 확인 전. |

감독 프로세스는 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 보호 정지가 진단 종료 코드에
반영됐고 복구 절차는 완료됐다. 파티션 표, OTA 선택 데이터, NVS, assets
및 eFuse에는 쓰지 않았다. 마이크 사용, 음성 수집이나 유료 API 호출은
없었다.

저전압 표시는 I²S TX 시작과 SDK 초기화 전에 이미 관측됐으므로
두 단계가 이 시험의 첫 관측에 필요한 조건은 아니었다. 리셋 해제부터
첫 읽기까지와 각 표본 사이의 전압은 미측정이다. 4.370V는 보호 비트가
읽힌 뒤의 별도 ADC 값이다. 앰프 입력 `AXP_PS`의 실제 전압 파형과
실제 스피커 재생, 독립 대화는 확인되지 않았다.
[CoreS3 호스트 회로도](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/490/Sch_M5_CoreS3_v1.0.pdf#page=4)
· [AW88298의 VDD ADC 설명](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=23)

`f50d1a9` Windows standalone 회귀 1,486개가 통과했고 8개는
건너뛰었다. V7 ELF·bin의 ESP32-S3 빌드와 이미지 검사, 실물에서
수집한 V7 레코드와 설치 이미지 바인딩 검증이 통과했다. 같은 커밋의
GitHub 검사는 9/9 통과다.
[Push CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45370103227)
· [PR CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45370114330)
· [ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45370114312)

## V8 ADC 뒤 저전압 표시 해제와 출고 복구

앰프의 전압 ADC 뒤에 저전압 상태를 한 번 더 읽는 V8 합성음 진단을
별도 승인 범위에서 1회 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `4d686b1fb7c467ae4fed23cfbf533fb68ba3fc26`, SHA256 `32433a472c265fb052816245a220ea6bb6490d23cd58155a94ee597868ed61e2` |
| 쓰기 전 확인 | 원본 A/B와 복구 파일의 길이·해시, 동일 보드, 16MB 플래시, 보안 상태, 파티션 표·OTA 선택 데이터 및 기존 OTA1 대조 통과 |
| 진단 쓰기 | `ota_1 [0x510000,0x552BF0)` 273,392바이트, 영향 섹터 `[0x510000,0x553000)`. 독립 검증 통과 |
| 초기화 구간 | `reset_uvls=[true,true,true]`, `standby_uvls=true` |
| 전환 이후 | `vdd=[570,579,"sampled",4482,false,560]`. `PWDN` 해제 읽기 확인 후 570µs에 최초 저전압 보고, 1,149µs에 4.482V ADC 표본, 1,709µs에 저전압 표시 해제 관측 |
| 기기 결과 | `amplifier_start_failed / wait_clock`, `clock_wait_last=stable`, `clock_wait_exit=protection_active`. `undervoltage`만 최초 보호로 보고됐고 PCM 전송 전에 정지 |
| 출고 복구 | `ota_1 [0x510000,0xA00000)` 5,177,344바이트. 독립 플래시 해시와 원본 파티션 표·OTA 선택 데이터 일치 확인 |
| 재부팅 | 출고 부팅 요청과 USB Serial/JTAG의 COM3 재연결 확인. 출고 화면은 현장 확인 전. |

감독 프로세스는 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 파티션 표, OTA 선택 데이터,
NVS, assets 및 eFuse에는 쓰지 않았다. 마이크 사용, 음성 수집이나
유료 API 호출은 없었다.

기존 2ms 정착 조건보다 앞선 두 시점에서 저전압 표시가 서로 다르게
읽혔다. 실제 전압 파형이나 저전압 상태의 정확한 전환 시점은
미측정이다. 별도 임시 Mock은 같은 포트 코드에 실물의 세 시각과
4.482V를 주입하고, 마지막 표본만 해제 또는 지속으로 바꿔 실행했다.
두 경우 모두 최초 보호 정지가 유지됐고 PCM은 전송되지 않았다.
후속 실물 재생과 독립 대화는 미검증이다.

Windows standalone 회귀 1,498개 통과, 8개 건너뜀을 기록했고
V8 ESP32-S3 컴파일·링크와 이미지 검사가 통과했다. 이번 실물에서
수집한 V8 레코드와 설치 이미지 바인딩 검증도 통과했다.
[Push CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45376911604)
· [PR CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45376929218)
· [ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45376929342)

## V9 시작 통과와 종료 확인 실패

검토한 저음량 합성음 이미지를 승인 범위에서 한 번 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `17600748564dfb26102f57264bb0996fa7beac49`, SHA256 `e92b0537fcd5c83eeb1b0610d5a6aa6e3c17d26ed318225accd1b211e2e37b32` |
| 설치 | 동일 보드, 원본 백업과 OTA1, 보안과 메타데이터 확인. `ota_1 [0x510000,0x552DA0)` 273,824바이트 쓰기와 독립 검증 통과. 영향 섹터 끝 `0x553000` |
| 시작 | `settling_uvls=[558,7847]`. `PWDN` 해제 읽기 확인을 기준으로 558µs에 정착 중 저전압 표시를 읽었고, 7,847µs에 보호 해제와 클럭 준비를 확인했다. 시작 단계는 `none`이었다. |
| 최종 결과 | `cleanup_failed`, `operating_admission=false`. DMA 완료, 음소거 확인, 자원 해제 중 어느 시점에 처음 실패했는지 V9 결과만으로 확정할 수 없다. 실제로 들린 소리는 현장 관찰 전이다. |
| 출고 복구 | 원본 OTA1 전체 `0x510000`에서 5,177,344바이트를 복구했다. 독립 플래시 해시와 원본 파티션 표·OTA 선택 데이터를 확인하고 출고 재부팅을 요청했다. COM3 복귀를 확인했다. |

감독 실행기는 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 쓰기는 OTA1에 한정했다.
마이크나 유료 API를 사용하지 않았다.

I²S 자원 해제 실패를 합성 시험에 주입하면 시작 단계가 `none`이고
최종 결과가 `cleanup_failed`라는 점이 같았다. 이 결과는 짧은 쓰기로
PCM 전송을 중단한 경우와 전송·음소거를 확인한 경우 모두에서 나왔다.
실제 자원 해제 실패 원인은 추가 관측이 필요하다.

## V10 DMA 완료와 대기 상태 확인 실패

승인받은 V10 저음량 합성음 진단을 한 번 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `4c37dbe26f8700d8203cd0dbd351fd982b6d469e`, SHA256 `2bd58f2f69affe9d782360191f293d976c7ff1629c3883aa54a8eb564c7f301c` |
| 임시 쓰기 | `ota_1 [0x510000,0x552F10)`, 274,192바이트. 영향 섹터 끝 `0x553000`. 동일 보드와 원본 OTA1 사전 대조 및 임시 앱 독립 검증 통과. |
| 시작 및 전송 | `startup_stage=none`, `settling_uvls=[556,7905]`. 초기 저전압 표시가 해제됐고, `end` 첫 값 `1`로 DMA 완료를 확인했다. 실제로 들린 소리는 관찰하지 않았다. |
| 종료 | `cleanup_failed`, `end=[1,3]`. 대기 상태 요청과 출력 비활성화 이후 첫 실패가 앰프 대기 상태 확인에 남았다. 해당 확인은 코덱 제어 상태와 `ID`, `SYSCTRL`, `SYSCTRL2`, `SYSST.SWS`를 검사한다. |
| 복구 | 원본 OTA1 5,177,344바이트의 독립 해시와 파티션 표·OTA 선택 데이터 일치 확인. 출고 재부팅 요청과 COM3 재연결 확인. |

감독 실행기가 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`로 종료했다. 쓰기는 OTA1에 한정했고,
마이크와 유료 API는 사용하지 않았다.

AW88298의 전원 차단 도식은 칩 구성을 I²S 클럭을 끄기 전에 끝내고,
물리 리셋과 전원 차단을 뒤에 두는 순서다. 이 도식과 V10 레코드만으로
I²C 읽기 오류, 앞선 코덱 제어 오류, 레지스터 값 불일치 가운데 하나를
확정할 수 없다. V11은 기존 확인에서 처음 실패한 검사만 보고하며
타이밍 조건과 실패 시 리셋 동작을 유지한다.
[AW88298 데이터시트 17쪽](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=17)

## V11 DMA 완료와 종료 시 스위칭 표시

승인한 V11 저음량 합성음 진단을 한 번 실행했다.

| 항목 | 결과 |
|---|---|
| 소스와 이미지 | `4c315c7c78d5d38da9b68d85109279f8f81ebb26`, SHA256 `869d9994993a38e41003423a3d3a0d34d59cc3d344886d484dd79ec476205b5c` |
| 임시 쓰기 | `ota_1 [0x510000,0x552F90)`, 274,320바이트. 영향 섹터 끝 `0x553000`. 사전 대조와 임시 앱 독립 검증 통과. |
| 시작 및 전송 | `startup_stage=none`, `settling_uvls=[556,7889]`. DMA 완료를 보고했다. 실제로 들린 소리는 관찰하지 않았다. |
| 종료 | `cleanup_failed`, `end=[1,20]`. 출력 비활성화 뒤 칩 ID와 전력·음소거 레지스터 검사를 통과했다. 첫 실패는 읽기에 성공한 `SYSST`의 `SWS=1`이었다. |
| 복구 | 원본 OTA1 5,177,344바이트의 독립 해시와 파티션 표·OTA 선택 데이터 일치 확인. 출고 재부팅 요청과 COM3 재연결 확인. |

감독 실행기는 `preflight_exit=0`, `trial_runner_exit=1`,
`factory_restore_verified=true`를 기록했다. 마이크와 유료 API를
사용하지 않았고, 쓰기 범위는 OTA1이었다.

V11은 I²S 클럭을 끄기 전 `SWS`를 검사하지 않았다. 모의 시험에서
클럭이 유지되는 동안만 스위칭 표시가 가라앉는 경우를 주입했더니
기존 순서는 거부했다. V12는 DMA를 확인한 정상 종료에서 하드 음소거와
전력 차단을 읽어 확인하고, 클럭을 유지한 채 `SWS=0`을 먼저 확인한다.
그 뒤 I²S를 중단하고 기존의 최종 대기 상태 검사도 적용한다. 이 순서의
실물 결과는 별도 승인 뒤 검증해야 한다.
[AW88298 전원 차단 순서](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=17)

## V12 오프라인 회귀와 ESP32-S3 빌드

Windows standalone 전체 회귀는 1,570개 통과, 5개 건너뜀이다.
정상 스위칭 종료, 지속 스위칭, STOP, 시계 후퇴, 늦게 돌아온 상태 읽기,
상태 읽기 실패, 클럭 중단 뒤 스위칭 재발과 실제 TX 비활성화 실패를
모의했다. 실제 프로브의 100Hz 틱에서도 표본 간 대기가 10ms 틱에
묶이지 않도록 ESP ROM 타이머를 사용한다. 소프트웨어 확인 한도까지
도착하지 않은 표본은 채택하지 않는다.

소스 `1c834a8892e015d33e016abfdae55b4ff3ec82b6`으로 ESP32-S3
V12 합성음 앱을 빌드하고 ELF와 바이너리를 대조했다. 진단 이미지
SHA256은 `5320421207078ea5667202fa509e6acfc566e2eb1c334acc11df38fcfd4667a2`다.
274,912바이트는 OTA1 `[0x510000,0x5531E0)`에 들어가고, 지우기
범위 끝은 `0x554000`이다. 기존 전체 백업 두 개와 OTA1 복구 이미지의
길이·해시를 로컬에서 대조했다. 검토 실행기가 승인 기록 없이 중단하는
경우를 검증했다. 이 이미지의 실물 시험과 운영 승인은 대기 중이다.

## V12 실물 결과와 V13 종료 순서

검토한 V12를 한 번 실행했다. 임시 쓰기는 274,912바이트를
OTA1 `[0x510000,0x5531E0)`에 적용했고, 영향 섹터 끝은 `0x554000`이다.
기동 통과 이후 `settling_uvls=[560,7976]`, `cleanup_failed`,
`end=[1,23]`을 기록했다. DMA는 완료됐고 스위칭 종료를 10ms
소프트웨어 판정 한도와 최대 8회 확인 범위에서 확인하지 못했다.
기록은 두 제한 중 어느 쪽에 먼저 도달했는지 구분하지 않는다.
실제 가청 재생은 관찰하지 않았다.

원본 OTA1 5,177,344바이트를 복구하고 별도 해시 검증을 통과했다.
파티션 표와 OTA 선택 데이터가 일치했다. 출고 재부팅 요청과 COM3
복귀를 확인했다. 진단은 합성음만 사용했다.

코드에서 V12의 전체 대기 상태 요청은 ESP32 TX가 살아 있는 동안에도
앰프의 `SYSCTRL.I2SEN=0`, `AMPPD=1`, `PWDN=1`을 동시에 적용했다.
AW88298 문서에 따르면 설정 모드에서는 `AMPPD=1`, `PWDN=0`으로
내부 발진기와 PLL이 작동하며 `I2SEN`은 앰프 내부 I²S를 제어한다.
이 차이로 V12에서 `SWS` 갱신이 멈췄을 가능성을 모의했다.
실제 칩에서 `SWS`가 갱신되지 않은 이유는 아직 확인되지 않았다.
[AW88298 전력 모드와 레지스터](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=16)

V13 모의 시험은 내부 클럭과 시스템을 끄면 이전 스위칭 상태를
유지하는 경우에 기존 V12 종료가 실패하고, 하드 음소거 뒤 `AMPPD`만
먼저 설정하면 정상 종료함을 확인했다. 스위칭 종료를 확인한 뒤에야
전체 대기 상태를 요청한다. STOP이나 앰프 차단 읽기 불일치가 있으면
전체 대기 상태와 기존 리셋 경로로 즉시 진행한다. V13에서 이 순서와
실제 가청 재생은 실물 검증이 필요하다.

V13 Windows standalone 전체 회귀는 1,576개 통과, 5개 건너뜀이다.
`5943e40f70ba82c4f39dda6ece026568ca8bd5ef` 소스의 ESP32-S3 빌드와
ELF·바이너리 대조가 통과했다. 이미지 SHA256은
`a0e58212ac8f7e9a4030b33e5eab845c835c2e9fe4d2e5add1aac2e388b0bff5`다.
275,152바이트의 임시 대상은 `ota_1 [0x510000,0x5532D0)`이고
영향 섹터 끝은 `0x554000`이다. 백업 A/B 및 원본 OTA1 복구 파일의
길이와 해시, 승인 기록이 없을 때 장치 접근 전에 멈추는 조건을
오프라인에서 검증했다.

## V13 실물 앰프 종료 확인과 출고 복구

2026-11-25 검토한 V13 합성음 이미지를 승인 범위에서 한 번 실행했다.
275,152바이트의 임시 쓰기와 독립 검증이 통과했다. 결과는
`startup_stage=none`, `settling_uvls=[561,7986]`,
`dma_and_mute_observed`, `end=[2,0]`이었다. 스위칭 종료와 최종
앰프 대기 상태에 성공했고, 실제 가청 출력과 앞면 STOP부터 전기적
음소거까지의 시간은 이 시험에서 관측하지 않았다.

원본 OTA1 5,177,344바이트의 복구·독립 해시 검증과 파티션 표·OTA
선택 데이터 대조를 통과했다. 출고 재부팅 요청 및 COM3 복귀를
확인했다. 감독기는 사전 대조와 시험 종료 코드 0, 원본 복구 검증
완료, 승인 범위 소비를 기록했다. 합성음 경로만 사용했다.

같은 소스 트리의 GitHub ESP32-S3 독립 대화 검토 앱은
1,904,800바이트로 링크됐다. 검증 파일의 부팅 Cloud OFF, 비공개
정책 없음, 설치 비승인을 확인했다. 로컬 한 턴 설정·빌드 검토·
예산 스냅샷·복구 관련 회귀 106개가 통과했다.
[ESP32-S3 GitHub 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45419528005)

## 재생 중 STOP 실물 시도와 화면 권한

2026-11-25 `b1b171e`의 `K151_SPEAKER_STOP_V1`를 한 번 시험했다.
OTA1 588,704바이트의 설치 검증과 START는 통과했고,
`preparation_failed`, `sample_to_standby_us=null`을 받았다.
재생 준비 완료 표지 이전에 중단됐으며 오디오 재생과 STOP 지연은
관측 대상에 도달하지 않았다.

원본 OTA1 5,177,344바이트를 복구하고 별도 해시 검증을 통과했다.
파티션 표와 OTA 선택 데이터가 일치했고 출고 재부팅 요청과 COM3
복귀를 확인했다. 감독 실행기는 `preflight_exit=0`,
`trial_runner_exit=1`, `factory_restore_verified=true`를 남겼다.

기존 ELF의 `display_activation_allowed()` 경로는 화면 전용 진단의
빌드 플래그만 허용했다. 결합 앱의 화면 시작은 일반 장치 HOLD에서
거부된다. 실제 권한 함수를 결합 모의 시험에 링크하자 화면 준비에서
같은 중단을 재현했다. 화면 활성화 조건에 결합 진단 플래그만 추가했고,
모의 시험에서 일반 장치 활성화가 계속 거부되는 것도 검사했다.

관련 Windows 회귀 413개와 standalone 전체 회귀 1,584개가
통과했다. 전체 회귀에서 5개는 환경 조건으로 건너뛰었다. 일반 HOLD,
기존 합성음, 화면 단독 진단, 결합 진단을 실제 권한 코드와 함께
컴파일해 화면과 장치 권한을 각각 대조했다. ESP32-S3 수정판 ELF의
화면 권한 함수와 이미지의 무결성도 확인했다.

`2c9ded106330e1be5ff933f37f3d3884da207473`의 수정판 이미지
SHA256은 `d7fda7bd833e1faa70d3e672f5c94279549636266acd0759b2da667a771aadb2`다.
임시 쓰기 범위는 OTA1 `[0x510000,0x59FB90)`의 588,688바이트이며
영향 섹터 끝은 `0x5A0000`이다. 원본 백업과 복구 파일을 대조했고,
이전 이미지의 승인을 수정판에서 거부하는 경우도 검증했다.
