# K151 출고 상태 연결 확인 — 2026-11-16 (한국 시간)

사용자가 현장에서 제공한 화면과 Windows 명령 결과를 정리했다.
클라우드 실행 환경에서 장치 LAN에 접속하거나 장치 명령을 보낸 결과는 아니다.
인증 토큰, 원본 화면, 기기 MAC, SSID, 계정 및 대화 내용은 이 기록에 넣지 않는다.

## 확인된 사실

| 항목 | 결과 / 범위 |
|---|---|
| 제품 | 사용자가 K151로 확인; 실제 LCD 개정판은 미확인 |
| 본체 펌웨어 | 본체 Setup 화면: V1.6.2 |
| 휴대폰 앱 | Settings의 Version: v1.2.12; 펌웨어 버전과 구분 |
| 제조사 연결 검사 | Xiaozhi OTA/configuration service connected, HTTP 200 |
| 제조사 연결 검사 | M5Stack Device API connected, HTTP 200 |
| 노트북 Wi-Fi | 로봇 표시 SSID와 일치, 2.4GHz; 같은 IPv4 /24 대역 |
| 최초 Ping | 노트북이 대상 호스트에 연결할 수 없다는 오류를 4회 반환 |
| ARP | 이후 대상 주소의 동적 MAC 항목 확인 |
| 재검사 Ping | 대상에서 4/4 정상 응답, 손실 0%, TTL 64; 최소67/최대253/평균119ms |
| 공식 앱 연결 | 본체 Avatar / 휴대폰 Motion에서 사용자가 Local Network 표시 확인 |

최초 Ping 실패의 원인은 확정하지 않는다. ARP·후속 Ping은 당시 도달성을 확인한 것이며,
공유기 설정 변경이나 코드 수정으로 해결했다고 주장하지 않는다.
Local Network 표시는 공식 앱과 본체의 연결 확인이다. 우리 엔진의 자세 조회, 모터 제어,
물리 정지, 카메라·음성, 실물24시간 시험은 아직 미실행이다.
PC Fake/Mock의 실제24시간 PASS는 [별도 기록](../SOAK.md)에 있다.

## 사용자가 선택한 다음 범위

1. 출고 펌웨어와 공식 앱을 유지하는 방향을 우선한다.
2. 공식 AI가 PC의 기능을 호출하는 MCP 확장을 먼저 완성한다.
3. 기존 PC OpenAI 엔진의 직접 로봇 제어와 음성 backend 교체는 별도 후속 작업이다.

## 소스와 제조사 답변에서 확인한 연결 방향

확인한 공식 소스: m5stack/StackChan
`28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400`.
2026-11-16 GitHub API의 main SHA와 로컬 캐시 SHA가 일치했다.

- [로컬 Avatar 클라이언트](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/utils/local_network/local_avatar_client.cpp):
  로봇이 휴대폰이 알린 WebSocket endpoint로 접속한다.
- [휴대폰 LAN 서비스](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/local_area_network_service.dart):
  페이지가 활성인 동안 서버를 열고 연결과 인증을 처리한다. 공개 소스의 설정 예제만으로
  실제 배포 앱과 호환되는 PC 직접 연결이 검증되는 것은 아니다.
- [앱 MCP 화면](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/view/home/mcp_page.dart):
  도구 목록이 비어 있으면 Offline을 표시한다. 이 표시만으로 Wi-Fi 고장을 단정하지 않는다.
- [제조사 답변](https://github.com/m5stack/StackChan/issues/126#issuecomment-6593389244):
  공식 펌웨어를 유지하고 PC 기능을 MCP 도구로 제공할 수 있다. 이때 공식 서비스의
  음성·AI pipeline을 계속 사용하며, MCP만으로 마이크 오디오나 AI backend가 PC로 바뀌지는 않는다.
- [제조사 안내에서 링크한 확장 예제](https://github.com/c1pher-cn/ha-mcp-for-xiaozhi/blob/main/README.en.md):
  외부 MCP 서버가 앱에서 받은 접속점 주소로 WebSocket 연결을 시작하고 도구를 제공한다.

사진의 MCP 접속주소는 PC가 로봇 도구를 조회하는 HTTP gateway 주소와 용도가 다르다.
토큰 재요청이 이전 토큰 폐기를 보장하지 않는다는 제조사 답변도 확인했다.
초기화/계정 해제를 토큰 폐기 수단으로 안내하지 않는다. 실제 토큰은 운영자가 로컬에서만 입력한다.

다음 개발안은 [공식 MCP PC 연결 진단기 설계](../superpowers/specs/2026-11-16-official-mcp-pc-bridge-design.md)에 있다.
후속 [PC 진단기](../OFFICIAL_MCP_PC.ko.md)의 오프라인 구현 검증은 별도로 추가했다.
실제 endpoint 연결·현장 도구 호출은 아직 미검증이다.
