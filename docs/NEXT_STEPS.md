# Next steps

## 2026-11-21 실물 후속: 모델 진단1회·원본 슬롯 복구

사용자 승인 뒤 기존 어댑터와 embedded pack의 [별도 무음 진단](K151_RESOURCE_BENCH.ko.md)을
실제ota_1에 한 번 설치했다. 512sample×64 합성 chunk, 최대7.615ms 추론,
질문384000/TTS960000bytes 동시 PSRAM 배치를 관측했다. 같은 슬롯 원본5177344bytes를
복구하고 독립 verify/표·OTA 전후 일치를 확인했다. 새 출고 얼굴/메뉴 관찰은 대기 중이다.
[실물 수치·범위](validation/2026-11-21-k151-silent-resource-bench.md)를 우선한다.
다음은 기존 운영 bootstrap의 실제 mic/출력 STOP·DMA drain과 TLS 동시 peak 증거다.
과거 실측으로 현재 readiness를 만들지 않는다. cloud 기본 OFF/운영 HOLD를 유지하며,
실제 호출어 인식·독립 GPT 성공은 아직 없다. 아래는 이 단계 전의 이력이다.

## Windows 인수 (2026-11-20, PR #3 후속)

기존 clean `feat/wakeword-josu`를696460c로 fast-forward한 뒤 Windows Mock
지연 진단·검증한 백업의 sanitized OTA 분석·고정 모델 재패킹·휴면 owner loop와
model/TLS 동시 peak admission을 추가했다. [인수 결과](validation/2026-11-20-windows-handoff.md)와
[설치/복구 준비](K151_NATIVE_INSTALL_PREP.ko.md)를 따른다. 기존696460c CI는 **8/9**이며
과거 check_timeout의 root cause는 아직 미확정이다. 새 진단은 제한 완화나 실패 재시도 없이
큐/worker/SQLite/전달/loop 지연을 나눈다. 최초에는COM3이Unknown이었으나 사용자 재연결
후COM3/303A:1001·S3/16MB/보호 OFF와 현재 표/OTA12KiB의 원본 일치를 직접 확인했다.
[현장 조회와 실제 partition SHA 진입점 연결](validation/2026-11-20-k151-current-usb-and-assets.md)을 따른다.
조회용 칩 리셋2회 뒤 flash 부팅 복귀를 요청했다. 설치/실물 모델 추론/유료 API는 미실행이다.
기존 한국어 보정 반복과 임의 문턱 변경은 하지 않는다.

## 현재 우선 작업 (2026-11-20)

최신 사용자 보정은 **calibration_not_separable**로 확인됐다. 기존 문턱으로 호출과 비호출을 분리할 수 없어 동일 등록 반복을 중단한다. 사용자는 추천한 **기본 호출어 지원 검증 → 독립 GPT 대화 우선** 방향에 진행을 지시했다. 공식 Hi StackChan 모델과 고정 IDF6.1/ESP-SR2.4.7의 실제 ESP32-S3 컴파일/링크/패킹을 임시 사본에서 확인했다. 24k→16k 스트림 변환·기성 모델 어댑터·호출 이벤트와 기존 질문/STT/GPT/TTS Mock 연결을 구현했다. 다음은 모델 자산/배치·무결성·동적 메모리와 운영 bootstrap 및 복구 계획 준비다. [현재 결과와 다음 순서](K151_BUILTIN_WAKE.ko.md), [검증 증거](validation/2026-11-20-k151-builtin-wakenet-preflight.md)를 따른다. 실물 인식/자원/독립 대화는 미검증이다. 아래는 이전 진단 이력이다.

현장18개 등록/보정 녹음은 모두 품질 검사를 통과했으나 마지막 품질 출력 뒤 helper가 일반 오류로 거부했다. 품질 출력이 특징 추출보다 앞서므로, 마지막 특징 추출과 이후 보정 중 어느 연산이 실패했는지는 미확정이다. 새 진단은 보정 분리 불가·SWK1 문턱 표현 범위·실행/형식 오류를 구분하고, 보정의 최악 호출/가장 가까운 비호출 번호와 거리만 표시한다. 기존 인식/등록 기준은 유지한다. [진단 검증과 한계](validation/2026-11-20-josu-calibration-diagnostics.md)를 참고하며, 이전 세션의 특징은 보존되지 않아 그 원인은 미확정이다. 새 helper로 원인을 확인하기 전 반복 등록이나 문턱 변경을 하지 않는다.

