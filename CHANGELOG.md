# 수정 로그
# written automatically by claude / revised & reviewed by Seoyeon Ko

## 2026-10-01

### 팀원용 설치·실행 가이드 추가 및 README 실행 안내 정정

- `SETUP_GUIDE.md` 신규: 각자 PC(PowerShell/VS Code)에서 설치 → `.env` → gcloud/Edge 로그인 → Streamlit 실행 → 끊겼을 때 이어서 실행 → 업데이트 순서 안내
- 확인된 사실: 현재 `run_pipeline.py`는 `__main__` 진입점이 없는 모듈(과거 커밋 8b6feab에서 제거)이라 `python run_pipeline.py`로는 아무것도 실행되지 않음. README 3.1·일일 실행 예시를 `streamlit run streamlit_app.py` 안내로 수정(`누락` 폴더의 `run_pipeline.py`는 단독 실행되므로 그대로)
- `requirements.txt`에는 `pillow`, `streamlit`, `google-cloud-bigquery`가 빠져 있음(`pyproject.toml`에는 있음). `requirements.txt`에 세 패키지를 추가해 `pyproject.toml`과 맞춤(2026-10-02). 가이드는 `uv sync` 권장, pip는 `pip install -r requirements.txt` 한 줄로 안내
- 가이드의 새 PC 처음부터 설치는 실제로 따라 해 보지 않음

### 파이프라인 전체 체크포인트(중간 저장) 확대: 1·3·4단계 추가 (2a·2b는 기존)

- 공용 `checkpoint_utils.py`: 임시 파일에 쓴 뒤 `os.replace`로 원자적 교체, 입력 fingerprint(수정 시각+크기) 불일치 시 체크포인트 무시, 3분 간격 저장기(`PeriodicCheckpoint`)
- 1단계 `sprinklr_export_excel.py`: 위젯 하나가 끝날 때마다 워크북+완료 위젯 목록 저장(fingerprint=조회 start/end). 재실행 시 완료된 위젯은 호출하지 않고 이어서 처리, 응답 샘플 임시 폴더 유지. 한계: 위젯은 WIDGET_CONFIGS 순서대로 소비하므로 느린 위젯 뒤에 이미 받은 응답은 크래시 시 다시 받음
- 3단계 `media_extractor.py`: 처리 단계(built, tiktok_done, gallery_dl_done, download_done, gallery_dl_fallback_done, download_fallback_done)와 asset 전체 상태를 저장하고, 다운로드 중에는 3분마다 저장. 실패 시 임시 media 폴더를 남기고 재실행하면 이어서 처리(받은 파일이 없으면 pending으로 되돌려 재다운로드). 한계: TikTok(yt-dlp)·gallery-dl 단계는 단계 종료 시점에만 저장
- 4단계 `llm_analysis_pipeline.py`: 성공한 Gemini 결과를 3분마다 저장(fingerprint=입력 Excel+모델+프롬프트). 재실행 시 성공한 행은 호출하지 않고 복원, 실패 행만 재시도. 최종 Excel 저장 후 체크포인트 삭제
- 검증(가짜 네트워크/Gemini, 실제 호출 없음): 1단계는 중간 크래시 후 재개한 결과가 원본 추출 결과와 완전히 동일(216/235행), 완료 위젯 11개 건너뛰고 1개만 재호출. 3단계는 5건 다운로드 후 크래시, 재개에서 나머지만 처리하고 체크포인트 정리. 4단계는 성공 10건 복원 후 90건만 호출, 입력 파일 변경 시 체크포인트 무시. 실제 Sprinklr·Gemini·다운로드로 끊김/재개를 검증하지는 않음

### media_extractor: Media Type 개수 > Media URL 개수 행 처리 (Row 76 ValueError 대응)

