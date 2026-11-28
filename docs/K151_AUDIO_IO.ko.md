# K151 오디오 전송 보강 — 운영 HOLD 유지

2026-11-21. [보드 조회·원본 복구](validation/2026-11-21-k151-board-readback-live.md)와
사용자의 출고 화면 복귀 확인 뒤 진행한 **코드·오프라인 작업**이다. 이번 단계에서
장치를 열거나 리셋/설치/녹음/유료 API를 실행하지 않았다. 기존 한국어 개인 등록과
100ms 입력 간격·160..2048 chunk 조건도 변경하지 않았다.

기존 K151CodecPort/질문 bridge/재생 sink를 유지한다. 코덱 SDK의 clock/slot 설정,
enable/close와 esp_codec_dev read/write를 통한 볼륨 처리를 재사용하고, PCM data
콜백만 작은 비소유 어댑터로 바꿨다. 새 운영 시스템이나 호출어 경로를 만들지 않았다.

## 실제로 막는 조건

| 조건 | 새 동작 |
|---|---|
| 기본 SDK PCM1000ms 대기 | 한 번의 IDF read/write에20ms wait 전달 |
| 성공 반환이지만 short/over byte count | 즉시 실패, 재시도·부족분 silence 성공 없음 |
| 음수 clock·역행·호출 뒤40ms 초과 | 실패 latch, 늦은 수신 PCM 폐기 |
| 잘못된 rate/bit/channel/mask·duplex·활성 중 format 변경 | SDK 설정 전에 거부 |
| SDK가 set_fmt/enable 오류를 무시하고 open OK 반환 | 어댑터 상태를 독립 검사하고 오류 종료 |
| 실패 후 재개·같은 port 재사용 | fault 보존, teardown 뒤에도 자동 재시작 없음 |
| 준비 전·잘못된 크기·부분 수신·오류 | 호출자 mono와 소유 수신 버퍼를 volatile store로 지움 |
| 함수 종료의 로컬 frame/재생 사본 | RAII volatile wipe; caller-owned const 재생 원본은 유지 |
| SDK close가 이미 raw I2S를 disable | 실제 channel.is_enabled 조회로 중복 disable 회피 |
| 채널 상태 조회 실패 | best-effort disable 후에도 불확실성/fault 보존 |

40ms는 **반환 후 검사**다. IDF는 내부 lock/queue에서 여러 번 기다리거나 OS가
task를 지연시킬 수 있으며 이 코드는 진행 중인 호출을 강제 선점하지 않는다.
20ms 요청과40ms 거부 조건을 물리 STOP 지연 보장으로 보고하지 않는다. 기존100ms
wake 프로토콜 검사도 그대로 남는다. 코덱 open/close·gain·I2C 설정은 이 PCM
시간 범위 밖의 동기 호출이며 실제 전원/mute/drain 증거가 필요하다.

SDK open이 데이터 설정 오류 뒤에도 코덱 설정을 일부 실행할 수 있어 input_open을
호출 전에 추적하고 실패 뒤 독립 close를 시도한다. 후속 비소유 control observer는
SDK가 버리는 register read/write/get_info 오류도 별도로 latch한다. 실제 microphone
활성화 전 전기적 조건과 제어 지연은 여전히 검증해야 한다. data disabled나 register
성공은 논리 상태이며 analog mute의 증거가 아니다.

## 소유권과 준비 상태

포트가 기존 SDK base data interface와 I2S handles를 소유한다. 어댑터는 빌려 쓰며,
모든 설정 callback을 **원래 base pointer**로 전달한다. codec device 삭제 뒤 어댑터를
분리하고 base를 단 한 번 해제한다. 어댑터 자체를 SDK free 함수에 넘기지 않는다.
콜백 재진입은 기다리지 않고 거부한다. 전체 port 생성/사용/종료는 한 owner task에
한정하며 다른 task의 동시 파괴를 지원한다고 주장하지 않는다.

