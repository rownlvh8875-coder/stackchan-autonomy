# StackChan Autonomy

K151용 독립 자율행동 엔진의 **Phase 0–3 Mock MVP**.
Observe → Perceive → Decide → Validate → Act → Evaluate 순환을 가상 로봇에서 실행한다.
실제 카메라 인식·마이크·스피커·서보·펌웨어·실제 OpenAI 계정 연결은 검증하지 않았다.
Phase 4는 MCP 계약·상태/각도/터치 파서와 메모리 내 gateway 통합 시뮬레이션을 제공한다.
물리 실행은 계속 차단돼 있다.

## Windows 설치와 첫 실행

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요하다.
소스와 uv.lock이 있는 프로젝트 루트에서 PowerShell로 실행한다.

```powershell
cd stackchan-autonomy
uv sync --frozen
# 기존 .env가 없다면 복사. 실제 키는 이 파일이나 안전한 환경변수에서만 설정한다.
Copy-Item .env.example .env
uv run --frozen stackchan-autonomy --cycles 3 --person
uv run --frozen pytest -q
uv run --frozen ruff check .
```

기본 Mock은 API 키·장치·gateway·오디오 라이브러리가 필요 없다.
--person은 사람 존재를 **가상 라벨로 주입**한다. 실제 이미지의 사람을 탐지하는 옵션이 아니다.
출력은 mode/robot/cycles/state/simulated_actions/cloud_requests의 JSON 요약이다.
기본 로그에는 비밀키·사진·음성·발화문·모델 이유를 기록하지 않는다.

```powershell
# 즉시 3회 데모: 30초를 기다리지 않으며 중복 관찰을 생략한다.
uv run --frozen python -m stackchan_autonomy --cycles 3
# 외부 장치/포트 없이 실제 MCP SDK 세션을 거치는 통합 시뮬레이션
uv run --frozen stackchan-autonomy --mode mcp-sim --cycles 3 --event touch
# 한국어 전사 fixture와 tone TTS를 쓰는 오프라인 음성 순환
uv run --frozen stackchan-autonomy --mode voice-sim --cycles 1 --event touch
# 신뢰하는 시스템 libopus가 있을 때만 raw Opus 변환도 검증 (스피커 재생 없음)
uv run --frozen stackchan-autonomy --mode voice-sim --cycles 1 --event touch --opus
# touch / 텍스트 음성요청 시뮬레이션 (녹음하지 않음)
uv run --frozen stackchan-autonomy --cycles 1 --event touch
uv run --frozen stackchan-autonomy --cycles 1 --event voice --text "안녕"
# 실제 30초 관찰 scheduler. Ctrl+C로 소프트웨어 중지.
uv run --frozen stackchan-autonomy --forever
```

Linux에서도 같은 uv 명령을 사용한다. 현재 클라우드 환경에서는 Python 3.12.14로
검증했다. Windows/Linux × Python 3.11/3.12의 [GitHub Actions CI](docs/CI.md)도
네 조합 모두 통과했다. Windows는 192개 통과, fork/libopus 미지원 2개 건너뜀이다.
클라우드 sandbox에서 SDK 플랫폼 정보 조회가 정지하면 테스트 환경의 실행 권한을
확인한다. 제품 코드의 TLS/체크섬을 끄거나 Mock을 실제 API 요청으로 대체하지 않는다.

## 설정

`config/robot.yaml`과 `config/personality.yaml`을 읽는다. 다른 디렉터리에서 실행할 때는
--config / --personality에 경로를 지정한다. 파일이 없는 설치 환경에서는 안전한 내장 기본값을
사용한다. 환경변수 > .env > YAML > 기본값 순서다. YAML에는 키를 넣을 수 없다.

