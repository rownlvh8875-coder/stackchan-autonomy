# K151 무음 24kHz WakeNet 실물 진단 중단과 원본 복구

2026-11-21 KST. 검토한 합성 입력 진단 1회와 같은 슬롯의 원본 복구를
사용자가 승인했다. COM3 독점 접근, 동일 ESP32-S3 rev0.2, 16MB,
Secure Boot 및 Flash Encryption OFF, 파티션 표·OTA 원본 일치와
`ota_1` 전체의 독립 digest 일치를 쓰기 전에 직접 확인했다. 로컬 원본
A/B와 복구 슬라이스의 길이와 SHA256도 다시 검증했다.

코드 `731bb2af103819113f97c53200e5d7fae450a696`의 실제 PR checkout은
`70c2150f987a4412324a9ad84982b3bd42d4c1b0`이다. 설치한 이미지 SHA256은
`edc4af1a0d13cee269cf9b3eb798a4af41c051c0af97b81bb30a9f556e703b18`이다.
[ESP32-S3 빌드](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44890869193)

| 실행 | 범위 | 결과 |
|---|---|---|
| 진단 이미지 쓰기 | `[0x510000,0x5D0B80)`, 789,376 B | 13.683초, 쓰기 digest 일치 |
| 진단 이미지 erase | `[0x510000,0x5D1000)`, 790,528 B | 도구의 실제 보고와 일치 |
| 독립 진단 verify | `[0x510000,0x5D0B80)` | 2.054초, digest 일치 |
| 원본 슬롯 복구 | `[0x510000,0xA00000)`, 5,177,344 B | 86.286초, 쓰기 digest 일치 |
| 독립 원본 verify | `[0x510000,0xA00000)` | 9.638초, digest 일치 |
| 파티션 표·OTA | 각 4,096 B·8,192 B | 쓰기 전·진단 뒤·복구 뒤 모두 원본 일치 |

복구 SHA256은 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`다.
재부팅 요청에는 검증된 보안 상태 조회 뒤 RTS hard reset 경로를 사용했다.
총 두 번의 flash 쓰기는 위 범위에 한정했다. 복구 뒤 출고 부팅을 요청했고
COM3을 PnP에서 다시 확인했다. 사용자가 이 재부팅 뒤 출고 얼굴·메뉴가
보인다고 확인했다.

## 실제 수신 결과

새 nonce가 왔고 START를 한 번 보냈다. 모델 준비, 로컬 TLS 단계, 합성
JSON·speech 처리와 `synthetic_inference`까지 총 여덟 단계 기록이 왔다.
그 뒤 두 번째 시작 대기 메시지에서 수신기는
`RECEIVE_ABORTED / DUPLICATE_BOOT_OR_NONCE`로 중단했다. STOP을 한 번
전송했고 같은 실행에서 추가 START는 없었다. 수신기 실행 시간은 5.4604초였다.
`SYNTHETIC_24K_COMPLETE`, 직접 추론 횟수를 담은 최종 결과, HOLD 완료는
수신하지 못했다. 원시 직렬 문자열과 nonce는 저장하지 않았다.

반복 시작 대기는 재시작에 부합한다. reset reason·panic 원인·backtrace와
32프레임 단계의 세부 위치는 확인되지 않았다. 다음 진단에서는 부팅의 reset
reason과 모델 reset 전후, 입력 버퍼 준비, 첫 poll·detect의 단계 경계를
고정된 필드로 구분해야 한다. 같은 이미지의 반복 설치나 제한 완화는
실행하지 않았다.

실제 실행한 코드의 Windows 로컬 시험은 root 500 PASS / 2 SKIP,
standalone 648 PASS / 5 SKIP, 집중 129 PASS였다. 실제 ESP32-S3
compile/link와 CI 9/9도 통과했다. 이번 실물 24kHz 합성 단계는
완료되지 않았다. 실제 음성 수집과 유료 API는 0회이며, 실물
“Hi StackChan” 인식과 독립 GPT 대화는 미검증이다.
[검증 및 CI 이력](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)
