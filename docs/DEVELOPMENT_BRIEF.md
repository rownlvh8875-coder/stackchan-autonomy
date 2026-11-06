# Codex 개발 지시서 — StackChan Autonomous AI

## 0. 프로젝트 개요

프로젝트명: StackChan Autonomous AI

목표는 M5Stack 공식 StackChan K151(ESP32-S3 기반)을 클라우드 AI와 연결하여 주변을 관찰하고, 상황을 판단하고, 적절한 행동을 스스로 선택하는 자율형 데스크톱 로봇을 만드는 것이다.

단순한 음성 챗봇이나 명령형 로봇이 아니라 다음의 자율행동 순환을 구현한다.

**Observe → Perceive → Decide → Validate → Act → Evaluate → Repeat**

개발 도구는 Codex, 주요 언어는 Python, AI 서비스는 OpenAI API를 사용한다.

운영 환경은 우선 Windows PC로 설정한다. 이후 Linux 서버나 Jetson 장치로 이전할 수 있도록 플랫폼 종속성을 최소화한다.

사용자에게 개발계획만 제출하고 종료하지 말고, 실제 코드 작성과 Mock 테스트까지 수행한다.

다만 사용자 승인 없이 물리 장치의 펌웨어를 변경하거나 실물 모터를 구동하지 않는다.

---

## 1. 반드시 조사할 기존 GitHub 저장소

다음 저장소를 최신 상태로 직접 확인한다.

### A. M5Stack 공식 소스

https://github.com/m5stack/StackChan

https://github.com/m5stack/StackChan-BSP

https://docs.m5stack.com/en/StackChan

조사 항목:
- 공식 K151 하드웨어 구성
- 기본 펌웨어와 커스텀 펌웨어의 차이
- 서보모터의 실제 동작 범위
- 카메라·마이크·스피커·터치센서 지원
- 펌웨어 복구 및 M5Burner 사용 절차
- 공식 MCP 기능이 있는 경우 지원 범위
- 기존 기능을 재사용할 수 있는 방법

### B. 핵심 기반 프로젝트

https://github.com/kisaragi-mochi/stackchan-mcp

최우선 분석 대상이다.

특히 다음 경로를 조사한다.

- `gateway/README.md`
- `gateway/pyproject.toml`
- `gateway/stackchan_mcp/`
- `gateway/stackchan_mcp/stdio_server.py`
- `gateway/stackchan_mcp/gateway.py`
- `gateway/stackchan_mcp/esp32_client.py`
- `firmware/main/boards/stackchan/`
- `docs/architecture.md`

기능별로 구현 여부와 실제 함수 또는 MCP Tool 스키마를 확인한다.

- `get_status`
- `take_photo`
- `move_head`
- `get_head_angles`
- `set_avatar`
- `set_blink`
- `set_all_leds`
- `get_touch_state`
- `listen`
- `say`

현재 브랜치의 구현과 문서가 다를 수 있으므로 README만 읽고 기능 지원을 확정하지 않는다.

MCP 게이트웨이는 장치를 연결하는 역할이고, 신규 자율행동 엔진은 별도 프로세스로 개발한다.

가능하면 기존 Streamable HTTP MCP daemon을 사용한다. 다중 클라이언트가 ESP32 장치 연결을 중복 점유하지 않도록 한다.

### C. 참고 프로젝트

https://github.com/migratorywhale/stackchan-mcp

특히 다음 기능을 검토한다.

- 얼굴 추적
- 음성 대화
- 표정 애니메이션
- 센서 이벤트
- MCP와 AI 에이전트 간 통신

단, 두 저장소의 펌웨어를 무검증으로 혼합하지 않는다. 필요한 기능의 설계와 구현 원리만 참고하고 호환성을 검증한다.

### 소스 조사 결과 기록 규칙

- 저장소 URL
- 확인한 브랜치 및 커밋 SHA
- 확인한 파일 경로
- 실제 코드 위치와 함수명
- 지원 여부
- 확인되지 않은 기능
- 라이선스 및 의존성 주의사항

