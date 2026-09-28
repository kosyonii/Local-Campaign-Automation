# 수정 로그
# written automatically by claude / revised & reviewed by Seoyeon Ko

## 2026-09-28

### case2 BEFORE(1~4단계) 측정 완료 — 총 소요시간 요약

- case2(2026-09-07~09-13, 4배 데이터) BEFORE 기준선(원본 코드: `raw_to_processed.py`/`comment_extractor.py`는 559303b 상태, `media_extractor.py`/`llm_analysis_pipeline.py`는 원본)
- 1단계 `sprinklr_export_excel.py`: 38.6초
- 2단계 `raw_to_processed.py`: **약 5,312초(88.6분, 추정 범위 5,312~5,434초 = 88.6~90.6분)**. 오후 3:35 PC 재부팅으로 중단돼 체크포인트에서 재개했기 때문에 두 구간을 합산한 추정값임
  - 앞 구간: 로그 생성 14:27:15 → 마지막 체크포인트 15:22 ≈ 3,285초(±1분). 상한은 로그 마지막 기록 15:24:02까지(3,407초). 프로세스가 실제로 언제 죽었는지는 불명이며, 앞 구간 시작 시각은 로그 파일 생성 시각으로 대체함. 앞서 "앞 구간 12:35~15:22"라고 한 것은 오류(12:35는 1단계 종료 시각)
  - 재개 구간: 15:53:26 → 16:27:13 = 2,027초(`module_timings.csv` 기록값). 재개 대기(15:36~15:53)는 제외
- 3단계 `media_extractor.py`: 2,134초(35.6분), 미디어 자산 1,224건 + FB 원본 게시물 후속 165건
- 4단계 `llm_analysis_pipeline.py`: 1,750초(29.2분), 1,076건 중 성공 989 / 사용자 조치 필요로 건너뜀 83 / 입력 생성 실패 3 / API 실패 1
  - 실패 4건: 403 PERMISSION_DENIED 1건(원인 미확인), 한 게시물 로컬 미디어 1,198MB가 안전 제한 450MB 초과 1건, 지원하지 않는 `.m4a`(`Raw Data_원문_502`, `_503`) 2건
- **합계: 약 9,235초(약 154분, 2시간 34분)**, 상한 기준 약 9,357초(156분)
- 재부팅 전 구간(1~482행)의 댓글 추출 채널별 기록은 메모리에만 있어 소실됨 → case2 채널별 통계는 재개 구간만 있음

### case2 BEFORE 2단계 결과 및 댓글 추출 이상 조사 (YT/TT)

- case2 BEFORE 2단계(`raw_to_processed.py`, 559303b 상태): 오후 3:35 PC 재부팅(이벤트 로그 User32 1074)으로 중단 → 체크포인트(`Raw Data_원문` 483행)에서 재개해 완료. 재개 구간 33.8분(2,027초), 888행. 앞 구간(재부팅 전)의 채널별 기록은 메모리에만 있어 소실. 메모리 부족은 원인이 아님(여유 7.8/15.6GB)
- 재개 구간 채널별(416건): X 89건 평균 6.7초, FB 50건 11.0초, IG 245건 1.8초, TT 14건 26.4초, YT 18건 3.8초. case1 채널별(609건) 합계는 YT 51.6%, X 31.5%, IG 11.0%, FB 4.8%, TT 1.1%
- **YT 18건 전부 미추출 → 차단이 아님**: 15건은 재조회 결과 댓글 0개(정상적인 "댓글 없음"). 오류 3건(yt-dlp `Unable to download API page: HTTP Error 403`) 중 2건(`ic2Se2Ftzd4`, `mGvgygPgZ_k`)은 재조회 시 댓글 20개가 있어 **일시적 403으로 실제 댓글을 놓친 것**. 현재 추출 코드는 403에 재시도가 없음 → 나중에 개선 항목(BEFORE/AFTER 비교에는 영향 없음)
- **TT 미추출(case2 14건, case1 2건 모두 0건)**: 예외/오류 없이(error=0) 매 건 약 26초(= 페이지 로딩 + 3초 대기 + `TIKTOK_COMMENT_WAIT_SECONDS` 20초 대기 후 타임아웃)에 `None` 반환. 즉 댓글 응답(xhr/fetch, URL에 "comment" 포함)을 20초 내 한 번도 수집하지 못함. 로그에는 TT 관련 메시지가 전혀 없음. 원인 조사 결과: (a) 자동화용 Edge(`.tiktok_edge_profile`, 포트 9222)는 처음에 로그인 쿠키가 없는 게스트 모드였음 → 사용자가 같은 프로필로 로그인 후 `sessionid` 등 쿠키 확인, (b) 그래도 재시도 4건 모두 `None`(약 27초). 원인은 **headless Edge**: 자동화가 `--headless=new`로 띄운 Edge의 UA는 `HeadlessChrome/154`이고, 로그인 상태에서 댓글 아이콘을 클릭해 패널이 열려도 `/api/comment/list/` 요청이 아예 발생하지 않음. 같은 프로필을 창이 보이는 Edge(UA `Edg/154`)로 열면 `/api/comment/list/`가 200으로 호출됨 → TikTok이 headless를 감지해 댓글 API를 막는 것으로 판단. 해결 방안(코드 수정 필요, 미적용): TT용 Edge를 headless가 아닌 창 모드(최소화 등)로 실행
- `media_extractor_v2.py`: 병렬 처리 뒤에 남아 있던 원본 순차 루프의 잔여 로그 출력(`if asset.status == "downloaded"` ...) 삭제 (마지막 자산 값을 잘못 출력하던 버그)
- 브랜치 `time-delay-optimization` 생성 및 push (커밋 cdb5b6a): 2a/2b/v2 파일과 `pipeline_service.py`, 아직 파이프라인에 갈아끼우지 않음

