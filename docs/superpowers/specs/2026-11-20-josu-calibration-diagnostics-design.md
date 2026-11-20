# 조수 보정 거부 진단 보완 설계

기존 사용자 승인 PC 마이크 진단 범위의 보완이다. 기준948b4cd / 기존PR#3. 현장 등록3+보정5/10의18개 녹음이 품질 검사를 통과했으나 마지막 품질 줄 뒤 local_helper_rejected가 발생했다. 품질 출력은 특징 추출보다 앞서므로 마지막 특징 추출과 이후 보정 중 실패 연산은 미확정이다. 원본/특징은 보관되지 않아 이 실행의 정확한 원인은 미확정이다.

## 선택과 범위

일반 오류 뒤 재녹음만 반복하는 방법은 정보를 늘리지 않는다. 모델/문턱을 완화하는 방법은 원인 근거와 오탐 검증이 없다. 기존 C++ 보정과 합격 조건을 유지하면서 보정 거부의 고정 원인과 극값 항목/거리만 알려 주는 방법을 선택한다(구현 판단). 자동 재시도/학습 재사용은 없다.

C++ host helper --calibrate의 성공 stdout SWK1은 그대로다. 유효한18개 distinct feature를 기존 calibrate_wake가 거부한 경우에만 stderr의 bounded JSON을 반환한다. reason은 calibration_not_separable 또는 calibration_threshold_out_of_range, 필드는 worst_wake_trial(1..5), nearest_nonwake_trial(1..10), worst_wake_distance_q8, nearest_nonwake_distance_q8다. 최소거리와 극값은 동일 wake_dtw_distance로 계산하며 기존 core/esp_app은 변경하지 않는다. malformed/duplicate/예상 밖 오류는 기존 일반 거부를 유지한다.

Python은 해당 모드/종료코드2/빈 stdout에서만 최대1024byte의 중복 key 없는 정확한 schema와 고정 reason, 유한 비음수 거리 및 정수 index 범위를 검증한다. 허용된 진단만 CalibrationError로 전달하고 CLI의 calibration 필드로 출력한다. 임의 stderr/필드/경로/원본/특징/프로필은 출력하지 않는다. 잘못된 진단은 local_helper_rejected로 남겨 정상 비호출이나 성공으로 세지 않는다.

실패 시 프로필 저장·독립 평가 없음. 성공 시 기존 고정 후 새 독립 평가/quiet/저장 보호 유지. 새 의존성, 마이크/카메라/로봇/COM3/네트워크/실제API/firmware/NVS/OTA/모터 접근 없음. 합성 시험은 실제 사용자 분리 가능성의 증거가 아니다.
