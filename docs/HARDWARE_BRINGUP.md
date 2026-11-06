# Hardware bring-up — 미실행 계획

사용자가 택배 수령부터 따라갈 절차는 **[제품 도착 후 상세 작업설명서](DEVICE_ARRIVAL_RUNBOOK.ko.md)**를
참고한다. 공식 출고 매뉴얼의 첫 부팅·앱 설정, Windows 명령, 개발 체크포인트,
실물 인수/24시간 시험과 [기록 양식](templates/DEVICE_ACCEPTANCE_RECORD.ko.md)을 포함한다.
아래 내용은 개발 담당을 위한 기술 요약이다.

이 문서는 Phase 4 도입 절차다. 이 작업에서는 장치 연결·플래시·모터 구동을 하지 않았다.
MCPRobotAdapter의 물리 실행은 코드에서 차단되며 환경변수만으로 해제되지 않는다.

1. K151/CoreS3 보드, 전원·배터리, 서보 모델/배선, 출고 펌웨어 버전을 기록한다.
   먼저 모터 주변을 비우고 수동 회전시키지 않는다. 전원 차단 방법을 확인한다.
2. 공식 제품 문서 https://docs.m5stack.com/en/StackChan 에서 현행 M5Burner,
   K151용 공식 복구 이미지, USB 드라이버/COM 포트 및 보드 선택 절차를 확인한다.
   다운로드 출처와 체크섬을 검증하고 기존 설정의 안전한 백업과 복구 수단을 마련한다.
   최초 환경에서는 403이었지만 게시 후 공식 문서의 복구 설명을 확인했다.
   문서상의 순서는 M5Burner에서 StackChan 검색 → Only Official → Download,
   USB-C 연결(베이스 포트 권장) → Burn → 해당 포트 → Start이다.
   포트가 없으면 RST 3초/녹색 표시로 download mode 진입을 설명한다.
   이 안내는 문서만 확인한 것으로, 설치 파일/펌웨어 체크섬과 실기 복구는 미검증이다.
   일반 CoreS3 이미지나 다른 Stack-chan 프로젝트 이미지를 호환된다고 추정하지 않는다.
3. 펌웨어 교체의 영향을 설명하고 **별도로 사용자 승인을 받은 후** 변경한다.
   출고 앱/모바일/보정/NVS 유지 여부를 확인한다. UPSTREAM_AUDIT.md에 기록한 커스텀
   SHA·릴리스가 일치하는지 확인한다. 여기에는 플래시를 자동 실행하는 스크립트가 없다.
4. 별도 gateway 환경에서 버전 0.20.0 또는 감사 SHA를 검토 후 설치한다.
   기존 daemon이 있으면 재사용한다. 단일 daemon 명령은 다음과 같다(이번에는 미실행).

   ```powershell
   # gateway 소스의 gateway/ 디렉터리 또는 별도의 uv tool 환경에서
   uv run stackchan-mcp serve --transport streamable-http
   ```

   WS 8765, capture 8766, MCP 8767/mcp. 토큰은 .env/보안 환경변수로만 전달한다.
   STACKCHAN_TOKEN, VISION_HOST 또는 VISION_URL, MCP HTTP 인증·allowed hosts는
   upstream docs/178-daemon-setup.md를 따른다. URL에 토큰을 넣지 않는다.
5. 읽기 전용으로 list_tools → get_status를 확인한다. connected=true,
   initialized=true, session_id와 장치 tools를 기록한다. 광고된 도구만 보고
   펌웨어가 지원한다고 판정하지 않는다. get_head_angles의 실제 반환 JSON과 단위를
   수집해 구현한 absolute pose 파서와 대조한다. 중립 각도를 추정하지 않는다.
6. 얼굴 표정/LED/터치를 하나씩 확인한다. 관련 PY32/센서 available 값을 확인한다.
   음성 엔진·얼굴 추적·다른 MCP 클라이언트·펌웨어 애니메이션의 서보 제어를 비활성화하거나
   소유권 lease를 확보한다. 공유 daemon의 queue만으로 독점 제어가 보장되지는 않는다.
7. **실물 모터 테스트를 별도 승인한 뒤** 현재 자세에서 작은 움직임부터 확인한다.
   custom 계약의 yaw −90..90, pitch 5..85, 단일 step <=15, 속도 low를 상한으로
   설정한다. 최초 step는 더 작게 잡는다. 출고 펌웨어 좌표와 섞지 않는다.
   전류·충돌·온도·이상음과 실제 피드백을 관찰한다. STOP과 통신 단절도 시험한다.
8. 카메라는 게이트웨이 capture 파일 보관 문제를 해결한 뒤 켠다. 클라이언트 메모리에서
   폐기해도 gateway 파일은 남는다. 세션 전용 임시 저장/삭제 보장과 장애 시 정리를 검증한다.
   이미지 전송은 별도 opt-in이다. 임의 remote path를 자동 읽기/삭제하지 않는다.
9. 음성은 터치/명시적 요청으로만 시작한다. ko 전사, 녹음 제한 시간,
   16kHz mono PCM/Opus 변환과 playback을 Mock부터 검증한다. 별도 전사 로그 보관을
   제거·설정하고 사용자의 음성 전송 동의를 받은 뒤 실제 STT/TTS를 연결한다.
10. 실물 T1–T10을 별도 보고서로 실행 기록한다. Mock PASS를 실물 PASS로 복사하지 않는다.
    무응답·ACK 유실 후 자동 재전송하지 말고 상태·세션을 확인한 뒤 수동으로 재개한다.

소프트웨어 STOP은 물리적 비상정지가 아니다. 토크 해제 도구 존재 여부와 실제 작동,
전원 차단, 낙하 위험은 장치에서 별도로 검증해야 한다.
