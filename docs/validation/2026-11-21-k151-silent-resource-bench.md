# K151 실제 무음 모델 진단 1회와 원본 슬롯 복구

2026-11-21 / Asia/Seoul. 사용자의 **“진행해 승인”**을 받은 뒤 검토한 이미지로
임시 설치→합성 무음 진단1회→같은 슬롯 원본 복구를 실행했다. 실제 모델 준비와
64chunk 추론은 완료됐고 원본 슬롯의 독립 digest 검증도 통과했다. 출고 부팅 재시작
요청 뒤 COM3/정상으로 돌아왔다. 최초 기록 때는 화면 관찰 대기였으며, 이후
보드 조회 승인 전 사용자가 **이번 모델 진단 복구 후 출고 화면 정상**을 확인했다.
이전 재연결 때의 얼굴 복귀 답변을 대신 사용하지 않았다.

[Sanitized 수치 JSON](2026-11-21-k151-silent-resource-bench.json).
원본 flash, 원본 앱 slice, raw metadata/직렬 로그와 nonce 값은 게시하지 않는다.

## 실제 실행한 이미지와 범위

코드 `ebed42c82dfc0bb661b99d9573724ac5381ce401`, 실제 CI checkout
`3510d171cc8dae81011b359d0fe258c6ef3880cd`, 앱 version `3510d171cc8d`.
IDF6.1 commit `fff9895c82d744c7237be8847347bdd1b07c6643`, ESP-SR2.4.7,
`wn9l_histackchan_tts3` / `DET_MODE_90` / 16kHz mono PCM16을 사용했다.

| 단계 | offset | 파일 bytes | erase 범위(끝 제외) | 실제 결과 |
|---|---|---:|---|---|
| 임시 진단 앱 쓰기 | `0x510000` | 625968 | `[0x510000,0x5A9000)` /626688bytes | 8.2s, 내부 digest 및 별도 verify PASS |
| 원본 slot1 복구 | `0x510000` | 5177344 | `[0x510000,0xA00000)` | 69.6s, 내부 digest 및 별도 verify PASS |

진단 앱 SHA256:
`465cf701b8af7679dcdec7e1645cf24dc7acf180b760d3dfae2d834c96d5a21b`.
원본 slot1 slice SHA256:
`39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`.
전체 원본 A/B 및 별도 물리 디스크 사본 각16777216bytes SHA256:
`c1241a7c87145ee8b9569cfbcfbb1f8c289641856f9b9b5ddf2ccd565019543e`.
이 SHA는 로컬 파일 검증이며 장치 readback은 esptool의 독립 digest 대조다.

당시 USB303A:1001/COM3, S3 QFN56 rev0.2/16MB/보호 OFF를 다시 확인했다.
직렬 사용 가능성이 있는 프로세스가 없음을 먼저 조회했고, ROM 연결에서도 busy 오류가
없었다. 보관 원본과 현재 전체ota_1 digest가 일치한 뒤에만 쓰기를 시작했다.
원본 슬롯은 이미 차 있는 앱이며 안전한 spare로 취급하지 않았다.

모든 장치 명령은 고정 esptool5.6.0, `--no-stub --connect-attempts 1`이었다.
쓰기/verify는 `--flash-mode keep --flash-freq keep --flash-size keep`과 위 offset을
사용했다. reset4회는 ROM 진입/진단 부팅/ROM 복귀/출고 부팅 요청이다.
파티션 표와 otadata 각4KiB/8KiB를 쓰기 전·진단 후·복구 후 읽어 세 시점의 byte 일치를
확인했다. raw metadata 총36KiB만 보관했고 NVS는 읽지 않았다.
bootloader/table/NVS/otadata/다른 슬롯/assets/coredump/eFuse 쓰기 명령은 없었다.
전체16MB flash 복구도 하지 않았다.

## 실물 추론과 메모리 관측

새 USB nonce에 START를 **한 번** 보냈고 재시작/재등록/재시험하지 않았다.
읽은 직렬 정보는 고정 진단 상태와 수치만 whitelist 저장했으며 알 수 없는 문자열과
raw 직렬 본문은 저장하지 않았다. 총 수신1.8039s에 `FINITE_BENCH_COMPLETED`와
`HOLD_UNTIL_RESET`을 관측했다. 이 시간은 SDK 준비/버퍼/추론/정리를 포함한다.

