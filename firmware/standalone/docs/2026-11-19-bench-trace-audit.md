# K151 오디오 계측 로그 오프라인 검증기 (2026-11-19)

**상태: 로그 구조·시간 계산 검증 도구. 하드웨어 계측·설치 승인 불가.**

`tools/bench_trace_audit.py`는 별도 절차로 이미 수집된 JSON 파일을 **읽기만** 한다. USB/시리얼/I2C/I2S/전원/마이크/API 연결, 로그 파일 수정, 장비 제어 또는 GitHub 업로드를 수행하지 않는다. 파일 크기는 128KiB, 시험 수는 100개로 제한한다. 입력을 그대로 출력하지 않고 오류 유형과 시간차만 보고한다.

실행 예시(파일은 실제로 존재해야 한다):

```powershell
uv run --frozen python firmware/standalone/tools/bench_trace_audit.py C:\\private\\bench-trace.json
```

입력 형식(아래 수치는 **가상 데이터**이며 K151 측정 결과가 아니다):

```json
{
  "schema": "k151-audio-bench-v1",
  "clock": "shared-instrument-monotonic-us",
  "trials": [
    {
      "id": "stop-01",
      "kind": "stop_mute",
      "events": [
        {"name": "physical_stop_edge", "source": "stop_scope", "t_us": 1000},
        {"name": "amplifier_electrically_muted", "source": "amp_scope", "t_us": 1600}
      ]
    },
    {
      "id": "drain-01",
      "kind": "tx_drain",
      "events": [
        {"name": "last_pcm_write_accepted", "source": "codec_write_trace", "t_us": 2000},
        {"name": "tx_dma_empty", "source": "dma_observer", "t_us": 2600},
        {"name": "codec_output_idle", "source": "codec_observer", "t_us": 3000},
        {"name": "amplifier_electrically_muted", "source": "amp_scope", "t_us": 3200}
      ]
    }
  ]
}
```

각 시험의 기록은 상단 시계 선언에 따라 **동일하게 동기화된 하드웨어 계측 시간축**을 사용한다는 *가정*에 한하여 차이를 계산한다. 기록의 명칭, 출처 및 시계 동기화가 정말 올바른지는 코드에서 확인할 방법이 없다. 파일의 SHA-256은 **그 파일 자체의 동일성**만 나타내며 측정기가 진짜인지 증명하지 않는다.

## 출력 의미와 보류 항목

정상적인 형식을 처리하더라도 `status=UNVERIFIED_OPERATOR_SUPPLIED_TRACE`, `source_authenticity_verified=false`, `common_clock_proven=false`, `electrical_safety_proven=false`, `install_authorized=false`가 유지된다. 불완전하거나 무효인 데이터는 `REJECTED_BENCH_LOG`로 거부한다. 고유 장치 ID·비밀번호·원본 오디오·개인 정보는 이 형식에 포함하면 안 된다. 측정 후에도 별도의 원본 계측 장비 캡처, 장비 교정/동기화 증거, 원본 백업·복구 절차, 정확한 OTA 슬롯 및 명시적 실기기 설치 승인이 필요하다.

별도 시험 파일을 2개 이상 확보한 후에는 [다중 로그 비교기](2026-11-19-bench-campaign-review.md)로 시험 종류별 분포를 계산할 수 있다. 파일과 수치가 서로 다르더라도 재현성·측정 장비 교정·안전성은 자동 인증되지 않는다.

본 저장소의 `app_main`은 여전히 HOLD 루프이며, `kK151PhysicalOutputEnabledInHoldImage=false` 등 하드웨어 기동 차단은 그대로 유지한다. 코드 검증 성공으로 공장 펌웨어를 변경하거나 K151의 물리적 STOP·증폭기·DMA 안전이 입증됐다고 결론 내리지 않는다.