위 항목을 `docs/UPSTREAM_AUDIT.md`에 기록한다.

확인되지 않은 기능을 지원된다고 추정해서 구현하지 않는다.

---

## 2. 전체 아키텍처

다음 구조를 기본으로 구현한다.

StackChan Hardware
↓
ESP32 Custom Firmware
↓
WebSocket / MCP
↓
Existing StackChan MCP Gateway
↓
New StackChan Autonomy Engine
↓
OpenAI Cloud API

자율행동 엔진은 다음 6개 모듈로 분리한다.

1. Perception: 이미지·음성·센서 이벤트 수집
2. AI Decision: 클라우드 AI 판단
3. Behavior: 행동 선택 및 우선순위
4. Memory: 최근 상황과 상호작용 기억
5. Action: 검증된 동작의 로봇 명령 변환
6. Safety: 안전 제한, 중지, 호출량 제한

각 모듈은 독립 테스트가 가능하도록 인터페이스를 분리한다.

AI 모델이 ESP32에 직접 펌웨어 명령을 보내는 구조는 금지한다.

---

## 3. 개발 기술 기준

- Python 3.11 이상
- `uv` 기반 의존성 관리
- `asyncio` 비동기 이벤트 루프
- Pydantic 기반 데이터 검증
- OpenAI 공식 Python SDK
- OpenAI Responses API
- MCP Python SDK
- SQLite 기반 선택적 기억 저장
- pytest 기반 자동화 테스트
- ruff 기반 코드 품질 검사

라이브러리 버전은 실제 호환성을 확인한 후 고정한다.

OpenAI 모델 ID는 코드에 하드코딩하지 않고 환경변수에서 설정한다.

모델의 이미지 입력, 구조화 출력, 한국어 지원 등 필요한 기능을 실제 API 문서와 계정 권한 기준으로 확인한다.

기존 Assistants API 기반으로 신규 개발하지 않는다.

---

## 4. Robot Adapter 개발

다음 두 가지 구현체를 만든다.

### FakeRobotAdapter

실제 로봇 없이 작동하는 테스트용 장치.

지원 기능:
- 가상 이미지 제공
- 가상 센서 이벤트 생성
- 가상 표정 변경
- 가상 고개 움직임
- 가상 음성 출력
- 실행 이력 기록

외부 API 키 없이 전체 자율행동 흐름을 검증할 수 있어야 한다.

### MCPRobotAdapter

기존 StackChan MCP Gateway에 연결하는 실제 장치용 구현체.

지원 기능:
- 연결 상태 확인
- 사진 촬영
- 표정 출력
- 서보모터 제어
- 터치 이벤트 확인
- LED 제어
- 음성 입출력 연동

실제 MCP 도구의 입력 스키마와 반환 형식에 맞춰 구현한다.

기능이 미구현되어 있거나 특정 펌웨어 버전에서만 사용 가능하면 Capability Check를 통해 해당 기능을 비활성화한다.

장치 연결 실패 시 프로그램이 무한 재시작하지 않도록 한다.

---

## 5. Autonomous Engine 개발

상태 머신을 구현한다.

BOOT
→ IDLE
→ OBSERVE
→ THINK
→ VALIDATE
→ ACT
→ COOLDOWN
→ IDLE

별도로 STOPPED, ERROR 상태를 둔다.

### 이벤트 유형

- TIMER_OBSERVE
- TOUCH_TAP
- TOUCH_STROKE
- PERSON_DETECTED
- SCENE_CHANGED
- VOICE_REQUEST
- USER_STOP
- DEVICE_DISCONNECTED
- CLOUD_API_ERROR

이벤트 큐에 우선순위를 적용한다.

우선순위는 다음과 같다.

1. 사용자 중지 및 안전 이벤트
2. 사용자 음성·터치 이벤트
3. 주요 환경 변화
4. 정기 관찰
5. 대기 중 애니메이션

중지 이벤트는 진행 중인 자율 작업을 취소하고 새로운 모터 명령의 실행을 차단해야 한다.

동시 제어 충돌 방지를 위해 장치 명령은 단일 실행 큐에서 순차 처리한다.

