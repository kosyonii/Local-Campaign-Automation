# 설치 및 실행 가이드 (Windows, PowerShell / VS Code)

로컬 PC에서 이 파이프라인을 처음 세팅하고 실행하는 순서입니다. 
세부 설명이 필요하면 `README.md`의 해당 장을 참고합니다.

예상 소요: 최초 세팅 30~60분 (계정/권한 발급 대기 시간 제외)

---

## 0. 시작 전에 받아 둘 것

아래는 담당자에게 요청해서 받아야 합니다. 직접 만들 수 없습니다.

| 항목 | 용도 | 받는 곳 |
|---|---|---|
| GitHub 레포 접근 권한 | 코드 다운로드 | 레포 담당자 |
| Sprinklr API Key, Access Token | 1단계 데이터 추출 | 레포 담당자 |
| Google Cloud 계정 + 프로젝트(`slcc-buzz-agent-dev`) 접근 권한 | 4단계 Gemini 분석 | 레포 담당자 |
| (선택) Instagram `cookies.txt` | IG 미디어 다운로드 성공률 향상 | 2-6단계 참고 |

---

## 1. 프로그램 설치

| 프로그램 | 필요 버전 | 설치 확인 명령 |
|---|---|---|
| Git | 최신 | `git --version` |
| Python | **3.14 이상** (`pyproject.toml` 기준) | `python --version` |
| Microsoft Edge | 최신 (Windows 기본 포함, X·Facebook·TikTok 로그인/수집에 사용) | 시작 메뉴에서 확인 |
| Google Cloud CLI | 최신 (Gemini 인증용) | `gcloud --version` |
| VS Code | 선택 | |
| uv | 선택, 권장 (패키지 설치가 빠르고 버전이 고정됨) | `uv --version` |

설치 후 PowerShell을 **새로 열어서** 위 명령으로 확인합니다.

---

## 2. 최초 1회 세팅

### 2-1. 코드 받기

본인 상황에 맞는 방법 하나만 진행합니다. 어느 쪽이든 검증이 끝난 버전만 올라가는 `main` 브랜치를 사용합니다.

**방법 A. 처음 받는 경우**

```powershell
cd "$HOME\Desktop"    # 레포를 둘 폴더로 이동 (원하는 폴더면 어디든 됨)
git clone https://github.com/kosyonii/Local-Campaign-Automation.git
cd Local-Campaign-Automation
```

**방법 B. 기존 레포(`dkyng11-25/Local-Campaign-Automation`)를 이미 받아 둔 경우**

새로 받을 필요 없이 기존 폴더에서 아래만 실행합니다. `.env`, `.venv`, 브라우저 로그인 세션, `.instagram_cookies.txt`는 git에 올라가지 않는 파일이라 그대로 쓰고, 2-3~2-6단계는 다시 하지 않아도 됩니다.

```powershell
cd "기존_레포_폴더_경로"
git status                  # 직접 수정한 파일이 있는지 확인 (아래 주의 참고)
git remote add seoyeon https://github.com/kosyonii/Local-Campaign-Automation.git
git fetch seoyeon
git checkout -b seoyeon-main seoyeon/main
```

이후 업데이트는 이 브랜치(`seoyeon-main`)에서 `git pull`만 하면 됩니다.

> **주의:** `git status`에 수정된 파일이 보이면(특히 `payload\*.json`) `git checkout`이 막힐 수 있습니다. 직접 수정한 내용이 필요 없다면 `git stash`로 잠시 치워 두고, 필요한 수정이었다면 담당자에게 먼저 문의하세요.
> 기존 레포의 `main` 브랜치는 그대로 두므로 언제든 `git checkout main`으로 돌아갈 수 있습니다.

### 2-2. 가상환경 만들고 패키지 설치

**방법 A. uv 사용 (권장)**

```powershell
uv sync
```

`uv.lock` 기준으로 `.venv`가 만들어지고 필요한 패키지가 모두 설치됩니다.

