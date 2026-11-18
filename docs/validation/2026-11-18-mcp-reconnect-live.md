# PC MCP 재연결 현장 확인 — 2026-11-18

날짜는 사용자 시간대 Asia/Seoul 기준이다. 사용자가 집 Windows 노트북의
cmd 출력을 제공했다. 안내한 노트북 Wi-Fi 단절·복구 절차 이후 **진단 모드의
공식 MCP 연결 자동 복구 PASS**로 기록한다. 이어 GPT 모드로 돌아온 뒤의
**GPT 답변 반환·로봇 음성 PASS**도 사용자가 확인했다. 실행 중인 사용자 PC에
클라우드에서 직접 접속하거나 네트워크 패킷을 측정한 결과는 아니다.

## 실행과 관측

사용자가 실행한 명령은 유료 GPT 도구를 활성화하지 않는 진단 모드다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" --directory "%USERPROFILE%\stackchan-soak-24h" run --frozen stackchan-pc-mcp --reconnect
```

초기 CONNECTED/INITIALIZED/TOOLS_LISTED 이후 아래 흐름을 확인했다.

```text
OFFICIAL_MCP_REMOTE_CLOSED
OFFICIAL_MCP_RECONNECT_WAIT=2
OFFICIAL_MCP_RECONNECTING=1
OFFICIAL_MCP_CONNECTING
OFFICIAL_MCP_CONNECTION_FAILED
OFFICIAL_MCP_RECONNECT_WAIT=4
OFFICIAL_MCP_RECONNECTING=2
OFFICIAL_MCP_CONNECTING
OFFICIAL_MCP_CONNECTION_FAILED
OFFICIAL_MCP_RECONNECT_WAIT=8
OFFICIAL_MCP_RECONNECTING=3
OFFICIAL_MCP_CONNECTING
OFFICIAL_MCP_CONNECTED
OFFICIAL_MCP_INITIALIZED
PC_CHECK_CODE=<초기와 다른 6자리 확인 코드>
OFFICIAL_MCP_TOOLS_LISTED
```

확인 코드는 초기 연결과 복구 후에 서로 달랐고, 새 세션의 초기화와 도구 목록
공개까지 도달했다. 위 코드 칸은 공개 기록용으로 바꾼 것이며 실제 입력값이 아니다.
재연결 중 주소를 다시 입력한 기록은 없다. 로그에 시각은 없어서 끊김 감지·복구의
실제 소요 시간은 측정하지 않았다.

## GPT 모드 복귀와 답변·음성 확인 — PASS

사용자는 안내한 진단 모드 종료 후 아래 실행 파일을 시작한 cmd 출력을 제공했다.

```cmd
"%USERPROFILE%\stackchan-soak-24h\scripts\start-gpt.cmd"
```

CONNECTED/INITIALIZED 이후 `PC_GPT_READY`와 `OFFICIAL_MCP_TOOLS_LISTED`가
나온 것을 확인했다. 공식 앱에도 연결 확인·시험 요약·`stackchan_gpt_reply`의
세 도구가 등록되어 있었다. 앱의 접속주소나 토큰은 이 기록에 옮기지 않는다.

이어 로봇 답변과 cmd의 `PC_GPT_ANSWERED` 표시가 모두 나왔는지 물었고, 사용자가
**“응 나왔어”**라고 확인했다. 새 유료 질문을 추가로 요구하지 않고 기존 표시를
확인하도록 했다. 따라서 이번 GPT 모드의 실제 답변 반환·로봇 음성은 사용자 보고로
PASS다. 정확한 호출 번호·모델·답변 원문·토큰/비용·응답 지연은 별도로 수집하지 않았다.

중간에 GPT 도구 호출이 도착하지 않는 문제가 보고되었으나, 최종 정상화의 정확한
조작과 원인은 확인되지 않았다. 이전 대화의 도구 목록 캐시 등의 가설을 확정하거나
PC 코드를 수정해서 해결했다고 판정하지 않는다.

## 확인 범위

- 실제 공식 서비스 진단 연결의 단절 감지,2→4→8초 대기,3회차 재접속과
  재초기화·새 확인 코드·도구 목록 공개를 사용자 로그로 확인했다.
- 이후 GPT 모드를 별도로 실행한 뒤 ANSWERED와 로봇 음성을 사용자 보고로 확인했다.
  GPT 요청 처리 중 Wi-Fi를 끊은 시험이나 GPT 세션의 음성 자동 복구 판정은 아니다.
- 진단 연결 복구와 GPT 모드 복귀·답변 확인 단계는 완료했다. 실물24시간 운영이나
  청구 검증은 이 확인에 포함되지 않는다.
- 새 펌웨어 설치나 USB·모터 조작은 수행하지 않았다. 클라우드 측에서 사용자
  API 키·MCP 주소로 실제 서비스에 접속하거나 유료 API를 호출하지 않았다.

[실행 설명서](../MCP_RECONNECT.ko.md) /
[구현·자동 검증](2026-11-17-mcp-reconnect.md)
