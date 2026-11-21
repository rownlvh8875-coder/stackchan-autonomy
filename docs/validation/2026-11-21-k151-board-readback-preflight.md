# K151 board readback 준비 검증 — 실물 미적용

2026-11-21. 코드 `36c4e98ed1b41aa04e80c7d662986649f29259e5`, 실제 CI checkout
`c991ec9523d6a82c6908c9aa4bade5b8fdb62991`, app version `c991ec9523d6`.
같은 `feat/wakeword-josu` / PR #3. [숫자 기록](2026-11-21-k151-board-readback-preflight.json),
[조회 범위·소스](../K151_BOARD_READBACK.ko.md)를 따른다.

| 구분 | 실제 결과 |
|---|---|
| Mock/오프라인 | root495PASS2SKIP; standalone550PASS5SKIP; Ruff/format350files PASS |
| 실제 ESP32-S3 compile/link | HOLD·기존 무음 모델 진단·새 board_probe 모두 PASS |
| 새 보드 진단 실물 설치/조회 | 미실행; 이번 기기 명령0/쓰기0 |
| 실제 Hi StackChan 인식 / 독립 GPT 한 턴 | 미검증 / 미검증 |

S3 [run44844341123](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44844341123),
job136660249862의 artifact14682032410을 내려받았다. ZIP SHA256
`b208f8b2928f776a0c6081649112f12a4446bce908305f9b78b915ad1abd2b86` 일치,
checkout/app version, Xtensa ELF/bin descriptor, checksum/SHA와 S3 revision,
실제 빌드 table.bin에서 IDF 도구가 생성한 CSV와 선택 slot/subtype/size/erase 범위를
로컬에서 재검증했다. notice50개 SHA와 프로젝트 MIT·IDF·FreeRTOS 고지도 대조했다.
보충 IDF component notice를 넓게 모은 것이며 모두 실제 링크됐다는 뜻은 아니다.
공통 검증기로 이전에 승인·실행했던 정확한 모델 진단 bin/ELF/모델도 다시 통과했다.

## 정확한 이미지·복구 범위

- app185744bytes, SHA256 `128969c002b9b1242679baf1658b66951fe7c7c076b00e573dd221d34ff5aa17`.
- ELF SHA256 `7d18bf169b9292812636c9df022616425f345b62903f28d5f6f079e70a85a9c4`.
- 임시 쓰기 `[0x510000,0x53D590)`, erase `[0x510000,0x53E000)`188416bytes/46sector.
  마지막2672bytes도 영향. 점유 중인 원본 ota_1이며 safe spare를 가정하지 않는다.
- 조회1회 뒤 같은 slot1 전체 `[0x510000,0xA00000)`5177344bytes 복구를 제안한다.
  복구 SHA256 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`.
- 원본A/B·별도 디스크 사본 각16777216bytes, SHA256
  `c1241a7c87145ee8b9569cfbcfbb1f8c289641856f9b9b5ddf2ccd565019543e`
  일치를 이번에 재확인했다. 원본 내용·설정·토큰은 업로드하지 않았다.

로컬 `.local/device-preflight/board-readback-20261121/INSTALL-REVIEW.ko.md`에
실행/검증/복구 명령·백업 증거·중단 조건을 준비했다. 실행하지 않았다. 승인 뒤에도
새 PnP/포트 사용/칩/보호/16MB/현재 table·OTA/원본slot digest 확인이 선행한다.
COM3는 이전 관측이다. 생성 bootloader/table/ota_data_initial과 IDF flash 예시는
사용하지 않는다. 새 조회는 START 뒤 GPIO12/11 mux와 I2C pointer/read를 수반한다.
NVS/table/OTA metadata/eFuse·전원/앰프 설정값 쓰기와 full16MB 복구는 포함하지 않는다.
이전 무음 진단과 다른 구체적 설치/조회/같은 슬롯 복구 승인 범위다.

## 코드 CI: 8/9, green 아님

| 이벤트 | 결과 | Run |
|---|---|---|
| Push | 4/4 PASS | [44844335376](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44844335376) |
| PR | 3/4 PASS | [44844341081](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44844341081) |
| S3 | 1/1 PASS | [44844341123](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44844341123) |

PR Windows3.11 job136660250179의 `test_live_heartbeat_renews_ownership_until_close`가
`contender.acquire()`의 StateUnavailable로 실패했다. root494PASS/1FAIL/2SKIP,
187.42s이며 **virtual soak 전에** 실패했다. 원본 SQLite 예외를 fromNone으로 감싸
로그에는 오류 코드와 정확한 실패 SQL 단계가 없다. 예전 cycle2492/COMMIT stall과
같은 원인으로 단정하지 않는다. 실패 job 재실행은0이다.

통과한 Windows3개는2880cycle PASS/cloud0/잔류task0이다. Push3.11 wall218.203s/
COMMITmax0.837006s, Push3.12 wall232.109s/COMMITmax0.856917s,
PR3.12 wall259.921s/COMMITmax1.891598s였다. Push3.12 loop lag max1.983436s,
serial queue max0.787775s, executor queue max0.018490s도 관측됐다. interruption1회는
lease_renew/sqlite_body/0.0229163s로 기록됐다. 서로 다른 aggregate maxima/snapshot이므로
같은 시점/원인을 증명하지 않는다.

노트북 유한 Mock120cycle(measured20)은3.297s PASS. COMMITmax3.3571ms,
executor queue max7.6132ms, loop lag max37.2925ms로 CI stall을 재현하지 못했다.
별도 실제 로컬 SQLite writer lock 제어 실험은 BEGIN에서 SQLITE_BUSY(code5)→
StateUnavailable 안전 거부를0.359s에 재현했다. 가능한 오류 경로이며 CI 원인 확정이
아니다. 실제 I/O 대기와 worker OS 비실행 시간도 미분리다. root engine/timeout/
lease/내구성/검사는 변경하지 않았다. 기존696460c8/9와 후속 실패는 PR에 보존했다.

## 남은 조건

이번 이미지에는 마이크/I2S·스피커·모델·NVS·Wi-Fi/API startup이 없다. 운영 HOLD와
cloud OFF를 유지한다. codec1.6.2의1000ms 대기·short read·PCM wipe 강화, 실제
전원/mute/STOP·DMA drain, TLS/음성 동시 peak와 호출어/GPT는 후속이다. 설정 조회는
전기적 동작 증명이나 readiness 권한을 주지 않는다. 부분 NACK 조합 fixture는 독립
검토 Minor로 남겼으며 전체 ACK/NACK과23개 SDK 경계는 검증했다. Important3는
RED→GREEN으로 수정했다. 이전 원본 복구 뒤 새 출고 얼굴/메뉴 관찰과 이번 이미지의
설치/조회1회/같은 슬롯 복구 승인을 받기 전 새 하드웨어 동작을 실행하지 않는다.
