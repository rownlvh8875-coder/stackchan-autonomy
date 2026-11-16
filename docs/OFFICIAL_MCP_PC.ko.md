# 출고 펌웨어를 유지하는 PC 연결 확인

K151의 공식 AI가 노트북의 읽기 전용 MCP 도구를 호출하는 기능이다.
출고 펌웨어와 StackChan World를 그대로 사용한다. 음성·대화 AI는 공식 서비스를 사용하며,
PC OpenAI 자율 엔진으로 바뀌는 것은 아니다. 이 진단기는 로봇 동작·촬영·녹음·파일·명령 실행을 제공하지 않는다.

연결 흐름: **노트북 도구 → 공식 MCP 접속점 ← 공식 AI/로봇**.
노트북이 외부로 연결하므로 공유기 포트 개방이나 별도 Home Assistant 설치는 필요 없다.
앞서 확인한 Local Network는 휴대폰과 로봇 사이의 별도 연결이며, 이 도구 등록의 증거는 아니다.

## 1. 기존 Windows 체크아웃 업데이트

cmd에서 한 번에 한 줄만 실행한다.

```cmd
git -C "%USERPROFILE%\stackchan-soak-24h" pull --ff-only
```

로컬 수정/충돌 오류가 있으면 출력을 확인한다. 강제 초기화하거나 다시 clone하지 않는다.
기존 PC Mock24시간 시험은 통과했으므로 이 연결 작업을 위해 반복할 필요는 없다.

## 2. 연결 확인 프로그램 실행

```cmd
"%USERPROFILE%\.local\bin\uv.exe" --directory "%USERPROFILE%\stackchan-soak-24h" run --frozen stackchan-pc-mcp
```

처음에는 잠긴 의존성을 설치할 수 있다. 이후 다음 입력 안내가 나타난다.

```text
Official MCP endpoint (hidden input):
```

휴대폰 StackChan World의 **Settings → MCP → Access point address** 복사 버튼으로
주소를 복사한다. 본인만 접근하는 방법으로 PC에 옮긴 뒤, 위 숨김 입력창에 주소만
한 번 붙여 넣고 Enter를 누른다. **입력 중 글자가 보이지 않는 것이 정상**이다.
주소를 이 채팅이나 GitHub에 보내거나, 실행 명령 뒤에 붙이지 않는다.

지원 주소는 앱이 표시하는 `wss` 방식의 공식 `api.xiaozhi.me` MCP 접속점이다.
토큰은 메모리에만 두며 설정 파일에 저장하지 않는다. 프로그램은 앱의 `.env`를 읽지 않는다.
자동화가 필요하면 `STACKCHAN_OFFICIAL_MCP_ENDPOINT` 환경변수를 사용할 수 있으나,
변수 값을 출력·공유하지 않는다. 일반 사용에는 위 숨김 입력 방식을 권장한다.

## 3. 등록과 실제 호출을 각각 확인

진행 단계에 따라 다음 고정 표시가 나온다.

| 표시 | 확인되는 사실 |
|---|---|
| `OFFICIAL_MCP_CONNECTING` | 접속 시도 중 |
| `OFFICIAL_MCP_CONNECTED` | WebSocket 연결 성공; 도구 등록은 아직 별도 |
| `OFFICIAL_MCP_INITIALIZED` | 초기화 응답 후 정상 완료 알림 또는 후속 요청 확인 |
| `PC_CHECK_CODE=123456` | 이 실행의 6자리 진단 코드; 실행마다 달라짐 |
| `OFFICIAL_MCP_TOOLS_LISTED` | 서버가 PC 도구 목록을 요청했고 응답을 보냄 |
| `PC_TOOL_CALLED=1` | 실제 PC 연결 확인 도구가 한 번 호출됨 |

1. 앱의 MCP 화면을 다시 확인해 `stackchan_pc_connection_status`가 나타나는지 본다.
   도구 이름이 보이지 않으면 등록 성공으로 판정하지 않는다.
2. 휴대폰의 Motion 페이지를 닫는다. 로봇 본체는 Home에서 **AI Agent**로 전환한다.
   Avatar 모드는 음성 대화 모드가 아니다.
