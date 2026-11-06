# Offline voice test report — 2026-11-06

Python 3.12.14 / Linux / libopus 1.5.2. 최종 판정은 MOCK_MVP_PASS다.

| 실행 / 대상 | 결과 |
|---|---|
| `pytest -q --junitxml=.local/voice-pytest.xml` | **194 PASS / 15.95초**, 오류·실패·skip 0 |
| `ruff check .`, `ruff format --check src tests` | PASS, Python 파일 36개 |
| `voice-sim --event touch --cycles 1` | PASS: 캡처/재생 각 1, IDLE, cloud_requests=0 |
| 같은 CLI에 `--opus` 추가 | PASS: raw Opus packet 7개, cloud_requests=0, 실제 스피커 사용 없음 |
| `uv build --offline` | PASS: sdist/wheel |
| wheel 설치 후 /tmp에서 같은 `voice-sim --opus` | PASS: 음성 모듈 4개 포함 확인, 가상 재생 1회/Opus7개/cloud0; editable 설치 복원 |

기존 148개 테스트를 유지하고 이번 단계에서 46개를 추가했다.
공식 OpenAI STT/TTS 문서 HTTP 200과 SDK 3.46.0 서명을 확인했다.
SDK MockTransport는 STT ko/in-memory WAV, TTS streaming 24kHz s16le, 동의/모델 설정,
공유 예산, no retry, timeout/500/잘못된 응답/큰 응답을 검증했다.
실제 계정·유료 API는 사용하지 않았다.

PCM 모델은 정렬/크기/시간/형식을 검사하고 WAV의 잘림/불완전 frame을 거부한다.
stereo→mono, 24kHz→16kHz 길이/DC/범위 및 Nyquist 위 신호 alias 억제를 검사했다.
실제 libopus의 16kHz mono 60ms packet 인코딩·디코딩이 통과했다. 이는 lossy codec의
지연/padding을 포함하며 한국어 음성 품질 증거가 아니다.

VoiceConversation은 수동 trigger만 녹음, 중복 요청 차단, STOP/lease 소실/연결 장애 시
입력 정리, 합성·재생 중 취소 후 완료 기록 방지, privacy 및 태스크 정리를 검증했다.
Fake ASR은 fixture이고 Fake TTS는 tone이다.

## 독립 리뷰와 수정

리뷰어가 당시 새 39개 테스트를 39 PASS / 2.87초로 실행하고 5개 주요 결함 및
WAV alignment 문제를 재현했다. 7개 회귀 테스트의 실패를 확인한 뒤 수정했다.

- 녹음이 취소를 삼켜도 STT 시작 전 취소를 다시 검사한다.
- 주입 SDK에도 retry=0을 적용해 예약 1회에 HTTP 자동 재시도가 붙지 않도록 한다.
- 모든 engine terminal fault가 공통 stop_event를 설정한다.
- facade가 DEVICE_DISCONNECTED 등 우선순위 0 이벤트를 전달한다.
- codec/voice runtime 실패가 CLI의 고정 메시지와 code 2로 끝난다.
- WAV의 선언 data 길이와 frame 정렬을 검사해 남은 bytes를 조용히 버리지 않는다.

WAV 문제도 검증 계약의 문제로 판단해 수정했다. 재리뷰는 실행하지 않았고 수정 후 전체
194개 suite를 검증했다. 물리 장치·라이브 API·gateway transport/auth·Windows/big-endian,
다른 PC/앱의 fencing, 음성 품질과 장기 운용은 리뷰 및 검증 범위 밖이다.

## 실행 환경 제한과 남은 검증

제한된 cloud shell에서 음성 변환 thread 종료가 정지하는 환경 차이를 재현했다.
승인된 실행 경로에서는 같은 CLI가 통과했다. 정지한 본 작업의 프로세스는 종료하고
별도 state 경로로 정상 동작을 확인했다. SDK/스레드 테스트는 승인된 실행 경로를 사용한다.
변환을 취소해도 이미 실행 중인 순수 CPU thread를 강제로 종료하는 보장은 하지 않는다.
그 결과가 후속 재생으로 전달되지 않는 경계를 검증했다.

실제 마이크/스피커, gateway PCM 인증·재생 ACK/STOP, 실제 한국어 ASR/TTS·계정·보관·청구,
Windows/DLL/big-endian 실기, 장기 운영은 미검증이다. memory 확장/얼굴 추적/웹 UI/Windows CI는
이번 음성 단계에서 구현하지 않았다. 환경 게시와 GitHub push도 하지 않았다.

후속 [CI 단계](CI.md)에서 GitHub 반영과 Windows/Linux × Python3.11/3.12 검증을
완료했다. Windows PCM 음성/wheel은 PASS이며 native libopus와 fork는 SKIP이다.
위 미구현·미실행 기록은 음성 단계 종료 시점의 이력이다.