- 원인: Sprinklr가 carousel 내부 asset 타입은 전부 줄바꿈으로 기록했지만 URL은 일부만 준 행에서 `normalize_source_medias`가 개수 불일치로 ValueError
- `normalize_source_medias`: Type > URL이면 오류 대신 URL별 타입을 UNKNOWN으로 두고, 다운로드 시 실제 응답 타입으로 확정(기존 2949·3096줄 동작). 위치 대응이 불가능해 타입을 임의로 짝짓지 않음
- `identify_post_media_type`: URL이 있고 raw Type이 2개 이상이면 게시글 타입을 CAROUSEL로 유지(URL이 1개여도)
- `prepare_campaign_input_for_processing`: URL 1개 + Type 여러 개이면 출력 시트의 Media Type 셀을 `carousel` 1개로 통일(URL 1개 = Type 1개). `normalize_source_medias`는 URL 1개 + `carousel` 1개일 때 asset 타입을 UNKNOWN으로 두고 다운로드 후 확정. `identify_post_media_type`은 raw Type에 carousel이 있으면 CAROUSEL 반환
- `derive_post_media_type`: raw Type이 carousel이면 다운로드 성공 asset이 1개여도 최종 post_media_type을 carousel로 유지(URL 1개 + Type 여러 개 행 대응). 성공 asset 2개 이상이면 종류와 무관하게 carousel인 기존 규칙은 그대로
- 검증: 260927 데이터(2026-09-21 00:00 ~ 09-27 23:59:59, `output/260927`)를 새로 추출해 451행 확인. 이 데이터에는 Type > URL 행이 없어 Row 76은 재현 못 함. 합성 입력으로만 동작 확인(실제 데이터 미검증)

### case1/case2 BEFORE·AFTER 단계별 소요시간 CSV 정리 + 추가 단축 후보 검토 (코드 변경 없음)

- `case_timing_comparison.csv`: case1(4차/7차, 5차 참고)·case2(1차/2차)의 단계별 시간과 2b 채널별 댓글 추출 상세. case1 BEFORE 2단계(4,428.7초)는 `module_timings.csv`가 없어 CHANGELOG 기록값, case2 BEFORE 2단계(5,312초)는 재부팅 중단으로 두 구간 합산 추정값. 댓글 추출 시간은 호출별 합계라 병렬 실행의 wall time이 아님
- 4단계 처리 방식: `llm_input` 시트의 게시물 1행 = Gemini 호출 1회, `ThreadPoolExecutor` 10워커(`GEMINI_MAX_WORKERS`), 재시도 3회, 요청 타임아웃 없음, thinking 설정 없음
- **4단계와 3단계/2b 의존성(코드 확인, 실행 검증은 안 함)**: 4단계 (A) Gemini 호출은 `campaign_media_result.xlsx`(3단계 결과)만 읽고 소비자 댓글 URL은 버림 → 2b와 무관. (B) `map_and_write_formatted_excel`은 2b가 덮어쓴 formatted 엑셀의 댓글 URL을 읽어 같은 파일에 쓰므로 2b 완료 필요. (A)를 3단계 직후 시작하면 추정 절감 case2 약 2,000초, case1 약 1,500초(추정, 4단계 전체를 (A)로 가정)
- **메모리 주의**: PC 15.6GB 중 Edge/VS Code가 약 7GB. case1 5차는 여유 5GB대에서 강제 종료됐고, 완주한 AFTER 측정의 최소 여유도 5.3~5.6GB. 4단계 (A)는 미디어를 inline bytes로 올리므로(게시물당 상한 450MB × 10워커) 2b·3단계와 겹치면 위험. 겹치기 전에 4단계 구간 실제 메모리와 미디어 용량 분포를 확인하고, 겹칠 때는 워커 수를 낮추는 것을 검토
- 기타 후보(미시도): 4단계 요청 타임아웃, thinking 수준 낮추기(품질 비교 필요), 워커 수 증가(429 주의), 2b의 X/FB 병렬화, TT는 항상 0건인데 건당 약 26초 소요
- 남은 일: 4단계 (A)/(B) 분리 및 3단계 직후 시작 구현 여부 결정

## 2026-09-30

### case2 AFTER 측정 (260913, 실행 폴더 `output/260913_2차`) — 중단 없이 완주, 합계 6,584.4초(109.7분)