### 최적화 2라운드 착수: (2) 2a/2b 분리, (3) YT/IG 병렬화 일반화, (5) 3단계·2b/3단계 병렬화 (복제 파일 기반, 아직 실제 파이프라인에 갈아끼우지 않음)

- case1/case2 BEFORE-AFTER 비교 방법론을 지키기 위해, case2 BEFORE 측정이 끝나지 않은 상태에서 원본 파일(`raw_to_processed.py`, `comment_extractor.py`, `media_extractor.py`)은 건드리지 않고 전부 복제본에서 작업. case1 때처럼 완전한 "before" 기준선을 훼손하지 않기 위함
- `raw_to_processed_2a.py` (신규, `raw_to_processed.py` 복제 후 수정): 댓글/reaction URL 추출 관련 코드(`CommentExtractorSession`, `wait_for_network_ready`, `build_url_cell_value` 호출) 전부 제거. Excel 정제만 수행하고 URL 컬럼에는 Permalink만 기록 (원래 의도했던 "URL=Permalink 단일값" 형태로 복귀)
- `consumer_reaction_url.py` (신규 2b 모듈): 2a가 만든 `*_formatted.xlsx`를 읽어 채널별 소비자 댓글/reaction URL을 추출하고, 같은 URL 컬럼을 `POST_URL\nCOMMENT_URL` 형식으로 덮어씀 (llm_analysis_pipeline.py의 `split_post_and_comment_urls()` 계약 그대로 유지)
- `comment_extractor_v2.py` (신규, HEAD의 `comment_extractor.py` 복제): 기존 YT 전용 prefetch 캐시(`_youtube_prefetch_cache`, `prefetch_youtube_comment_urls`)를 채널 범용으로 일반화 — `_PREFETCHABLE_EXTRACTORS` 레지스트리(YT/IG), `prefetch_comment_urls(channel, urls, max_workers)`, `pop_cached_result(channel, url)`. 채널별 평균 소요시간 차이(YT 평균 22s대 vs IG 평균 2s대)에 맞춰 동시성 차등 적용: `YOUTUBE_PREFETCH_MAX_WORKERS=6`, `INSTAGRAM_PREFETCH_MAX_WORKERS=12`. 기존 `prefetch_youtube_comment_urls()`/`pop_cached_youtube_result()`는 하위 호환용 얇은 래퍼로 유지
- `consumer_reaction_url.py`에 위 일반화된 prefetch를 연결: 시트 내 YT/IG permalink를 채널별로 먼저 훑어 각각 병렬 prefetch
- `media_extractor_v2.py` (신규, HEAD의 `media_extractor.py` 복제): `process_media_assets()`의 순차 `for asset in media_assets` 루프(URL feasibility 검사 + 실제 다운로드)를 `ThreadPoolExecutor(max_workers=8)` 기반 병렬 처리로 변경. asset마다 독립적인 HTTP 호출/파일 쓰기라 경합 없음. YouTube(다운로드 없음)/이미 처리된 asset은 기존처럼 순차 처리 후 병렬 대상만 추림
- `pipeline_service.py`: 신규 함수 `run_2b_and_3_concurrently()` 추가 — 2b(`consumer_reaction_url.py`)와 3단계(`media_extractor`)가 1단계 raw 엑셀만 공통으로 필요로 하는 독립 브랜치임을 이용해(`media_extractor.py`는 2a/2b의 formatted.xlsx가 아니라 raw 엑셀을 직접 읽음, `build_excel_paths()` 확인) 두 모듈을 스레드 2개로 동시 실행. 기존 `run_module()`/`run_single_module()`/`PIPELINE_MODULES`는 전혀 수정하지 않음. `module_timings.csv` 동시 기록 경합 방지용 `_MODULE_TIMING_CSV_LOCK` 추가(순차 호출에는 영향 없음)
- **현재 상태**: 위 신규/복제 파일들은 case2 BEFORE 측정(2,3,4단계)이 끝난 뒤 실제 파이프라인(`PIPELINE_MODULES`, 의존성 검증 등)에 갈아끼우고 case1+case2로 AFTER 재측정 예정. (4) X/FB/TT async 전환 여부는 그 실측 결과를 보고 결정 (코드 변경 없음, 보류)