**방법 B. pip 사용**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install pillow streamlit google-cloud-bigquery
```

> `requirements.txt`에는 `pillow`, `streamlit`, `google-cloud-bigquery`가 빠져 있어서 마지막 줄을 따로 설치합니다.
> `Activate.ps1` 실행이 막히면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행합니다.

VS Code를 쓰는 경우: 폴더를 연 뒤 `Ctrl+Shift+P` → `Python: Select Interpreter` → `.venv`를 선택합니다. 터미널은 VS Code의 PowerShell을 그대로 쓰면 됩니다.

### 2-3. `.env` 파일 만들기

프로젝트 루트(`run_pipeline.py`와 같은 폴더)에 `.env` 파일을 만들고 받은 값을 넣습니다.

```env
SPRINKLR_API_KEY=여기에_키
SPRINKLR_ACCESS_TOKEN=여기에_토큰
```

선택 설정(기본값이 있어서 보통은 필요 없음): `GOOGLE_CLOUD_PROJECT`(기본 `slcc-buzz-agent-dev`), `GEMINI_MODEL`, `GEMINI_MAX_WORKERS`(기본 10).

`.env`는 `.gitignore`에 들어 있어서 git에 올라가지 않습니다.

### 2-4. Google Cloud 로그인 (Gemini 인증)

```powershell
gcloud auth login
gcloud config set project slcc-buzz-agent-dev
gcloud auth application-default login
```

브라우저가 열리면 회사 Google 계정으로 로그인합니다. `Reauthentication failed`, `DefaultCredentialsError`가 나오면 위 로그인을 다시 수행합니다. 이 인증은 만료되므로 **매일 첫 실행 전에 `gcloud auth application-default login`을 다시 하는 것을 권장합니다.**

`gcloud.ps1을 로드할 수 없습니다` 오류가 나오면 `README.md` 6.4의 `gcloud.cmd` 직접 실행 방법을 사용합니다.

### 2-5. 소셜 채널 로그인 (최초 1회)

X, Facebook 댓글 수집은 이 PC 전용 Edge 프로필(`.x_edge_browser_profile`, `.fb_browser_profile` 등)에 로그인한 세션을 씁니다. 이 폴더는 PC마다 따로 만들어지며 git으로 공유되지 않습니다.

1. 파이프라인 실행 중 로그인이 필요하면 Edge 창이 **자동으로 열립니다.**
2. 열린 창에서 해당 계정으로 로그인합니다.
3. 로그인을 마치면 **그 Edge 창을 직접 닫습니다.** 이후 실행부터는 세션을 재사용합니다.
4. 세션이 만료되면 같은 창이 다시 열립니다. 제한 시간은 10분입니다.

사용할 계정은 담당자에게 확인합니다. TikTok은 필요할 때 Edge가 자동 실행됩니다.

### 2-6. (선택) Instagram cookies.txt

IG 미디어 다운로드는 `.instagram_cookies.txt` 파일이 있으면 로그인 쿠키를 사용합니다. 파일이 없으면 쿠키 없이 시도하므로 일부 게시물이 실패할 수 있습니다.

1. Edge/Chrome에 Instagram 로그인
2. 쿠키를 Netscape 형식 `cookies.txt`로 내보내는 확장 프로그램으로 내보내기
3. 프로젝트 루트에 `.instagram_cookies.txt`라는 이름으로 저장 (git에 올라가지 않음)

---

## 3. 설치 확인 (처음 한 번)

프로젝트 루트에서 실행해서 오류가 없는지 봅니다.

```powershell
uv run python -c "import pandas, openpyxl, requests, playwright, yt_dlp, gallery_dl, streamlit, google.genai; print('OK')"
```

`OK`가 출력되면 설치가 끝난 것입니다. pip 방식이면 `.venv`를 활성화한 상태에서 `uv run`을 빼고 `python -c "..."`로 실행합니다.

---

## 4. 파이프라인 실행 (Streamlit 웹 화면)

현재 코드에서 `run_pipeline.py`는 단독 실행 파일이 아니라 Streamlit 화면이 불러 쓰는 모듈입니다. `python run_pipeline.py`로는 아무것도 실행되지 않으므로, 아래 방법으로 실행합니다.

### 4-1. 화면 띄우기

```powershell
uv run streamlit run streamlit_app.py
```

pip 방식: `python -m streamlit run streamlit_app.py`

브라우저가 `http://localhost:8501`로 열립니다. `start_streamlit_server.bat`은 쓰지 않습니다. 이 파일은 다른 PC의 고정 경로를 가리킵니다.
화면을 띄운 PowerShell 창은 실행이 끝날 때까지 닫지 않습니다.

### 4-2. 전체 실행 (1~4단계)

`Full Pipeline` 탭에서 조회 시작/종료 시각을 입력하고 실행 버튼을 누릅니다.

```text
조회 시작 시각: 2026-09-21 00:00:00
조회 종료 시각: 2026-09-27 23:59:59
```

> **종료 시각의 초는 반드시 `59`로 입력합니다.** `00`이면 해당 분의 데이터가 누락될 수 있습니다.

실행 로그에 표시되는 `Output 폴더` / `Media 폴더`(예: `output\260927`, `media\260927`)를 메모해 둡니다. 같은 날짜로 여러 번 실행하면 `_1차`, `_2차` 폴더가 만들어집니다.

단계별 역할:

| 단계 | 파일 | 하는 일 |
|---|---|---|
| 1 | `sprinklr_export_excel.py` | Sprinklr에서 Raw 데이터 추출 |
| 2 | `raw_to_processed.py` | Raw Excel 정제 |
| 3 | `media_extractor.py` | 게시물 이미지·영상 다운로드 |
| 4 | `llm_analysis_pipeline.py` | Gemini 분석 |