- 실행 방식: BEFORE의 raw 엑셀만 새 폴더 2차에 복사, 미디어 폴더 새로 생성, 2a → 2b+3단계 동시 → 4단계를 한 번에 실행(중단·재개 없음). 1단계는 raw 재사용. yt-dlp 2026.08.19, `max_comments` 수정 반영(BEFORE와 조건이 다름). 로그 `case2_logs_after/case2_after.log`, 메모리 `case2_logs_after/mem_case2.csv`(최소 여유 5.6GB)
- 폴더명: 차수 검증이 예전 이름을 1차로 인식하지 못해 BEFORE 폴더 `output/260913`, `media/260913`을 `260913_1차`로 이름만 변경(내용 그대로)
- 단계별: 2a 3.5초, 3단계 1,236.5초, 2b 3,205.3초(3단계와 동시, 2b·3 wall 3,205.3초), 4단계 3,375.6초 → **합계 6,584.4초**
- BEFORE 대비: 2단계+3단계 약 7,446초(5,312+2,134) → 3,205.3초로 **약 57% 단축**. 전체 약 9,235초 → 6,584.4초로 **약 29% 단축**. 4단계는 1,750초 → 3,375.6초로 약 93% 증가
- 4단계 지연: `llm_analysis_pipeline.py`는 미수정. 처리 속도 분당 17.7건(프롬프트 토큰 약 11,600/초)으로 case1 7차(분당 16.8건)와 비슷 → Gemini 서버 측 지연으로 추정(확정 못 함). BEFORE 4단계 결과 엑셀에 XML 오류(잘못된 문자)가 있어 BEFORE와 처리 속도 직접 비교는 못 함
- 4단계 결과: 성공 988 / 사용자 조치 필요로 건너뜀 83 / 입력 생성 실패 3 / API 실패 2 (BEFORE 989 / 83 / 3 / 1). API 실패 2건은 500 INTERNAL, 429 RESOURCE_EXHAUSTED(BEFORE는 403 1건). 입력 생성 실패 3건은 BEFORE와 동일(미디어 1,198MB > 450MB 1건, `.m4a` 2건)
- 댓글 URL 추출: BEFORE `comment_extraction_timings.csv`는 재부팅 후 재개 구간 416건만 있어, AFTER에서 같은 URL 416건만 골라 비교. 성공 294 → 297. 채널별 FB 28 → 27, IG 192 → 191, X 74 → 76, TT 0 → 0, YT 0/18 → 3/18. 성공→실패 4건(FB 1, IG 3), 실패→성공 7건(IG 2, X 2, YT 3). YT 403은 로그에 0건
- AFTER 전체(888건) 추출 성공은 681건: FB 27/50, IG 284/341, TT 0/14, X 212/268, YT 158/215. BEFORE 앞 구간(1~482행)은 기록이 소실돼 전체 비교 불가
- 참고: TT 추출 0건은 BEFORE와 동일한 기존 문제(조사 기록 참조). BEFORE YT 0/18은 당시 YouTube 일시 제한 영향으로 보이나 확정 못 함

### case1 AFTER 처음부터 재측정 (260920, 실행 폴더 `output/260920_7차`) — 중단 없이 완주, YT 추출률 BEFORE 수준 회복

