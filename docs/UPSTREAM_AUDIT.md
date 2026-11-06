# Upstream Audit

확인일: 2026-11-06. HTTPS Git으로 기본 브랜치의 HEAD를 직접 가져와 확인했다.
아래는 **소스 확인** 결과이며 장치 실행·계정 권한 확인 결과가 아니다.
외부 코드는 프로젝트에 복사하거나 펌웨어와 링크하지 않았다.

## 확인한 버전

| 저장소 | 브랜치 | 커밋 SHA | 라이선스 확인 |
|---|---|---|---|
| https://github.com/m5stack/StackChan | main | `28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400` | `firmware/LICENSE`: MIT; 루트 전체에 동일 적용된다고 추정하지 않음 |
| https://github.com/m5stack/StackChan-BSP | main | `e2f3b02dbe7f28e26a02adc72bef3aa2c545e4a0` | 루트 MIT; 내장 드라이버는 개별 고지 검토 필요 |
| https://github.com/kisaragi-mochi/stackchan-mcp | main | `03fbd92774c37844e11ea097e632df28f2a5f4e5` | 게이트웨이 MIT; SCServo_lib 및 결합 펌웨어 GPL-3.0 경계 |
| https://github.com/migratorywhale/stackchan-mcp | master | `7673c4c9cb93a342824f94c2a91432e4cdbafcf0` | 루트 MIT; THIRD_PARTY_NOTICES.md 별도 |

소스 링크는 해당 SHA의 `blob/<SHA>/<path>`로 재현할 수 있다. 조사 캐시는
`/workspace/.cache/stackchan-upstream/`에 있으며 런타임 의존성이 아니다.

## A. 공식 K151 및 기본 펌웨어

확인 파일: 양쪽 공식 저장소 `README.md`, StackChan의 `firmware/README.md`,
`firmware/main/hal/hal_mcp.cpp`, `firmware/main/hal/hal_servo.cpp`,
BSP의 `src/StackChan-BSP.h`, `src/drivers/Si12T/Si12T.{h,cpp}`.

- 공식 README: CoreS3 / ESP32-S3 240MHz, Flash 16MB, PSRAM 8MB,
  2인치 터치 디스플레이, 0.3MP 카메라, 1W 스피커, 듀얼 마이크,
  IMU, 근접·조도 센서, microSD. 본체: 피드백 서보 2개, RGB LED 12개,
  3영역 터치, IR, NFC, 550mAh 배터리. 모두 실제 장치에서는 미확인.
- README의 수평 360°/수직 90° 하드웨어 설명은 **명령 허용 범위가 아니다**.
  공식 `hal_servo.cpp:337–353`의 구성은 0.1도 단위 yaw −1280..1280,
  pitch 30..870이다. 영점·보정과 소프트웨어 계층을 함께 확인해야 한다.
- 공식 MCP는 존재한다. `Hal::xiaozhi_mcp_init` (`hal_mcp.cpp:16`)에
  `self.robot.get_head_angles`, `self.robot.set_head_angles`,
  `self.robot.set_led_color`, reminder 생성/목록/중지 등록이 있다.
  get_head_angles 설명의 중립값은 `{yaw:0,pitch:0}`이며,
  set_head_angles 안내는 yaw −128..128, pitch 0..90, speed 100..1000이다.
  스키마의 생략 sentinel −9999 및 HAL의 제한과 구분해야 한다.
  이는 아래 커스텀 게이트웨이와 **동일 계약이 아니다**.
- 기본 펌웨어는 앱/표정/ESP-NOW/모바일/OTA를 포함한다. 커스텀 MCP 프로젝트는
  xiaozhi-esp32 포크의 별도 보드와 게이트웨이를 사용한다. 출고 펌웨어에
  아래 10개 도구가 그대로 호환된다고 보장하지 않는다.
- 공식 빌드 문서는 ESP-IDF 6.1, fetch_repos.py, idf.py build를 명시한다.
  이 작업에서는 펌웨어 의존성을 설치하거나 빌드·플래시하지 않았다.

