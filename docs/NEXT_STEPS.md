# Next steps

## Phase 4 — 계약 검증 후 실제 MCP Adapter

현재 구현: MCPRobotAdapter.connect/discover/status/touch_state, 공개 Tool 스키마와
장치 tools 교집합, 절대 pose 파싱, 세션·장치 고정, 시간초과/취소 fault latch.
`--mode mcp-sim`에서 factory 소유의 메모리 내 gateway를 통한 전체 engine을 실행한다.
사진/서보/표정/blink/LED/가상 listen·say 계약을 테스트했지만, 실물의 capture/execute 및
음성은 여전히 차단돼 있다. 실제 HTTP/auth/ESP32 연동은 미검증이다.

구현할 계약:

- get_head_angles 파서는 구현했다. 실제 기기의 단위·중립·보정 및 UART 피드백을 확인한다.
- take_photo(question 필수) → inline JPEG만 취급; gateway 임시 보관/정리 정책을
  해결한 경우에만 허용. 이미지가 없으면 비활성 capability, remote path fallback 금지.
- move_head의 정수 타깃/speed=low, 양자화 전후 범위/slew, servo_init_ok ACK,
  전후 device/session 확인을 시뮬레이션으로 구현했다. 실물 이동 완료/피드백과는 구분한다.
- set_avatar(face), set_blink(enabled), set_all_leds(r,g,b), get_touch_state →
  실제 JSON error/available 및 isError 처리, 지원 도구가 없으면 비활성화.
- 서버 schema 변경·누락 required·세션/장치 교체·잘못된 pose/사진·취소/timeout은
  메모리 내 통합 테스트를 추가했다. 실제 권한/토큰 만료/HTTP 단절 테스트는 남아 있다.
  같은 DB/resource를 쓰는 이 앱의 프로세스 간 lease는 구현했다.
  다른 앱·다른 PC·장치 자체 동작을 통제하는 gateway fencing은 별도로 구현해야 한다.

완료 기준: 별도 실물 승인, 복구 준비, 승인한 작은 각도/표정/터치/LED,
STOP·분리·재연결 테스트 기록. 기본 물리 실행 비활성화 유지.

## Phase 5 — 음성 / Memory / 고급 동작

1. `VoiceInput.listen(language="ko", duration_ms=...) -> Event(VOICE_REQUEST)`:
   터치/명시 요청으로 시작, gateway listen의 STT 엔진을 검증한다. OpenAI STT는
   설치된 SDK와 현재 계정 모델로 확인하며 WAV wrapping/16kHz Opus decoding을 시험한다.
2. `PlaybackAdapter.play_pcm(pcm, sample_rate, channels)`:
   OpenAI TTS의 실제 출력 형식 확인 후 mono s16le로 변환, gateway /pcm 토큰 경로와
   16kHz 리샘플링·Opus 전송을 검증한다. say의 기본 voicevox를 OpenAI TTS로 오인하지 않는다.
   migratorywhale의 24kHz HTTP 계약은 별도 adapter가 필요하다.
3. 상시 녹음/wake word는 별도 선택 기능. 기본적으로 만들지 않는다.
4. 현재 SQLite는 최근 event/intent/result 시각만 저장한다. 사용자 설정/로봇 상태,
   세션 간 인사 시각 보존과 마이그레이션/보관기한을 추가한다. 지속 API 예산과
   누적 사용량 메타데이터는 공용 SQLite로 구현하고 재시작·프로세스 경쟁을 테스트했다.
   원시 대화·이미지·오디오·생체 신원 데이터는 기본 저장 대상에서 제외한다.
5. 얼굴 추적은 비식별 bounding box → 작은 head delta로 분리한다. 실제 탐지 정확도,
   추적 lease 및 정지 테스트가 필요하다. 사진의 사람이 누구인지 판단하지 않는다.
6. 웹 대시보드는 로컬 인증·privacy 상태·STOP·실물 승인 상태만 제공하는 별도 작업이다.
   아직 UI/서버를 만들거나 외부 포트를 공개하지 않았다.
7. 장기 운용: 24시간 이상 soak, API 계정/비용 확인, 메모리·태스크·재시작 복원,
   event flood 우선순위, 다른 앱의 모터 충돌을 실제 환경에서 검증한다.

## 외부 검증 선행 조건

- 게시 후 공식 제품/구조화 출력 문서 접근을 확인했다. 이미지/오디오 API와 가격,
  실제 계정 모델 지원은 해당 기능을 연결하기 전에 추가 확인한다.
- Windows 3.11+에서 uv sync --frozen / pytest / CLI 실행 검증.
- 계정 모델이 Responses/strict schema/이미지/한국어를 지원하는지 현재 문서·실제 계정으로 확인.
- 실제 API 호출은 opt-in이며 키를 채팅이나 Git에 넣지 않는다.
- 게이트웨이 사진 보관/전사 로그 문제 해결 및 펌웨어 변경·모터 구동 별도 승인.
