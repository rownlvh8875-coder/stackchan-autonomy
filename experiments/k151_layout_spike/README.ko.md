# K151 백업 파티션 진단 시제품

**실험용 읽기 전용 도구다. 설치 도구나 사용 가능한 빈 슬롯을 판정하는 프로그램이 아니다.**
제조사 문의 대신 직접 연결을 만들어 보자는 요청의 첫 확인 단계다. 현재 로봇은 변경하지 않는다.

로컬16MB 원본 파일의 SHA256을 지정한 값과 비교한 뒤, 표준 위치0x8000의 ESP-IDF
파티션 표와 MD5를 검증하고 주소·크기·형식만 출력한다. 설정 내용·인증키·앱 코드는
해석하지 않는다. 비표준 파티션 이름은 출력에서 가린다. 이미지 전체는 해시 확인을
위해 프로세스 메모리에 읽지만 외부로 전송하거나 파일에 다시 쓰지 않는다.

USB·직렬 포트·네트워크에 연결하지 않고 `.env`도 읽지 않는다. 새 의존성은 없다.
동작 중인 슬롯·안전한 설치 대상·복구 가능성을 추측하지 않는다. 오류가 나면 고정 코드로
중단하며 파일 일부나 원문 오류·경로를 출력하지 않는다.

사용자 노트북에서 저장소를 업데이트한 뒤, 현재 확인된 원본 A 파일에 다음을 실행한다.

```cmd
"C:\Users\user\.local\bin\uv.exe" --directory "C:\Users\user\stackchan-soak-24h" run --frozen python experiments/k151_layout_spike/inspect_layout.py "C:\Users\user\stackchan-soak-24h\.local\device-backup\k151-original-20261118-01\factory-a.bin" --expected-sha256 C1241A7C87145EE8B9569CFBCFBB1F8C289641856F9B9B5DDF2CCD565019543E
```

JSON 출력만 검토한다. 원본 `.bin`은 채팅이나 GitHub에 올리지 않는다.
실제 배치 확인 후 원본 보존·새 앱 크기·실행 모드·복귀 방법을 설계해야 한다.
시제품을 제품 기능으로 통합하거나 실제 펌웨어를 설치하는 작업은 이번 도구 범위가 아니다.

파티션 형식 근거:
[고정 ESP-IDF gen_esp32part.py](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/partition_table/gen_esp32part.py).