- 실행 방식: BEFORE(4차)와 같은 raw 엑셀을 새 폴더 7차에 복사, 미디어 폴더 새로 생성, 2a → 2b+3단계 동시 → 4단계를 한 번에 실행(중단·재개 없음). yt-dlp 2026.08.19, `max_comments` 수정 반영 상태(BEFORE와 조건이 다름). 로그 `case1_logs_v3/after7.log`, 메모리 `case1_logs_v3/mem7.csv`(최소 여유 5.3GB)
- 단계별: 2a 1.8초, 3단계 408.8초, 2b 1,927.6초(3단계와 동시, 2b·3 wall 1,927.6초), 4단계 2,159.9초 → **합계 4,089.3초(68.2분)**. BEFORE 7,314.4초 대비 약 44% 단축
- 4단계가 5차(1,012초)보다 2배 이상 길었음: `llm_analysis_pipeline.py`는 미수정. 641건 제출은 17:18에 끝났고 이후 응답 대기가 길었음(요청 타임아웃 설정 없음, 로그에 403 1건·503 1건). 원인은 Gemini 서버 측 지연으로 추정되나 확정 못 함. 4단계 결과는 BEFORE/5차와 동일(성공 599 / 사용자 조치 필요 40 / API 실패 2)
- 댓글 URL 추출(`comment_extraction_timings.csv`): BEFORE 478 → 7차 494. 채널별 FB 18/21 동일, IG 222 → 221, TT 0/2 동일, X 170 → 187, **YT 68/92 동일**(5차 4/33이었음). YT 403은 로그에 0건. YT 추출 시간 2,479초 → 674초
- 참고: 2b 시간이 5차(약 2,262초, 재개 포함 잠정치)보다 짧고, YT 회귀는 재현되지 않음 → 5차의 YT 하락은 일시적 YouTube 제한이었을 가능성이 높음(확정 아님). X 추출이 늘어난 이유는 미확인
- 4단계 도중 사용자가 formatted 엑셀을 열었으나(`~$` 잠금 파일) 결과 파일 저장에는 영향 없었음

## 2026-09-28

### case1 AFTER 측정 결과 (260920, 실행 폴더 `output/260920_5차`) — 시간은 크게 단축, YT 댓글 URL 추출률은 크게 하락

