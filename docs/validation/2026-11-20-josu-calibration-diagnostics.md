# 조수 개인 보정 거부 진단 보완 (2026-11-20, Asia/Seoul)

## 현장 근거와 한계

사용자가 제공한 다음 실행은 등록3개와 보정 호출5개/비호출10개가 모두 품질 검사를 통과한 후 local_helper_rejected로 끝났다. 품질 출력은 해당 입력의 특징 추출 전이므로, 마지막 특징 추출 또는 이후 보정 중 실패 연산은 미확정이다. 독립 평가에 도달하지 않았고 개인 프로필도 저장되지 않았다. 실제 원본/특징은 보관되지 않았으므로 정확한 과거 원인을 복구하지 못한다. 사용자 진단의 개별 음향 수치/원본 로그를 공개하거나 학습에 쓰지 않았다.

현재 helper의 모든 거부가 같은 문구로 가려지는 소프트웨어 문제를 재현했다. 원래 보정 함수는 호출의 최대 최소거리와 비호출의 최소 최소거리가 겹치거나 midpoint가 SWK1 문턱으로 표현되지 않으면 거부한다. 이 조건은 정상적인 보수적 거부일 수 있으므로 인식 기준을 바꾸지 않았다. 잘못된 형식/실행 오류도 가능하며 현재 결과를 분리 불가라고 단정하지 않는다.

## 변경과 계약

- C++ host helper의 기존 --calibrate 성공 wire는 보존한다. 유효한18개 distinct 특징을 원래 calibrate_wake가 거부한 경우만 고정 failure reason과 극값 trial/index/q8 거리의 stderr JSON을 반환한다.
- calibration_not_separable / calibration_threshold_out_of_range를 구분한다. 번호는 보정 호출1..5 및 비호출1..10이며 실제 단어·화자 인식 결과가 아니다.
- Python은 --calibrate, 종료코드2, 빈 stdout에서만1024byte 이하의 중복 key 없는 정확한 schema, allowlisted reason, 범위/타입·유한 거리·원인과 수치의 일관성을 검증한다. 검증한 스칼라만 CLI calibration 필드로 전달한다. 미지/손상/초과/다른 모드 응답은 일반 private helper 거부다.
- 실패 시 독립 평가나 profile 저장 없음. 원본/특징/해시/개인 profile의 콘솔 출력·새 음성 파일/업로드·자동 재녹음/평가 재학습 없음. 새 의존성/실제 마이크/COM3/로봇/API/펌웨어/NVS/OTA/모터 변경 없음. core/esp_app은 기준948b4cd와 동일하다.

## 확인한 검증

먼저 실제 C++와 Python/CLI에서 새 원인 진단 assertions4FAIL, 기존72PASS3Windows-onlySKIP를 관측했다. 수정 뒤 PC 진단/등록100PASS3Windows-onlySKIP. 합성 상수 특징의 분리 실패는 q8최악 호출1280·가까운 비호출256으로 손계산하며, sparse 특징은 분리 가능하지만 midpoint<1인 다른 거부다. 기존 성공 threshold9344 및 binary SWK1, malformed/duplicate의 일반 거부를 회귀 검사한다. 임의 stderr/추가필드/잘못된 reason/모순된 수치/비유한·음수·큰 거리/잘못된 번호·모드·코드·stdout·길이는 노출하거나 신뢰하지 않는다.

전체 로컬 Python487PASS2Windows-onlySKIP(67.88초), standalone306PASS7SKIP(122.83초), PC100PASS3Windows-onlySKIP(8.89초), Ruff check/format318files 및 diff check PASS. standalone SKIP은 Windows CMD3/SAPI2/로컬 libcjson-dev 부재2다. 단일 검토 및 정확한 새 head의 CI는 완료 후 [PR#3](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에 기록한다. 합성 시험의 PASS는 실제 개인 목소리를 구분할 수 있다는 증거가 아니다. 다음 현장 실행에서 해당하는 두 보정 거부 조건이 발생하면 검증한 진단을 볼 수 있다. 특징 추출/실행/알 수 없는 형식 오류는 일반 거부로 남을 수 있고 추가 조사가 필요하다. 새 진단이나 모델 인식 성공을 보장하지 않는다.

## 단일 독립 검토 후 수정

검토 Important2건을 수락했다. 중복 JSON 필드가 잘못된 앞 값을 가리는 문제는5개 회귀에서 먼저 FAIL을 확인한 뒤 decoding 단계에서 거부하도록 수정했다. 마지막 품질 줄만으로 실패 helper 연산을 단정하는 문구와 다음 실행의 확정 진단 약속은 코드의 출력/호출 순서를 따라 바로잡았다. 사람용 문서에는 소스 문구를 검사하는 테스트를 추가하지 않았다. Minor2건(실패 시 실제 run_session의18capture 순서 회귀 보강, 문턱 진단의 현재 midpoint 기준 설명 보완)은 후속 항목으로 남겼다. 새 검토를 반복하지 않는다.

검토자는 두 revision의 실제 C++ 바이너리로 성공 SWK1 전체2507byte 일치, 중복/짧은 입력의 일반 거부 일치도 확인했다. 중복 key 수정 뒤 PC105PASS3Windows-onlySKIP.

## 구현 판단과 보류

- 과거 세션 원인을 집계 로그로 추정하거나 기준을 조정하지 않는다. 원본/특징 부재로 새 자료가 필요하며 현재 실패는 복원할 수 없다.
- 모든 일반 오류에 연산/단계 필드를 추가하는 확장은 보류한다. 이번 진단 두 조건에 해당하지 않는 실패는 원인 미확정으로 남을 수 있다.
- 기존 subprocess 수집 방식을 변경하지 않는다.1024byte는 수집 후 진단 수락 한도이며, 로컬 빌드 helper를 신뢰하는 구조다. 교체/손상된 helper가 과도하게 출력하는 경우 수집 메모리를 미리 제한하는 변경은 이번 범위 밖이다.
- 실제 사용자/K151 성능과 문턱 변경은 검증하지 않는다. 합성 PASS만으로 설치·GPT 자동 연결 완료를 주장할 수 없다.
- 원격 CI는 coordinator가 push 후 정확한 head로 확인하고 PR에 기록한다. 로컬 Linux PASS와 원격/Windows의 새 head 성공을 혼동하지 않는다.
- Minor 보류1: CLI 거부 회귀는 실제 C++ 예외를 주입하며 실제 run_session 실패의 정확한18capture 순서를 새로 단언하지 않는다. 현재 코드는 평가 전에 보정하지만 미래 순서 회귀를 이 시험 하나로 보장하지 않는다.
- Minor 보류2: 표현 범위 거부는 현재 선택한 midpoint 검사다. 모든 다른 정수 문턱도 분리 불가라는 증거는 아니다. operator guide의 해당 설명 보완은 후속 항목이다.

## 최종 로컬 재검증

수정 후 root487PASS2Windows-onlySKIP(66.87초), standalone311PASS7SKIP(122.95초), PC105PASS3Windows-onlySKIP(9.64초), Ruff check/format318files 및 git diff check PASS. 입력/음향 모델·core/esp_app·API·장치 접근 변경 없음. Windows/Linux/ESP compile-only의 정확한 최종 커밋 결과는 PR#3의 현재 검증 기록에 별도로 남긴다.
