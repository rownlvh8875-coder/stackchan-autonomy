# USB 관찰 모듈 준비와 설치 전 확인

이 문서는 K151의 **사진 한 장·접촉/IMU 이벤트를 PC가 읽고 GPT가 설명하는 확장**을
다룬다. 현재 출고 펌웨어와 공식 앱에서 성공한 GPT 음성 대화는 그대로 사용하면 된다.
아래 관찰 기능에는 별도 시험용 펌웨어가 필요하다. **기기 설치는 아직 승인되지 않았다.**
다음 작업은 [원본 백업·복구 준비](K151_BACKUP_RECOVERY.ko.md)다. 사용자는 현재 외출 중이므로
실제 포트·백업 결과는 미확인이다. 공식 저장소의 기여자가 공개 빌드용 제품 인증 구현/설정
절차가 없다고 확인했으므로, 공식 앱 유지 조건의 설치 HOLD는 백업만으로 해제되지 않는다.

## 현재 준비한 범위

- 공식 펌웨어1.6.2 소스의 고정 버전에 추가하는 읽기 전용 USB 모듈.
- 명시한 포트와 기기를 페어링하는 PC 진단기. 가상 데이터로 자동 대체하지 않는다.
- 사진의 길이·SHA256·JPEG 디코딩·크기·요청/부팅 일치·최신성을 확인하는 클라이언트.
- 이미지 전송을 별도로 켰을 때만 등록되는 `stackchan_gpt_observe(question)` 도구.
  기존 `stackchan_gpt_reply`는 텍스트 대화용으로 유지된다.

USB는 ESP32-S3 native USB Serial/JTAG 전용이다. 서보 UART, 기존 LAN/MCP 주소와
다르다. UART0는 콘솔로 남기고 USB 보조 콘솔은 끈다. 이미지가 포함될 수 있는 공식
카메라 DEBUG hexdump를 막기 위해 로그 최대 수준은 INFO 이하로 제한한다.
실제 K151 커넥터 배선·Windows 드라이버·DTR/RTS에 의한 재부팅은 아직 확인하지 않았다.

## 지금 할 작업과 다음 순서

| 단계 | 결과 | 상태 |
|---|---|---|
| 코드·PC 통신·GPT 입력 | 합성 사진/로컬 SDK·MCP로 검증 | 개발 검증 완료, 실물 증거 아님 |
| 실제 ESP32-S3 컴파일 | 고정 소스/SDK/의존성, 바이너리 체크섬 | [빌드 기록](validation/2026-11-17-usb-observer-build.json) 확인 |
| 기기 백업·복구 및 호환성 | 아래 항목을 구체적으로 확정 | 설치 HOLD |
| 승인한 이미지 설치 | 정확한 보드/설정/복구법과 별도 승인 | 아직 진행하지 않음 |
| 오프라인 관찰 | 사진·센서·BUSY·재연결·시간 제한 | 실물 확인 대기 |
| GPT 사진 설명 | 실제 API 요청과 로봇 음성·기존 앱 동시 사용 | 실물 확인 대기 |
| 모터·자율 동작 | 제어권·STOP·실제 피드백부터 검증 | 이후 단계 |

설치 전에 다음을 먼저 해결해야 한다.

