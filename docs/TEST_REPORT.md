# Test Report

최신 저장/제어권 회귀 실행일: 2026-11-13 / Python 3.12 / Linux 클라우드 환경.
최신 로컬 전체 pytest: **287 PASS, 0 FAIL, 0 SKIP**, 47.88초.
저장 지연·제어권·취소·종료 회귀 15개를 추가했다. 기본10초 제어권에서 단일12초 저장 지연
중 실제 갱신3회와 동작 성공을 확인했고, 전체2분 실행·독립 wheel 설치도 통과했다.
[Windows 실제 시험 실패와 새 진단 항목](SOAK.md)은
기존 실시간10분/가상24시간 PASS와 구분한다. Windows 집 노트북 보고서는 9시간46분에
`engine_failure`로 종료됐다. 두 번째 보고서는9시간24분에 제어권 상실이 확인됐고,
최대 순환11.796초를 기록했다. 동기 파일 저장이 갱신을 막는 경로를 재현·수정했으며
정확한 Windows 지연 원인과 실시간24시간 성공은 아직 미검증이다.
아래 2026-11-06 수치는 이전 단계 이력이다.
후속 HTTP23개·안정성14개를 추가했다. [HTTP 검증](TRANSPORT_TEST_REPORT.md),
[실시간10분/가상24시간 결과](SOAK.md)를 참고한다.
선택적 영속 메모리에 36개 회귀 테스트를 추가했다. [메모리 계약](MEMORY.md) 참고.
CI 추가 후 독립 임시 venv에 wheel을 설치해 Mock/MCP/음성/Opus 실행도 통과했다.
메모리 CLI의 설치 entry point와 프로세스 재시작/발화 정책 smoke도 통과했다.
[CI 검증 범위와 원격 실행 결과](CI.md)를 참고한다.
오프라인 음성 단계에서 46개를 추가했다. native Opus 테스트도 실행했다.
[최신 음성 테스트 결과](VOICE_TEST_REPORT.md)를 참고한다. 아래 수치는 이전 단계 이력이다.
지속형 제어권/예산 작업에서 31개를 추가했다. 아래 117개 결과는 MCP 단계의 이력이다.
게시 후 새 환경에서 기존 60개 테스트가 통과했고, MCP 관련 57개를 추가했다.
최초 MVP의 60 PASS / 7.73초와 JUnit 10.16초 기록은 아래 이력에 해당한다.
현재 범위의 최종 판정: **MOCK_MVP_PASS**.
실제 K151/OpenAI 계정/펌웨어 검증 결과를 뜻하지 않는다.
이전 음성/CI 커밋의 GitHub Actions는 Windows/Linux × Python3.11/3.12 네 조합 모두 PASS다.
Linux는 각각194 PASS, Windows는 각각192 PASS와 fork/libopus 2 SKIP이다.
영속 메모리 브랜치의 원격 결과는 [해당 Actions 실행](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions?query=branch%3Afeat%2Fpersistent-memory)에서 구분한다.
HTTP·안정성 후속 브랜치의 원격 결과는 [별도 Actions 실행](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions?query=branch%3Afeat%2Ftransport-soak)에서 구분한다.

## 최초 MVP 검증 명령과 결과 (이력)

프로젝트 루트 `/workspace/stackchan-autonomy`:

| 실행 명령 | 결과 |
|---|---|
| `.venv/bin/python -m pytest -q --junitxml=.local-test-results.xml` | PASS: 60개, 실패/skip 0; 결과를 .local/pytest.xml로 이동 |
| `.venv/bin/ruff check .` | PASS: All checks passed |
| `.venv/bin/ruff format --check src tests` | PASS: 19개 파일 |
| `UV_CACHE_DIR=/workspace/.cache/uv uv build --offline` | PASS: sdist 및 py3-none-any wheel 생성 |
| `UV_CACHE_DIR=/workspace/.cache/uv uv run --frozen --no-sync stackchan-autonomy --cycles 3 --person` | PASS: mock/fake, cycles=3, IDLE, simulated_actions=1, cloud_requests=0 |
| `.venv/bin/python -m compileall -q src` | PASS |
| wheel을 uv pip install --offline --no-deps --reinstall로 설치 | PASS; 의존성은 기존 검증 venv 사용 |
| wheel CLI를 /tmp에서 실행 | PASS: 1회 touch, simulated_actions=1, cloud_requests=0 |
| `bash .local/install.sh`, 이어서 `uv sync --frozen` 재실행 | PASS: editable 설치 복원 및 반복성 검증 |
| `uv run --frozen pytest -q` | 당시 PASS: 60개 / 7.73초 |

