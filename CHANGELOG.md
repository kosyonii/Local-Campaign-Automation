# 수정 로그

## 2026-09-27

### 절전모드 해제 직후 DNS 실패로 인한 미디어 추출 전체 실패 수정

- 원인 진단: `260920_4차` step2(`raw_to_processed.py`) 실행이 두 차례(12:38, 14:11) 전부 yt-dlp `getaddrinfo failed (Errno 11001)`로 실패. Windows 이벤트 로그(Kernel-Power/Power-Troubleshooter) 대조 결과 두 실패 모두 노트북 절전모드 해제(전원 버튼) 후 1~3초 만에 실행되어, Wi-Fi가 아직 재연결(재인증+DHCP+DNS)되지 않은 상태에서 `www.youtube.com`/`www.instagram.com` resolve가 통째로 실패한 것으로 확인. DNS 서버(KT 168.126.63.1/.2)·호스트 파일·프록시·VPN 자체는 문제 없음을 별도 확인
- `raw_to_processed.py`에 `wait_for_network_ready()` 추가: media/comment 추출 시작 직전 `www.youtube.com`/`www.instagram.com` DNS resolve를 2초 간격으로 재시도(최대 30초)하여 절전 해제 직후 재실행되어도 Wi-Fi 재연결을 기다린 뒤 진행하도록 함. 30초 내 resolve가 계속 실패하면 경고만 남기고 진행(원인 불명 DNS 장애까지 무한 대기하지 않기 위함)

## 2026-09-22

### 인증 정보 관리 개선

- `transform_local_campaign.py`, `upload_to_bq.py`의 GCP 서비스 계정 key 경로 하드코딩 제거
- 프로젝트 루트 `.env` 파일에서 `GOOGLE_SERVICE_ACCOUNT_FILE` 환경변수를 읽어오는 방식으로 변경
- `.env`에 값이 없을 경우 기존 `GOOGLE_APPLICATION_CREDENTIALS` 환경변수를 대체 사용
- `upload_to_bq.py`에 key 경로 미설정 시 명확한 에러 메시지를 반환하는 예외 처리 추가

### 의존성 관리

- `pyproject.toml`에 `gallery-dl`, `google-genai`, `playwright` 패키지 추가
- 신규 패키지 반영에 따른 `uv.lock` 갱신

### Payload 데이터 업데이트

- 아래 12개 payload JSON 파일의 `startTime`, `endTime` 값을 최신 기간으로 갱신
  - `payload_1_1_comment.json`
  - `payload_1_2_reply.json`
  - `payload_1_3_repost.json`
  - `payload_2_1_전략법인_X.json`
  - `payload_2_2_전략법인_IG.json`
  - `payload_3_1_partner_x.json`
  - `payload_3_2_partner_ig.json`
  - `payload_3_3_partner_yt.json`
  - `payload_3_4_partner_tt.json`
  - `payload_4_1_gcl_ig.json`
  - `payload_4_2_gcl_tt.json`
  - `payload_5_1_minigame_fb.json`
- `startTime` 1789008300000 → 1789965780000, `endTime` 1789094759000 → 1790052239000로 통일 변경

## 2026-09-23

### 누락건 payload 시간범위/필터 수정

- `payload_6_1_누락건.json`의 `startTime`/`endTime`을 2026-08-09 00:00:00 ~ 2026-09-22 00:00:59 (KST) 범위로 확장
- QUERY 필터에 X(Twitter) status ID 2건(`2100545298959311096`, `2100541138818019802`) 추가 → 기존 IG 게시물 5건 + X 게시물 2건, 총 7건 대상
- `SN_MESSAGE_TYPE` 필터 수정: NIN에서 `303`(Instagram Mention) 제거, IN에 `303`, `311`(Instagram Tagged Media) 추가 → 기존 필터가 공동게시물(Mention/Tagged Media)을 전부 걸러내던 문제 해결. `304`(Instagram Comment Mention)는 계속 제외
- 위 설정으로 누락 pipeline 1~4단계 실행: 7건 중 4건 성공(LLM 분석 완료), 3건은 Instagram Media URL 만료(HTTP 403)로 미디어 추출 실패 → 수동 처리 필요 (보류 중)
- 필터 원인 진단용 테스트 payload 2개 추가: `payload_6_1_누락건_test.json`(QUERY만), `payload_6_1_누락건_test2.json`(QUERY + SN_MESSAGE_TYPE groupBy 진단용)

### 위젯 호출 구간 타이머 로깅 추가 (병렬화 before/after 측정용)

- `sprinklr_export_excel.py`에 `log_widget_call_timer()` 헬퍼 추가: 위젯별 `fetch_all_sprinklr_pages()` 호출 시작/종료와 전체 위젯 호출 구간(phase_start/phase_end)을 `[WIDGET_CALL_TIMER]` 태그로 로깅
- 타이머는 Excel 쓰기/DataFrame 변환은 제외하고 Sprinklr API 호출(hasMore 페이지네이션 포함) 구간만 측정
- 실행 종료 시 위젯별 소요시간과 `sum_widget_elapsed_sec`(직렬 합산) vs `phase_wall_elapsed_sec`(전체 wall time) 요약 출력
- 목적: 12개 위젯 순차 호출을 위젯 단위 병렬화(ThreadPoolExecutor + 공용 `sprinklr_rate_limiter.py`)로 전환하기 전, 동일 로그 포맷으로 순차/병렬 실행의 소요시간을 직접 비교하기 위함

### Sprinklr 위젯 병렬 호출 도입

- 신규 `sprinklr_rate_limiter.py` 추가: `buzz_volume_adaptor.py`의 검증된 `SlidingWindowRateLimiter` + 429/403(Developer Over Rate) 자동 재시도 패턴을 일반화해서 분리(원본 `buzz_volume_adaptor.py`는 미수정, rate limiter 인스턴스는 호출자가 직접 생성해서 주입)
- `sprinklr_export_excel.py`: `ThreadPoolExecutor`로 12개 위젯을 동시에 fetch. Widget 내부 hasMore 페이지네이션은 계속 순차 처리(커서 의존). Excel 쓰기는 openpyxl이 thread-safe가 아니므로 fetch 완료 순서와 무관하게 항상 `WIDGET_CONFIGS` 순서대로 메인 스레드에서만 수행
- fail-fast 유지: 위젯 하나라도 실패하면 `_STOP_EVENT`로 나머지 진행 중인 호출에 취소 신호를 보내고 즉시 전체 중단 (기존 순차 버전과 동일한 "하나 실패 시 전체 중단" 동작)
- rate limit 튜닝: 최초 설계(Sprinklr 시간당 한도 1,000회의 90%인 900회/시간을 60초 창당 15회로 환산)로 2026-09-14~09-20 데이터컷 재검증 시 오히려 순차보다 느려짐(127.55s vs 순차 102.26s) — 실제 주간 호출량이 총 31회뿐이라 자체 rate limiter가 병목이 된 것으로 확인. 실제 위험(12위젯 동시 첫 요청 burst, Sprinklr 403 실측 2건)에 맞춰 "동시 burst 완화"만 목표로 하는 `12회/5초`로 재조정
- 최종 검증(동일 2026-09-14~09-20 범위, 순차 결과와 행 수·응답 페이지 수 완전 일치 확인): 위젯 호출 구간 102.26s → 37.91s (약 63% 단축)