HOLD app_main은 포트를 생성·prepare하지 않는다. speaker_on의 두 false 상수와
drain=false를 유지한다. 과거 보드 설정값·모델 heap 수치로 owner/assets/power/
readiness를 true로 만들지 않는다. 이번 코드의 target 빌드는 실물 음성 성공이 아니다.

## ES7210 마이크 단독 준비

`prepare_microphone_only`는 수명 동안 유효한 로컬 소유자 동의와 STOP 상태를
받는다. 현재 보드 식별, 마이크 전원·클록 핀, 입력 클록 중 앰프 격리,
I2S0 독점 소유도 각각 확인돼야 한다. 보드 조회에서 얻은 레지스터값만으로는
이 조건을 채울 수 없다.

I2S RX만 예약하고 짝 채널과 활성 상태를 확인한 뒤 핀을 설정한다. 포트는
24kHz PCM16, 2슬롯 TDM으로 초기화하고 ES7210에 기존의 bounded read
인터페이스를 넘긴다. SDK I2S data factory가 같은 포트의 TX를 찾는 경로를
거치지 않으며, 이 경로에서 AW88298이나 TX를 할당하지 않는다. MCLK는
GPIO0과 공유되므로 핀 설정 전에 전기적 조건을 확인해야 한다.

동의 철회나 STOP을 관측한 호출은 PCM을 지우고 포트를 fault 상태로 전환한
뒤 해제를 시도한다. 닫기 오류에서도 raw RX 상태를 확인한다. 해제 실패
후 입력 요청은 하드웨어를 다시 건드리지 않으며, 보존한 I2S handle은
명시적 종료에서 정리할 수 있다. 실제 driver 호출의 선점 지연, FIFO 초기화
및 마이크 채널은 현장에서 검증해야 한다.
[마이크 단독 검증](validation/2026-11-21-k151-microphone-only.md)

## 코덱 제어 오류 후속

K151CodecControl은 SDK I2C 객체를 빌려 원래 pointer와 register 인자를 그대로
전달한다. SDK ES7210의 update_reg_bit는 read 오류를 버리고, 상위 gain/close는
일부 codec 반환값을 버린다. 따라서 초기화/open/gain/close 뒤 독립 observer를
검사한다. 해제 중 생긴 오류도 shutdown 실패로 남고, 이후 성공 호출·detach가
fault를 지우지 않는다. 오류 뒤 cleanup 전달은 허용하지만 재시작은 차단한다.
codec/device를 먼저 삭제하고 observer를 분리한 뒤 원래 control만 해제한다.

null data handle은 false/INVALID_ARG로 거부한다. 이때 유효한 제한 크기의 read
버퍼는 volatile wipe하고 caller-owned write 원본은 유지한다. I2S 상태 조회 실패
주입 시험은 best-effort disable이 성공해도 shutdown/fault가 실패 상태임을 확인한다.
고정 SDK의 수정하지 않은 ES7210 C도 별도 host fixture로 실행해 실제 read 오류
누락과 observer의 감지를 대조한다. [후속 검증](validation/2026-11-21-k151-codec-control.md).

## 드라이버 해제 실패 후 소유권

raw RX/TX 삭제가 실패하면 포트가 I2S handle을 보존한다. 이후 명시적 shutdown이
해당 채널만 한 번씩 정리할 수 있고, 이미 해제한 채널/SDK 객체는 다시 만지지 않는다.
자동 반복·재시작은 없으며 나중에 정리돼도 원래 fault와 false 결과는 유지한다.
destructor의 마지막 best-effort도 실패할 수 있어 완전한 자원 회수를 보장하지 않는다.