## Phase 4 후속 검증 — 게시된 환경에서 계속 진행

새 환경의 소스/캐시/의존성 복원과 기존 60개 테스트를 **60 PASS / 3.60초**로 확인했다.
이전 코드/환경 설정을 다시 적용하지 않았다. 이번 변경에서도 환경 초안 수정·게시,
Git push, 실물·유료 API 호출은 하지 않았다.

| 실행 / 대상 | 최신 결과 |
|---|---|
| `uv sync --frozen` | PASS: 기존 고정 의존성 유지 |
| `uv run --frozen pytest -q --junitxml=.local/phase4-pytest.xml` | **117 PASS / 8.14초**, 오류·실패·skip 0 |
| `ruff check .`, `ruff format --check src tests` | PASS, Python 파일 23개 포맷 검사 |
| `uv run --frozen stackchan-autonomy --mode mcp-sim --cycles 3 --event touch` | PASS: mcp-sim/mcp-simulated, IDLE, actions=1, cloud_requests=0 |
| 기존 `--mode mock --cycles 3 --person` | PASS: 기존 동작 유지, actions=1, cloud_requests=0 |
| `uv build --offline` | PASS: sdist/wheel, schema JSON·MIT 고지 포함 확인 |
| 새 wheel 설치 후 /tmp에서 `--mode mcp-sim --cycles 1 --event touch` | PASS: IDLE, actions=1, cloud_requests=0; 이어서 editable 설치 복원 |

추가 테스트는 다음을 검증한다.

- 실제 MCP SDK의 메모리 내 server/client를 거치는 전체 자율행동 engine.
- 도구 스키마 및 device tools 교집합, 작업별 재검사, required/type/range/미지원 제약 차단.
- 기본각 추정 없이 유한한 절대 pose 파싱, null/bool/string/범위 밖/JSON 오류 거부.
- 정수 각도 양자화 전후 slew/범위 제한, speed=low, 도달한 타깃 재전송 방지.
- motor ACK 전체 구조 및 필요한 축의 motion_started 확인. **이동 완료 증거가 아님**.
- JPEG inline만 수용, 원격 path fallback 없음, 비정상 base64/비JPEG/isError/JSON 오류 차단.
- 표정·blink·LED·touch의 실제 입력 이름과 결과, unavailable 센서에서 유령 이벤트 없음.
- 녹음하지 않는 가상 한국어 전사/listen 및 가상 발화/say; 실제 STT/TTS가 아님.
- 세션/장치 교체, 잘못된 SDK 응답, timeout/취소 후 fault latch와 후속 명령 차단.
- 시뮬레이터의 상속된 connect 경로를 이용해 원격 physical=False adapter를 만드는 우회 방지.
- 동일 adapter 내부 직렬 실행, 취소 후 메모리 내 세션 태스크 정리.

독립 리뷰에서 원격 연결 상속/SDK ValidationError 예외/부족한 ACK/미지원 schema 제약
문제를 재현했고, 9개 회귀 실패를 확인한 뒤 수정했다. 추가 malformed marker 4개와
도달 타깃 재전송 1개도 RED→GREEN으로 검증했다. 리뷰 후 두 번째 리뷰는 실행하지 않았다.

**중요한 취소 한계:** client timeout/취소는 이미 보낸 요청을 원격에서 되돌리거나 중지했다는
증거가 아니다. 제어된 테스트에서 client timeout 후 서버가 늦게 적용하는 경우도 재현했다.
adapter는 그 상태를 fault로 잠그고 추가 요청/재전송을 차단한다. 이전 테스트의
'server request cancellation'이라는 이름은 이 보장을 과장하므로 수정했다.
물리적 비상정지·다른 클라이언트의 동작 차단·장치 자체 애니메이션 제어는 별도 검증 대상이다.

SDK HTTP 테스트는 진짜 OpenAI SDK 3.46.0과 **로컬 MockTransport**를 사용했다.
MCP discovery는 SDK 1.30.0의 **메모리 내 서버/클라이언트 세션**을 사용했다.
로봇 네트워크·실물·유료 API 호출은 없었다.

