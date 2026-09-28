# 수정 로그

## 2026-09-28

### [보류] Instagram 미디어 추출 로그인 벽 — 누락건 4건 미해결

- `누락/output_누락/260922_누락` 결과 확인: IG 게시물 5건 중 1건만 성공(row5, Sprinklr가 크롤링 시점에 잡아둔 직접 미디어 URL이 아직 살아있었음), 나머지 4건은 `manual_action_required`로 LLM 분석 스킵됨(HTTP 403 / gallery-dl 실패 / 미디어 판별 불가)
- 원인: 직접 URL이 만료되면 gallery-dl로 게시물 페이지를 직접 여는 대체 경로를 타는데, Instagram이 익명 접근을 로그인 페이지로 리다이렉트함 (실측: 4건 전부 재현)
- 1차 해결 시도: 기존 Twitter/X와 동일한 `--cookies-from-browser edge` 방식(Edge에 로그인된 쿠키를 gallery-dl이 직접 읽음)을 Instagram에도 적용 시도 → Edge/Chrome의 Application-Bound Encryption 때문에 gallery-dl/yt-dlp가 쿠키 DB를 복호화하지 못하는 것으로 확인 (yt-dlp도 동일 증상, 알려진 이슈: https://github.com/yt-dlp/yt-dlp/issues/10927). Twitter도 로그인 필요한 게시물이면 같은 문제를 겪을 가능성 있음
- 2차 해결 시도: Windows 정책으로 Application-Bound Encryption을 끄는 방법은 보안 약화에 해당해 Claude Code 자동 승인이 차단 + 관리자 권한도 없어 보류
- `media_extractor.py`에 `is_instagram_url()`, `INSTAGRAM_USE_COOKIES_FILE`/`INSTAGRAM_COOKIES_FILE_PATH` 설정을 미리 추가해둠: 브라우저 확장으로 내보낸 Netscape 형식 `.instagram_cookies.txt`가 프로젝트 루트에 있으면 gallery-dl `--cookies` 옵션으로 자동 사용, 없으면 기존과 동일하게 조용히 무시(부작용 없음). `.gitignore`에도 추가
- **현재 상태: 보류.** 지금은 영향받는 게시물이 4건뿐이라 급하지 않다고 판단해 나중으로 미룸. `.instagram_cookies.txt` 파일만 채워 넣으면 바로 동작하는 상태로 남겨둠

## 2026-09-27

### 절전모드 해제 직후 DNS 실패로 인한 미디어 추출 전체 실패 수정

- 원인 진단: `260920_4차` step2(`raw_to_processed.py`) 실행이 두 차례(12:38, 14:11) 전부 yt-dlp `getaddrinfo failed (Errno 11001)`로 실패. Windows 이벤트 로그(Kernel-Power/Power-Troubleshooter) 대조 결과 두 실패 모두 노트북 절전모드 해제(전원 버튼) 후 1~3초 만에 실행되어, Wi-Fi가 아직 재연결(재인증+DHCP+DNS)되지 않은 상태에서 `www.youtube.com`/`www.instagram.com` resolve가 통째로 실패한 것으로 확인. DNS 서버(KT 168.126.63.1/.2)·호스트 파일·프록시·VPN 자체는 문제 없음을 별도 확인
- `raw_to_processed.py`에 `wait_for_network_ready()` 추가: media/comment 추출 시작 직전 `www.youtube.com`/`www.instagram.com` DNS resolve를 2초 간격으로 재시도(최대 30초)하여 절전 해제 직후 재실행되어도 Wi-Fi 재연결을 기다린 뒤 진행하도록 함. 30초 내 resolve가 계속 실패하면 경고만 남기고 진행(원인 불명 DNS 장애까지 무한 대기하지 않기 위함)

### YT 댓글 추출 병렬화 (ThreadPoolExecutor prefetch)

- `260920_4차` step2 재검증 결과 채널별 소요시간 중 YT(92건, 2043.6초)·X(217건, 1531.4초)가 대부분을 차지하는 것을 확인. X/FB/TT는 로그인 세션 유지를 위해 Playwright persistent context(동기 API, 단일 스레드 전용, 프로필 디렉터리 단일 프로세스 락) 하나를 세션 전체에서 공유하고 있어 단순 스레드풀 병렬화가 불가능하고, 계정 잠김 리스크도 있어 별도 검토로 보류. YT/IG는 세션·브라우저 상태를 공유하지 않는 순수 yt-dlp 호출이라 Sprinklr 위젯과 동일한 패턴 적용 가능
- `comment_extractor.py`: `CommentExtractorSession`에 YT 결과 prefetch 캐시(`_youtube_prefetch_cache` + lock) 추가. `prefetch_youtube_comment_urls()`로 시트의 YT permalink를 `ThreadPoolExecutor`(기본 6 workers)로 동시에 `extract_youtube_comment_url()` 호출해 캐시를 채우고, 기존 `extract_comment_url()`의 YT 분기는 `pop_cached_youtube_result()`로 캐시를 먼저 소비(캐시 미스 시 기존처럼 동기 호출로 자연스럽게 fallback, 중복 집계 없음)
- `raw_to_processed.py`: `process_one_sheet()` 본 처리 루프 전에 해당 시트의 YT permalink를 먼저 훑어 `prefetch_youtube_comment_urls()`를 호출하도록 추가
- 실측 검증: 실제 캠페인 데이터 중 가장 느렸던 YT 영상 5건(기존 순차 기록 합계 328.4초)을 병렬 prefetch로 재실행 → 81.0초(약 가장 느린 영상 1건 수준) = **4.05배 단축**, 5건 전부 정상 추출
- 부수 조사: `max_comments`를 50→5로 줄이면 개별 호출이 빨라질 거라 가정하고 테스트했으나 실측상 유의미한 차이 없음(병목은 댓글 페이지 수가 아니라 yt-dlp가 영상당 거치는 기본 요청들의 네트워크 왕복)을 확인하고 50으로 원복. 효과 없이 "상위 댓글이 전부 작성자 고정 댓글인 영상에서 결과를 못 찾을 위험"만 키우는 변경이었음

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