### case2 BEFORE 측정 방법론 오염 발견 및 재측정

- case2(2026-09-07~09-13, 4배 데이터) BEFORE 베이스라인을 처음 실행했을 때 `raw_to_processed.py`/`comment_extractor.py`가 지난 세션에 이미 커밋된 YT 병렬화(`4112da3`)를 포함한 상태로 돌고 있음을 발견 — YT 병렬화 효과가 섞여 들어가 순수 "before" 기준선이 아니게 됨
- 커밋 `559303b`(DNS 수정은 포함, YT 병렬화는 미포함) 시점으로 `raw_to_processed.py`/`comment_extractor.py`를 임시로 되돌려 case2를 처음부터 재실행. case1의 원래 BEFORE 측정과 동일한 조건으로 맞춤
- 재실행 도중 시스템 메모리 부족으로 백그라운드 프로세스가 강제 종료되는 일이 발생(Claude Code 자체 보호 로직에 의한 종료, 코드 문제 아님) → 이를 계기로 중간 저장(체크포인트) 기능 추가(아래)
- 두 파일은 case2 BEFORE(2,3,4단계) 측정이 모두 끝난 뒤 HEAD 상태로 원복 예정

### 중간 저장(체크포인트) 기능 추가 — 메모리 부족 등 외부 강제종료 대비

- `raw_to_processed.py`(현재 임시로 case1 이전 상태로 되돌려진 버전)와 `consumer_reaction_url.py`(신규 2b 모듈)에 동일한 패턴으로 추가
- 3분마다(`CHECKPOINT_INTERVAL_SECONDS=180`) 워크북 + 진행 상태(JSON: 다음 처리할 행, 완료된 시트, output row 카운터, seen_urls/processed_count 등)를 임시 파일에 저장 후 `os.replace`로 원자적 교체 — 저장 도중 프로세스가 죽어도 기존 체크포인트 파일은 손상되지 않음
- 재실행 시 체크포인트가 있으면 자동으로 그 지점부터 이어서 처리(시트/행 단위로 정확히 재개), 없으면 처음부터 시작
- 정상 완료 시 체크포인트 파일 자동 삭제
- 격리 환경에서 저장→재개→정리 라운드트립 단위 테스트로 검증 완료

### pipeline_service.py 인코딩 버그 수정

- `run_module()`의 `subprocess.Popen(..., text=True, ...)`가 명시적 encoding 없이 시스템 로캘(cp949)로 자식 프로세스 stdout을 디코딩하다가, 한글/이모지가 포함된 UTF-8 출력에서 `UnicodeDecodeError` 발생
- `encoding="utf-8", errors="replace"`를 명시적으로 추가. 이번 세션 전에는 `pipeline_service.py`의 Python API(`run_single_module`/`run_local_campaign_pipeline`)가 실제로 호출된 적이 없어 잠재해 있던 버그였음

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