## B. 핵심 기반: kisaragi-mochi

`gateway/pyproject.toml`: 패키지 0.20.0, Python >=3.10,
MCP >=1.27,<2, websockets, aiohttp, zeroconf, Pydantic. 선택 TTS/STT는
Opus 네이티브 라이브러리와 외부 서비스/모델이 추가로 필요하다.
우리 프로젝트는 게이트웨이를 라이브러리로 import하지 않고 별도 프로세스로 둔다.

확인한 핵심 위치:

- `gateway/stackchan_mcp/stdio_server.py`: `create_server:1419`,
  `list_tools:1427`, `_dispatch_mcp_tool:840`, `call_tool:3223`.
- `gateway/stackchan_mcp/gateway.py`: `Gateway.start:161`, `stop:209`.
- `gateway/stackchan_mcp/esp32_client.py`: `call_tool:1278`, `get_status:1443`.
- `firmware/main/boards/stackchan/stackchan.cc`: 피치 보호와 도구 등록.
- `docs/architecture.md`, `docs/178-daemon-setup.md`, `gateway/README.md`.

### 실제 공개 Tool 스키마와 결과

위치는 모두 `stdio_server.py`; 표의 지원은 코드 구현을 뜻한다.
공통 결과는 MCP `CallToolResult.content`의 TextContent(JSON); 사진에는 ImageContent가
추가된다. `isError`뿐 아니라 JSON `error`/`ok`/`available`도 확인해야 한다.

| 도구 | 스키마 위치 | 실제 입력 / 라우팅 / 결과 | 지원 및 제약 |
|---|---|---|---|
| get_status | 1435, dispatch 861 | `{}` → `esp32.get_status`; connected, device_id, tools_count, 연결 시 initialized/session_id/tools | 로컬 게이트웨이 구현; 장치별 목록은 list_devices와 구분 |
| take_photo | 1492 | **question 필수 string** → self.camera.take_photo; image_path/size_bytes/question 텍스트 + inline JPEG | 구현됨; 설명에 AI 분석이라 쓰여 있으나 capture_server는 저장 영수증을 반환 |
| move_head | 1660, 검증 1001 | yaw integer −90..90, pitch integer 5..85 필수; speed low/mid/high 또는 양의 정수 → self.robot.set_head_angles | 구현됨; 범위 밖 reject, bool 각도 reject |
| get_head_angles | 1934 | `{}` → self.robot.get_head_angles; 장치 결과 전달 | 구현됨; 실제 자세 피드백·모터 동작은 미검증 |
| set_avatar | 2064, mapping 1175 | face 필수: idle/happy/thinking/sad/surprised/embarrassed/off → **self.display.set_avatar** | 구현됨; architecture.md의 self.avatar.set_face 설명은 현재 코드와 다름 |
| set_blink | 2180 | **enabled boolean 필수** → self.display.set_blink | 구현됨; 일부 README의 state 표기는 현재 입력과 다름 |
| set_all_leds | 2302 | r/g/b 각각 integer 0..255 필수 → self.led.set_all | 구현됨; PY32 실패 시 available=false 가능 |
| get_touch_state | 2268 | `{}` → self.touch.get_touch_state; 영역 상태/최근 tap·stroke·idle/경과시간 | 구현됨; 이벤트 알림 확장과 polling은 별도 |
| listen | 2702, dispatch 908 | duration_ms 100..30000, engine 기본 faster-whisper, language 선택(명시적으로 ko 사용), model, motion none/face-only/look-up, look_up_pitch 5..85 | `stt.orchestrator.listen_and_transcribe` 구현됨; STT extra/백엔드·토큰 필요 |
| say | 2636, dispatch 894 | **text 필수**, voice 기본 voicevox, speaker_id/name, reference_audio 선택 | `tts.orchestrator.synthesize_and_send` 구현됨; TTS extra/엔진 필요, 광고만으로 사용 가능 판정 불가 |