- 실행 방식: BEFORE(`260920_4차`)와 같은 원본 raw 엑셀을 새 폴더 5차에 복사(미디어 폴더도 새로 만들어 캐시 영향 제거), 2a → 2b+3단계 동시 → 4단계. 1단계는 raw 재사용(BEFORE와 동일). 로그 `case1_logs/case1_after_part1_killed.log`, `case1_logs/case1_after_part2.log`, 메모리 기록 `case1_logs/mem_part2.csv`
- **중간에 메모리 부족으로 강제 종료됨**(19:15 직후): 2b 실행 중 Claude Code가 시스템 메모리 부족으로 백그라운드 프로세스를 중지시킴(코드 오류 아님). 당시 여유 5GB대, 평소 Edge/VS Code가 약 7GB 사용 중이었음. 정리 후(여유 7GB) 2b를 체크포인트(233행, fingerprint 일치)에서 재개, 3단계는 이미 완료돼 2b와 4단계만 재실행. 재개 구간 최소 여유 3.8GB
- AFTER 단계별: 2a 2.1초, 3단계 398.1초(6.6분, 2b와 동시), 2b 앞 구간 약 1,241초(18:55~마지막 체크포인트 19:15:47) + 재개 구간 1,021.1초 = 약 2,262초, 4단계 1,012.2초(16.9분)
- **AFTER 합계 약 3,276초(54.6분)** = 2a 2.1 + 2b·3 wall time 약 2,262 + 4단계 1,012 (종료 직후 재작업분이 앞 구간에 섞여 있어 잠정치)
- BEFORE case1: 2단계 순수 기준(559303b) 4,428.7초 + 3단계 1,925.1초 + 4단계 960.6초 = 7,314.4초(121.9분) → **약 55% 단축**. YT 병렬만 적용한 중간 시도(2단계 2,740.7초)를 기준으로 하면 5,626.4초(93.8분) 대비 약 42% 단축
- 4단계 결과: BEFORE와 API 성공 599 / 사용자 조치 필요 40 / API 실패 2로 동일. 실패 2건은 403 PERMISSION_DENIED 1건, 500 INTERNAL 1건(재시도 없음)
- **품질 회귀 (미해결)**: formatted Excel의 소비자 댓글 URL 추출 건수 BEFORE 478 → AFTER 418. 채널별 FB 18/21 동일, IG 222 → 220, X 170 → 169, TT 0/2 동일, **YT 68/92 → 11/92**. 원인은 확정 못 함. 가능성: 2b의 YT 6개 병렬 prefetch + 동시 실행 중 다른 작업으로 YT 일시 403(yt-dlp `Unable to download API page: HTTP Error 403`) 증가 — AFTER 로그에 403이 앞 구간 55건, 재개 구간 14건 있었음(BEFORE 로그는 stderr 기록 여부가 불분명해 직접 비교 불가). YT 403은 case2 BEFORE에서도 일시적으로 발생해 댓글을 놓친 사례가 있고 재시도가 없음
- **YT 회귀 원인 조사(21:20, 코드 수정 없음)**: 잃은 URL 57건(BEFORE만 성공), 양쪽 성공 11건, AFTER만 성공 0건, 양쪽 실패 24건. 잃은 URL 12건을 현재 추출 함수로 재시도하니 워커 1개(순차)와 6개 모두 **12/12 전부 `HTTP 403`**. 범용 영상(`dQw4w9WgXcQ`)의 댓글 조회도 403, 같은 영상 메타데이터 조회(댓글 제외)는 성공(comment_count 3800). 즉 지금은 **워커 수와 무관하게 이 PC의 YouTube 댓글 API 접근이 막힌 상태**(16시대 프로브 때는 대부분 성공했음). 따라서 AFTER의 YT 추출률 하락은 병렬화가 직접 원인이라기보다, 하루 동안 누적된 호출로 인한 YouTube 측 차단/제한이 실행 중 이미 걸렸을 가능성이 큼(확정은 아님). BEFORE case1의 YT 68/92는 9/27 22:23 결과(당시 YT 병렬 적용)라 병렬 자체는 통과했음
- **YT 차단 확인 결과(23:37)**: 설치된 yt-dlp(2026.07.04)가 최신(2026.08.19)보다 오래돼 `uv pip install -U yt-dlp`로 올린 뒤 댓글 5개 조회가 성공했으나, 같은 시각 **옛 버전(2026.07.04)을 격리 환경(`uv run --isolated`, venv 무변경)에서 돌려도 성공** → 차단은 버전 문제가 아니라 **일시적 제한이었고 21:20(차단) ~ 23:37(해제) 사이 약 2시간 안에 풀림**(16:39에는 성공). 정확한 해제 시각은 모름. 주의: 현재 venv는 2026.08.19로 올라간 상태 — BEFORE는 2026.07.04로 측정했으므로 AFTER 재측정 조건을 맞추려면 되돌리는 것을 권장(`uv pip install yt-dlp==2026.7.4`)
- **YT 재현 테스트 결과(23:49~00:08, yt-dlp를 2026.07.04로 되돌린 뒤)** — 원인 미확정, 가설 여러 개 기각: (a) 잃은 URL 24건으로 워커 1개 순차 테스트는 처음 3건이 전부 403이라 중단(6개 병렬 비교 못 함), (b) 같은 시각 범용 영상과 "양쪽 성공했던" URL은 댓글 5개 조회 성공 → 전면 차단이 아님, (c) 잃은 URL 3건 메타데이터 조회는 성공(공개, 댓글 3,800~4,200개, 연령/라이브 제한 없음), (d) 잃은 URL 하나는 `max_comments=5`로 한 번 성공(4.3초)·`comment_sort=new`도 성공했으나 곧이어 `mweb` 403, `tv`는 "The page needs to be reloaded" 실패, (e) 추출 함수로 6건을 3회씩(5초·10초 백오프) 재시도해도 5건이 계속 403(1건만 1회에 성공), (f) 댓글 수를 20개로 제한해도 6건 전부 403 → **댓글 개수 과다, 워커 수, 짧은 재시도, yt-dlp 버전 어느 것도 원인으로 확인되지 않음**. 시각에 따라 성공/실패가 섞이는 간헐적 제한으로 보이며, 이 테스트의 호출(100회 이상)이 오히려 제한을 연장했을 수 있음 → 더 이상 YT를 두드리지 않고 쿨다운 후 소량으로 재확인 필요
- **YT 재측정(09-30 16:03~16:07, yt-dlp 2026.07.04)**: 잃은 URL 57건 중 15건 재조회. 순차 3건 3/3 성공(건당 25~74초), 6워커 병렬 12건 12/12 성공(wall 107.4초, 건당 32~65초). 403 0건 → **병렬(6워커)은 원인이 아니고 9/28~29의 403은 일시적 제한이 풀린 것으로 판단**. 단, 건당 소요가 정상(약 4초)보다 10배 이상 느려 스로틀링이 남아 있을 가능성. 57건 전수 재조회나 pipeline 재실행은 아직 안 함. 스크립트는 scratchpad(`lost.py`, `probe.py`, `par.py`)
- **YT 속도 저하 원인 확정 + 수정(09-30 16:14~16:25)**: `comment_extractor._extract_with_ytdlp`가 `max_comments`를 `["50,50,0,0,1"]`(문자열 1개)로 넘겼는데, Python API에서는 yt-dlp가 쉼표를 나눠주지 않아 `int_or_none`이 None → **댓글 수 제한이 통째로 무시**되고 있었음(같은 URL이 댓글 1,224개·35초 → 수정 후 50개·2.5초). 이전 주석의 "max_comments를 줄여도 소요시간 차이 없음" 실측도 이 때문이었음. 영상당 요청 수가 수십~수백 배 많았으므로 **YT 403 노출이 커진 것도 이 버그가 원인 후보**(BEFORE/AFTER 모두 해당, 확정은 아님). 수정: `["50","50","0","0","1"]`(top-level 50개, 답글 제외). Back-up의 BEFORE 파일은 그대로 둠
- 수정 후 검증: 잃은 URL 57건 중 42건 재조회 전부 성공(6워커 12건 wall 14.4초[yt-dlp 2026.07.04], 6워커 30건 wall 26.4초·건당 평균 5.1초[2026.8.19]). 수정 전 같은 조건 12건은 wall 107.4초·건당 32~65초. 답글을 더 이상 받지 않으므로 '첫 비작성자 댓글'이 예전과 달라질 수 있음(top-level만 대상) — 파이프라인 전체 재실행으로 추출 결과는 아직 비교 안 함
- **yt-dlp 2026.8.19 반영**: `pyproject.toml`을 `>=2026.8.19`로 올리고 `uv.lock` 갱신, `uv sync`(이때 lock에 없던 pyopenssl 26.3.0이 venv에서 제거됨). 주의: lock과 venv가 어긋난 상태에서 `uv run`을 하면 venv가 lock 버전으로 되돌아감. BEFORE는 2026.07.04로 측정했으므로 AFTER 재측정은 버전이 다름
- 남은 과제: 워커 수별 YT 재측정, 403에 대한 재시도/백오프 추가 검토, case2 AFTER 측정, 앞 구간 채널별 기록은 소실
- 참고: 4단계 API 실패 2건 원인(403/500)은 미확인

