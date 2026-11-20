# 조수 개인 보정 거부 진단 보완 (2026-11-20, Asia/Seoul)

## 현장 근거와 한계

사용자가 제공한 다음 실행은 등록3개와 보정 호출5개/비호출10개가 모두 품질 검사를 통과한 후 local_helper_rejected로 끝났다. 독립 평가에 도달하지 않았고 개인 프로필도 저장되지 않았다. 실제 원본/특징은 보관되지 않았으므로 정확한 과거 원인을 복구하지 못한다. 사용자 진단의 개별 음향 수치/원본 로그를 공개하거나 학습에 쓰지 않았다.

현재 helper의 모든 거부가 같은 문구로 가려지는 소프트웨어 문제를 재현했다. 원래 보정 함수는 호출의 최대 최소거리와 비호출의 최소 최소거리가 겹치거나 midpoint가 SWK1 문턱으로 표현되지 않으면 거부한다. 이 조건은 정상적인 보수적 거부일 수 있으므로 인식 기준을 바꾸지 않았다. 잘못된 형식/실행 오류도 가능하며 현재 결과를 분리 불가라고 단정하지 않는다.

## 변경과 계약

- C++ host helper의 기존 --calibrate 성공 wire는 보존한다. 유효한18개 distinct 특징을 원래 calibrate_wake가 거부한 경우만 고정 failure reason과 극값 trial/index/q8 거리의 stderr JSON을 반환한다.
- calibration_not_separable / calibration_threshold_out_of_range를 구분한다. 번호는 보정 호출1..5 및 비호출1..10이며 실제 단어·화자 인식 결과가 아니다.
- Python은 --calibrate, 종료코드2, 빈 stdout에서만1024byte 이하의 정확한 schema, allowlisted reason, 범위/타입·유한 거리·원인과 수치의 일관성을 검증한다. 검증한 스칼라만 CLI calibration 필드로 전달한다. 미지/손상/초과/다른 모드 응답은 일반 private helper 거부다.
- 실패 시 독립 평가나 profile 저장 없음. 원본/특징/해시/개인 profile의 콘솔 출력·새 음성 파일/업로드·자동 재녹음/평가 재학습 없음. 새 의존성/실제 마이크/COM3/로봇/API/펌웨어/NVS/OTA/모터 변경 없음. core/esp_app은 기준948b4cd와 동일하다.

## 확인한 검증

먼저 실제 C++와 Python/CLI에서 새 원인 진단 assertions4FAIL, 기존72PASS3Windows-onlySKIP를 관측했다. 수정 뒤 PC 진단/등록100PASS3Windows-onlySKIP. 합성 상수 특징의 분리 실패는 q8최악 호출1280·가까운 비호출256으로 손계산하며, sparse 특징은 분리 가능하지만 midpoint<1인 다른 거부다. 기존 성공 threshold9344 및 binary SWK1, malformed/duplicate의 일반 거부를 회귀 검사한다. 임의 stderr/추가필드/잘못된 reason/모순된 수치/비유한·음수·큰 거리/잘못된 번호·모드·코드·stdout·길이는 노출하거나 신뢰하지 않는다.

전체 로컬 Python487PASS2Windows-onlySKIP(67.88초), standalone306PASS7SKIP(122.83초), PC100PASS3Windows-onlySKIP(8.89초), Ruff check/format318files 및 diff check PASS. standalone SKIP은 Windows CMD3/SAPI2/로컬 libcjson-dev 부재2다. 단일 검토 및 정확한 새 head의 CI는 완료 후 [PR#3](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에 기록한다. 합성 시험의 PASS는 실제 개인 목소리를 구분할 수 있다는 증거가 아니다. 다음 현장 실행은 정확한 거부 원인을 수집할 뿐 모델 인식 성공을 보장하지 않는다.