### 각도와 정지

`stackchan.cc:1138–1149`: SAFE_PITCH_MIN=0, MAX=88;
RECOMMENDED_PITCH_MIN=5, MAX=85. 이는 해당 커스텀 펌웨어의 보호이며
공식 펌웨어의 좌표·동작 범위와 혼용하지 않는다. MVP는 5..85 및 yaw −90..90만
사용하고 한 번의 델타를 15도 이하로 제한한다. 실물의 충돌·부하 검증은 별도다.
`set_servo_torque` 도구가 존재하지만 물리적 비상정지를 증명하지 않는다.
이미 하드웨어에 도달한 명령은 Python task 취소만으로 되돌릴 수 없다.

### daemon·음성·개인정보

- 현재 코드/문서에서 `stackchan-mcp serve --transport streamable-http`를 확인했다.
  MCP 기본 주소는 127.0.0.1:8767/mcp, ESP32 WS 8765, capture HTTP 8766이다.
  하나의 daemon에 연결한다. 추가 stdio gateway를 실행하지 않는다.
  daemon의 직렬화가 다른 앱의 움직임/자율 애니메이션까지 독점해 주지는 않는다.
- README/architecture의 음성 'planned' 표기는 낡았다. 실제
  `tts/orchestrator.py:synthesize_and_send`, `send_pcm_stream:700`,
  `stt/orchestrator.py:listen_and_transcribe:353`를 확인했다.
  장치 경로는 16kHz mono signed-16-bit PCM ↔ Opus이다.
  `capture_server.py`의 `/pcm`은 외부 PCM을 받아 source rate에서 16kHz로 변환하며,
  별도 PCM token을 사용한다. OpenAI TTS의 출력 샘플레이트를 자동으로 같다고
  가정하지 않는다. WAV/PCM 파싱·리샘플링 후 PlaybackAdapter가 필요하다.
- **사진 영구 보관 기본값 충돌:** `capture_server.handle_capture:121`,
  199–211은 파일을 저장하고 경로를 반환한다. 기본 경로는 ~/.stackchan/captures.
  `_photo_contents:1324`는 경로 확인 후 작은 JPEG를 inline화한다.
  클라이언트가 이미지를 버려도 게이트웨이 파일은 남는다. 따라서 이 MVP의
  MCP capture는 비활성화했다. 원격 경로를 임의로 읽거나 삭제하지 않는다.
- `stt/openai_whisper.py:172`는 전사문을 로그에 포함한다. 실제 음성 연결 전
  게이트웨이 로그 정책/보관을 확인·수정해야 한다. 클라우드 키는 별도 보안 설정한다.

## C. 참고: migratorywhale

실제 확인 파일/함수:

- `scripts/stackchan_face_tracker.py`: `OpenCvFaceDetector:31`, `FaceTracker:78`.
- `mcp_server/face_tracking.py`: `acquire_tracker_lock:26`, `TrackingLease:45`,
  `select_face:162`, `FaceMotionController:288` — 얼굴 중심 기반 추적·lease/단일 점유 설계.
- `mcp_server/mcp_tools.py:register_tools:223`, `mcp_server/listening.py:capture_ready_recording:11`,
  `mcp_server/voice_inbox.py:append_event:17/read_events:25` — 이벤트/음성/MCP 도구 계층.
- `firmware/src/face_service.cpp`, `mic_service.cpp`, `playback_service.cpp`,
  `servo_service.cpp`, `camera_service.cpp` — 별도의 HTTP 기반 펌웨어.

24kHz mono s16le `/play/pcm`과 WAV URL `/play`, snapshot/face/move 등을 사용하는
별도 계약이다. kisaragi의 16kHz Opus/WS 경로와 혼합하지 않는다. 얼굴 추적은
신원 식별이 아니며, 이 MVP에는 실제 CV 모델/추적을 포함하지 않았다.
설계 참고만 했으며 소스·이미지 자산·음성 엔진 코드를 재배포하지 않는다.

