# PC MCP 재연결 현장 확인 — 2026-11-18

날짜는 사용자 시간대 Asia/Seoul 기준이다. 사용자가 집 Windows 노트북의
cmd 출력을 제공했다. 안내한 노트북 Wi-Fi 단절·복구 절차 이후 **진단 모드의
공식 MCP 연결 자동 복구 PASS**로 기록한다. 실행 중인 사용자 PC에 클라우드에서
직접 접속하거나 네트워크 패킷을 측정한 결과는 아니다.

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

確認コードは初回と復旧後で異なり、新しいセッションの初期化とツール一覧
公開まで到達した。上のコード欄は公開記録用の置き換えで、実際の入力値ではない。
再接続時のアドレス再入力は記録されていない。ログに時刻はなく、切断検出や
復旧までの実経過秒数は測定していない。

## 確認した範囲と次の確認

- 実際の公式サービスへの初期接続、切断検出、2→4→8秒の待機表示、
  3回目の再接続、再初期化・新確認コード・ツール一覧公開をユーザー出力で確認。
- 今回は `--gpt` なし。GPT処理中の通信断・課金・回答・ロボット音声の復旧は
  この出力から判定しない。既存のGPT回答・音声PASSは以前の別の記録に限る。
- 次は診断モードをCtrl+Cで終了し、`scripts/start-gpt.cmd` を起動する。
  GPT_READYと新しい質問へのGPT_ANSWERED、実際のロボット音声を確認する。
  この切り替え・音声確認はまだ未確認。
- 新しいファームウェアのインストール、USB・モーター操作は行っていない。
  クラウド側でAPIキーやMCP接続アドレスを読み出したり接続したりしていない。

[実行説明書](../MCP_RECONNECT.ko.md) /
[実装・自動検証](2026-11-17-mcp-reconnect.md)
