# Windows lease 실패 근거와 실패 전용 계측

2026-11-21, Asia/Seoul. 새 운영 기능이 아닌 기존 pytest/TimingProbe 연결이다.
production action/storage/control/state_store/soak와 제한/내구성은 변경하지 않았다.

## 실제8a34bc1 CI — 7/9

| Run | 결과 |
|---|---|
| [Push44857963485](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44857963485) | 3/4 |
| [PR44857968647](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44857968647) | 3/4 |
| [S344857968630](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44857968630) | 1/1 |

정확한 head는8a34bc1793ecb7846c264605100d19fd1f3f09c4이며 모두 첫 attempt다.
실패job 재실행0, 새 commit 전 세 run의 최종 결과를 확인해 cancellation으로
대체하지 않았다. S3 job136704501371은 변경한 codec포트를 컴파일하고 세 앱의
compile/link를 완료했다. Linux job136704484538의 C++ gate589PASS41SKIP다.
실물 설치/인식이나 독립 GPT 성공 증거가 아니다.

Push Windows3.12 job136704484345는
`test_valid_verification_uses_remaining_lifetime_not_a_fixed_fraction`의 두 번째
claim에서 StateUnavailable(control verification timed out)로 정지했다.
root494PASS1FAIL2SKIP148.74s이며 virtual soak 전이다. TTL1.5/sleep0.6을 바꾸지
않았다. CI 당시 단계별 trace가 없어 정확한 지연 위치는 알 수 없다.

PR Windows3.12 job136704502085는 root495PASS2SKIP156.65s/PC108PASS 뒤
virtual cycle1618에서 engine_failure/check_timeout으로 안전 정지했다.
wall190.359s, cloud0/잔류task0이다. 완료COMMIT max3.0079481s,
loop lag50.4251ms, interruption에는 renewal의COMMIT4.4934378s와 check의
serial_wait2.1306888s가 기록됐다. 완료 최대치와 중단 경과는 별도 지표다.
COMMIT 단계에는 worker의 OS 비실행 시간도 포함되므로 물리 디스크 지연으로
단정하지 않는다. Push/PR Windows3.11은 각각2880cycle PASS, wall207.422/198.531s,
COMMITmax0.233053/0.763054s, interruption0/1, cloud0/잔류task0이다.

## 짧은 로컬 조회와 변경 범위

실패한 root 시험을 원래 TTL/sleep 그대로 한 번 계측해1PASS0.95s였다.
SQLite check3.2959ms/thread CPU0ms(Windows 해상도 한계),COMMITmax3.1756ms,
serialwait107.0989ms,executorwait1.9141ms,looplag12.3574ms를 관측했다.
interruption1은 종료 중 heartbeat취소이며 CI 실패 원인으로 확대하지 않는다.
이 pass로 실패를 대체하거나 CI의 I/O/OS 원인이 해결됐다고 주장하지 않는다.

해당 시험에만 opt-in `lease_timing_probe`를 붙였다. async fixture는 loop monitor를
시작/정리하고 runner context에서 trace를 수집한다. 최종 pytest call report가
failed일 때만 고정 schema JSON을 출력한다. snapshot은 유한 stage/operation label·
기간·최대16개 interruption뿐이며 argument/path/SQL/key/exception 본문은 출력하지
않는다. 원래 TTL1.5/주입sleep0.6·성공 assertion·TimeoutError·fault 처리는 그대로다.

실패/성공 subprocess 계약2개를 RED→GREEN으로 확인했고, 검토 뒤 skip/xfail
출력 문제도2RED→GREEN으로 수정했다. capture를 끄고 pass 출력도 노출해 숨김을
막으며 무조건 출력하는 임시 사본을 negative control로 검출한다. 검사 생략이나
실패 whitelist가 아니다. 근본 원인 대신 다음 실제 실패의 증거 부족을 줄이는 변경이다.

보고기 추가 후 compiler 경로를 포함한 전체 root500PASS2SKIP91.07s,
집중6PASS4.14s, Ruff/format·diff PASS다. 중간 compiler 경로 누락 run의3개 추가 SKIP는
이 최종 실행에서 실제 컴파일로 확인했다. 같은 검토자가 후속 범위를 확인했고,
pass의 stdout가 pytest capture에 숨는 Important는-rP/-s와 무조건 출력 negative
control로, skip/xfail Minor는 최종 report.failed 조건과 RED→GREEN으로 보완했다.
추가 CI는 [PR3/checks](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에
exact head로 연결한다. [기계 판독 기록](2026-11-21-lease-failure-reporting.json).
기존 firmware의
standalone625PASS5SKIP103.07s/집중66PASS는8a34bc1에서 확인한 그대로이며 이
후속은 firmware 파일을 바꾸지 않는다. 장치 접근·리셋·flash·실음성·유료 API0,
HOLD/cloud OFF/물리 출력·drain false와 기존 owner/model/PCM 보호를 유지한다.

## 2026-11-22 워커 완료 뒤 이벤트 루프 지연 재현

내장 모델 연결 `a21385c`의 PR Windows 3.12는 기존 지연 주입 시험 한 건의
계측 assertion에서 실패했다. 기본 시험 499 통과·1 실패·2 건너뜀이었고,
가상 soak 단계에 이르기 전이었다. 실패 지점에 도달하기 전에 시험의
안전 정지, lease 상실, 워커 1회 및 잔류 작업 0 조건은 통과했다.
[Windows 3.12 job](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44916950444/job/136884491573)

Windows 3.12에서 장치 없이 8사이클로 제한한 시험에 워커 완료까지의 루프
지연을 주입해 같은 assertion 실패를 재현했다. 안전 정지와 `renew_timeout`,
워커 실행 156ms, 최대 루프 지연 167ms를 관측했다. 확인된 계측은
`lease_check/delivery`와 `lease_renew/pre_submission_deadline`이었다.
실패 CI 로그에는 해당 실행의 상세 stage 값이 없어 두 작업 순서가 정확히
같았는지는 확인할 수 없다.

시험은 작업 제출 지점에서 워커의 순서를 제어한다. 첫 경우는 워커가
실행을 시작한 뒤 루프를 재개하고 실제 기한 중단 기록까지 워커를 붙잡는다.
두 번째는 워커가 결과를 준비할 때까지 루프를 멈춘다. 두 경우 모두
lease check 자체의 stage와
안전 정지, 워커 1회, 클라우드·잔류 작업 0을 검증한다. 운영 코드·timeout·lease
제한은 바꾸지 않았다. 이 재현은 원래 696460c 가상 soak의 원인 규명과 별개다.
