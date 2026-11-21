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
호출 전에 추적하고 실패 뒤 독립 close를 시도한다. SDK의 코덱 제어/I2C 오류 전달을
전부 해결한 것은 아니다. data disabled는 논리 상태이며 analog mute의 증거가 아니다.
실제 microphone 활성화 전 이 제어 경로와 전기적 조건도 검증해야 한다.

## 소유권과 준비 상태

포트가 기존 SDK base data interface와 I2S handles를 소유한다. 어댑터는 빌려 쓰며,
모든 설정 callback을 **원래 base pointer**로 전달한다. codec device 삭제 뒤 어댑터를
분리하고 base를 단 한 번 해제한다. 어댑터 자체를 SDK free 함수에 넘기지 않는다.
콜백 재진입은 기다리지 않고 거부한다. 전체 port 생성/사용/종료는 한 owner task에
한정하며 다른 task의 동시 파괴를 지원한다고 주장하지 않는다.

HOLD app_main은 포트를 생성·prepare하지 않는다. speaker_on의 두 false 상수와
drain=false를 유지한다. 과거 보드 설정값·모델 heap 수치로 owner/assets/power/
readiness를 true로 만들지 않는다. 이번 코드의 target 빌드는 실물 음성 성공이 아니다.

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
회귀를 포함한다. Ruff/format356files·diff 검사도 통과했다. 실제 S3 target과
현재 commit의 CI 결과는 별도로 확인하며 이 로컬 통과로 green을 선언하지 않는다.
