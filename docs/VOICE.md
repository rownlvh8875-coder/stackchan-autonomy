# Phase 5 — 오프라인 음성 어댑터와 오디오 변환

현재 검증 범위는 장치/API 키 없이 실행하는 voice-sim과 SDK MockTransport 테스트다.
실제 마이크·스피커를 열거나 실제 STT/TTS API를 호출하지 않았다.

## 실행

```powershell
uv run --frozen stackchan-autonomy --mode voice-sim --event touch --cycles 1
# 신뢰하는 시스템 libopus가 있을 때만, 실제 raw Opus 변환을 추가로 수행
uv run --frozen stackchan-autonomy --mode voice-sim --event touch --cycles 1 --opus
```

출력은 기존 metadata 요약에 audio_captures/audio_playbacks/opus_packets를 추가한다.
전사문·발화·원시 오디오는 출력하지 않는다. 기본 Mock에는 API 키가 필요 없다.
voice-sim은 --forever 및 정기 timer 이벤트를 받지 않으며 터치/명시 voice 요청으로만
1회씩 수행한다. FakeMic는 메모리 내 무음, Fake ASR은 fixture 전사문, Fake TTS는
440Hz tone이다. 한국어 인식 정확도나 자연스러운 한국어 TTS 품질을 입증하는 기능이 아니다.

## 구성

- RecordedVoiceInput: Microphone.record → SpeechTranscriber.transcribe → VOICE_REQUEST.
  실제 마이크는 차단한다. 현재 FakeMicrophone만 제공한다.
- GatewayVoiceInput: 기존 MCP listen의 전사문을 받는 별도 입력 경로다.
  gateway listen은 이미 STT를 수행하므로 다시 OpenAI STT를 호출하지 않는다.
  감사한 공개 MCP 표면에 raw 마이크 PCM/Opus 반환 도구는 없어 이를 만들어 추정하지 않았다.
- VoiceConversation: 수동 이벤트만 허용하고 중복 요청은 voice_busy로 거부한다.
  기존 제어권을 확보하며 STOP/lease 소실을 감시해 입력 작업을 정리한다.
- SpeakingRobotAdapter: 기존 AI/안전/단일 action owner를 유지하고 speak만
  합성 → 16kHz mono 정규화 → PlaybackAdapter로 연결한다.
- FakePlaybackAdapter: metadata만 제한된 history에 저장한다. /pcm용 payload를
  구성하고 선택적으로 실제 Opus 인코딩을 실행하지만 실제 HTTP/스피커에는 전달하지 않는다.

## 형식과 제한

PCM16Audio는 signed 16-bit little-endian, 지원 sample rate, 1/2채널,
완전한 sample/frame 정렬, 최대 30초를 검증한다. 원시 bytes는 repr/직렬화에서 제외한다.
WAV parser는 실제 header에서 sample rate/channels/width를 읽으며 16-bit PCM만
받는다. 압축/8-bit/비정상·잘린 입력과 큰 payload는 거부한다.

normalize_pcm은 stereo 평균 downmix와 windowed-sinc 저역 필터를 사용해
16kHz mono로 변환한다. 24kHz→16kHz에서 Nyquist 위 신호의 aliasing 억제,
DC/길이/진폭 범위를 테스트했다. 변환은 제한된 입력을 메모리 내 CPU 작업으로 처리한다.
취소해도 이미 실행 중인 Python worker thread의 순수 계산을 강제로 끝내지는 못하지만
그 결과를 후속 재생으로 전달하지 않는다. 오디오 파일은 생성하지 않는다.
현재 cloud의 제한된 shell에서는 thread 종료가 정지하는 환경 차이가 있어, SDK/음성 CLI
검증은 승인된 실행 경로로 수행했다. 후속 [CI](CI.md)에서 Windows의 PCM 음성
시뮬레이션과 설치 wheel 실행도 통과했다. Windows native libopus는 여전히 미검증이다.

OpenAI TTS에 response_format=pcm을 요청하며 공식 문서의 24kHz s16le 계약을 사용한다.
OpenAI가 반환하는 opus container를 장치의 raw Opus packet과 같다고 가정하지 않는다.
장치 경로는 감사한 upstream의 **16kHz / mono / 60ms = 960 samples**다.
우리 Opus helper는 마지막 frame을 0-padding하고, decoder 왕복은 codec 지연/손실과
padding을 포함한다. 무손실 변환이나 정확한 원본 길이 복원으로 설명하지 않는다.

libopus는 신뢰하는 OS 설치본을 동적으로 사용하며 바이너리를 다운로드하거나 wheel에
재배포하지 않는다. 현재 Linux libopus.so.0 (1.5.2)로 실제 인코딩·디코딩을 검증했다.
네이티브 라이브러리가 없으면 --opus는 명시적으로 실패하고 PCM 시뮬레이션은 계속 사용할 수
있다. Windows의 libopus/DLL 배치와 실제 실행은 미검증이다. native codec 테스트가
없는 환경에서는 해당 테스트만 SKIP으로 보고한다.

## OpenAI 음성 API 어댑터

OpenAIAudioService는 공식 SDK를 사용하며 다음 설정을 명시해야 한다.

- STACKCHAN_CLOUD_ENABLED=true, STACKCHAN_AUDIO_TRANSMISSION=true.
- OPENAI_API_KEY는 안전한 환경변수/.env에만 저장.
- STACKCHAN_STT_MODEL, STACKCHAN_TTS_MODEL, STACKCHAN_TTS_VOICE.

모델 ID는 코드에 고정하지 않는다. 서비스는 매 요청마다 동의를 확인하고 STT/TTS/기존
Responses가 같은 persistent SQLite 예산을 공유한다. SDK retry는 0이다.
기본 분당 2회 한도에서는 STT+Decision+TTS 3회를 한 분 안에 모두 허용하지 않으므로,
실제 연동 시 필요한 한도를 사용자가 비용 기준으로 명시적으로 설정해야 한다.
프로그램이 동의나 한도를 자동으로 올리지 않는다.

STT는 메모리 WAV를 ko로 전송한다. TTS는 streaming PCM을 최대 30초/1,440,000 bytes로
제한한다. timeout/잘못된 응답/예산·저장소 장애는 후속 출력 없이 실패한다.
녹음/전사는 실패 시 voice_unavailable, 이미 action 단계의 합성/재생 실패는 기존
action fault 정책을 따른다. 반복 호출·재전송하지 않는다.

음성 요청 예약과 오류 수는 기록하지만, 오디오 endpoint의 과금/token 수를 추정하지 않는다.
기존 provider의 token 집계는 알려진 Responses API usage만 반영한다. 실제 청구와
정확한 account 권한/모델 품질은 미검증이다. 기본 CLI의 voice-sim은 이 서비스 대신
FakeSpeechService를 사용하므로 실제 cloud 설정이 있어도 음성 API를 호출하지 않는다.

## 실제 gateway 연결 전 남은 일

pcm_upload는 `/pcm`, application/octet-stream, X-Sample-Rate=16000,
X-Channels=1 및 raw bytes만 구성한다. 인증 토큰을 payload repr에 넣거나 실제 전송하지 않는다.
실제 HTTP transport/별도 PCM 토큰/재생 ACK·중지·장치 상태는 기기 도착 후 구현·검증한다.
gateway의 사진 보관/전사 로그 정책, Opus/PCM 배관과 모터 제어권도 확인해야 한다.
실제 마이크·스피커·모터·펌웨어는 별도 승인 전에 활성화하지 않는다.