I2C bus는 동일하게 처리할 수 없다. 고정 IDF의
[bus destroy](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2c/i2c_master.c#L841)는
해제 전 interrupt 정리 실패와 **해제 후** pin 정리 오류를 모두 반환할 수 있다.
삭제 오류 뒤 이 pointer는 재접근하지 않고 fault만 보존한다. 아직 살아 있는 bus의
회수 성공이나 물리 mute를 주장하지 않는다. 반면
[I2S delete](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/i2s_common.c#L1237)는
실패를 free 전에 반환하므로 실패한 채널 handle의 보존이 가능하다. 이는 고정 버전의
소유권 계약이며 SDK 버전을 바꾸면 다시 확인해야 한다.

AW88298 host double은2바이트 register 값을 검사한다. 임시 source 사본에서 read나
write 길이를1로 잘라 실제 포트 시험이 실패하는 negative control도 실행한다.
원문 SDK와 운영 출력 false는 바꾸지 않았다.
[해제 후속 기록](validation/2026-11-21-k151-codec-release.md).

## 재현·검증 근거

기존 실제 포트를 pinned codec1.6.2 헤더와 IDF C ABI double로 컴파일해1000ms
대기 전달을 재현했다. 설정 오류를 무시하는 SDK open, 이미 닫힌 채널의 중복
disable, reader 거부 뒤 남은 PCM도 실패 시험으로 확인한 뒤 수정했다.
실제 read/write·정확한 count·단조 clock·오류 latch·setup/cleanup을 시험한다.
host double은 실제 DMA/clock 배선·SDK 내부 lock 지연을 측정하지 않는다.

최적화-O2 assembly에서 수명이 끝난 PCM의 zero store가 남는지 검사한다.
일반 std::fill destructor로 바꾼 negative control은 실제로 지움이 사라지고,
volatile RAII와 invalid-frame 거부 지움은 남는다. SDK/DMA 내부 복사본이나 CPU
register의 완전 소거를 주장하지 않는다.

고정 SDK 헤더·LICENSE는 테스트 fixture에 원문 그대로 두고 파일 SHA를 검사한다.
[SDK1.6.2 기본 I2S 구현](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/platform/audio_codec_data_i2s.c)과
[codec open/read/write/close](https://github.com/espressif/esp-adf/blob/af7b72fb2b73d4f513d3cede01c13518ab216735/components/esp_codec_dev/esp_codec_dev.c)를 감사했다.
IDF의 [고정 I2S API](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/include/driver/i2s_common.h)와
[드라이버 구현](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/i2s_common.c)도 대조했다.
최종 suite·실제 target/CI 결과는 후속 검증 기록으로 추가한다.

## 관련 Windows 계측 시험 수정

직전 문서cd06769 CI는8/9였다. PR Windows3.11 job136672698831가
`test_shared_executor_queue_is_distinct_from_operation`의0.0261449>=0.03에서
실패했다 (root494PASS/1FAIL/2SKIP182.51s, virtual soak 전).
40ms timeout이 계측 시작 후30ms 대기를 보장하지 않는다. timeout을 건 뒤 trace가
시작되기 전35ms의 유한 지연을 주어 serial/executor 두 시험을 로컬에서 실패시켰다.

timeout40ms·TimeoutError·실제 lock/pool·취소·drain·operation count 검사는 유지한다.
trace 구간 안에 있는 별도 실측 timestamp로 양의 대기 구간을 구하고, 기록된 계측
구간이 이를 포함하는지 검사한다. 임의 최소값을 낮추거나 실제 시간을 가짜로
바꾸지 않는다. 같은35ms 재현 조건에서2PASS, 전체 계측 모듈8PASS였다.
실제 CI stall의 물리 I/O/worker 비실행 시간 원인이 해결된 증거는 아니다.
runtime/lease/deadline/SQLite 내구성·검사와 실패 CI 재실행은 변경하지 않았다.

독립 검토 Important인 Windows autocrlf fixture 변환은 임시 Git checkout에서
실패를 재현한 뒤-text로 차단했다. 원본 헤더/license byte SHA가 Windows checkout
후에도 일치한다. Minor인 null interface handle 방어와 get_info 실패 주입 fixture는
후속이다. 정상 pinned SDK 경로는 live interface pointer를 공급하며, 실제 상태 조회
실패 시 코드가 fault를 보존하도록 구현됐지만 그 분기 회귀 시험은 아직 없다.

최종 로컬 전체 검증은 root495PASS2SKIP115.99s, 선택 의존성을 포함한
standalone586PASS5SKIP113.43s다. 최적화/assertions ON 컴파일러와 Git checkout
회귀를 포함한다. Ruff/format356files와 자체 작성 파일의 diff 검사를 통과했다.
원문 SDK audio_codec_if.h의 trailing space는 archive SHA 보존을 위해 유지한다.
staging 뒤 확인한 이 원문 공백과 생성 provenance JSON의 CRLF를 전체 diff PASS로
표현하지 않는다. 생성 JSON만 LF로 정리했고 원문 SDK는 변경하지 않았다. 실제 S3 target과
현재 commit의 CI 결과는 별도로 확인하며 이 로컬 통과로 green을 선언하지 않는다.

후속: 초기5cd310f CI는 **4/9**였다. 실제 S3 세 앱은 PASS였고, Linux4개는
위 최적화 검증기가 literal0 store만 인식해 각2FAIL/548PASS/41SKIP였다.
GCC의 zeroed-register store도 확인하도록 별칭/zero-bit 추적을 추가했고 nonzero·
덮어쓴·무관한·부분 byte register를 거부하는 회귀를 유지했다. 보강 뒤 로컬
standalone **592PASS5SKIP90.79s**, 최적화 집중9PASS다. GNU 실제 CI는 후속에서
확인한다. [검증 기록](validation/2026-11-21-k151-bounded-audio-io.md)을 함께 본다.
PR Windows3.11은 별도0.1초 시험 lease의 acquire_timeout으로 주입한 check 전에
실패했다. 해당 기대값을 넓히거나 TTL을 늘리지 않았으며 원인 미확정으로 보존한다.

## 출력 준비 — GPIO에 연결하지 않는 I2S 송신 진단

2026-11-22. 질문 전용 실물 시험에서 발화 종료를 확인한 뒤 스피커
출력 준비로 진행했다. 새 `k151_silent_tx_probe` 앱은 별도 USB
START 한 번으로 I2S0 송신 채널만 준비한다. 모든 오디오 GPIO에
`I2S_GPIO_UNUSED`를 지정하고, 24kHz·16비트 스테레오 240프레임짜리
DMA 디스크립터 두 개에 모두 0을 미리 채운다. 앱에는 마이크, 앰프,
Wi-Fi, NVS 및 WakeNet을 연결하지 않는다.
[고정 IDF의 GPIO 처리](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/i2s_common.c#L1062-L1094)

미리 채운 바이트 수가 정확하고 실제 드라이버 콜백에 해당하는
`on_sent`가 서로 다른 두 DMA 버퍼를 보고한 뒤에만 완료로 분류한다.
콜백은 샘플을 읽거나 내보내지 않는다. I2S 채널 비활성화와 삭제가
성공하면 `two_descriptors_observed`를 기록한다. 관측은 활성화
직전부터 100ms 안에 확인해야 한다. 승인 철회, STOP, 시계 역행,
중복·잘못된 이벤트, 초기화·해제 실패 뒤에는 완료를 보고하지 않는다.
[고정 IDF의 DMA 미리 채우기](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/i2s_common.c#L1455-L1507)
[고정 IDF의 DMA 완료 콜백](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_driver_i2s/i2s_common.c#L781-L813)

관측 범위는 내부 DMA 전달 완료다. 실제 출력 핀의 I2S 타이밍,
FIFO 비움, AW88298 음소거 및 물리 STOP에는 별도 실물 증거가
필요하다. 기존 운영 HOLD는 스피커 사용을 계속 차단한다. 합성
데이터만 사용했고 장치나 유료 API에는 접속하지 않았다.

## 출력 준비 — AW88298 음소거 초기화와 합성 재생

ESP Codec Dev 1.6.2 아카이브 SHA256을 검증하고 원본 AW88298 드라이버를
모의 I2C에 연결했다. 기본 SDK 초기화는 SYSCTRL에서 증폭기를 켜고
I2S를 활성화하는 값을 쓰며, SYSCTRL2의 HMUTE를 해제한다. 동일
드라이버가 다시 활성화되거나 mute(false)를 호출할 때도 출력이
준비되기 전에 상태가 바뀔 수 있다.
[SDK 원본 및 SHA256](../firmware/standalone/tests/sdk_esp_codec_dev_1_6_2/provenance.json)

K151 출력 제어에 음소거 초기화 프로필을 적용한다. 16비트 AW88298
프로토콜과 SDK의 나머지 레지스터 전송을 재사용한다.

| 보호 레지스터 | 초기화 중 유지하는 설정 |
|---|---|
| SYSCTRL 0x04 | I2S 입력 비활성, 앰프 및 장치 power-down 설정 |
| SYSCTRL2 0x05 | HMUTE 유지 |
| HAGCCFG4 0x0C | 감쇠 코드 0x60–0xC0 유지, 데이터시트 매핑 기준 48dB 이상 감쇠 |

보호 비트는 기록한 뒤 다시 읽어 확인한다. reset은 기존 확인을
폐기한다. 잘못된 크기·쓰기 오류·읽기 오류·읽기값 불일치는 준비를
중단한다. 오류 뒤 정상 설정은 거부하지만 보호값을 유지하는 종료
동작은 시도한다. 마이크의 ES7210 제어 경로에는 기존 전달 방식을
유지한다.

20ms 합성 신호를 10ms 블록 두 개로 보내고 정상 종료와 음소거를
확인했다. STOP을 첫 블록 도중 모의 주입한 경우에는 둘째 블록을
보내지 않았고 출력이 정지 상태로 전환됐다. 위 시험은 모의
하드웨어의 소프트웨어 상태를 검증한다. 실제 앰프 전원 전환,
물리 음압과 음소거, FIFO에 남은 데이터와 물리 STOP 지연은 이후
실물에서 확인해야 한다. HOLD 출력 차단 상태에서 검증했으며 사용자
음성이나 유료 API를 사용하지 않았다.

## GPIO 격리 I2S 송신 진단의 실물 시험 준비

GPIO 격리 무음 송신 앱을 53c397b의 ESP-IDF 6.1 빌드에서 받았다.
앱·ELF·파티션 구간·이미지 SHA256을 로컬에서 독립 검증했다.
수집기는 전용 START 도전값에만 응답하고, 별도 승인 및 독립 설치
검증이 같은 검토 ID와 이미지 SHA256에 연결됐는지 확인한다.
실물에서 수집하는 값은 고정 `K151_SILENT_TX_V1` 상태와 종료 HOLD다.
다른 시험의 START·결과와 임의 필드를 거부한다.
[ESP32-S3 무음 송신 진단 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/45028484568)

| 검토 항목 | 확인한 범위 |
|---|---|
| 이미지 SHA256 | `ce391f7582ac7b9a6007d497c15eb8f322a4c985b9c33f4f6da4d1a992e16282` |
| 임시 쓰기 | `ota_1 [0x510000,0x53FFF0)`, 196,592바이트 |
| 섹터 지우기 | `ota_1 [0x510000,0x540000)`, 196,608바이트 |
| 원본 복구 | `ota_1 [0x510000,0xA00000)`, 5,177,344바이트 |
| 복구 파일 SHA256 | `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb` |
| 시험 범위 | `ONE_SILENT_TX_PROBE_AND_OTA1_RESTORE` |

원본 전체 백업 A/B와 해당 슬롯 부분의 digest를 확인했다. 설치
쓰기 직전에 같은 보드, 보안 상태, 파티션 표·OTA 선택 데이터,
현재 원본 슬롯을 독립 확인한다. 임시 쓰기가 시작됐으면 시험의
성공·중단·오류와 관계없이 원본 슬롯 전체를 복구한다. 복구 digest와
메타데이터가 일치하면 출고 재부팅을 요청하고 COM 복귀를 확인한다.
Windows 오프라인 집중 회귀 119건과 실행기·복구 모의 시험 11건이
통과했다. 포트를 열거나 실물에 쓰기 전 별도의 1회 승인이 필요하다.
