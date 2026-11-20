# K151 원본 A/B 오프라인 교차검증 (추가한 읽기 전용 점검)

범위: 사용자의 로컬 백업 파일 두 개를 **읽기만** 하며, 로봇·USB·네트워크
접근과 플래시 쓰기/삭제 기능은 없다. 장치 원본 파일을 GitHub에 올리지 않는다.

기존 `experiments/k151_layout_spike/inspect_layout.py`를 재사용해
각 16,777,216B 파일의 SHA-256, ESP-IDF 파티션 테이블 MD5 및 7개 파티션
위치·크기를 검증한다. A/B 전체 바이트 일치도 따로 확인한다. 결과에는 경로나
원본 바이너리·NVS 내용을 출력하지 않는다.

실제 사용자 파일을 이 서버에서 읽거나 해시를 다시 계산하지 않았다. 기존
`docs/validation/2026-11-18-k151-original-backup.json`의 해시는 사용자
Windows 출력에 기반한 값이다.

### 언젠가 사용자 PC에서 점검할 때에만 (선택, 실행되지 않음)

`python firmware/standalone/tools/offline_factory_recovery.py --factory-a "<사용자 로컬 A 경로>" --factory-b "<사용자 로컬 B 경로>" --expected-sha256 <사용자가 확인한 64자리 해시>`

두 파일이 동일해도 결과는 **TWO_LOCAL_BACKUPS_MATCH_NOT_INSTALL_AUTHORIZATION**이다.
독립 보관 사본·OTA 활성 슬롯·공식 앱 인증 유지·실제 복구 쓰기·전원 차단 복귀
증명은 결코 PASS로 변경하지 않는다. 실행 결과에 공장 이미지 내용을 포함하지 않는다.

테스트에서는 가짜 16MB ESP32 이미지를 새로 만들어 MD5·SHA·파티션 배치와
불일치/변조를 검증하며 **사용자의 백업은 사용하지 않는다.**

**금지:** 이 도구의 PASS를 설치 승인, 쓰기 주소 추천, OTA 슬롯 추천,
이전 펌웨어 복구 성공 또는 K151 공장 인증 호환성 입증이라고 주장하지 않는다.
