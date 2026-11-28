# K151 새 WakeNet 컨텍스트 무음 진단 실측

2026-11-21 KST. 검토한 이미지의 무음 시험 1회와 같은 슬롯의 원본 복구를
사용자가 승인했다. COM3 독점 접근, 동일 ESP32-S3 rev0.2, 16MB,
Secure Boot 및 Flash Encryption OFF, 원본 파티션 표·OTA와 `ota_1`
전체 digest 일치를 쓰기 전에 확인했다. 원본 A/B와 복구 파일의 길이와
SHA256을 로컬에서 다시 검증했다.

실행 코드 `354d363b7a66903d95732d713b2f432038d4bb66`, 실제 빌드 checkout
`5bd224e81862a26771e0477eb59c63351d861934`. 시험 이미지 SHA256은
`e69c3a0ad22f1459923b75838081702a75411b151691d6454f5deb5ac08466b9`다.
[ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44909533517)

| 실행 | 범위 | 결과 |
|---|---|---|
| 진단 이미지 쓰기 | `[0x510000,0x5D13C0)`, 791,488 B | 14.016초, 쓰기 digest 일치 |
| 진단 이미지 erase | `[0x510000,0x5D2000)`, 794,624 B | 실제 도구 보고 일치 |
| 독립 진단 verify | `[0x510000,0x5D13C0)` | 2.159초, digest 일치 |
| 원본 슬롯 복구 | `[0x510000,0xA00000)`, 5,177,344 B | 86.716초, 쓰기 digest 일치 |
| 독립 원본 verify | `[0x510000,0xA00000)` | 9.670초, digest 일치 |
| 파티션 표·OTA | 각 4,096 B·8,192 B | 쓰기 전·진단 뒤·복구 뒤 원본 일치 |

복구 SHA256은 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`다.
출고 부팅을 요청했고 PnP에서 `COM3` 복귀를 확인했다. 출고 화면의
사용자 확인은 대기 중이다.

## 무음 합성 실행 결과

최초 시작 대기의 reset reason은 USB reset인 `11`이었다. START를 1회
전송하고 11개 경계, `SYNTHETIC_24K_COMPLETE`, `FINITE_BENCH_COMPLETED`와
`HOLD_UNTIL_RESET`을 수신했다. 수신기 전체 시간은 4.8098초다. 두 reset은
모두 반환했고 두 번째 시작 메시지는 없었다. STOP은 보내지 않았고 같은
시험을 반복하지 않았다. `operating_admission:false`였다.

| 관측 | 결과 |
|---|---|
| 기존 합성 직결 추론 | 512샘플 × 64개, 최대 7.241ms, 100ms 초과 0, 감지 0 |
| 공통 입력 경로 | 24kHz 10ms 합성 프레임 32개, 최대 poll 9.006ms |
| reset 경계 | 첫 reset 및 마지막 reset의 begin/return을 모두 수신 |

최대 poll에는 USB checkpoint 출력 비용이 포함된다. 로컬 TLS와 합성
응답이 동시에 살아 있을 때의 free는 내부 307,899 B와 PSRAM
5,723,848 B였다. 두 reset은 TLS 객체가 정리된 뒤 질문·재생 버퍼가
살아 있는 단계였다. 이 한 번의 결과에서 실제 GPIO·마이크·앰프·Wi-Fi
클록이나 운영 시 최대 메모리·지연을 판정할 수 없다.

컨텍스트를 교체하는 이 이미지에서는 이전 reset 구간의 panic이
재현되지 않았다. 앞선 SDK 내부의 정확한 예외 위치는 미확정이다.
새 실제 음성 수집·저장·전송과 유료 API는 0회였다. 실제 `Hi StackChan`
인식, 물리 STOP, 독립 GPT 대화는 검증 대기다.
[이전 panic 실측](2026-11-21-k151-wake-reset-panic-live.md)

실행 코드의 Windows 로컬 root 500 PASS / 2 SKIP, standalone
670 PASS / 5 SKIP, 집중 127 PASS 및 실제 S3 빌드·CI 9/9는
기존 기록과 같다. [PR 및 검증 이력](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)