---

## 6. Vision과 상황 인식

초기에는 정기적인 사진 촬영 방식으로 구현한다.

기본 관찰 주기는 30초로 설정한다.

설정값으로 변경할 수 있어야 한다.

가능하면 로컬에서 이미지 변화량을 먼저 측정하여 변화가 적을 때는 클라우드 API 호출을 생략한다.

다음 정보를 추출하도록 설계한다.

- 사람이 있는지
- 주요 물체가 무엇인지
- 이전 관찰 대비 변화가 있는지
- 반응이 필요한 상황인지
- 행동 필요성이 낮아 대기할지

AI가 시각 정보를 잘못 해석할 가능성을 고려한다.

불확실한 정보만으로 특정 사람의 신원이나 민감한 특징을 추론하지 않는다.

최종 판단은 사용자에게 불필요하게 반복 발화하지 않도록 설계한다.

사진은 별도 저장 허용이 없으면 분석 후 폐기한다.

---

## 7. OpenAI Decision Engine

OpenAI Responses API로 상황을 해석하고 행동을 선택한다.

입력:
- 현재 관찰 결과
- 필요한 경우 카메라 이미지
- 최근 이벤트
- 현재 로봇 상태
- 최근 행동 기록
- 성격 설정
- 안전 제한

출력은 자유로운 실행 코드가 아닌 검증 가능한 구조화 데이터로 제한한다.

예시 스키마:

```json
{
  "intent": "emote",
  "emotion": "happy",
  "speech": "안녕하세요!",
  "yaw_delta_deg": 0,
  "pitch_delta_deg": 0,
  "reason": "사용자가 인사를 요청함"
}
```

허용할 행동 종류:
- idle
- look
- emote
- speak

복합 행동은 별도 안전 검증 단계를 통과한 경우에만 실행한다.

모델이 반환한 수치는 실제 기기에서 허용되는 범위를 재검증한다.

잘못된 JSON, 미지원 행동, 유효하지 않은 각도, 모델 거부 또는 응답 중단이 발생하면 안전하게 대기한다.

AI 출력에 포함된 명령 문자열을 셸에서 직접 실행하지 않는다.

클라우드 AI가 파일 삭제, 임의 명령 실행, 외부 서비스 접속 등 로봇 본래 범위를 벗어나는 행동을 할 수 없도록 제한한다.

---

## 8. 안전한 행동 실행

모터 제어 보호 계층을 구현한다.

- 서보 허용 범위 검증
- 급격한 각도 변경 제한
- 명령 빈도 제한
- 중복 명령 제거
- 마지막 명령 재실행 방지
- 사용자의 수동 중지 우선 처리
- 통신 장애 시 안전 대기
- 단일 모터 명령 실행 주체 유지

피치 각도는 기존 MCP에서 명시하는 권장 범위를 우선 적용하고, 다른 축은 실제 펌웨어 제한을 확인한 후 설정한다.

AI 모델의 임의 각도를 그대로 하드웨어에 전달하지 않는다.

장치에 물리적인 비상정지 기능이 구현되어 있는지는 별도로 확인한다. 소프트웨어 명령 차단을 물리적 비상정지와 동일하다고 가정하지 않는다.

실물 장치 제어는 기본적으로 비활성화한다.

사용자가 명시적으로 실물 테스트를 승인한 후에만 활성화한다.

---

## 9. 음성 기능 설계

기본 언어는 한국어로 설정한다.

음성 파이프라인:

Microphone
→ Speech-to-Text
→ OpenAI Decision
→ Text-to-Speech
→ StackChan Speaker

OpenAI의 STT·TTS API를 우선 검토한다.

기존 MCP Gateway의 녹음 기능과 스피커 재생 경로를 우선 활용하되, 기존 음성 엔진과 클라우드 TTS의 오디오 형식이 호환되는지 실제 코드로 확인한다.

호환되지 않으면 별도 Playback Adapter를 구현한다.

최초 구현은 사용자의 터치 또는 명시적 음성 요청으로 시작한다.