| 설정 | 기본값 / 의미 |
|---|---|
| STACKCHAN_OBSERVE_INTERVAL_S | 30초 |
| STACKCHAN_MAX_UNCHANGED_INTERVAL_S | 300초; 변화가 없어도 재분석 |
| STACKCHAN_SPEECH_COOLDOWN_S | 300초; 자동 인사·발화 억제 |
| STACKCHAN_COMMAND_INTERVAL_S | 1초; 초과 명령은 버림 |
| STACKCHAN_MAX_STEP_DEG | 15도 이하; 더 보수적인 값만 허용 |
| STACKCHAN_REQUESTS_PER_MINUTE/HOUR/DAY | 2 / 30 / 100, rolling window |
| STACKCHAN_STATE_PATH | .local/autonomy.sqlite3; 제어권·API 예산 공용 DB |
| STACKCHAN_CONTROL_RESOURCE | stackchan:default; 동일 로봇 제어권 ID |
| STACKCHAN_LEASE_TTL_S | 10초; TTL/3마다 갱신 |
| STACKCHAN_BUDGET_NAMESPACE | openai:default; 모델과 무관하게 공유하는 API 예산 |
| STACKCHAN_CLOUD_ENABLED | false, --mode cloud도 별도 필요 |
| STACKCHAN_IMAGE_TRANSMISSION | false; 명시 설정 후 이미지 전송 |
| STACKCHAN_AUDIO_TRANSMISSION | false; OpenAI STT/TTS 어댑터의 별도 동의 |
| STACKCHAN_STT_MODEL / STACKCHAN_TTS_MODEL | 미설정; 계정에서 확인한 모델을 명시 |
| STACKCHAN_TTS_VOICE | 미설정; 사용자가 선택한 지원 voice ID |
| STACKCHAN_VOICE_CAPTURE_MS | 5000ms; 명시 요청 1회당 100..30000ms |
| STACKCHAN_DRY_RUN | true; 이 MVP는 항상 Fake에서 시뮬레이션 |
| STACKCHAN_HARDWARE_ENABLED | false; true로 바꿔도 이 버전은 물리 실행을 허용하지 않음 |
| STACKCHAN_MEMORY_PATH | 미설정; 선택적 metadata/설정 SQLite, [관리 방법](docs/MEMORY.md) |
| STACKCHAN_MEMORY_RETENTION_S | 604800초(7일); 이력·발화/관찰 시각 보관, 60..31536000 |

기본 모터 envelope는 **감사한 커스텀 gateway**의 yaw −90..90 / pitch 5..85이다.
공식 펌웨어의 영점/좌표와 동일하다고 가정하지 않는다.
복합 행동은 현재 거부하며 idle/look/emote/speak만 허용한다.
STOP은 진행 중 작업을 취소하고 새 명령을 차단한다. 통신 장애·명령 실행 중 timeout은
자동 retry 없이 fault로 잠근다. 재개는 원인을 확인한 뒤 새로운 engine으로 수동 수행한다.
사진은 기본적으로 저장하지 않으며, SQLite에는 이벤트·행동 종류·결과·시각만 기록한다.
선택적 메모리를 켜면 자동 발화 설정과 마지막 관찰 상태도 저장한다.
`uv run --frozen stackchan-memory show/set/clear`로 관리하며 로봇 위치를 복원하지 않는다.

## OpenAI Responses API 연결 (실계정 미검증)

현재 모델 이름·권한·한국어·strict schema·이미지 지원은 공식 API 문서와 해당 계정에서
확인해야 한다. 모델 ID를 프로젝트에서 정하지 않는다. API key를 채팅에 붙이지 않는다.
유료 API는 호출하지 않았다. 게시 후 환경에서는 공식 제품/구조화 출력 문서의
접근을 확인했지만, 계정 모델 권한과 실제 API 응답은 여전히 미검증이다.

```powershell
# 실제 값을 .env 또는 안전한 환경변수에 설정한다.
$env:STACKCHAN_OPENAI_MODEL = "<계정에서 확인한 Responses 지원 모델 ID>"
$env:STACKCHAN_CLOUD_ENABLED = "true"
# OPENAI_API_KEY도 보안 환경변수/.env에 설정한다.
uv run --frozen stackchan-autonomy --mode cloud --cycles 1 --event voice --text "안녕"
```

이는 여전히 **FakeRobot**을 사용하지만 클라우드 요청은 실제 비용이 발생할 수 있다.
사진 입력은 `STACKCHAN_IMAGE_TRANSMISSION=true`를 추가로 설정해야 한다.
현재 Fake 사진은 합성 fixture라서 실제 환경 인식 검증에 사용할 수 없다.
OpenAI 어댑터는 store=false, strict JSON Schema, timeout, SDK retry 0으로 요청한다.
오류·거부·중단·잘못된 응답은 idle이며 잘못된 각도/복합 행동은 실행 단계에서 거부한다.
사용량은 provider.usage의 요청·실패·input/output tokens에 집계한다. 예산은
공용 SQLite에 기록돼 재시작해도 유지된다. provider.usage는 현재 프로세스 통계,
provider.budget.snapshot()은 공유 누적 통계다. token 수는 청구액이 아니며,
응답이 유실된 요청의 token 사용량은 알 수 없다.

## 제어권 lease와 영속 예산

음성 기능의 오프라인 실행과 입력/출력 형식은 [VOICE](docs/VOICE.md)를 참고한다.

CLI는 제어권을 확보한 뒤 시작한다. 다른 프로세스가 같은 로봇을 점유 중이면
종료 코드 2로 안내하며, 새 명령을 보내지 않는다. heartbeat 갱신 실패나 lease 만료는
새 명령 차단·로컬 작업 취소·엔진 ERROR 종료로 이어진다. 정상 종료는 태스크 정리 후
lease를 반환하고, 강제 종료 시 기본 10초 뒤 만료된다.