3. “**PC 연결 확인 코드를 알려줘**”라고 말한다.
4. 노트북에 `PC_TOOL_CALLED=1`이 나타나고, 로봇이 읽어 준 코드가 현재 노트북의
   `PC_CHECK_CODE`와 같은지 비교한다. 로봇이 말만 했는데 호출 표시가 없으면 실제 도구 호출을
   확인한 것이 아니다. 호출마다 횟수는 증가하며 코드는 같은 실행 동안 유지된다.

진단 코드는 인증 비밀이 아니므로 그 코드와 고정 진행 표시만 공유할 수 있다.
결과는 **목록 등록 / PC 호출 도착 / 음성 코드 일치**로 나누어 기록한다.
로봇 자세·제어권·물리 STOP 또는 실물24시간 시험의 PASS로 옮기지 않는다.

## 4. 종료와 오류

같은 접속주소용 진단기는 창 하나만 유지한다. 노트북과 cmd가 실행 중이어야 PC 도구를 쓸 수 있다.
종료는 **Ctrl+C**다. `OFFICIAL_MCP_STOPPED`와 종료 코드130을 사용할 수 있다.
이 진단기의 종료는 로봇 모터 정지나 공식 AI 서비스의 종료를 뜻하지 않는다.

연결이 끊기면 자동 재접속하거나 도구 호출을 재실행하지 않는다. 원인을 확인한 뒤 수동으로
다시 실행한다. 공유할 때는 아래 고정 오류 코드만 보내고, 접속주소는 가린다.

| 오류 | 다음 확인 |
|---|---|
| `OFFICIAL_MCP_INVALID_ENDPOINT` | 앱 복사 버튼의 전체 주소인지 확인; 토큰 없이 주소를 재작성하지 않음 |
| `OFFICIAL_MCP_SECRET_INPUT_UNAVAILABLE` | 일반 cmd에서 직접 실행; 숨김 입력을 지원하지 않는 리디렉션/도구 사용 여부 확인 |
| `OFFICIAL_MCP_ARGUMENTS_INVALID` | 실행 명령 뒤에 주소나 다른 값을 붙였는지 확인 |
| `OFFICIAL_MCP_INITIALIZATION_TIMEOUT` | 연결 후30초 동안 초기화와 후속 통신이 완료되지 않음; 앱 접속점 상태와 공식 서비스 확인 |
| `OFFICIAL_MCP_REMOTE_CLOSED` / `OFFICIAL_MCP_CONNECTION_FAILED` | 네트워크·인증·공식 서비스 상태 확인; 주소/원시 예외를 공유하지 않음 |
| `OFFICIAL_MCP_PROTOCOL_FAILED` | 지원하지 않는 메시지/순서/크기; 고정 코드와 발생 단계로 조사 |
| `OFFICIAL_MCP_REDIRECT_REJECTED` | 접속점이 다른 주소로 이동을 요구함; 앱의 최신 주소와 공식 서비스 안내 확인 |

잘못된 입력은 종료 코드2, 연결/프로토콜 오류는1이다. 오류에 토큰·원시 응답·traceback을 출력하지 않는다.
허용한 접속주소를 벗어나지 않도록 자동 리다이렉트도 따라가지 않는다.
이미 끝난 호출에 대한 정상 취소 알림은 연결을 끊지 않고 처리한다.
프로그램 자체는 OpenAI API를 호출하지 않는다. 로봇의 공식 음성·AI 서비스 이용 조건은 별도다.

노출된 토큰의 폐기는 제조사 지원으로 확인한다. 새 토큰 요청이나 계정 해제/초기화가 이전 토큰을
무효화한다고 보장하지 않는다. [제조사 답변](https://github.com/m5stack/StackChan/issues/126#issuecomment-6593389244) 참고.

## 검증 범위

클라우드/CI에서는 로컬 가상 접속점으로 실제 WebSocket·MCP SDK 대화를 시험한다.
사용자의 토큰이나 장치에 접속하지 않는다. 실제 앱 목록과 로봇 음성으로 위 절차를
확인하기 전에는 현장 PC 연동 성공으로 표시하지 않는다.

2026-11-17 현장 시험에서는 사용자가 실제 PC 도구 호출과 로봇의 진단 코드 일치를 확인했다.
[현장 PASS 기록](validation/2026-11-17-official-mcp-pc-live.md)을 참고한다.
이 기록의 코드는 해당 실행의 값이며, 새 실행에서는 현재 cmd에 나온 코드를 기준으로 비교한다.