## 최초 MVP 조사에서 확인 불가였던 항목

아래 403 결과는 최초 MVP 시점의 기록이다. 게시 후 후속 조사 결과는 다음 절을 따른다.

- https://docs.m5stack.com/en/StackChan 직접 요청: 프록시 403.
  공식 저장소 설명은 검증했지만 현행 M5Burner UI, K151 복구 이미지·절차·체크섬은
  확인하지 못했다. HARDWARE_BRINGUP.md의 절차는 실행 전 확인할 계획이다.
- https://developers.openai.com/api/docs/guides/structured-outputs 와 images-vision,
  https://openai.com/api/pricing/ 직접 요청도 프록시 403.
  실제 설치한 공식 SDK 3.46.0의 Responses create 서명과 JSON Schema HTTP 요청은
  MockTransport로 검증했다. 계정에서 사용할 모델의 이미지/구조화 출력/한국어 지원,
  실제 과금·가격표·권한은 **BLOCKED / 미검증**이다. 모델 ID나 가격을 추정하지 않는다.
- 필요한 세 도메인은 환경 설정 **초안에만** 저장했다. 적용·게시하지 않았다.
- 라이브 장치, 내장 센서·토크 해제·오디오·M5Burner 복구는 모두 미검증이다.

## 의존성 버전 확인

PyPI 메타데이터와 실제 설치 후 테스트로 OpenAI 3.46.0, MCP 1.30.0,
Pydantic 2.14.3, pydantic-settings 2.16.2, Pillow 13.0.0, PyYAML 6.0.3을 고정했다.
OpenAI 3.x는 httpx2, MCP 1.x는 httpx를 사용하는 차이가 있어 별도 테스트 경계를 둔다.
전체 전이 버전·artifact hash는 uv.lock에 기록했다. 게이트웨이는 이 프로젝트의
런타임 의존성에 포함하지 않았다. 해당 gateway 버전과의 실물 상호운용성은 미검증이다.

## 게시 후 후속 확인 — 2026-11-06

새 게시 버전에서 기존 소스/캐시/의존성이 복원됐고, 기존 60개 테스트가 통과했다.
이전 변경을 다시 적용하거나 환경 초안을 수정하지 않았다.

- https://docs.m5stack.com/en/StackChan : HTTP 200, 공식 본문을 직접 확인했다.
  Motion Angle Notice는 Y축 **5~85° 권장**, 극단 각도에서 stall/영구 손상 가능성을
  명시하며 X축에 별도 제한이 없다고 설명한다. 우리 −90..90 yaw 제한은 감사한
  커스텀 gateway 계약에 따른 더 좁은 소프트웨어 제한으로 유지한다.
- 공식 문서의 Restore Factory Firmware: M5Burner에서 StackChan 검색 →
  Only Official → Download → USB-C 연결(베이스 포트 권장) → Burn → 해당 포트 → Start.
  포트가 나타나지 않으면 RST 3초/녹색 표시로 download mode 진입을 설명한다.
  **문서 확인만 했으며 다운로드/플래시/서보 테스트는 실행하지 않았다.**
  배포 이미지 체크섬과 실기 복구 성공은 아직 미검증이다.
- 공식 문서는 출고 앱이 original StackChan core를 대상으로 하며 비정품 대체
  CoreS3/CoreS3-SE/CoreS3-Lite와의 연결을 보장하지 않는다고 설명한다. 동일 ESP32-S3라는
  이유로 출고 앱·하드웨어 변형·커스텀 gateway 호환성을 추정하지 않는다.
- https://developers.openai.com/api/docs/guides/structured-outputs : HTTP 200.
  Responses의 JSON Schema strict 출력과 required/additionalProperties, 거부 및
  불완전한 응답 처리 설명을 확인했다. 기존 코드의 처리 경계를 유지한다.
  실제 계정 모델의 권한/이미지/한국어/실제 청구는 여전히 미검증이다.