1. 장치 전체 flash와 NVS/보정 데이터의 백업, 해시, 실제로 실행 가능한 복구 경로.
2. 정확한 LCD/보드 변형과 native USB 연결 포트. 임의의 COM 포트를 선택하지 않는다.
3. 공개 소스 `secret_logic.cpp`의 인증 대체값 문제. [기여자 답변](https://github.com/m5stack/StackChan/issues/134#issuecomment-6812198686)은
   제품 인증 구현이 공개 소스에 없고 SDKCONFIG 설정으로 켤 수 없다고 설명한다.
   공식 앱·서비스·현재 GPT 음성이 유지된다고 보장할 수 없다. 제조사의 지원되는
   빌드/프로비저닝 경로를 확인하거나 backend 변경을 별도로 결정해야 한다.
4. 원래 부팅의 서보 초기화와 조건부 NVS 지우기 검토. 이 관찰 모듈이 읽기 전용이어도
   원래 펌웨어의 부팅·AI 기능은 모터를 움직일 수 있다.
5. 공식 카메라 드라이버의 dequeue 대기 시간과 고장 후 복구. PC는 시간 제한 후
   오류로 닫고 자동 재시도하지 않지만, 상위 PC 시간 제한이 장치 드라이버를 중단시키지는 않는다.
6. 정확한 이미지와 설정, 복구법에 대한 사용자 설치 승인.

제조사 비밀키 추출이나 기존 계정 인증 우회는 해결 방법에 포함하지 않는다.

## 승인된 설치 이후에만 사용할 PC 순서

**지금 실행할 필요가 없는 후속 시험 절차다. 출고 펌웨어에는 이 USB 규약이 없다.**
명령은 Windows **cmd**, 저장소 폴더 기준이며 예시 `COM7`은 확인한 실제 포트로 바꾼다.
프로필 경로도 명시하면 설치된 wheel을 다른 폴더에서 실행할 수 있다.

먼저 클라우드 없이 물리 연결을 신뢰하는 선택을 명시하고 페어링한다.

```cmd
uv run --frozen stackchan-observe pair --port COM7 --profile .local/observer/profile.json --accept-pairing
```

정상 표시는 `PC_OBSERVER_PAIRED`다. 프로필에는 로컬 기기 ID만 저장하며, 이미 존재하면
덮어쓰지 않는다. 다른 기기로 바뀌면 오류다. 새 기기 페어링은 기존 프로필을 따로 보관하고
새 프로필 경로를 지정하는 운영자 선택으로 한다. 이는 암호학적 기기 인증이 아니다.

```cmd
uv run --frozen stackchan-observe status --port COM7 --profile .local/observer/profile.json
```

```cmd
uv run --frozen stackchan-observe capture --port COM7 --profile .local/observer/profile.json
```

`capture`는 사진을 파일로 저장하거나 화면에 출력하지 않는다. 출처·경과 시간·센서
메타데이터만 출력한다. 센서 이벤트가 없으면 `null`이다. `head_pose=null`,
`pose_verified=false`는 의도된 결과다. 촬영 시각은 PC 요청 시작부터 보수적으로 계산한
경과 시간이며, 장치와 PC의 시계를 동기화했다는 의미가 아니다.

이벤트 숫자는 공식 HAL enum이다. 접촉0=None,1=Press,2=Release,3=SwipeForward,
4=SwipeBackward; IMU0=None,1=Shake,2=PickUp. `age_ms`는 이벤트 캐시의 경과 시간이며
현재 접촉 여부나 원시 가속도/방향각 측정이 아니다. 이벤트 구독 시작 전 값은 알 수 없다.

그다음 실제 이미지 전송을 원할 때 로컬 `.env`에 다음을 추가한다. 기존 API 키/모델/
cloud opt-in 설정도 필요하며 모델의 이미지 입력 지원 여부는 계정에서 확인해야 한다.

```dotenv
STACKCHAN_IMAGE_TRANSMISSION=true
```

```cmd
uv run --frozen stackchan-pc-mcp --gpt --observer-port COM7 --observer-profile .local/observer/profile.json
```

공식 MCP 주소는 기존처럼 숨김 입력한다. 로봇에게 “GPT로 지금 카메라에 무엇이 보이는지
설명해 줘”라고 말해 `PC_OBSERVE_CALLED=N`, `PC_OBSERVE_ANSWERED=N`과 실제 답변을
함께 확인한다. 키·주소·사진은 채팅에 보내지 않는다. 기존 GPT 호출 예산을 공유한다.
API에는 질문·JPEG 한 장·센서 출처만 보내며, 기기/포트/부팅 ID는 보내지 않는다.
전송 JPEG는 검증한 픽셀로 새로 인코딩하여 EXIF 등 부가정보와 뒤에 붙은 데이터를 제거한다.
사진과 설명은 텍스트 대화 이력이나 로컬 파일에 보관하지 않는다. 단, API 전송 자체는
외부 전송이며 공급자의 데이터 처리 정책이 적용된다. `store=false`를 사용한다.

연속 촬영/감시, 이미지 기반 모터 명령이나 실제 STOP 보장은 포함하지 않는다.
이 도구가 공식 AI의 별도 로봇 제어 도구까지 제한하는 것도 아니다.

## 오류와 종료

오류는 `PC_OBSERVER_PAIRING_REQUIRED`, `IDENTITY_CHANGED`, `PROTOCOL_FAILED`,
`BUSY`, `UNAVAILABLE`, `CONSENT_REQUIRED`, `CANCELLED` 고정 코드로 표시한다(모두 `PC_OBSERVER_` 접두사).
BUSY나 부분 전송·시간 초과 후에는 연결을 재사용하지 않는다. 해당 프로그램을 종료하고
원인을 확인한 뒤 새 실행에서 다시 handshake한다. 자동 재시도/대체 이미지는 없다.
기본 요청 제한10초(진단 CLI의 `--timeout-s`로1–30초). `Ctrl+C`는 PC 프로그램을 종료하며,
이미 동작 중인 공식 펌웨어 전체나 모터에 대한 긴급 정지 명령은 아니다.

기술 규약은 [승인 설계](superpowers/specs/2026-11-17-factory-usb-observer-design.md),
개발자 빌드는 [펌웨어 README](../firmware/observer/README.md), 검증은
[검증 기록](validation/2026-11-17-usb-observer.md)을 참고한다.