| 항목 | 실제 관측 |
|---|---|
| 모델 chunk | 512samples /16kHz /mono PCM16 |
| 합성 무음 추론 | 64chunk, 최대7615µs, 100ms 초과0, 합성 감지0 |
| 질문 vector | 384000bytes, 실제 PSRAM 배치true |
| TTS vector | 960000bytes, 질문 vector와 동시에 PSRAM 배치true |
| 진단 앱의 실제 발화/마이크/스피커/모터/Wi-Fi/API | 초기화/명령/시험 없음 |
| TLS/JSON 동시 peak, operating admission | 미측정 /false 유지 |

| 단계 | internal free | internal largest | PSRAM free | PSRAM largest |
|---|---:|---:|---:|---:|
| 준비 전 baseline | 371427 | 249856 | 8385164 | 8257536 |
| 모델 준비 후 resident | 354283 | 241664 | 8047576 | 7995392 |
| 모델+질문+TTS | 354283 | 241664 | 6694860 | 6684672 |
| 합성 추론 후 | 354283 | 241664 | 6694860 | 6684672 |
| 정리 후 | 371339 | 249856 | 8385136 | 8257536 |

단위bytes. 모델 준비 전후 free 감소는 internal17144/PSRAM337588이다.
이 차이에는 PSA/global 초기화와 allocator 효과가 포함되므로 순수 신경망 RAM으로
단정하지 않는다. 모델 이후 동시 PCM 단계의 PSRAM free 감소는1352716bytes다.
정리 후 baseline 대비 free 차이는 internal88/PSRAM28bytes다. 한 번의 표본으로
누수나 장기 메모리 안정성을 판정하지 않는다.

local minimum monitor는 baseline 출력 뒤 시작했다. 모델 준비 후부터 정리까지
internal 최소346259/PSRAM 최소6694860을 관측했다. JSON의 baseline minimum은
이전 startup watermark이므로 local window의 minimum과 직접 비교하지 않는다.

## 판정과 다음 운영 연결 조건

실물에서 검증한 것은 **승인한 embedded pack의 로드·모델 context 준비·합성 무음
추론·동시 PCM allocator 배치·원본 슬롯 복구**다. 실제 “Hi StackChan” 인식률,
ambient 오탐률, 마이크24k→16k 실시간 공급 간격, 물리 STOP-to-mute/DMA drain,
질문/TLS/JSON/TTS 동시 peak와 독립 GPT 한 턴은 아직 검증하지 않았다.

다음 운영 bootstrap은 기존 NativeVoiceLoop/VoiceTurnCoordinator를 재사용하며,
실제 codec/네트워크가 살아 있는 현재 model-resident snapshot과 TLS 동시 peak를
다시 공급해야 한다. 이 과거 수치 파일을 현재 준비 상태로 넣거나
`question_tls_tts_peak_measured`/owner/assets를 무조건true로 만들지 않는다.
HOLD와 cloud 기본 OFF, 입력 간격100ms/chunk160..2048, 원래 STOP/SDK 단일 소유권/
terminal cleanup/volatile PCM wipe 보호를 유지한다. 개인 조수 등록은 재실행하지 않았다.

실행 이미지의 호스트456PASS5SKIP와 실제S3 build PASS는 이전에 확인했다.
그 코드의 CI는 **8/9**다: push44769990066 4/4, PR44770003494 3/4,
S3 build44770003545 1/1. PR Windows3.12 job136404806243의 cycle2763
renew_timeout은 COMMIT 안6.6713888s interruption이며 원인은 미확정이다.
실물 모델 진단 성공으로 Windows Mock 지연이나 wheel timeout이 해결됐다고 하지 않는다.
이번 기록 추가는 문서 변경이며 새 runtime 코드를 만들거나 안전 제한을 완화하지 않는다.

후속 사용자 관찰: 다음 보드 조회 승인 전에 “정상이야 다음단계진행해”로 출고
화면 복귀를 확인했다. 그 이후 별도 [보드 조회·복구](2026-11-21-k151-board-readback-live.md)도
완료했고 그 재부팅 뒤에도 새 얼굴/메뉴 복귀 확인을 받았다.

감사 기록: 최초 원본 슬롯 verify 자체는 성공했지만 로컬 wrapper가 성공문구를
`verified`로 잘못 검사해 멈췄다. 저장된 `Verification successful (digest matched)`
로그를 확인해 후처리만 바로잡았고 장치 verify 명령을 재실행하지 않았다.
