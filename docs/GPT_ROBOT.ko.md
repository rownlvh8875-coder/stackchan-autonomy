# GPT API 답변을 로봇으로 듣기

목표는 **로봇에 질문 → PC의 GPT API가 답변 생성 → 로봇이 답변 재생**이다.
출고 펌웨어와 공식 앱을 유지한다. 공식 서비스가 음성 인식·도구 선택·재생을 담당하고,
새 PC 도구 `stackchan_gpt_reply`가 OpenAI Responses API를 호출한다.
이 채팅과 별도인 로봇용 API 대화이며, 최근3회 성공한 대화만 프로그램 메모리에 유지한다.
프로그램을 종료하면 이 대화 문맥은 지워진다.

일반 대화를 항상 GPT로 보내도록 장치 전체 backend를 교체하는 기능은 별도다.
현재는 공식 AI의 도구 호출 경로이므로, 처음에는 “GPT에게 물어봐”라고 요청한다.
2026-11-17에 사용자가 GPT 성공 표시와 정상 로봇 음성 응답을 확인해
[현장 PASS](validation/2026-11-17-gpt-robot-reply-live.md)로 기록했다.
정확한 호출 번호·실제 모델 ID·발화 원문은 별도 수집하지 않았다.

## 1. 기존 프로그램 종료·업데이트

현재 연결 프로그램 창에서 **Ctrl+C**를 누른다. cmd에서 아래 한 줄을 실행한다.

```cmd
git -C "%USERPROFILE%\stackchan-soak-24h" pull --ff-only
```

같은 공식 MCP 접속주소를 쓰는 PC 프로그램은 창 하나만 실행한다.

## 2. 노트북에만 API 설정

```cmd
notepad "%USERPROFILE%\stackchan-soak-24h\.env"
```

메모장에서 아래 항목을 설정하고 저장한다. 기존 파일이 있으면 해당 항목을 수정하고
같은 이름의 항목을 중복 추가하지 않는다. **실제 키는 본인 노트북 파일에만 입력한다.**
키가 보이는 파일·화면·실행 명령을 채팅이나 GitHub에 보내지 않는다.
메모장의 파일명이 `.env.txt`가 아니라 **`.env`**인지 확인한다.

```dotenv
OPENAI_API_KEY=여기에_본인의_OpenAI_API_키
STACKCHAN_CLOUD_ENABLED=true
STACKCHAN_OPENAI_MODEL=gpt-6-luna
STACKCHAN_GPT_REASONING_EFFORT=none
```

