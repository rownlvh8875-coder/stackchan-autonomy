# K151 native wake 설치 전 검토 자료

## 2026-11-28 ESPHome과 Home Assistant 우선 검토

K151은 `Hi StackChan` 감지·마이크·스피커를 맡고, 상시 실행 중인
Home Assistant에서 한국어 Assist 파이프라인을 구동한다. “한국어 답변만”
용도의 별도 파이프라인에서 OpenAI 대화 에이전트를 선택하고 기기 제어
도구를 주지 않는 구성을 검토했다. 기본 로컬 명령 우선 옵션과 별도의
문장 트리거가 요청을 먼저 처리할 수 있다.
[Assist 파이프라인과 음성 위성](https://www.home-assistant.io/voice_control/) ·
[OpenAI 대화 에이전트 설정](https://www.home-assistant.io/integrations/openai_conversation/)

### 음성 모델과 한국어 모의 검증

Home Assistant Core 2026.11.3 소스에서 OpenAI STT와 TTS의 한국어
언어 항목 `ko-KR`을 확인했다. 이 버전의 기본 TTS는 `gpt-4o-mini-tts`와
Speech API를 사용한다. OpenAI의 종료 예정일은 이 모델이 **2027-01-06**,
기본 STT `gpt-4o-mini-transcribe`가 **2027-02-26**이다.
[Home Assistant STT 코드](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation/stt.py) ·
[Home Assistant 모델 기본값](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/openai_conversation/const.py) ·
[OpenAI 종료 예정 목록](https://developers.openai.com/api/docs/deprecations)

상시 사용 후보로 Home Assistant의 Wyoming 연동과
`wyoming_openai` v0.9.1(`2f91ab5`)을 로컬의 별도 환경에서 검토했다.
모의 시험에서 사용한 인식 모델은 `gpt-transcribe`, 합성 모델은
`gpt-realtime-2.1-mini`다. 한국어 전용 음성 인식은
`WYOMING_LANGUAGES=ko-KR` 광고와
`STT_EXTRA_BODY={"languages":["ko"]}`를 함께 사용하는 구성을 시험했다.
지정값 없이 `ko-KR`을 보내면 기본 경로가 그대로 OpenAI에 전달한다.
공식 인식 API가 안내하는 한국어 형식에 맞춰 `ko`로 지정했다.
[Wyoming 언어 및 모델 설정](https://github.com/roryeckel/wyoming_openai/blob/2f91ab5476b668e236eb846a63aa28b31eaf2f3a/README.md) ·
[OpenAI 전사 언어 코드](https://developers.openai.com/api/docs/guides/speech-to-text#supported-languages)

모의 요청에서 한국어 전사와 Realtime의 24kHz 모노 PCM 반환을
확인했다. Wyoming 구성요소의 테스트는 658개 통과, Windows 소켓
차이로 1개 건너뜀이었고 한국어 추가 시험 1개도 통과했다. 공급자의
Realtime 합성은 실험 기능이며 기본 로그에 전사·합성 텍스트 일부가
포함될 수 있다. 이 구성요소의 기본 실행에는 프로젝트의 지속 예산이
적용되지 않는다.
[Wyoming 음성 처리 코드](https://github.com/roryeckel/wyoming_openai/blob/2f91ab5476b668e236eb846a63aa28b31eaf2f3a/src/wyoming_openai/handler.py)

### 한국어 음성 서비스의 로그와 사용량 보호

`python -m stackchan_autonomy.ha_voice`는 검토한 Wyoming 처리기를
사용한다. `wyoming-openai==0.9.1`(커밋 `2f91ab5`),
`wyoming==1.11.0`, `openai==3.44.0`으로 구성한 별도 Python 환경에서
검증했다. Home Assistant가 같은 네트워크 네임스페이스에서
`127.0.0.1:10300`에 연결하는 구성을 대상으로 한다.

서비스 환경에서 `STACKCHAN_CLOUD_ENABLED`와
`STACKCHAN_AUDIO_TRANSMISSION`을 모두 켜고 `OPENAI_API_KEY`를
공급해야 시작할 수 있다. `STACKCHAN_STATE_PATH`는 재시작 뒤에도 같은
파일을 쓰도록 절대 경로로 지정한다. 키는 서비스 환경에서 읽으며 작업
폴더의 `.env`는 읽지 않는다.

- STT 요청과 Realtime TTS 연결 전에 같은 SQLite 예산을 각각 한 건씩
  예약한다. 기본 한도는 분당 2건, 시간당 30건, 24시간당 100건이다.
  통상 음성 한 턴에 2건이며, 실패나 취소로 반환하지 않는다. 재시작
  후에도 같은 경로와 예산 이름을 쓰면 집계가 유지된다. 저장소를 쓸 수
  없거나 한도가 소진되면 해당 OpenAI 요청 전에 중단한다.
- 이 서비스는 음성을 파일에 저장하지 않고, 공급자 및 Wyoming 로그를
  끈다. 실패 상태는 고정 코드로 남기고 Home Assistant에 전달하는 오류
  메시지에서 요청과 공급자 예외 내용을 제거한다.
- 기본 Home Assistant OpenAI 통합을 선택하면 그 GPT 요청은 이
  예산을 사용하지 않는다. 아래 `StackChan GPT` 대화 에이전트를
  선택하면 같은 예산에 GPT 요청을 포함할 수 있다.

Home Assistant가 사용하는 이벤트 순서로 로컬 TCP의 서비스에 합성
PCM을 보냈다. 모의 OpenAI로 한국어 전사, 24kHz PCM 응답, 한도 초과
차단, 공급자 오류, 입력 길이 제한을 확인했다. 이 시험은 로봇을
연결하거나 Home Assistant를 배포하거나 유료 API를 호출하지 않았다.
[Home Assistant Wyoming STT 코드](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/wyoming/stt.py) ·
[Home Assistant Wyoming TTS 코드](https://github.com/home-assistant/core/blob/92da9f154079459b9e547126f9bd9fce726de16a/homeassistant/components/wyoming/tts.py)

### GPT 답변을 포함한 연속 대화와 지속 예산

별도 작업인 `python -m stackchan_autonomy.ha_conversation`은
`127.0.0.1:10301`에서 Home Assistant의 질문 텍스트를 받는다.
기존 GPT Responses 처리기의 모델 설정, 답변 길이 제한, 재시도 금지,
`store=false` 및 SQLite 선예약을 재사용한다. 이 경로는 요청마다
현재 질문을 보내고 직전 질문·답변을 모델에 다시 전송하지 않는다.
연속 대화는 재생 뒤 대기로 돌아가고 새 호출어로 다음 질문을 받는
경로다. GPT 응답이 물음표로 끝나도 자동 수신을 요청하지 않는다.

추후 설치 시 두 서비스에 같은 `STACKCHAN_STATE_PATH`, 같은
`STACKCHAN_BUDGET_NAMESPACE`와 같은 시간별 한도를 공급한다.
GPT 서비스에는 계정에서 쓸 `STACKCHAN_OPENAI_MODEL`도 지정한다.
인식·GPT·합성에 각각 한 건이 들어가므로, 60초 안에 두 번 대화하는
시험 설정은 `STACKCHAN_REQUESTS_PER_MINUTE=6`이다. 기본값은 2건이며
전체 세 단계를 허용할 분·시간·24시간 한도가 각각 3건 이상이어야
GPT 서비스가 시작된다. 요청 실패나 이미 전송한 질문의 취소는 예약을
반환하지 않는다. 단계별로 예약하므로 잔여 한도에 따라 응답 도중
합성이 차단될 수 있다.

Home Assistant의 설정 폴더에
`config/home_assistant/custom_components/stackchan_gpt`를
`custom_components/stackchan_gpt`로 복사한 뒤 통합을 추가한다.
한국어 Assist의 대화 에이전트는 **StackChan GPT**, 인식과 합성은
로컬 Wyoming 서비스를 선택한다. 질문 전용 파이프라인에서 로컬 명령
우선 및 별도로 설정한 문장 트리거의 우선 적용을 확인한다. 두 서비스
포트는 Home Assistant와 같은 루프백을 사용할 때 접근할 수 있다.
Home Assistant 설정에는 OpenAI 키를 넣지 않는다.
[Home Assistant 대화 엔티티 인터페이스](https://contributors.home-assistant.io/core/entities/conversation/)

모의 OpenAI 요청으로 두 턴의 여섯 단계, 같은 SQLite 경로로 재시작한
후의 차단, 60초 뒤 재개, 연결이 끊긴 대기 요청의 미전송을 확인했다.
실제 Home Assistant Core 2026.11.3을 임시 환경에서 실행해 통합 추가,
로컬 TCP를 통한 한국어 모의 답변, 한도 차단과 통합 해제를 검증했다.
Home Assistant 자체의 질문 로그·음성 캐시 정책, 실물 STOP, 유료 응답의
실제 합성 및 재생은 상시 적용 전에 확인한다.

### Linux 상시 호스트의 자동 시작과 예산 복구

`config/home_assistant/systemd/`에는 같은 Linux 호스트에서 실행할
systemd 서비스와 설정 예제가 있다. systemd 247 이상과
호스트 네트워크를 사용하는 Home Assistant Container를 기준으로
준비했다. Home Assistant의 별도 운영체제나 다른 컴퓨터에 설치한
경우에는 두 서비스의 루프백 연결 구성을 별도로 준비해야 한다.
[Home Assistant Container 설치](https://www.home-assistant.io/installation/linux/) ·
[systemd 자격 증명](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Credentials)

`stackchan-assist.target`을 활성화하면 부팅 시 음성·GPT 서비스가 함께
시작한다. 두 서비스는 같은 `settings.env`와 전용 계정
`stackchan-assist`, 영구 저장 경로 `/var/lib/stackchan-assist/`를
사용한다. 프로세스 오류는 제한된 횟수만 다시 시작하며, 설정이나
예산을 확인할 수 없어 종료 코드 2로 멈추면 관리자가 상태를 확인한다.
OpenAI 키는 root 권한으로 관리하는 `/etc/stackchan-assist/openai-key`를
systemd 자격 증명으로 전달한다.
[systemd 재시작 정책](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#Restart=)

호스트를 선택한 뒤 적용하는 순서다.

1. 전용 계정을 준비한다. 고정된 프로젝트 버전으로
   `/opt/stackchan/venv-conversation`에 잠금 파일의 의존성을 설치한다.
   `/opt/stackchan/venv-voice`에는 앞서 검증한 Wyoming 버전과
   `pydantic-settings`, `PyYAML`을 설치하고 로컬 프로젝트 wheel을
   `--no-deps`로 추가한다. 음성 환경은 Python 3.12 이상을 사용한다.
2. 처음 설치할 때만 예제 설정을 `/etc/stackchan-assist/settings.env`로
   복사한다. 영구 경로와 예산 이름을 먼저 확정한다. 새 설치의 최초
   예산 파일은 두 서비스가 정지한 상태에서 아래 명령으로 한 번 만든다.
   기존 파일은 그대로 보존하며, 일시적으로 파일이 사라진 경우에는
   복구 절차를 적용한다.

```sh
sudo systemd-run --pipe --collect -p User=stackchan-assist -p Group=stackchan-assist \
  -p StateDirectory=stackchan-assist -p StateDirectoryMode=0700 -p UMask=0077 \
  -p EnvironmentFile=/etc/stackchan-assist/settings.env \
  /opt/stackchan/venv-conversation/bin/python -B -m stackchan_autonomy.ha_host initialize-budget
```

3. 소유자가 모델·비용·음성 전송 범위를 확인한 뒤 클라우드와 오디오
   설정을 켠다. 키 파일은 root만 읽을 수 있게 두고, 두 유닛 파일을
   `/etc/systemd/system/`에 배치한다. 아래 점검은 파일과 예산만
   확인하고 `HA_HOST_READY`를 출력한다.

```sh
sudo systemd-run --pipe --collect -p User=stackchan-assist -p Group=stackchan-assist \
  -p EnvironmentFile=/etc/stackchan-assist/settings.env -p UnsetEnvironment=OPENAI_API_KEY \
  -p LoadCredential=openai-key:/etc/stackchan-assist/openai-key \
  /opt/stackchan/venv-conversation/bin/python -B -m stackchan_autonomy.ha_host check
sudo systemd-analyze verify /etc/systemd/system/stackchan-assist.target
```

4. 상시 사용 전환을 승인한 뒤 `sudo systemctl daemon-reload`와
   `sudo systemctl enable --now stackchan-assist.target`로 시작한다.
   `systemctl is-active stackchan-assist@voice.service stackchan-assist@conversation.service`에서
   두 서비스 상태를 확인한다. 두 포트는 `127.0.0.1`에서만 열린다.
   중단하거나 이전 운영 방식으로 돌리려면
   `sudo systemctl disable --now stackchan-assist.target`을 사용한다.
[일회성 systemd 명령](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html)

정전이나 저장소 장애 후 파일이 없어졌거나 예산 이름이 달라졌다면,
두 서비스를 정지하고 원래 경로·마운트·파일을 먼저 확인한다. 기존
지출이 들어 있는 정상 DB가 복구되면 `check`를 실행한 뒤 시작한다.
DB를 보관할 때는 두 서비스를 정지하고 SQLite 백업 기능을 사용한다.
최근 사용량이 빠진 사본만 있다면 실제 지출과의 대조가 끝날 때까지
유료 운영을 보류한다.

오프라인 시험에서는 임시 DB로 음성 작업 프로세스가 예약을 확정한
뒤 강제 종료하고 새 GPT 작업 프로세스에서 같은 분당 한도를 확인했다.
빈 파일·파일 유실·다른 예산 이름에서는 작업이 시작되기 전에 멈췄다.
Ubuntu CI의 `Linux Assist start and recovery rehearsal`은 임시 systemd
유닛과 합성 자격 증명을 사용한다. 부팅 대상의 등록, 두 작업 자동 시작,
강제 종료 후 자동 재시작, 대상 재시작·중단, 예산 파일 유실·복원을
실제 서비스 관리자에서 시험한다. 작업자는 모의 요청을 사용하며 CI
호스트의 전원 재부팅은 하지 않는다. 설치할 Linux 호스트의 부팅과
Home Assistant Container의 동시 시작은 실제 환경에서 확인한다.

### ESPHome 전환과 순정 전체 복구의 읽기 전용 검증

`firmware/standalone/tools/check_esphome_transition.py`로 배포본 두
파일의 해시, ESP32-S3 앱 체크섬과 새 파티션 배치를 확인할 수 있다.
기존 순정 A/B와 기준 해시 및 M5Stack의 같은 릴리스에 속하는 factory·OTA
파일을 넣는다. 기존 순정 A/B와 두 배포본으로 이 도구를 실제 실행했다.

RAM에서 임시 이미지 쓰기 도중 중단, 새 NVS 쓰기, 전체 복구 도중
중단을 각각 모사했다. 두 배포본 모두 순정 16MiB 전체와 일치하도록
복구됐다. 기존 한 턴용 OTA1·NVS 복구와 초기 지움 범위만 복구하는
방식은 해당 모의 조건에서 불일치했다. 두 파일의 경로와 순정 사본의
내용은 보고서에 들어가지 않는다. 실제 복구와 앞면 STOP은 실물에서
확인되지 않았다. 펌웨어 쓰기, 로봇 연결, 서버 배포 및 유료 요청은
이번 검증에 포함하지 않았다.

## 2026-11-28 계측기 없이 검토한 상시 사용 경로

### 순정 펌웨어와 기존 GPT 연결을 상시 호스트에서 실행

기존 GPT 연결을 다른 상시 호스트에서 실행하면 Windows 노트북을
꺼도 된다. K151은 순정 호출어와 재생 경로를 그대로 사용한다. 공식
서비스가 음성을 인식하고 재생하며, GPT 연결은 전달받은 텍스트로 OpenAI
Responses API를 호출한다. 모든 질문의 GPT 호출을 보장하지는 않는다.
[기존 실물 GPT 연결](validation/2026-11-17-gpt-robot-reply-live.md) ·
[M5Stack 순정 음성 및 MCP 안내](https://docs.m5stack.com/en/StackChan/)

기존 `stackchan-pc-mcp --gpt --reconnect`는 터미널 입력이 없는 환경에서도
비공개 프로세스 환경의 `STACKCHAN_OFFICIAL_MCP_ENDPOINT`와 API 설정을
읽을 수 있다. 같은 호스트의 고정 절대 경로인 `STACKCHAN_STATE_PATH`와
같은 `STACKCHAN_BUDGET_NAMESPACE`를 사용하면 작업 폴더가 달라져도
SQLite 예약을 이어간다.
오프라인 회귀는 실행기를 두 번 시작하고 두 번째 실행의 한도 초과 질문이
OpenAI SDK의 모의 HTTP 전송부에 도달하지 않는 것을 확인했다.
MCP·GPT·복구 회귀 146개를 통과했다. 새 호스트는 연결하거나 배포하지 않았다.

### M5Stack ESPHome과 Home Assistant에서 OpenAI 음성 대화 실행

M5Stack이 공개한 K151 음성 펌웨어의 소스에는 `Hi StackChan` 모델,
본체 마이크·스피커와 Home Assistant Assist 연결, 재호출 시 대화 또는
안내음을 중단하는 분기가 있다. 앞면 터치 중단의 실물 동작은 미확인이다.
Home Assistant의 OpenAI 통합에서 음성 인식, 대화 에이전트, 음성 합성을
선택할 수 있다. 상시 Home Assistant 호스트가 필요하고, 이 프로젝트의
별도 유료 요청 한도는 그 통합에 자동으로 적용되지 않는다.
[M5Stack 공개 음성 설정](https://github.com/m5stack/esphome-yaml/blob/ef4542ab698daf3ceca1784afd5947a344733162/common/stackchan-voice-assistant-base.yaml) ·
[Home Assistant OpenAI 통합](https://www.home-assistant.io/integrations/openai_conversation/)

공개 배포본만 내려받아 GitHub의 SHA-256, ESP32-S3 앱 봉투, 파티션 표
체크섬을 확인했다. 각 `.ota.bin`은 같은 배포본의 `.factory.bin` 안
`0x10000`에 정확히 들어 있었다.

| 공개 배포 | factory 이미지 길이와 SHA-256 | 오프라인 모형에서 최초 쓰기 영향 범위 |
| --- | --- | --- |
| 2026.3.0 | 5,126,528바이트 · `25e16c82b0a239f3becf6bcc98e81790ff9168bf407651ca6c9d805c19bfbc53` | `[0x000000, 0x4E4000)` |
| 2026.11.0 사전 공개판 | 3,293,584바이트 · `a4488b77b9e75d740efcae6c7a50a59af90fe513089f9a53f110c4fd711c2924` | `[0x000000, 0x325000)` |

2026.3.0의 공개 파일은 릴리스 태그보다 늦게 첨부됐고 같은 태그에서
음성 설정 소스를 찾지 못했다. 그 배포본의 소스 재현과 실물 동작은
미검증이다.
[M5Stack 2026.3.0](https://github.com/m5stack/esphome-yaml/releases/tag/2026.3.0) ·
[M5Stack 2026.11.0](https://github.com/m5stack/esphome-yaml/releases/tag/2026.11.0)

두 배포본 모두 순정 부트로더 범위와 파티션 표, 순정 NVS·OTA 선택
데이터·PHY·OTA0를 덮는 범위다. 새 OTA 슬롯은 `0x10000` 및
`0x7D0000`, 새 NVS는 `0xF90000`에서 시작한다. 검증한 16MiB 순정
A/B 사본을 RAM에서 사용했다. 기존 한 턴용 OTA1·NVS 복구만 하면 파티션
표가 돌아오지 않았다. 새 NVS에 쓰는 경우를 모사하자 최초 쓰기 범위만
복구해도 전체가 일치하지 않았다. RAM에서 원본 전체를 복원하자 A/B
기준과 일치했다. 실제 ESPHome 시험 전에는 전체 순정 복구 범위와 쓰기
절차를 별도로 검토해야 한다.

### 순정 음성 서버 변경과 K151 단독 경로

고정 공개 Xiaozhi 소스에서 NVS의 OTA URL을 읽는 경로를 확인했다.
순정 A/B의 두 앱 영역에도 관련 문자열이 있었다. 이 문자열만으로
현재 순정 앱이 설정 변경을 지원하는지, 사설 음성 서버와 호환되는지는
확정할 수 없다. 이 경로를 적용하더라도 호환 음성 서버가 필요하다.
[고정 Xiaozhi의 OTA 설정 읽기](https://github.com/78/xiaozhi-esp32/blob/49b4380b3faa0ceadd28a3e78aaf0f311c46c57e/main/ota.cc#L56-L64)

추가 호스트 없이 K151이 직접 OpenAI를 호출하는 작업에는 기존 독립
펌웨어가 해당한다. 이번 작업은 다른 경로를 로컬에서 비교한 것이다.
독립 펌웨어의 설치 판정은 HOLD다. 로봇 접속·쓰기와 유료 호출은 0회다.

## 2026-11-28 기존 기록으로 상시 재생 조건 확인

기존 전원·스피커·STOP 진단 보고서 6개를 로컬에서 다시 확인했다.
두 프로젝트의 로컬 기록 폴더와 저장소 검증 자료에서 128KiB 이하의
관련 로그 후보 1,233개를 확인했다. 공통 계측 시간축 형식에 맞는 로그와
일반 계측기 원본 확장자의 파일은 이 범위에서 발견하지 못했다.

| 조건 | 기존 기록에서 확인한 사실 | 상시 재생에 필요한 근거 |
| --- | --- | --- |
| AXP2101 전원 | 대기 시 내부 ADC의 VSYS 4.443V. 별도 시작 진단에서 저전압 표시를 읽은 뒤 앰프 내부 ADC 표본 4.370V와 4.382V. | 기동·재생·정지 구간의 전원 레일과 저전압 표시 시점의 전압이 미확인이다. |
| AW9523 리셋 | 보드의 ID·방향·출력 레지스터를 읽었고, 리셋 해제 뒤 I²S를 시작하는 별도 이미지도 실행했다. | 실제 리셋 신호와 전원 레일의 순서가 미확인이다. |
| AW88298 음소거와 종료 | V13 합성음 종료에서 `dma_and_mute_observed`, `end=[2,0]`. 기기 내부 DMA 완료·레지스터·스위칭 종료·앰프 대기 확인이다. | 실제 앰프 출력이 음소거에 도달하는 시점과 독립적인 신호 대조가 미확인이다. |
| DMA·코덱 유휴 | V13 정상 종료에 DMA 완료가 기록됐다. 수정판 USB STOP에서 TX 유휴가 관측됐고 DMA 완료는 기록되지 않았다. | 정상 종료와 STOP 경로의 DMA 비움·코덱 유휴를 앰프 출력과 함께 독립적으로 대조할 근거가 없다. |
| 재생 도중 STOP | 수정판 USB STOP에서 PCM 6블록, 앰프 대기와 I²S TX 유휴 확인. 별도 앞면 시험에서 `DISPLAY_STOP_LATCHED` 확인. | 6블록은 60ms 분량의 PCM이다. 앞면 STOP 신호부터 실제 앰프 음소거까지의 지연은 미확인이다. |

과거 USB를 분리한 상태에서 GPT 답변과 대기 복귀를 확인한 한 턴 기록은
그 시험의 근거로 남긴다. 상시 모드와 통합 재부팅 시험은 각각의 전원·리셋·
음소거·STOP·DMA 조건을 적용한다. 관련 정책 회귀는 다른 조건을 충족한
상태에서 각 근거를 하나씩 비워도 거부되고, 한 턴 보고서를 넣어도 두 모드가
열리지 않음을 확인했다. 관련 Windows 오프라인 시험 270개가 통과했다.
임시 소스 사본에서 재부팅 모드의 독립 STOP 검사 또는 한 턴 근거의
모드 제한을 각각 무력화했을 때 새 회귀가 두 변경을 모두 검출했다.
실물 접속, 쓰기 및 유료 API 호출은 0회다.

[정확한 보드 조회](validation/2026-11-21-k151-board-readback-live.md) ·
[전원·스피커·USB STOP 기록](validation/2026-11-24-k151-speaker-live.md) ·
[앞면 STOP 기록](validation/2026-11-23-k151-panel-live.md) ·
[계측 로그 검증기](../firmware/standalone/docs/2026-11-19-bench-trace-audit.md)

## 2026-11-28 재부팅·연속 대화·STOP 통합 시험 준비

### 계측기 없이 확인할 수 있는 기능과 기존 기록

로봇 내부 기록과 스피커에서 실제로 들리는 소리를 함께 보면
합성음 재생과 앞면 터치로 재생이 멈추는 동작을 확인할 수 있다.
이 범위에는 다음 자료를 사용한다.

| 확인 항목 | 계측기 없이 확인 가능한 범위 | 기존 실물 기록 |
| --- | --- | --- |
| 전원과 리셋 | AXP2101 대기 전압, AW88298 VDD 표본·저전압 표시, AW9523 출력 래치의 상태를 읽는다. | 대기 전압과 후속 VDD 표본이 있다. 기동·재생·정지 중 전체 전원 파형과 물리 리셋 신호의 순서는 미확인이다. |
| 음소거와 정리 | 앰프 음소거·대기 레지스터, 스위칭 종료, TX 유휴를 읽는다. 사용자가 합성음이 끊기는 것을 귀로 확인할 수 있다. 별도 동의가 있으면 노트북 내장 마이크도 가청 출력 확인에 쓸 수 있다. | V13 정상 종료에서 스위칭 종료와 대기를 관찰했다. 수정판 USB STOP은 PCM 전송 중 대기와 TX 유휴를 확인했다. 스피커 단자의 전기 신호와 음소거 시점은 미확인이다. |
| 앞면 STOP | 첫 PCM 전송 이후 앞면 입력을 한 번 받아 STOP 래치, PCM 중단, 앰프 대기·TX 유휴를 같은 시험에서 대조한다. | 화면 전용 시험에서 앞면 래치를 확인했다. 가청 재생을 확인한 V2 화면 시험은 `cleanup_failed`였고, 성공한 자동 시험의 입력은 USB STOP이었다. |

앞면 입력 시간은 펌웨어가 GPIO를 읽어 STOP을 감지한 시각이다.
현재 구현은 10ms 주기의 ESP Timer 작업을 사용하며, 작업 지연으로
실제 입력과 표본 시각이 벌어질 수 있다. 대기나 대체 리셋까지의
기기 내부 시간과 가청 출력 확인은 상시 재생에 필요한 물리 전원 파형과
전기적 STOP→음소거 실측을 대신할 수 없다.
[AW88298 상태 비트와 전압 ADC](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/k127%20CM4STACK/AW88298.pdf#page=31) ·
[ESP Timer 작업 지연](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/api-reference/system/esp_timer.html#significant-delays-while-dispatching-callbacks) ·
[스피커 실물 기록](validation/2026-11-24-k151-speaker-live.md) ·
[앞면 STOP 실물 기록](validation/2026-11-23-k151-panel-live.md)

호스트 수신기는 재생 안내가 늦거나 없는 경우와 자동 USB STOP이
겹친 경우 앞면 STOP의 대기·대체 리셋 시간 보고를 거부한다. 성공한
대기 시간에 정리 실패 단계가 함께 기록돼도 거부한다. 실제 계측
검증기, 펌웨어의 출력 차단 조건, 기존 보드 및 복구 정책을 유지한다.
기존 결과 다섯 건을 다시 대조했다. 합성 USB·로그 검증 154개와
호스트 코덱·음소거·운영 정책 검증 343개를 통과했다.

### 앞면 터치 한 번으로 합성음 중단 확인

별도 승인 후 기존 V3 합성음 진단을 수동 앞면 모드로 한 번 실행한다.
진단은 24kHz 합성음을 최대 2.5초 재생한다. 안내 창은 첫 PCM 전송
신호를 받으면 터치 문구를 한 번 표시하고, 결과를 받거나 수신을 중단하면
터치 구간을 닫는다.

1. **터치 안내가 뜨고 삐 소리가 들리면** 로봇 앞면 화면을 가볍게 한 번
   터치한다. 둘 중 하나라도 없거나 소리가 이미 끝났으면 그대로 둔다.
2. USB는 연결해 둔다. 시험 결과와 관계없이 실행기는 원본 OTA1을 복구하고
   독립 검증과 재부팅 요청을 마친다. 안내 창을 닫아도 복구는 계속된다.
3. 순정 화면이 돌아온 뒤, 터치 직후 소리가 끊겼는지만 확인한다.
   실행기는 듣기 결과를 해당 시험에 한 번만 기록한다. 합성음을 듣는
   과정에서는 마이크·녹음·Wi-Fi·유료 API를 사용하지 않는다.

기능 확인은 같은 수동 시험에서 앞면 STOP, 합성음 버퍼 전송 중단, 앰프
대기·TX 유휴와 사용자가 들은 소리 중단이 모두 맞을 때 성립한다.
자동 USB STOP, 톤을 끝까지 전송한 경우, 소리를 못 들었거나 자연 종료와
구분이 어려운 경우에는 성공으로 판정하지 않는다. 기기 내부 시간은
GPIO 표본부터 대기 확인까지이며 전기적 음소거 지연은 별도 항목으로 남는다.

기존 V3 이미지의 OTA1 쓰기 시작점은 `0x510000`, 이미지 길이는
589,664바이트다. 플래시 섹터 작업 범위는 `[0x510000, 0x5A0000)`이다.
복구할 때는 원본 OTA1의 `[0x510000, 0xA00000)` 5,177,344바이트를
되돌린다. NVS와 OTA 선택 정보는 이 시험의 쓰기 범위 밖이다.

### 설치 보류와 통합 시험 절차

현재 판정은 **통합 실물 시험 설치 보류**다. 같은 기기에서 한 턴을
확인한 재생 및 STOP 기록은 한 턴 정책에 묶여 있다. 현재 연속 대화
정책은 전원 레일, 리셋 순서, 앰프 음소거, STOP 지연과 DMA·코덱 유휴
근거를 확인해야 시작한다. 계측기 없이 직접 듣고 화면을 보는 단계는
기능 확인에 사용하며, 해당 근거를 대신하지 않는다.

한 번의 임시 설치로 확인할 순서는 아래와 같다.

1. 로봇에 설정을 암호화해 저장한다. 기존 시험에서 NVS를 복구했으므로
   이번에는 재부팅 전에 합의한 짧은 질문으로 비어 있지 않은 예산
   기록을 만든다. 예약이 확인된 시점의 기록을 기준으로 잡는다.
2. 전원을 껐다 켠 뒤 USB 없이 로봇에서 잠금을 해제한다. 새 요청 전
   앞 단계의 예산이 그대로 로드되고 다시 초기화되지 않았음을
   확인한다. 검토용 기록은 일치 여부만 남긴다. 기록을 읽을 수
   없으면 네트워크를 시작하지 않는다.
3. 화면의 유료 대화 동의를 거쳐 첫 응답을 끝까지 듣고 호출어 대기로
   돌아오는 것을 확인한다. 두 번째 답변이 나오는 동안 앞면을 한
   번 터치한다. 재생이 멈추고 새 요청 없이 종료 상태가 유지되어야
   한다. 같은 60초 구간에 세 예약이 겹치지 않도록 기존 분당 제한을
   적용한다.
4. 성공, 중단, 시간 초과 모두 같은 복구 절차를 쓴다. 같은 보드와
   파티션 표·OTA 데이터를 다시 확인하고 OTA1 원본과 **그 시험 직전**
   NVS를 차례로 복원한다. 각 범위를 독립 검증하고 표·OTA 데이터를
   다시 대조한 뒤 순정 부팅과 얼굴 화면을 확인한다. 복구 검증 실패
   때는 완료 처리나 재시험 없이 해당 복구 단계에 머문다.

검토 범위는 재부팅 전 한 턴과 뒤 두 턴이다. 한 턴당 질문 음성
최대 8초를 STT로 보내고, 전사 텍스트를 GPT로, 답변 텍스트를 TTS로
보낸다. 최대 세 턴·아홉 요청 단계이며 중간 STOP 뒤에는 호출을
재개하지 않는다. 기존 한 턴 실행기의 승인은 사용 범위가 다르다.

통합 시험의 예산 가드는 기존 예산과 시험 ID·단계·누적 횟수를
같은 NVS 레코드에 저장하도록 구현했다. 첫 부팅은 검토한 기존
예산 또는 별도로 승인한 최초 생성을 거쳐 한 턴을 갖는다.
재부팅은 첫 응답 뒤 대기 복귀가 확인되고 검토한 예산이 일치할
때 한 번만 다음 단계를 연다. 두 번째 부팅의 시작도 새 요청 전에
저장·재읽기한다. 저장 결과 불확실, 기록 누락·손상, 잘못된 시험 ID,
예정 밖 재부팅은 새 유료 요청을 막는다. 소비한 횟수는 롤링
예산 창이 지나도 초기화되지 않는다.

통합 시험 모드는 첫 설정에서 한 턴을 화면으로 승인받는다. 첫 답변
뒤 대기 복귀를 확인하고 마이크·스피커·모델·네트워크를 닫는다.
STOP 감시를 유지한 채 시험 ID와 당시 예산을 `sc_gpt/trial_ckpt`에
별도로 저장·재확인하고 재부팅 안내를 표시한다. 화면 표시가 실패하거나
그때 STOP이 들어오면 다음 부팅을 열지 않는다.

다음 부팅은 저장한 설정을 잠금 해제하고, 앞의 안내를 본 사람이
화면에서 두 턴을 새로 승인하는 절차다. 별도 저장한 예산과 현재
시험 예산을 바이트 단위로 비교한다. 권한을 다시 저장·검증하고
화면에 예산 확인을 표시한 다음 네트워크를 시작한다. 과거 한 턴
기록은 이 모드의 연속 재생 조건을 충족시키지 않는다.

로컬 통합 검토는 `check_conversation_image.py --local-reboot-trial`에서 한다.
핀 고정 ESP-IDF 체크아웃(`--idf-dir`)과 시험 직전 NVS로 예산 기준을 분석하고,
앱·ELF·소스 버전·복구 범위와 함께 하나의 매니페스트에 기록한다. 이전 시험의
재부팅 체크포인트 또는 잠금 설정이 남아 있으면 설치 전 검토를 중단한다. 통합 이미지
표시와 복구용 A/B 원본, 원본 OTA1, 시험 직전 NVS가 모두 필요하다. 검토 결과는
설치나 복구를 승인하지 않는다.

통합 실행기는 `paid_trial_operator.py --execute --reboot-trial`을 사용한다.
같은 로컬 폴더의 `approval.json`에 `review_sha256`과 `board_reference_sha256`,
`install_and_restore_ota1`과 `restore_nvs`에 대한 승인, `reboot_trial_paid_turns`의
`before_reboot: 1`과 `after_reboot: 2`가 필요하다. `create_initial_budget`는
기준 예산이 누락일 때 `true`로 명시적으로 승인하고, 기존 예산이 있으면
`false`로 기록한다. 설정 저장은 `sc_owner/owner_cfg_v2`, 예산 갱신은 `sc_gpt/budget`과
`sc_gpt/trial_ckpt`에 해당한다. 도구는 기존 한 턴 승인과 공개·한 턴·상시 운영
이미지를 통합 시험에서 거부한다.

USB를 분리한 동안 사람이 로봇의 안내와 답변, 대기 복귀, STOP을 확인한다.
첫 응답 확인 뒤 전원을 껐다 켜고, 실행기가 최소 60초 뒤 화면 잠금 해제를
안내한다. 이는 기존 분당 예약 제한을 적용하기 위한 대기다. 설정 암호와
질문·답변은 실행기의 결과에 기록하지 않는다. 소프트웨어는 예산 비교를 통과한
뒤에만 재부팅 후 대기 화면으로 진행한다.

USB 조기 재연결, 시험 실패 또는 시간 초과에도 같은 복구를 시도한다.
같은 USB 포트·보드가 돌아오지 않으면 쓰기 없이 중단하고 복구 기록을 남긴다.
그 경우 기존 파일과 승인으로 `--recover --reboot-trial`을 사용해 복구만 이어갈
수 있다. 실행기는 검증 후 순정 부팅 요청까지 확인한다. 순정 얼굴 화면 복귀는
로봇 화면에서 확인한다.

기존 A/B와 한 턴 시험 직전 사본을 읽기 전용으로 검증했다.
`f275cdf` 검토 이미지 1,919,120바이트를 RAM의
`[0x510000, 0x6E4890)`에 배치했으며 지움 범위 끝은
`0x6E5000`이다. 설치 중단, 실행 중 NVS 변경, OTA1 복구 중단,
NVS 복구 중단 네 상황에서 OTA1 `[0x510000, 0xA00000)`과 NVS
`[0x9000, 0xD000)`를 복원해 기준 전체 이미지와 대조했다.
현재 실물의 설치 전 상태는 승인된 준비 단계에서 별도로 확인한다.
[원본 백업과 복구 근거](K151_BACKUP_RECOVERY.ko.md)

호스트에서 재부팅 기준 예산의 바이트가 첫 요청 전까지 그대로이고,
두 번째 답변의 재생 중 STOP 뒤에도 예약 세 건을 유지하는 것을 확인했다.
STOP 뒤에는 새 요청이나 새 예산 쓰기가 없었다. 설정, 대화, 유료 한 턴
실행기의 승인·복구 관련 오프라인 시험 235개를 통과했다.

최신 [오디오 I/O 코드 보강](K151_AUDIO_IO.ko.md)은 오프라인 작업이다. PCM 짧은
대기·exact count·반환 후 시간 검사와 지움을 추가했으며, 새 실물 설치/음성/API
승인 요청용 운영 이미지가 아니다. 운영 HOLD와 전원/mute/STOP 제약을 유지한다.

후속 [보드 readback](K151_BOARD_READBACK.ko.md)은 사용자 승인 뒤1회 실행·완료했다.
원본 slot1 복구·독립 verify·표/OTA 일치와 사용자 얼굴/메뉴 복귀를 확인했다.
[최신 실물 범위·증거](validation/2026-11-21-k151-board-readback-live.md)를 우선한다.
운영 앱 HOLD를 유지하며, 아래 준비·미승인 문구는 그 이전 단계의 이력이다.

2026-11-21 승인 후속: **운영 앱의 HOLD는 유지**한다. 별도 검토한 무음 진단 앱만
1회 임시 설치해 실물 모델 추론/동시 PCM 배치를 확인한 뒤 원본slot1을 복구했다.
장치의 독립 verify와 표/OTA 전후 일치가 PASS이며, 뒤의 보드 조회 승인 전 사용자가
이 모델 진단 복구 뒤 화면 복귀도 확인했다.
[실물 이미지·쓰기/복구 범위·실측](validation/2026-11-21-k151-silent-resource-bench.md)을 우선한다.
아래의 미설치/복구 미실행 문구는 그 전 준비 단계의 이력이다. 전체16MB 복구와
실제 호출어/질문/TLS/재생/STOP/독립 GPT 및 운영 readiness는 여전히 미검증이다.

2026-11-20 Windows 인수. **현재 설치 패키지는 HOLD이며 쓰기 승인 요청 단계가 아니다.**
같은 `feat/wakeword-josu` / PR #3에서 기존 모듈을 연결한다. 원본/개인 프로필/키는
배포하지 않는다. [인수 검증](validation/2026-11-20-windows-handoff.md)을 함께 본다.

사용자 재연결 후 현재COM3/S3/16MB/보호 OFF와 표/OTA12KiB의 원본 일치를 확인했다.
장치의 readonly DATA model partition 전체 SHA를 사용하는 `prepare_local`도 휴면
연결했다. [후속 조회·코드 검증](validation/2026-11-20-k151-current-usb-and-assets.md)을 따른다.
현재 원본 표에는 model partition이 없으며 새 펌웨어/모델을 쓰지 않았다.

## 준비한 자산과 배치 제약

공개 ESP-SR commit `2f8c4b0459db5bbb39abd77adae27962d6d94bcb`의 모델 파일 3개를
로컬에 공급하고 각각의 고정 SHA256, 길이, pack header/offset, 최종 SHA를 검증했다.
`prepare_wakenet_assets.py`는 로컬 파일만 읽고 출력은 새 파일로만 생성한다.

| 자산 | 길이 | SHA256 |
|---|---:|---|
| wn9l_histackchan_tts3 model pack | 292607 | `0255855e56bf72d1e072d2e0cbee4fb3ce1ac2c48f7fee6c8cd591f83e59ed95` |
| 원본 factory-a.bin / factory-b.bin 각각 | 16777216 | `c1241a7c87145ee8b9569cfbcfbb1f8c289641856f9b9b5ddf2ccd565019543e` |

모델 pack의 로컬 준비는 **장치 partition의 무결성 검증이 아니다.**
K151WakeNetPort::prepare의 owner/assets_verified 입력에 이 사실을 대신 넣지 않는다.
운영 bootstrap은 실제 로컬 소유자 동의, 장치에서 읽은 model partition SHA,
동적 메모리 증거를 각각 공급해야 한다. SDK global loader는 다른 직접 사용자가
없어야 하며 한 live adapter만 소유한다. 정확한 model/mode/rate/chunk 검사는 유지한다.

휴면 `prepare_local(owner,stop)`은 draft0xF00000/1MiB의 main-flash·DATA·model·readonly·
unencrypted를 확인한 뒤 IDF 전체 파티션 SHA를 비교한다. pack 뒤0xff padding을 포함한
SHA는 `1d04bf6a1f6775d43ab4398bbbac1bc4606f5c4130fe1a853851ec5df7f21d1b`다.
검증 실패는 같은 객체의 legacy bool 진입으로도 우회할 수 없다. 로컬 소유자 UI 및
실제 메모리 admission은 여전히 필요하며 실제 SHA 호출은 장치에서 실행하지 않았다.

원본 파티션 표는 다음과 같이 재검증했다. **변경된 offset/길이는 모두 0**이다.

| 영역 | 시작 offset | 길이 bytes |
|---|---|---:|
| partition table | 0x8000 | 4096 (table sector) |
| nvs | 0x9000 | 16384 |
| otadata | 0xD000 | 8192 |
| phy_init | 0xF000 | 4096 |
| ota_0 | 0x20000 | 5177344 |
| ota_1 | 0x510000 | 5177344 |
| assets | 0xA00000 | 4194304 |
| coredump | 0xE00000 | 65536 |

전용 model 영역 후보는 `0xF00000..0xFFFFFF`(1048576bytes)다. 원본 표의 영역과
겹치지 않고 **검증한 과거 백업에서만** 전부 0xFF임을 확인했다. 실제 현재 빈 공간,
제조사 hardcoded 사용 여부, write safety를 입증하지 않는다. 이를 사용하려면
새 partition table과 그에 맞는 app의 별도 검증/승인이 필요하다. 현재 sdkconfig의
IDF 기본 표나 flash 예제는 실물에 적용할 수 없다. 후보 CSV/bin은 설치 파일로 발행하지 않는다.

원본 otadata는 seq1/seq2 모두 VALID·CRC 정상으로, 고정 IDF의 rollback ON/OFF
두 해석 모두 `ota_1`을 선택 후보로 가리킨다. seq_label은 출력하지 않았다.
현재 실행 슬롯은 제조사 bootloader 설정·이미지 검증/fallback·이후 업데이트의
영향을 받을 수 있다. **ota_1은 빈 슬롯이 아니며 어느 쪽도 안전한 spare로 승인하지 않는다.**

## 운영 연결과 남은 증거

`NativeVoiceLoop`는 이미 준비된 model/audio와 기존 NativeWakeController,
VoiceTurnCoordinator를 단일 owner task에서 직렬로 연결한다. wake mic를 종료한 새
epoch만 질문으로 넘기고, 재생 뒤 cooldown에서 새 wake capture로 돌아간다.
cloud enable을 호출하지 않으며 STOP/동의 철회/readiness 상실/오류는 종료 latch다.
app_main은 이를 생성하지 않고 기존 HOLD를 유지한다.

확장 메모리 admission은 실제 model이 살아 있는 동안의 capability별 free/largest
block, 실제 PCM allocator의 PSRAM 배치, 질문+TLS/JSON+TTS의 동시 peak를 요구한다.
model flash bytes나 HOLD 앱의 정적 크기로 model RAM을 추정하지 않는다. 실제 값은
아직 없으므로 장치 admission은 미충족이다. 큰 snapshot flag를 외부에서 임의로
설정하는 경로는 추가하지 않았다. 모델 이후 free에서 내부32KiB/PSRAM128KiB 여유와
기존 보수적 PCM 예산을 모두 확인하며 이 정책 자체는 실측/설치 승인 증거가 아니다.

실물 전 남은 작업은 장치 model partition 공급/읽기 SHA 검증, allocator 배치와
model/TLS 동시 실측, 독립 STOP-to-mute·전원/reset·TX DMA drain 관측, 실제 K151
mic timing과 추론 chunk/지연이다. 현재 codec의 output enable과 drain은 여전히
hard HOLD다. 100ms/chunk160..2048을 실물 근거 없이 완화하지 않는다.

## 원본 복구 명령 초안 (미실행)

복구 범위는 같은 기기의 전체 `[0x0,0x1000000)`다. bootloader/partition/NVS/
OTA 앱/assets/coredump를 과거 백업 상태로 되돌리므로 이후 설정/계정 변경도
되돌아갈 수 있다. eFuse·서보 controller·서버 데이터는 복구하지 않는다.
다른 저장장치 사본과 실제 복구 쓰기는 아직 미검증이다.

실제 복구가 승인된 경우에만, 재조회한 VID303A/PID1001 포트·같은 칩/용량·보호 상태와
두 백업 SHA를 확인하고 다른 GPT/serial 프로그램을 종료한 뒤 사용할 명령 형태다.
`COM_CONFIRMED`는 현재 검증한 실제 포트로 바꾸기 전에는 실행할 수 없는 자리표시자다.
esptool 5.6.0의 아래 옵션은 **로컬 --help만** 조회해 확인했다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" tool run --from esptool==5.6.0 esptool --chip esp32s3 --port COM_CONFIRMED --before no-reset --after no-reset --no-stub --connect-attempts 1 write-flash --flash-mode keep --flash-freq keep --flash-size keep 0x0 "%USERPROFILE%\stackchan-soak-24h\.local\device-backup\k151-original-20261118-01\factory-a.bin"
```

ROM Download Mode와 조회를 먼저 확인해야 한다. 포트를 여는 동작은 PnP 조회와 다르다.
기본 verify-flash는 차이 내용을 표시하는 `--diff`를 사용하지 않는다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" tool run --from esptool==5.6.0 esptool --chip esp32s3 --port COM_CONFIRMED --before no-reset --after no-reset --no-stub --connect-attempts 1 verify-flash --flash-mode keep --flash-freq keep --flash-size keep 0x0 "%USERPROFILE%\stackchan-soak-24h\.local\device-backup\k151-original-20261118-01\factory-a.bin"
```

포트/칩/보호/해시 불명, 연결·write·verify 실패, brownout, 출력 불확실이면 중단한다.
자동 재시도·erase-all·force·보호 우회·eFuse 조작을 사용하지 않는다. 검증 뒤에만
정상 부팅/기존 기능 복귀를 별도로 확인한다. 복구 성공을 현재 확인한 것으로 기록하지 않는다.
새 펌웨어 설치 명령은 운영 이미지·SHA·정확한 변경 sector 영향과 복구 조건까지
확정한 manifest를 만든 뒤 실제 쓰기 승인을 요청할 때 제시한다.

## 실제 API 한 턴 시험 준비 범위

현재 cloud OFF, 실제 요청 0이다. 별도 승인 시 전송할 범위는 새 질문만 최대8초
24kHz mono PCM16(384000bytes + WAV/multipart), STT 전사 최대500자, GPT 답변 최대300자,
TTS 요청은 그 답변, 수신 재생 PCM은 최대20초/960000bytes다. 호출어 음성·개인 등록
특징·이미지·원본 flash는 이 요청에 포함하지 않는다. 새 실음성 파일 저장도 별도 승인 대상이다.

한 턴은 STT/GPT/TTS 각 최대1회, 총3개 유료 요청을 저장 예산에 선차감한다. 일부
실패도 이미 발생한 비용을 환불로 처리하지 않고 자동 재전송하지 않는다. 실제 모델/계정은
아직 선택·승인되지 않았으므로 금액 상한은 미정이다. 시험 전 정확한 3모델/voice,
당시 공식 분당/입출력 token 또는 문자 요율, GPT token 상한 및 1턴 비용 상한을 계산해
전송 범위와 함께 제시해야 한다. 이 자료만으로 유료 시험을 승인한 것으로 취급하지 않는다.