API 요청은 HTTP 전에 원자적으로 예산을 예약하며, 실패·강제 종료 때도 예약을 환급하지 않는다.
DB에는 식별자·시각·generation·집계 수치만 저장하고 키·사진·음성·대화는 저장하지 않는다.
잠금/손상 시 새 제어와 클라우드 호출을 차단한다.

다른 작업 디렉터리에서도 같은 제어권/예산을 쓰려면 **같은 절대 DB 경로와 resource,
namespace, 한도**를 설정해야 한다. [설정·복구·보장 범위](docs/COORDINATION.md)를 참고한다.
이 기능은 로컬 PC의 참여 프로그램끼리 적용되며, gateway fencing이나 물리적 비상정지는 아니다.

## 실제 장치 연결

`MCPRobotAdapter.connect(url, headers=...)`는 기존 Streamable HTTP daemon 연결 API다.
`discover()`, `status()`, `touch_state()`는 도구·상태·절대 각도·터치의 읽기 전용 점검이다.
실제 장치의 쓰기/촬영/녹음 경로는 아직 차단돼 있다.
기본 MCP 주소는 127.0.0.1:8767/mcp이며 추가 ESP32 gateway를 띄우지 않는다.
네트워크 인증과 실제 HTTP transport는 테스트하지 않았다. 읽기 전용 연결도
사용자가 지정한 gateway가 준비된 후에만 수행한다. 이번 작업은 해당 연결을 실행하지 않았다.

`--mode mcp-sim`은 factory가 자체 생성한 메모리 내 server/client만 사용한다.
원격 URL을 simulator로 지정하는 옵션이 없고 TCP 포트를 열지 않는다.
감사 SHA의 실제 도구 스키마와 펌웨어 응답 형태를 사용해 정수 각도·speed=low,
inline JPEG·표정·blink·LED·touch·가상 전사/발화를 검증한다. 이미지 경로는 읽거나
삭제하지 않는다. JPEG는 200KiB/4백만 픽셀 이하로 제한한다.
실제 CV·STT·TTS·장치의 이동 완료·기계적 안전을 검증하는 기능은 아니다.

매 작업마다 도구 목록을 재확인하고 device_id/session_id 변경, 잘못된 응답,
시간초과/취소를 fault로 잠근다. 모터 타깃은 반올림한 뒤에도 15도 slew를 재검사한다.
ACK의 초기화 플래그만으로 성공 처리하지 않으며, 필요한 축의 시작 상태를 함께 확인한다.
이는 이동 완료나 실제 위치 도달을 보장하지 않는다. 타임아웃 전에 보낸 요청은 서버에서
나중에 적용될 수 있다. 이 경우 새 요청과 재전송을 차단하고 수동 확인이 필요하다.
어댑터와 action owner의 직렬화는 **현재 프로세스 안에서만** 유효하다.
같은 DB/resource를 쓰는 이 앱 프로세스 사이의 lease는 구현했다.
다른 앱·기기의 자체 애니메이션을 제어하는 gateway 소유권은 아직 구현하지 않았다.

물리 연결은 [HARDWARE_BRINGUP](docs/HARDWARE_BRINGUP.md) 순서로 진행한다.
펌웨어 변경과 모터 테스트는 각각 명시적인 승인이 필요하다. gateway는 기본 사진을
디스크에 보관하고 일부 STT 엔진은 전사문을 로그에 남기므로 이를 해결하기 전에는
실제 capture/음성을 활성화하지 않는다. 소프트웨어 STOP은 물리적 비상정지가 아니다.

## 구조와 검증 문서

- [ARCHITECTURE](docs/ARCHITECTURE.md): 여섯 모듈, 상태 머신, 동시성·개인정보 경계
- [UPSTREAM_AUDIT](docs/UPSTREAM_AUDIT.md): 네 저장소 SHA, 실제 스키마/라이선스/문서 차이
- [TEST_REPORT](docs/TEST_REPORT.md): 실행한 검사 및 PASS/FAIL/BLOCKED
- [NEXT_STEPS](docs/NEXT_STEPS.md): Phase 4–5 인터페이스와 실제 검증 기준
- [WORK_LOG](docs/WORK_LOG.md): 단계별 파일·테스트·리뷰 수정 기록

작성한 Python 코드는 상류 펌웨어를 복사하거나 수정하지 않았다.
별도 gateway/펌웨어를 재배포할 때는 각 프로젝트와 내장 코드의
라이선스 경계를 확인해야 한다.
시뮬레이터의 공개 gateway schema/설명은 감사 SHA에서 추출했으며,
출처와 MIT 고지는 [THIRD_PARTY_NOTICES](src/stackchan_autonomy/data/THIRD_PARTY_NOTICES.md)에
기록하고 wheel에 함께 포함했다.