제한된 shell sandbox에서는 SDK의 플랫폼 정보 조회가 정지하는 현상을 재현했다.
같은 테스트를 승인된 환경 명령으로 실행하면 통과했다. 테스트 통과를 위해 SDK/TLS
검증을 제거하지 않았다. SDK 어댑터 자체에는 총 wall timeout도 추가·검증했다.

## 요구 시나리오 T1–T10

| 시나리오 | 결과 | 검증 범위 / 테스트 |
|---|---|---|
| T1 기본 가상 동작 | PASS | test_t1_complete_loop_and_t2_simulated_person_event; 실제 engine/queues/action/FakeRobot |
| T2 사람 감지 이벤트 | PASS (시뮬레이션) | 가상 PNG와 명시 person label → PERSON_DETECTED → 한국어 인사; **실제 CV 탐지 미구현** |
| T3 반복 인사 방지 | PASS | test_t3_repeated_person_greeting_is_suppressed_until_cooldown; 명시 voice 요청 예외도 별도 검증 |
| T4 잘못된 AI 응답 | PASS | 닫힌 스키마, NaN/Inf/bool/미지원 intent/과도한 각도/복합 행동 거부 |
| T5 API 장애 | PASS (Mock HTTP) | 실제 SDK transport에서 429/500/timeout/거부/중단/invalid JSON/null; idle 및 retry 없음 |
| T6 장치 연결 장애 | PASS (Fake) | ACK 유실을 시뮬레이션하고 fault latch/중복·재전송 없음; 실제 TCP/WS 단절 미검증 |
| T7 사용자 중지 | PASS | AI 취소, 실행 중 명령 취소, 큐 drain, 새 명령 차단; 물리적 비상정지 미검증 |
| T8 키 없음 | PASS | API 키를 제거한 CLI subprocess와 Mock provider/FakeRobot 동작 |
| T9 개인정보 보호 | PASS (현재 앱) | 키 repr/직렬화 제외, raw media/전사 로그 없음, SQLite metadata only; 상류 gateway 정책은 미해결 |
| T10 연속 운영 | PASS (유한 soak) | warmup 100 + 추가 1000회, bounded histories/태스크 수/할당 증가 <1MB; 24시간 leak-free 보장은 아님 |

## 지속형 제어권·API 예산 후속 검증

| 실행 / 대상 | 결과 |
|---|---|
| `.venv/bin/python -m pytest -q --junitxml=.local/coordination-pytest.xml` | **148 PASS / 13.70초**, 오류·실패·skip 0 |
| `ruff check .`, `ruff format --check src tests` | PASS, Python 파일 29개 |
| 독립 리뷰의 대상 테스트 | 당시 53 PASS / 5.16초; 이후 fork 회귀 테스트 추가·수정 |
| 기존 Mock / MCP 시뮬레이터 CLI 각 3회 | PASS: IDLE, 가상 행동 1회, cloud_requests=0 |
| offline sdist/wheel build 및 wheel 실행 | PASS: 새 3개 모듈 포함; /tmp에서 mcp-sim 1회 실행, 0 cloud requests; editable 복원 |

추가 검증 범위:

- 실제 프로세스 6개가 같은 resource에 경쟁할 때 lease 소유자 **1개**.
- 실제 프로세스 6개가 공유 예산 2회에 경쟁할 때 성공 예약 **2개**.
- 재구성/재시작 후 분·시간·일 rolling 한도와 누적 요청/token/오류 수 유지.
- 예약 후 os._exit로 종료돼도 예약이 남음. HTTP 전에 예약하고 불확실한 호출은 환급하지 않음.
- 강제 종료된 소유자는 TTL까지 점유하며, 만료 후 높은 generation으로 인계.
- 이전 handle이 새 소유자를 갱신하거나 반환하지 못함.
- heartbeat 갱신, 만료/소실 시 활성 로컬 명령 취소·후속 명령 차단·대기 엔진 ERROR 종료.
- close 뒤 heartbeat 태스크 정리와 제어권 반환, 큐/기억/태스크 수의 유한 반복 안정성.
- SQLite 잠금/파일 손상/잘못된 저장 시각에서 새 제어·HTTP 차단. 원시 파일 임의 삭제 없음.
- 시계 rollback이 예산을 초기화하거나 살아 있는 owner를 해제하지 못함.
- 실제 SDK MockTransport에서 provider를 새로 생성해도 예산을 다시 쓸 수 없음.
- mock/mcp-sim CLI에서 제어권 경합·DB 오류는 code 2와 고정 메시지, traceback 없음.
- **실제 Linux fork**에서 부모가 먼저 만든 lease를 자식이 상속해도 부모의
  acquire/check/renew/release 권한을 얻지 못하며 부모의 점유가 유지됨.

