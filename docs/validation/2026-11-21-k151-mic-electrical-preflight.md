# K151 마이크 실물 시험 전 전기 확인

Windows PnP의 ESP32-S3 USB Serial/JTAG 장치가 COM3에서 정상으로
표시됐다. 원본 백업 A/B는 각 16,777,216바이트이며 알려진 SHA256과
일치했다. USB 직렬 포트를 열거나 보드를 재부팅하지 않았다. 새 실물
측정, flash 쓰기, 음성 수집, 유료 API 호출은 0회다.

## 회로와 기존 관측값

- CoreS3 v1.0 회로도 1쪽의 배선은 ALDO1을 VDD_1V8, ALDO2를
  VDDA_3V3, ALDO3을 VDDCAM_3V3에 연결한다. 같은 페이지의 설명은
  ALDO3에 codec/mic VDDA 용도를 적고 있다. 4쪽 ES7210의 전원 넷은
  VDDA_3V3이다. 보드의 실제 배선과 전압을 확인할 때 이 불일치를 반영한다.
  [M5Stack 회로도](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/490/Sch_M5_CoreS3_v1.0.pdf#page=1)
- 이전 진단은 AXP2101 `0x90=0xBF`와 `0x94=0x1C`를 읽었다.
  레지스터상 ALDO1/2/3 enable bit가 켜져 있고 ALDO3 설정값은 3.3V다.
  당시 ALDO1/2 전압 설정과 실제 rail 전압은 관측하지 않았다.
  [AXP2101 데이터시트](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/K128%20CoreS3/AXP2101_Datasheet_V1.0_en.pdf#page=53)
- AW_RST는 AW9523B P0_2에서 AW88298의 active-low RSTN으로 이어진다.
  앞선 진단의 P0 direction `0x18`과 출력 래치 `0x07`은 해당 비트의
  방향 설정 output, 래치 high를 가리킨다. 그때 GPIO/LED mode는 읽지
  않았으므로 핀 전기 상태는 미확인이다.
  [AW9523B 데이터시트](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/products/core/CoreS3/AW9523B-EN.pdf#page=18)
  [AW88298 데이터시트](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/core/K128%20CoreS3/AW88298.PDF#page=2)
  [이전 실물 진단](2026-11-21-k151-board-readback-live.md)

## 읽기 전용 변경과 검증

기존 nonce 1회 진단에서 AXP2101 `0x92/0x93`과 AW9523B `0x12`를
추가했다. `pmic_aldo12_valid`와 `pmic_aldo12_values`는 이 순서의
ALDO 설정값이다. `aw_p0_mode_valid`와 `aw_p0_mode`는 Port0의
GPIO/LED 모드 값이다. 기존 필드, 주소 probe, 읽기 제한 30ms 및 실행
슬롯·리비전 검사를 유지한다. 상태/인터럽트 레지스터와 설정 쓰기는 이
진단의 접근 범위에 없다.

기존 코드에서 세 읽기가 빠진 시험을 먼저 실패시켰다. 새 observer의
26개 SDK 경계마다 실패·STOP·동의 철회를 주입해 부분 결과 폐기와 해제를
검증했다. 실제 진단 진입점의 모의 START 후 기존 JSON 필드와 새 값,
`operating_admission:false`, HOLD 복귀도 검사했다.

Windows 로컬에서 root 500 PASS / 2 SKIP, standalone 646 PASS /
5 SKIP, 최종 읽기 전용 집중 시험 88 PASS였다. 독립 코드 검토 뒤
보고 호환 시험이 기존 ACK·앰프·터치 필드의 값까지 검사하도록 보강했다.

## 실측이 필요한 항목

실제 보드의 리비전과 ES7210의 VDDA_3V3·MICBIAS12 상태를 확인한다.
I2S 캡처 전후의 GPIO0/MCLK, GPIO34/BCK 및 GPIO33/WCK와 같은
구간의 AW88298 RSTN·스피커 출력 상태를 관측해야 입력 클록 중 앰프
격리 여부를 판단할 수 있다. USB PnP와 I2C 설정으로 이 전기 상태를
판정할 수 없다.

운영 `app_main`은 HOLD다. 다음 물리 시험은 별도의 마이크·WakeNet
진단으로 실물 PCM의 채널·FIFO fresh start·STOP과 기본 호출어 인식을
확인한다. 변경 범위와 복구 자료는 해당 이미지에 대해 따로 작성한다.
새 설정값을 읽는 것은 그 시험의 승인이나 판정에 해당하지 않는다.