- 가격·이미지·오디오 관련 최신 페이지는 이번 MCP 작업에서 추가 검증하지 않았다.
  실계정 호출·새 secret 요구·유료 API 호출은 하지 않았다.

### Phase 4에서 추가 확인한 펌웨어 반환 계약

모든 위치는 같은 감사 SHA의 `firmware/main/boards/stackchan/stackchan.cc`다.

- `self.robot.set_head_angles:6393`, 반환 `6464` 부근:
  servo_init_ok, uart_num, yaw_pos, pitch_pos, yaw_motion_started, pitch_motion_started.
  일반적인 `{"ok":true}` 형태가 아니다. motion_started는 숫자 0/1이다.
  servo_init_ok는 초기화 상태일 뿐 실제 이동 완료나 물리적 안전의 증거가 아니다.
- `self.robot.get_head_angles:6527`: yaw/pitch 숫자; ReadPos 실패 시 null/error/servo_ok.
  null/누락을 중립 0/45도로 바꾸면 안 된다.
- `self.display.set_avatar:6854`: face/ok; 실패 시 error.
  set_blink는 enabled/ok를 반환한다.
- `self.touch.get_touch_state:7028`: available, zone0..2, raw, enabled/masked 등과
  last_event(tap/stroke/idle), last_event_age_ms. unavailable은 터치 이벤트가 아니다.
- `self.led.set_all:7100`: available 및 ok/error.
- gateway stdio_server.py:1300 부근은 firmware TextContent를 결합해 전달한다.
  outer isError뿐 아니라 내부 JSON을 확인해야 한다.

`src/stackchan_autonomy/data/upstream_mcp_tools.json`에 gateway의 10개 도구 스키마를
실제 AST에서 추출해 저장했다. 출처 SHA/path와 MIT 고지를 함께 보존한다.
시뮬레이터는 이 스키마와 위 반환 계약을 사용하며 외부 장치/포트에는 연결하지 않는다.
프로토콜 시뮬레이션 결과를 ESP32/HTTP/auth/실물 검증으로 확대하지 않는다.

## Phase 5 음성 계약 추가 확인 — 2026-11-06

- 공식 https://developers.openai.com/api/docs/guides/text-to-speech 와
  https://developers.openai.com/api/docs/guides/speech-to-text 에서 HTTP 200을 확인했다.
  TTS raw PCM은 **24kHz, signed 16-bit little-endian, header 없음**이라고 명시한다.
  언어 목록에 한국어가 있지만 실제 계정/선택 모델/음질을 검증한 것은 아니다.
- 설치 SDK 3.46.0의 audio.transcriptions.create와
  audio.speech.with_streaming_response.create 서명을 확인했다.
  STT ko/in-memory WAV, TTS response_format=pcm 요청은 MockTransport로 검증했다.
  모델/voice ID는 사용자 설정이며 실제 API 요청은 실행하지 않았다.
- 감사 SHA의 gateway/stackchan_mcp/tts/audio_utils.py는 16kHz/mono/60ms=960 samples,
  PCM→Opus frame 경로를 정의한다. OpenAI의 opus 응답 container와 이 raw packet을
  동일시하지 않고 PCM에서 별도 인코딩한다.
- capture_server.py:385의 handle_pcm은 /pcm, 별도 PCM token, X-Sample-Rate,
  X-Channels=1 및 선택 X-Message-Id를 사용한다. 새 pcm_upload는 고정 형식 payload만
  구성하고 token/HTTP/스피커 전송은 구현하지 않았다.
- 변환/네이티브 codec wrapper는 새 구현이며 upstream Python/servo 코드를 복사하지 않았다.
  신뢰하는 OS libopus를 동적으로 사용하고 바이너리를 재배포하지 않는다.
  Linux libopus 1.5.2로 실제 raw packet 인코딩/디코딩을 검증했다.
  Windows/DLL/장치 오디오는 여전히 미검증이다.