추가 현장 결과에서 무발화의 약한 끝 활동 때문에 등록이 거부될 수 있음을 확인했다.
주활동 대비 낮은 에너지가 분리된 끝으로 구간을 확장하지 않도록 하고, 무발화 잡음은
경고를 남기면서 실제 오탐 평가에 포함한다. 기본3초 및 녹음 종료 표시를 사용한다.
[수정 검증과 실제 재시험 범위](validation/2026-11-20-josu-background-activity.md)를 참고한다.


기본 호출어는 **“조수”**이며 “조수야”는 신규 프로필의 비호출어다. 실제 노트북 발화에서
`UNVERIFIED_NO_MATCH`가 보고돼 입력 품질·VAD/추출 경계·DTW 거리 진단과 개인 등록/새 평가
경로를 준비했다. [상세 실행 순서](../firmware/standalone/docs/2026-11-20-josu-human-mic.md)와
[검증 범위](validation/2026-11-20-josu-human-mic-diagnostics.md)를 따른다. 현재 할 일은 노트북의
새 진단 JSON 및 독립된 실제 목소리 평가다. 실제 사람/K151 인식 성공은 미검증이며
기기 설치·OTA/NVS·모터·유료 API 실행은 이번 범위 밖이다. 아래는 이전 경로의 이력이다.


최신 지시(2026-11-18): 사용자는 **제조사 문의를 취소하고 직접 연결을 개발**하라고 했다.
[문의 초안](M5STACK_OBSERVATION_API_REQUEST.ko.md)은 미게시 상태로 철회했다.
이후 사용자는 공식 앱은 필수가 아니고 원하는 기능의 정상 작동이 우선이라고 확인했다.
최종 목표는 로봇 자체의 GPT API 연결·독립 기능이며, 기존 USB 규약은 개발·진단에
재사용한다. [개발 전 확인](validation/2026-11-18-direct-observer-development.md)과
[읽기 전용 파티션 진단 시제품](../experiments/k151_layout_spike/README.ko.md)을 준비했다.
사용자가 원본 SHA·표 MD5와 실제 앱 슬롯2개를 확인했다.
[실제 배치 기록](validation/2026-11-18-k151-backup-layout.json)과
[독립 GPT 음성 펌웨어 검토용 설계](superpowers/specs/2026-11-18-standalone-gpt-design.md)를 참고한다.
이후 사용자는 터치 시작 대신 이름/손가락 제스처를 요청했고 호출어 **“조수야”**를 선택했다.
사용자는 최초 로컬 음성 등록도 가능하다고 확인했다. 기기 내 특징/템플릿 감지·질문 자동
종료·개인화 등록·실측 기준을 설계에 반영하고 재검토했다. 수정 설계의 구현 승인은 대기 중이다.
기존 터치 시작 제안으로 구현하지 않는다. 제스처는 현재 첫 구현 필수 조건이 아니다.
활성/빈 슬롯과 안전한 설치 대상은 아직 미확인이다. 실제 설치는 별도로 결정한다.
제조사 키 추출이나 공식 인증 재현으로 해결하지 않는다.

## 기존 PC/출고 펌웨어 경로의 구현·현장 기록

PC MCP 자동 재연결과 Windows 간편 실행을 구현했고,2026-11-18(한국 시간)에
사용자가 진단 연결의 단절 후 자동 복구와 이후 GPT 모드의 ANSWERED·로봇 답변을
확인했다. [현장 PASS 기록](validation/2026-11-18-mcp-reconnect-live.md)을 참고한다.
[실행·종료·질문 재전송 제한](MCP_RECONNECT.ko.md)을 참고한다. 물리 장치 접근이나
펌웨어 교체 없이 출고 상태의 GPT 대화 연결에 사용하는 선택 기능이다.

사용자는 이후 자율 기능 진행을 요청했고, **공식 펌웨어 기반 PC 연결 확장안 준비**를
선택했다. 다음 첫 단계는 [USB 관찰 전용 연결](FACTORY_OBSERVER_NEXT.ko.md)이다.
승인한 설계의 코드·오프라인 검증을 준비했으며, 다음은 [설치 전 확인](USB_OBSERVER.ko.md)의
백업·복구·보드/USB·공식 인증 호환성 확인이다. 실제 설치·모터 동작 승인은 포함하지 않는다.
공식 저장소 기여자는 공개 빌드에 제품 인증 구현/설정 경로가 없다고 확인했다.
따라서 공식 앱을 유지하는 설치는 현재 HOLD다. [검토 근거](validation/2026-11-17-k151-recovery-compatibility.md)와
[집에서 시작할 원본 백업·복구 준비 순서](K151_BACKUP_RECOVERY.ko.md)를 참고한다.
2026-11-18에는 Windows COM3의 USB 식별과 실제 ESP32-S3·보호 상태·16MB 조회까지
확인했고, 원본 A/B 각16MB·동일 SHA256도 확인해 백업 파일 일치를 통과했다.
이후 정상 부팅·기존 앱/GPT 복귀와 공식 앱 Monitoring Camera의 영상 표시도
사용자가 확인했다. 별도 사본과 이후 상태는 [실물 USB 진행 기록](validation/2026-11-18-k151-usb-preflight.md)을 따른다.
공식 앱의 카메라 표시 확인을 PC 사진 수신·GPT 이미지 입력 성공으로 확대하지 않는다.

