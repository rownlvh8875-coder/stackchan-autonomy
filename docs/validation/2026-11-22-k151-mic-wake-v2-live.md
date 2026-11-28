# K151 V2 수신 전용 호출어 실물 시험

2026-11-22 KST에 승인된 V2 이미지를 사용해 K151 내장 마이크와
WakeNet을 한 번 시험하고 출고 슬롯을 복구했다. 실행 코드의 브랜치 커밋은
`6a4d3f41ee88b2f141e42e71222a048af000cc41`, 해당 CI의 빌드 checkout은
`d0d334e17765c843f3b35efe8b99dfabcad6764f`다. 두 커밋에서 펌웨어와
워크플로 파일은 일치한다. 앱·ELF·내장 모델의 결합과 SHA256은 Windows에서
확인했다. [ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44996281497)

## 호출어 감지

호스트가 로컬 START를 한 번 전송했고, 사용자가 수신 안내 뒤 “Hi StackChan”을
한 번 말했다고 확인했다. 수집기는 감지 결과와 종료 HOLD를 확인했다.

| V2 종료 필드 | 관측값 |
|---|---|
| `result` | `detected` |
| `stage` | `complete` |
| `codec_cleanup_unverified` | `false` |
| `operating_admission` | `false` |
| `frames_read` | 471 |
| `all_zero_frames` | 6 |
| `full_scale_samples` | 0 |

이번 결과는 해당 발화의 실물 감지 1회를 기록한다. 이전 V1의 `fault`는
이번에 재현되지 않았고 발생 단계는 미확정이다. 실제 음성 파일 저장, 외부 전송,
유료 API 호출은 각각 0회였다. 질문 녹음과 발화 종료, STT, GPT, TTS, 재생 및
대기 복귀는 실물 독립 대화에서 검증해야 한다.
[이전 V1 시험 기록](2026-11-22-k151-mic-wake-live.md)

## 설치 범위와 출고 복구

쓰기 전 동일 보드의 보안 설정, 16MB 플래시, 원본 전체 백업 A/B,
파티션 표, OTA 선택 데이터와 현재 `ota_1` 전체 digest를 확인했다.
V2 앱은 SHA256
`1001da382d142ee83e20edc5c9ae38e563c58c28572dbfd9a99253d299cbe418`이며
706,928바이트를 `[0x510000,0x5BC970)`에 썼다. 실제 지우기 범위는
`[0x510000,0x5BD000)` 708,608바이트였다. 부팅 전에 앱을 독립 검증했다.

시험 뒤 `ota_1 [0x510000,0xA00000)` 전체 5,177,344바이트를 복구했다.
독립 플래시 검증에서 원본 슬롯 SHA256
`39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`가
일치했다. 파티션 표와 OTA 선택 데이터는 쓰기 전, 시험 뒤, 복구 뒤 세
시점에 일치했다. 출고 부팅 요청 뒤 Windows PnP에서 COM3 상태가
`OK`였고, 사용자가 평소 출고 얼굴 또는 메뉴의 복귀를 확인했다.

| 실제 작업 | 벽시계 시간 |
|---|---:|
| 쓰기 전 원본 슬롯 독립 검증 | 9.675초 |
| V2 앱 쓰기 | 12.650초 |
| V2 앱 독립 검증 | 1.979초 |
| V2 앱 부팅 요청 | 0.695초 |
| 원본 슬롯 전체 복구 | 83.575초 |
| 복구 슬롯 독립 검증 | 9.648초 |
| 출고 펌웨어 부팅 요청 | 0.687초 |

## 실행 코드의 자동 검증

`6a4d3f4`의 GitHub CI는 Push 4/4, PR 4/4, ESP32-S3 빌드 1/1로
통과했다. 여기에는 Windows Python 3.12의 가상 soak가 포함된다.
로컬 Windows 기본 스위트에서 관측된 SQLite 커밋 실패 1건은 별도
결과다. 위 감지·복구 기록은 실제 보드에서 수집했다.
[Push CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44996275384)
· [PR CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44996281481)