### 최적화 2라운드 코드를 실제 파이프라인에 갈아끼움 (AFTER 측정 준비 완료)

- 파일 이름은 그대로 두고 내용만 교체(Streamlit 등 다른 코드가 쓰는 이름 유지): `raw_to_processed.py` ← 2a(정제만, 체크포인트 포함), `comment_extractor.py` ← v2(채널 범용 YT/IG prefetch), `media_extractor.py` ← v2(병렬 다운로드). 중복 방지를 위해 `raw_to_processed_2a.py`, `comment_extractor_v2.py`, `media_extractor_v2.py`는 삭제(git 이력에 남음). BEFORE 원본은 `Back-up/`에 보관
- `consumer_reaction_url.py`(2b)가 `comment_extractor_v2` 대신 `comment_extractor`를 import하도록 수정
- `pipeline_service.py`: `CONSUMER_REACTION_MODULE` 신규 단계 추가(`FOLLOW_UP_MODULES`, `--overwrite` 인자, 의존성 검사: formatted Excel 필요), 전체 파이프라인 루프에서 2b와 3단계(media_extractor)를 `run_2b_and_3_concurrently()`로 **동시에** 실행하고 진행 표시는 두 단계를 함께 started/completed 처리, 이 함수가 `run_paths`를 직접 받도록 확장
- `streamlit_app.py`: 필수 파일 목록과 모듈 라벨에 `consumer_reaction_url.py` 추가
- 확인한 것: 모듈 import, 문법 컴파일, 모듈 목록/의존성 검사(260913 실행 폴더 기준 모두 통과). **실제 파이프라인 실행은 아직 하지 않음** — 2b 전체와 2b/3 동시 실행은 AFTER 측정이 첫 실전 실행
- 손대지 않음: `run_pipeline.py`(옛 독립 복사본, 자체 목록/루프), `누락/` 폴더(자체 모듈 사본), 4단계는 2b 완료 여부를 파일로 확인하지 못하고 파이프라인 순서로만 보장됨(2b를 건너뛰고 4단계만 개별 실행하면 댓글 URL이 비어 있을 수 있음)