상시 마이크 녹음은 기본 비활성화한다.

자동 음성 감지 및 Wake Word 기능은 별도의 선택 기능으로 추가한다.

음성 동작은 테스트 환경과 실제 하드웨어 환경을 구분한다.

---

## 10. Personality 및 Memory

`config/personality.yaml`을 작성한다.

초기 성격:
- 친근하고 자연스러운 한국어 사용
- 짧고 명확한 대답
- 상황에 맞는 얼굴 표정
- 과도한 인사와 발화 억제
- 사용자 활동을 불필요하게 방해하지 않음
- 모르는 것은 모른다고 대답

SQLite 기반 메모리는 선택적으로 활성화한다.

저장할 정보:
- 최근 상호작용
- 인사한 시각
- 사용자 설정
- 로봇 상태
- 최근 행동 이력

민감한 대화 원문, 촬영 이미지, 음성 파일은 기본적으로 영구 보관하지 않는다.

로봇에 사람을 식별하는 생체인식 기능은 기본 구현 범위에서 제외한다.

---

## 11. API 비용 및 개인정보 보호

다음 설정을 제공한다.

- 최대 분당 API 요청 수
- 최대 시간당 API 요청 수
- 최대 일일 API 요청 수
- 사용량 기록
- 이미지 전송 ON/OFF
- 음성 전송 ON/OFF
- 클라우드 판단 ON/OFF
- 로컬 Mock 모드
- Dry Run 모드

첫 번째 버전은 사용량 제한을 보수적으로 설정한다.

API 모델별 가격은 공식 가격표에 따라 별도로 확인한다.

정확한 결제액을 계산할 수 없는 경우 추정치와 실제 청구액을 구분한다.

API 키는 `.env` 또는 운영체제의 안전한 환경변수에서만 읽는다.

API 키, Wi-Fi 암호, MCP 인증 토큰을 코드나 GitHub 저장소에 저장하지 않는다.

`.gitignore`, `.env.example`을 제공한다.

클라우드에 이미지·음성을 보내는 기능은 사용자의 명시적 설정 후 활성화한다.

---

## 12. 테스트 시나리오

다음 테스트를 구현한다.

### T1. 기본 가상 동작
Mock 모드에서 관찰·판단·행동 루프가 정상적으로 실행되는지 확인한다.

### T2. 사람 감지
샘플 이미지에서 사람을 감지한 이벤트가 발생했을 때 적절한 행동을 선택하는지 확인한다.

### T3. 반복 인사 방지
같은 상황이 반복되어도 설정된 쿨다운 동안 인사를 반복하지 않는지 확인한다.

### T4. 잘못된 AI 응답
미지원 명령이나 비정상적인 서보 각도 요청이 차단되는지 확인한다.

### T5. API 장애
OpenAI API 응답 실패, 시간초과, 사용량 제한 발생 시 안전하게 대기하는지 확인한다.

### T6. 장치 연결 장애
MCP 서버 연결이 끊겼을 때 제어 명령이 누락·중복·재실행되지 않는지 확인한다.

### T7. 사용자 중지
자율행동 중 사용자가 STOP을 요청하면 새로운 행동이 즉시 차단되는지 확인한다.

### T8. API 키 미설정
외부 API 키 없이 Fake AI와 Fake Robot으로 테스트를 수행할 수 있는지 확인한다.

### T9. 개인정보 보호
비밀키, 음성 원본, 이미지 원본이 기본 로그에 기록되지 않는지 확인한다.

### T10. 연속 운영
가상 장치로 반복 관찰 및 이벤트 처리 테스트를 실행하여 메모리 누수 징후, 태스크 중복, 명령 충돌 등을 검사한다.

테스트 결과는 PASS / FAIL / BLOCKED로 구분하여 기록한다.

테스트를 실행하지 않았다면 PASS로 표기하지 않는다.

---

## 13. 개발 작업 순서

### Phase 0 — Upstream Audit
기존 저장소를 분석하고 구현 범위, 인터페이스, 의존성과 문제점을 문서화한다.