다른 탭: `Missing Cases`(누락건 보완), `Individual Module`(단계별 재실행), `Buzz Volume`(별도 실행). 사용법은 `README.md` 3.3, 4장 이후를 참고합니다.

---

## 5. 중간에 끊겼을 때 (이어서 실행)

1~4단계에는 체크포인트가 있어서, **끊겼던 실행 폴더에 같은 단계를 다시 실행하면 이어서 처리합니다.**

> `Full Pipeline`을 다시 실행하면 **새 차수 폴더**가 만들어져서 처음부터 시작합니다. 이어가려면 `Individual Module` 탭을 사용합니다.

### 5-1. Streamlit에서 이어서 실행

1. `Individual Module` 탭을 엽니다.
2. `Module`에서 끊긴 단계를 고릅니다.
3. `Work Date`에 작업 날짜(조회 종료일, 예: 2026-09-27)를 고릅니다.
4. `Existing Run`에서 끊겼던 실행(`output\260927` 등)을 고릅니다.
5. 실행합니다.

### 5-2. PowerShell에서 직접 이어서 실행 (화면이 안 뜰 때)

끊긴 단계 하나만 실행합니다. 예: `output\260927`, `media\260927`

```powershell
# 1단계 (조회 시작/종료 시각을 끊기기 전과 똑같이 입력)
uv run python sprinklr_export_excel.py --output-dir "output\260927"

# 2단계 (작업 날짜 260927 입력)
uv run python raw_to_processed.py --output-dir "output\260927"

# 3단계 (작업 날짜 260927 입력)
uv run python media_extractor.py --output-dir "output\260927" --media-dir "media\260927"

# 4단계 (작업 날짜 260927 입력)
uv run python llm_analysis_pipeline.py --output-dir "output\260927"
```

- 1단계는 **끊기기 전과 같은 시각**을 입력해야 이어집니다(다르면 처음부터 시작).
- 체크포인트는 결과 파일 옆의 숨김 파일(`.xxx.checkpoint.json` 등)입니다. 정상 완료되면 자동 삭제되므로 직접 지우지 않습니다.
- 4단계는 성공한 Gemini 호출은 다시 하지 않고 실패한 행만 재시도합니다.
- 입력 파일이 바뀌었으면 옛 체크포인트는 자동으로 무시됩니다.
- 이미 완성된 결과를 일부러 다시 만들 때만 `--overwrite`(1~3단계), `--overwrite-results`(4단계)를 붙입니다.

---

## 6. 업데이트 받기 (코드가 바뀌었을 때)

실행 중인 작업이 없을 때 진행합니다.

```powershell
git pull
uv sync
```

(2-1 방법 B로 받았다면 `seoyeon-main` 브랜치에 있는 상태에서 실행합니다. `git branch`로 확인할 수 있습니다.)

pip 방식은 `git pull` 후 `pyproject.toml`/`requirements.txt`가 바뀌었을 때만 `python -m pip install -r requirements.txt`를 다시 실행합니다.

`git pull`이 "local changes would be overwritten"으로 막히면, 직접 수정한 파일이 있다는 뜻입니다. 특히 `payload\*.json`은 git이 추적하므로 임의로 수정하지 않습니다. 수정했다면 담당자에게 문의하세요.

---

## 7. 자주 나는 문제

| 증상 | 확인 |
|---|---|
| `python`이 인식되지 않음 | Python 설치 시 "Add to PATH" 체크 여부, PowerShell 재시작 |
| `requires-python >=3.14` 오류 | `python --version`이 3.14 이상인지 확인 |
| `.ps1` 실행 정책 오류 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Sprinklr 401/403 | `.env`의 키와 토큰 값, 만료 여부를 담당자에게 확인 |
| `DefaultCredentialsError`, `Reauthentication failed` | `gcloud auth login`과 `gcloud auth application-default login` 재실행 |
| X/FB 수집이 계속 실패 | 열린 Edge에서 로그인 후 창을 닫았는지 확인. 같은 프로필의 Edge가 이미 열려 있으면 먼저 닫기 |
| IG 미디어 다운로드 실패가 많음 | `.instagram_cookies.txt` 유효 여부 확인 |
| 메모리 부족으로 프로세스가 종료됨 | Edge, VS Code 등을 정리하고 5장의 방법으로 이어서 실행 |

---

## 8. 보안 수칙

공유하거나 커밋하지 않습니다: `.env`, Sprinklr Key/Token, 서비스 계정 JSON, `.instagram_cookies.txt`, 브라우저 프로필 폴더, 고객 데이터가 담긴 Excel(`output\`)과 미디어(`media\`).
위 항목들은 `.gitignore`에 들어 있지만, 새 파일을 만들 때는 `git status`로 한 번 더 확인합니다.