사용자는 다음 우선 작업으로 **GPT API가 답변을 만들고 로봇이 말하는 연결**을 지시했다.
현재 구현한 [GPT 음성 답변 경로](GPT_ROBOT.ko.md)는 검증된 공식 MCP를 확장하며,
출고 펌웨어/앱을 유지한다. **2026-11-17에 사용자가 로컬 설정 후 GPT ANSWERED 표시와
정상 로봇 음성 응답을 확인해 이 연결 단계를 통과했다.**
[GPT 현장 PASS 기록](validation/2026-11-17-gpt-robot-reply-live.md)을 참고한다.
공식 서비스는 음성 인식·도구 선택·재생을 계속 맡는다. 독립 음성 backend와 직접 실물
자율제어는 아래 어댑터/STOP 과제와 구분한다. 추가 연결 대기 시험으로 이 작업을 미루지 않는다.

제품 도착 후 사용자 작업 순서는 [상세 작업설명서](DEVICE_ARRIVAL_RUNBOOK.ko.md)의 D00–D10을
따른다. 아래 개발 과제는 D03–D04의 호환성/물리 어댑터 체크포인트에서 실행한다.

2026-11-16: K151 V1.6.2의 제조사 서비스·PC Ping·공식 앱 Local Network를 확인했다.
사용자는 출고 펌웨어/공식 앱을 유지하고 **공식 AI가 PC 기능을 호출하는 MCP 확장**을
먼저 선택했다. [현장 기록](validation/2026-11-16-k151-factory-bringup.md)과
[PC 연결 진단기 설계](superpowers/specs/2026-11-16-official-mcp-pc-bridge-design.md)을 참고한다.
이 확장은 아래 PC 엔진의 실물 제어 어댑터와 별도다.
[PC 연결 확인 실행 순서](OFFICIAL_MCP_PC.ko.md)에 따라 목록 등록·실제 호출·음성 코드 일치를
각각 확인한다. **2026-11-17에는 사용자가 실제 PC 호출과 로봇 음성 코드 일치를 확인해
이 연결 단계를 통과했다.** [현장 PASS 기록](validation/2026-11-17-official-mcp-pc-live.md) 참고.
후속 PC 기능으로 보관된 실시간24시간 시험의 읽기 전용 요약 조회를 추가했다.
[음성 조회 순서](OFFICIAL_MCP_PC.ko.md#4-완료한-24시간-시험-결과를-음성으로-조회)에 따라
새 호출 표시·음성 수치·PC Fake/Mock 범위를 확인한다. **2026-11-17에 사용자가 실제 호출
표시와 음성의 PASS·약24시간·83,157회·재시작/복원332회를 확인했다.**
[요약 조회 현장 PASS](validation/2026-11-17-official-mcp-soak-summary-live.md) 참고.
아래 직접 실물 제어 과제와는 별도다.

## Phase 4 — 계약 검증 후 실제 MCP Adapter

현재 구현: MCPRobotAdapter.connect/discover/status/touch_state, 공개 Tool 스키마와
장치 tools 교집합, 절대 pose 파싱, 세션·장치 고정, 시간초과/취소 fault latch.
`--mode mcp-sim`에서 factory 소유의 메모리 내 gateway를 통한 전체 engine을 실행한다.
사진/서보/표정/blink/LED/가상 listen·say 계약을 테스트했지만, 실물의 capture/execute 및
음성은 여전히 차단돼 있다. HTTP/auth는 로컬 loopback fixture로 검증했고,
실제 gateway/auth/ESP32 연동은 미검증이다.

구현할 계약:

- get_head_angles 파서는 구현했다. 실제 기기의 단위·중립·보정 및 UART 피드백을 확인한다.
- take_photo(question 필수) → inline JPEG만 취급; gateway 임시 보관/정리 정책을
  해결한 경우에만 허용. 이미지가 없으면 비활성 capability, remote path fallback 금지.
- move_head의 정수 타깃/speed=low, 양자화 전후 범위/slew, servo_init_ok ACK,
  전후 device/session 확인을 시뮬레이션으로 구현했다. 실물 이동 완료/피드백과는 구분한다.
- set_avatar(face), set_blink(enabled), set_all_leds(r,g,b), get_touch_state →
  실제 JSON error/available 및 isError 처리, 지원 도구가 없으면 비활성화.
- 서버 schema 변경·누락 required·세션/장치 교체·잘못된 pose/사진·취소/timeout은
  메모리 내 통합 테스트와 로컬 TCP 기반 [HTTP 인증·단절·수동 재연결](TRANSPORT_TEST_REPORT.md)을
  검증했다. 실제 gateway의 토큰 발급/갱신·TLS·장치 세션 검증은 남아 있다.
  같은 DB/resource를 쓰는 이 앱의 프로세스 간 lease는 구현했다.
  다른 앱·다른 PC·장치 자체 동작을 통제하는 gateway fencing은 별도로 구현해야 한다.

완료 기준: 별도 실물 승인, 복구 준비, 승인한 작은 각도/표정/터치/LED,
STOP·분리·재연결 테스트 기록. 기본 물리 실행 비활성화 유지.

## Phase 5 — 음성 / Memory / 고급 동작

1. `VoiceInput.listen(language="ko", duration_ms=...) -> Event(VOICE_REQUEST)`:
   RecordedVoiceInput/GatewayVoiceInput 및 FakeMic/fixture ASR을 구현했다.
   OpenAI STT의 ko/WAV/예산/동의 처리는 SDK MockTransport로 검증했다.
   실제 gateway STT 엔진·마이크·계정 모델은 기기 도착 후 확인한다.
2. `PlaybackAdapter.play_pcm(pcm, sample_rate, channels)`:
   PCM/WAV·anti-alias 16kHz mono 변환·시스템 libopus 60ms packet 왕복을 구현했다.
   TTS의 공식 24kHz PCM 형식은 문서/SDK MockTransport로 확인했다. /pcm payload는
   구성하지만 실제 token/HTTP 전송·재생은 아직 차단했다.
   say의 기본 voicevox를 OpenAI TTS로 오인하지 않는다.
   migratorywhale의 24kHz HTTP 계약은 별도 adapter가 필요하다.
3. 상시 녹음/wake word는 별도 선택 기능. 기본적으로 만들지 않는다.
4. 선택적 [영속 메모리](MEMORY.md)에 event/intent/result, 발화/인사 시각, 자동 발화 설정,
   마지막 관찰 상태와 마이그레이션/보관기한을 구현했다. 상태는 모터 복원에 쓰지 않는다.
   stackchan-memory show/set/clear와 재시작·설정 반영·저장 장애를 검증했다. 지속 API 예산과
   누적 사용량 메타데이터는 공용 SQLite로 구현하고 재시작·프로세스 경쟁을 테스트했다.
   원시 대화·이미지·오디오·생체 신원 데이터는 기본 저장 대상에서 제외한다.
5. 얼굴 추적은 비식별 bounding box → 작은 head delta로 분리한다. 실제 탐지 정확도,
   추적 lease 및 정지 테스트가 필요하다. 사진의 사람이 누구인지 판단하지 않는다.
6. 웹 대시보드는 로컬 인증·privacy 상태·STOP·실물 승인 상태만 제공하는 별도 작업이다.
   아직 UI/서버를 만들거나 외부 포트를 공개하지 않았다.
7. [안정성 도구](SOAK.md)로 가상24시간과 실시간10분을 검증했고, 2026-11-15 접수한
   Windows PC Fake/Mock 보고서는 실제86400.047초/83157회, 재시작·복원332회를 통과했다.
   다음에는 실물24시간 이상 운용, API 계정/비용 확인, 실물 환경의 메모리·태스크·재시작 복원,
   event flood 우선순위, 다른 앱의 모터 충돌을 실제 환경에서 검증한다.

## 외부 검증 선행 조건

- 게시 후 공식 제품/구조화 출력 문서 접근을 확인했다. 이미지/오디오 API와 가격,
  실제 계정 모델 지원은 해당 기능을 연결하기 전에 추가 확인한다.
- Windows/Linux × Python 3.11/3.12 CI를 추가했다. 실제 Actions 결과는 [CI 기록](CI.md)에
  구분하며, Windows의 fork와 시스템 libopus 미지원 SKIP은 실행 성공으로 세지 않는다.
- 계정 모델이 Responses/strict schema/이미지/한국어를 지원하는지 현재 문서·실제 계정으로 확인.
- 실제 API 호출은 opt-in이며 키를 채팅이나 Git에 넣지 않는다.
- 게이트웨이 사진 보관/전사 로그 문제 해결 및 펌웨어 변경·모터 구동 별도 승인.