### Phase 1 — Initial Skeleton
Python 프로젝트 구조, 설정 관리, Robot Interface, FakeRobotAdapter, 기본 CLI를 만든다.

### Phase 2 — Cloud Decision MVP
OpenAI Responses API 어댑터와 구조화된 Decision Schema를 구현한다. Mock AI도 제공한다.

### Phase 3 — Autonomous Loop MVP
이벤트 큐, 관찰 스케줄러, 안전 검증 계층을 연결한다. 가상 로봇의 자율행동을 완성한다.

### Phase 4 — Hardware Adapter
공개된 MCP 명령을 사용해 실제 StackChan과 연결한다. 하드웨어가 없으면 코드와 Mock 테스트까지만 검증한다.

### Phase 5 — Voice, Memory and Advanced Behavior
한국어 음성, 기억, 얼굴 추적, 웹 대시보드 및 장기 운영 기능을 추가한다.

이번 첫 실행에서는 Phase 0~3을 실제 구현하고 자동 테스트까지 수행한다.

Phase 4~5는 구체적 개발계획과 인터페이스 설계를 완료하되, 실물 기기·외부 API·사용자 승인 등이 필요한 검증을 완료한 것으로 표시하지 않는다.

---

## 14. 산출물

다음 파일과 기능을 제공한다.

1. 실행 가능한 Python 프로젝트
2. 가상 로봇 및 Mock AI
3. OpenAI API 연동 코드
4. 자율행동 엔진
5. 안전 검증 모듈
6. 테스트 코드
7. `.env.example`
8. `config/robot.yaml`
9. `config/personality.yaml`
10. `README.md`
11. `docs/ARCHITECTURE.md`
12. `docs/UPSTREAM_AUDIT.md`
13. `docs/TEST_REPORT.md`
14. `docs/HARDWARE_BRINGUP.md`
15. `docs/NEXT_STEPS.md`

README에는 Windows에서의 설치·실행 방법, Mock 테스트 실행, 환경변수 설정, 클라우드 API 연결, 실제 하드웨어 연결 절차를 포함한다.

실제 테스트하지 않은 기능은 문서에서 명확히 구분한다.

---

## 15. GitHub 및 작업 관리

현재 작업 디렉터리 내에서 `stackchan-autonomy` 프로젝트를 개발한다.

기존 저장소의 소스 코드를 임의로 덮어쓰지 않는다.

외부 저장소를 참고하거나 의존성으로 연결할 때 라이선스와 버전을 기록한다.

각 단계별 변경 파일 및 검증 결과를 남긴다.

원격 저장소가 이미 설정되어 있으면 상태를 확인한다.

사용자가 요청하지 않은 원격 저장소 생성, 강제 푸시, 기존 브랜치 삭제, PR 머지 등은 수행하지 않는다.

새 GitHub 저장소가 필요하지만 아직 없다면 로컬 프로젝트를 완성하고 원격 연결 방법을 보고한다.

---

## 16. Codex 최종 보고 형식

작업 완료 후 아래 형식으로 한국어 보고서를 작성한다.

### A. 개발 완료 현황
단계별 완료·미완료·차단 여부

### B. 실제 구현 기능
작성 파일과 주요 클래스·함수

### C. 기존 GitHub 활용 현황
재사용 코드, 적용 버전, 수정 사항, 출처

### D. 검증 결과
실행 명령, 통과 테스트 수, 실패 테스트 수

### E. 미검증 항목
실제 StackChan, API 키, 하드웨어 제어, 펌웨어 관련 확인 필요 사항

### F. 다음 작업
실물 기기 도착 후 필요한 설치와 테스트 순서

### G. 최종 판정
MOCK_MVP_PASS / PARTIAL / BLOCKED 중 하나

계획만 작성하고 종료하지 말 것.

실제 코드 작성과 테스트를 우선 수행하되, 하드웨어가 없는 상태에서는 Mock 기반 검증 범위를 넘어서 정상 동작을 주장하지 말 것.

**지금 Phase 0의 소스 검증부터 시작하고, Phase 3의 Mock 기반 자율행동 MVP까지 구현하라.**