독립 리뷰는 fork 시 UUID 상속 결함을 재현했다. 회귀 테스트가 실패하는 것을 확인한 뒤
owner를 PID에 바인딩했고, 해당 테스트와 최종 전체 suite가 통과했다. 리뷰 이후의 수정은
회귀/전체 테스트로 검증했으며 재리뷰를 실행했다고 주장하지 않는다.

lease는 같은 로컬 DB/resource를 쓰는 참여 프로세스에 한정된다. 다른 앱/PC,
gateway fencing, 이미 보낸 명령의 취소, 물리적 정지는 보장하지 않는다.
예산도 같은 DB/namespace/한도를 공유하는 이 앱의 예약 한도이며 실제 청구액은 아니다.
시계 점프의 가용성 영향, DB 삭제/설정 분리, 응답 유실 후 알 수 없는 token 수는
[COORDINATION.md](COORDINATION.md)에 명시했다. 이 단계 당시 미검증이던 Windows/Python3.11은
후속 [CI](CI.md)에서 검증했다. Windows fork는 지원하지 않아 별도 SKIP이다.

## 독립 리뷰와 회귀 검증

리뷰 에이전트가 코드와 테스트를 읽고 다음 문제를 오프라인에서 재현했다.
이를 별도 테스트에서 실패하는 것을 확인한 뒤 수정했다.

- cycle timeout/호출자 취소 후 백그라운드 동작 잔류 → active worker 취소·대기, fault latch.
- 어댑터 ValueError로 worker가 죽고 future가 미해결 → owner 경계에서 해결, 후속 요청 fault.
- 사람 감지가 VOICE_REQUEST와 원문을 덮어씀 → 우선순위 높은 사용자 이벤트 유지.
- 최초 분석 실패 후 같은 장면을 영구 생략 → 분석 성공 여부 추적, 다음 정기 관찰에서 재시도.
- 동일 발화를 cooldown 이후에도 영구 차단 → 발화 dedupe 기간 제한, 명시 요청 예외;
  모터 중복 재실행 차단은 유지.
- 추가 자체 점검: 정지된 HTTP transport에서도 provider 자체 wall timeout으로 idle 복귀,
  이미지 opt-in일 때만 base64 이미지 포함.

초기 RED 단계의 모듈 부재 collection error, 회귀 6개 FAIL 및 timeout FAIL은
개발 중 확인한 실패다. **최종 전체 실행에서 모두 해소**됐다. 독립 리뷰 이후의
수정은 회귀 테스트와 전체 suite로 검증했으며 두 번째 리뷰를 실행한 것은 아니다.

## BLOCKED / 미검증

| 항목 | 상태 / 이유 |
|---|---|
| 실제 OpenAI 모델·계정 권한·이미지·한국어·과금 | BLOCKED: 키/모델 미제공, 실제 호출 미실행; 공식 구조화 출력 문서는 후속 HTTP 200 확인 |
| 공식 M5Stack 문서·M5Burner 복구 절차 | 문서 조회 PASS(후속 HTTP 200); 이미지 체크섬·실제 플래시/복구는 미검증 |
| 실제 MCP HTTP/auth/ESP32 세션/장치 도구 | BLOCKED: 장치/gateway 없음; 메모리 내 SDK 경로만 PASS |
| 실물 서보/센서/사진/음성/긴급 정지 | BLOCKED: 장치 없음 및 물리 테스트 승인 없음 |
| Windows 및 Python 3.11 실행 | 후속 CI PASS: 네 조합 설치/테스트/빌드/wheel; Windows fork/libopus는 SKIP |
| Phase 5 | 오프라인 음성/API 어댑터·변환은 Mock 검증; 실제 음성/face tracking/dashboard/24h 운영은 미검증 |
| 게시된 이전 snapshot 복원 | PASS: 새 환경에서 파일·의존성과 기존 60개 테스트 확인; 이번 후속 변경은 미게시 |
