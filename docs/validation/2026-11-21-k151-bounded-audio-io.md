# K151 제한된 PCM 전송 검증 — 실물 미적용

2026-11-21, Asia/Seoul. [코드 범위](../K151_AUDIO_IO.ko.md),
[기계 판독 결과](2026-11-21-k151-bounded-audio-io.json).
이 기록은 PCM 코드5cd310f와 최적화 검증기 보강 시점의 결과다. 후속 commit의
실제 CI는 같은 [PR #3](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에 분리해 갱신한다.

기존 K151CodecPort/SDK clock·slot·코덱·볼륨 경로를 유지한 비소유 data callback이다.
driver wait20ms 한 번 호출, exact byte count, 단조 clock·반환 후40ms 거부와
sticky fault를 적용했다. SDK setup/enable 오류를 open이 무시해도 독립 state로
실패를 감지한다. 포트 수명은 한 owner task에 한정한다. 예산은 물리 STOP 보장이
아니며 동기 I2C/open/close·드라이버 내부 대기는 별도 검증이 필요하다.

## 로컬·독립 검토

- 실제 포트+고정 codec1.6.2 헤더와 IDF C ABI double을 실행했다. 1000ms wait,
  거부 뒤 남은 PCM·중복 disable·활성 format 변경을 먼저 실패시킨 뒤 수정했다.
- 초기 전체 root495PASS2SKIP115.99s/standalone586PASS5SKIP113.43s.
  검증기 보강 뒤 standalone592PASS5SKIP90.79s, 최적화 집중9PASS.
- -O2의 실제 zero store를 확인하며 ordinary-fill negative control은 소거된다.
  register zeroing/덮어쓰기/부분 byte 추적도 검사한다. SDK/DMA 내부 사본의 완전
  소거나 타겟의 실제 마이크 동작을 증명하는 시험은 아니다.
- 독립 검토 Important1인 Windows SDK fixture 줄바꿈 변환을 실제 Git checkout에서
  RED→GREEN으로 고쳤다. 헤더/license는 원문 SHA를 유지한다. 원문 공백1곳은
  변경하지 않고 기록했다. 생성 provenance만 LF로 정리했다.
- Minor null-interface handle 방어/get_info 실패 주입 fixture는 남아 있다.
  정상 SDK는 live pointer를 공급한다. 실제 get_info 실패 코드는 fault를 유지하지만
  이 분기의 회귀 주입 시험은 아직 없다.

## 실제 target·초기 CI: 4/9

코드 `5cd310f4f5527d03b12d9a842a6ce0f818d61d03`의
[S3 run44851513434](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44851513434),
job136683706095는 PASS다. 실제 로그의 `k151_bounded_i2s.cpp.obj` 컴파일과
HOLD/무음 모델 진단/보드 진단 세 앱의 compile/link 완료를 확인했다.
고정 IDF6.1 commit fff9895c82d744c7237be8847347bdd1b07c6643이다.
HOLD bin의 크기/정적 RAM을 운영 앱 자원 여유로 해석하지 않는다.

| 이벤트 | 성공 | Run |
|---|---:|---|
| Push | 2/4 | [44851505977](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44851505977) |
| PR | 1/4 | [44851513416](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44851513416) |
| S3 | 1/1 | [44851513434](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44851513434) |

Linux4개는 최적화 proof2개가 GCC register-zero store를 인식하지 못해 실패했다.
각2FAIL548PASS41SKIP이고 LLVM/Windows 로컬과 다른 생성 형태다. matcher를 보강했고
재현/negative control을 유지했다. 같은 실패 job을 재실행해 green을 얻지 않는다.
PR Windows3.11 job136683706455는 root494PASS1FAIL2SKIP149.64s였다.
`test_measured_slow_lease_worker_still_fails_closed_without_retry`에서 test-only
TTL0.1s의 acquisition이 먼저 acquire_timeout으로 정지해 기대한 check/renew 주입에
도달하지 못했다. TTL·기대 reason 집합을 넓히지 않았다. 실제 I/O/worker 비실행
시간 원인은 분리되지 않았으며 firmware 성공으로 숨기지 않는다.

## 이전 Windows 계측 시험과 변경 범위

이전cd06769는8/9였고 PR Windows3.11 job136672698831가
executor wait0.0261449>=0.03 가정에서 실패했다. timeout을 건 뒤 trace 시작 전35ms
지연을 넣어 serial/executor 두 시험을 로컬 RED로 재현했다. 동일40ms timeout과
TimeoutError·실제 큐·취소/drain/count를 보존하고, 별도 실측 대기 구간을 기록
계측이 포함하는지 비교하도록 수정했다. 동일35ms 주입2GREEN, 해당 모듈8GREEN.
이는 수초 COMMIT stall/heartbeat/명령 진입 대기의 모든 원인을 고친 증거가 아니다.

이번 작업의 기기 명령/flash/실음성/API는0이다. 마지막 [실물 보드 조회](2026-11-21-k151-board-readback-live.md)
뒤 원본 복구·사용자 출고 화면 복귀 상태를 바꾸지 않았다. 운영 HOLD, 출력 false,
drain=false, cloud OFF와 기존100ms gap/chunk160..2048은 유지했다. 실제 마이크·
호출어·질문/VAD·STT/GPT/TTS·재생·physical STOP/TLS peak는 후속이다.