### 2b(`consumer_reaction_url.py`) 재실행 멱등성 및 오래된 체크포인트 문제 수정

- **재실행 멱등성**: 2b가 이미 처리한 파일에 다시 돌면 URL 칸 값이 `게시물URL\n댓글URL`이라 이를 통째로 게시물 URL로 추출기에 넘기던 문제 → `extract_post_url()` 추가, 줄바꿈이 있으면 첫 줄만 게시물 URL로 사용(prefetch 대상 수집과 본 루프 모두)
- **오래된 체크포인트**: 2a가 formatted Excel을 새로 만든 뒤에도 옛 체크포인트 워크북에서 조용히 이어가던 문제 → 체크포인트 JSON에 `source_fingerprint`(formatted Excel의 수정 시각+크기)를 저장하고, 불러올 때 현재 파일과 다르거나 값이 없으면 경고 후 무시하고 처음부터 시작
- 검증(네트워크 없이 가짜 추출기로): 같은 시트를 2번 처리해도 두 번 다 깨끗한 permalink가 추출기에 전달됨, 같은 원본이면 이어하기, 원본이 바뀌었거나 fingerprint 없는 옛 체크포인트는 무시됨. 실제 2b 전체 실행은 하지 않음
- 남은 위험: prefetch 구간 중 체크포인트 없음(시간 손해만, 그대로 둠), IG 동시 요청 증가(AFTER 측정에서 IG 실패 건수로 확인 예정)

### BEFORE 파일 복원 + 체크포인트 기능 유지 및 2a 이식

- `raw_to_processed.py`/`comment_extractor.py`를 BEFORE 측정용 559303b 상태에서 HEAD로 복원(YT 병렬 prefetch 복귀). 복원 전에 측정에 쓴 버전을 `Back-up/raw_to_processed_case2_BEFORE_with_checkpoint.py`, `Back-up/comment_extractor_case2_BEFORE_559303b.py`로 보관
- 체크포인트 기능(3분 간격 워크북+진행 상태 원자적 저장, 재실행 시 이어서 처리, 정상 완료 시 정리)은 커밋 안 된 상태로 원본 `raw_to_processed.py`에만 있었음 → 유지: HEAD 복원본에 패치를 그대로 재적용(충돌 없음)하고, `raw_to_processed_2a.py`에도 같은 기능을 이식
- 2a 검증(격리 폴더, case2 raw 엑셀 사본): 중단 없이 실행한 결과와, 도중 강제 종료(`os._exit`) 후 재실행해 체크포인트에서 이어서 완료한 결과가 889행 모두 동일, 완료 후 체크포인트 파일 정리 확인. 2a는 댓글 추출이 없어 전체 실행이 약 2.4초. 원본 `raw_to_processed.py`(HEAD+체크포인트)는 컴파일 확인만 했고 실행 검증은 하지 않음
- **발견한 문제 및 수정**: `consumer_reaction_url.py`는 `raw_to_processed`에서 `wait_for_network_ready`를 import하지만 `raw_to_processed_2a.py`에는 이 함수가 없었음. 2a를 `raw_to_processed.py` 자리에 갈아끼우면 2b가 ImportError로 실행되지 않는 문제 → `wait_for_network_ready`와 `NETWORK_READY_*` 상수, `import socket`을 원본에서 2a로 그대로 옮김. 2a를 `raw_to_processed.py` 이름으로 복사한 임시 폴더에서 `consumer_reaction_url`을 import해 성공 확인(2b 실제 실행은 아님), 2a 재실행도 정상. 앞서 리뷰에서 "필요한 이름이 모두 있다"고 한 것은 잘못이었음

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