위 모델은 [현재 공식 모델 목록](https://developers.openai.com/api/docs/models)의
저비용 대화용 시작 예시다. 모델 ID는 코드에 고정하지 않으며 본인 계정에서 사용할 수 있는
Responses·구조화 출력 지원 모델로 바꿀 수 있다. `none` 추론 설정도 해당 모델이 지원해야 한다.
다른 모델을 쓰며 설정을 생략하려면 `STACKCHAN_GPT_REASONING_EFFORT` 행을 지운다.
각 계정·모델의 사용 가능 여부는 실제 요청으로 확인한다. 위 현장 PASS는 사용자가 실행한
설정의 성공이며, 모든 계정/모델의 권한이나 과금을 일괄 검증한 결과는 아니다.

API 사용량은 본인 OpenAI API 계정에 과금된다. ChatGPT 구독과 별도이며,
기본 요청 한도는 **분당2회·시간당30회·하루100회**, 응답 출력 상한은600토큰이다.
요청 한도는 금액 상한을 의미하지 않는다. 한도는 SQLite에 남아 재시작해도 유지되고,
실패·시간초과 요청도 사용한 요청으로 남긴다. 예산 DB에 질문·답변 원문은 저장하지 않는다.
OpenAI 요청에는 `store=false`를 사용하며 제공자의 데이터 처리 정책은 별도로 적용된다.

## 3. GPT 모드로 실행

자동 복구를 사용하려면 [Windows 간편 실행·자동 재연결](MCP_RECONNECT.ko.md)을 따른다.
기존 설정과 출고 펌웨어를 유지하며 `scripts/start-gpt.cmd` 또는 `--gpt --reconnect`로 실행한다.
아래 기존 명령은 단일 연결 모드다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" --directory "%USERPROFILE%\stackchan-soak-24h" run --frozen stackchan-pc-mcp --gpt
```

`Official MCP endpoint (hidden input):`가 나오면 앱의 MCP 접속주소를 이 숨김 입력창에만
붙여 넣고 Enter를 누른다. OpenAI API 키를 이 칸에 넣지 않는다.
`--gpt`가 없는 기존 명령은 연결 확인·시험 요약 두 도구를 제공하며 유료 GPT를 켜지 않는다.

| 표시 | 의미 |
|---|---|
| `PC_GPT_READY` | GPT 모드가 설정되고 MCP 초기화 완료; API 성공은 아직 별도 |
| `PC_GPT_CALLED=1` | 첫 GPT 도구 호출 도착 |
| `PC_GPT_ANSWERED=1` | 해당1번째 호출의 실제 API 응답을 검증해 반환함 |

호출 번호는 증가한다. 실패한 호출에는 ANSWERED가 나오지 않는다.
모델·질문·답변·키·원시 API 오류는 cmd에 출력하지 않는다.
API 인증·서버 장애 때 자동 재시도하거나 가짜 답변으로 대체하지 않는다.

## 4. 로봇으로 첫 실제 질문

휴대폰 Motion 화면을 닫고 로봇을 **AI Agent** 모드로 둔다.

> GPT에게 물어봐. 너는 어떤 도움을 줄 수 있는지 한국어 두 문장으로 소개해 줘.

`PC_GPT_CALLED=N` 다음에 **`PC_GPT_ANSWERED=N`**이 나타나고 로봇이 질문에 맞는
한국어 답변을 하는지 확인한다. 이 두 표시와 음성 결과를 알려주면 실제 API 연동 결과를 기록한다.
호출 표시 없이 나온 답변은 GPT 도구 성공으로 판정하지 않는다.

일상 대화에서 GPT 도구를 우선하려면 공식 앱 **AI Agent Config**에서 현재 사용하는
Agent의 편집 화면에 있는 **Character Description**에 아래 내용을 추가할 수 있다.
기존 설정 내용을 보관하고 현재 바인딩을 유지한다. 실제 메뉴가 다르면 명시적 질문으로 먼저 시험한다.

```text
일반 질문과 대화 답변은 stackchan_gpt_reply 도구로 생성한다.
사용자의 질문을 question에 전달하고, 성공하면 answer 내용을 덧붙임 없이 자연스럽게 읽는다.
PC 연결 코드나 시험 결과는 해당 전용 도구를 사용한다.
GPT 도구가 실패하면 연결 또는 사용량 한도 문제를 알리고, GPT 답변인 것처럼 대신 만들지 않는다.
```

이 지침은 공식 AI의 도구 선택을 유도하며 모든 발화의 강제 라우팅을 보장하지 않는다.
PC는 이미지·오디오를 받지 않으며 전달받은 텍스트 질문과 제한된 대화만 OpenAI로 보낸다.
노트북과 cmd를 켜 두어야 한다. 종료는 **Ctrl+C**다. 기존 단일 연결 모드는 수동 실행,
`--reconnect` 모드는 일시적인 MCP 연결 오류만 자동 복구하며 GPT 질문을 재전송하지 않는다.

## 오류 확인

| 고정 코드 | 확인할 내용 |
|---|---|
| `PC_GPT_CONFIG_REQUIRED` | `.env` 파일명·키·모델·cloud=true·추론 설정이 유효한지 확인 |
| `PC_GPT_INVALID_QUESTION` | 비어 있거나1200자를 넘는 질문·잘못된 인자 여부 확인 |
| `PC_GPT_BUDGET_EXHAUSTED` | 분·시간·일 요청 한도 도달; 해당 창이 지나야 해제됨 |
| `PC_GPT_STORAGE_UNAVAILABLE` | 로컬 예산 DB 경로·쓰기 권한·잠금 상태 확인; 예약 실패 시 API 요청 차단. 응답 후 집계 실패도 이 코드로 알림 |
| `PC_GPT_UNAVAILABLE` | 키/계정 권한·모델/추론 지원·크레딧·네트워크·시간초과·응답 형식 확인 |

기존 MCP 연결 오류는 [PC 연결 설명서](OFFICIAL_MCP_PC.ko.md)를 따른다.
오류를 공유할 때는 고정 코드만 전달한다. 키나 접속주소를 확인용으로 보내지 않는다.
이 연결은 로봇의 직접 모터·STOP·카메라 제어 완료를 뜻하지 않는다.
