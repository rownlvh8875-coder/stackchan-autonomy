# K151 다중 계측 로그 비교 — 오프라인 캠페인 분석기

**상태: SOURCE/STRUCTURE-ONLY. 실제 계측 또는 하드웨어 설치 승인과 무관.**

`tools/bench_campaign_review.py`는 기존 `bench_trace_audit.py` 형식의 JSON 계측 로그 **2~16개**를 읽기만 한다. 장치를 연결하거나 호출하지 않으며 파일을 수정하지 않는다. 로그에는 보안키, 시리얼번호, 파일 경로, 원본 음성 등 식별 가능하거나 민감한 데이터를 넣지 않는다.

```powershell
uv run --frozen python firmware/standalone/tools/bench_campaign_review.py C:\\private\\run-a.json C:\\private\\run-b.json
```

요구 조건은 각 파일의 엄격한 K151 벤치 스키마 충족, 각 파일의 SHA-256 상이, `stop_mute`와 `tx_drain` 각각 서로 다른 파일 **2개 이상**에서 기록 존재이다. 독립된 파일 두 개가 동일한 측정에서 복사되었거나 같은 시계 오류를 공유할 가능성은 여전히 있다. 로그 포맷의 `shared-instrument-monotonic-us` 문구는 입증 자료가 아니라 **미검증 입력의 자기 선언**이다.

각 시험 종류에 대해 `stop_to_electrical_mute_us`, `last_write_to_dma_empty_us`, `last_write_to_codec_idle_us`, `last_write_to_amp_mute_us`의 표본 수, 최소, 중앙, 최대, 범위를 출력한다. 값이 서로 일치하더라도 **재현성 PASS·기기 안전성 PASS를 부여하지 않는다**. 시험 횟수·측정 방법·클럭 교정·기기 상태 등 신뢰성에 관한 외부 증거는 독립적으로 검증해야 한다. 안전한 최대 STOP 지연시간이나 적정 DMA 배출 시간에 대해 **검증되지 않은 임계값을 임의로 적용하지 않는다**.

출력에는 파일의 내용 SHA-256과 시험 종류별 수만 포함하며 원본 파일 경로와 이벤트 타임스탬프는 재출력하지 않는다. 중복 파일, 잘못된 형식, 누락된 시험 종류, 크기 초과 입력은 비정상 종료 코드 2로 거부한다.

성공적으로 계산해도 `status=UNVERIFIED_MULTI_TRACE_SUMMARY`, `repeatability_proven=false`, `cross_file_clock_sync_verified=false`, `raw_measurement_provenance_verified=false`, `electrical_safety_proven=false`, `install_authorized=false`를 유지한다.

결과는 물리적 STOP 계측, 증폭기 음소거·DMA 비움 신호, 교정된 공통 계측 시계 및 출고 펌웨어 복구 검증을 대신하지 않는다. `app_main`의 HOLD, PCM 출력 비활성화 플래그, 공장 펌웨어는 변경하지 않는다.
