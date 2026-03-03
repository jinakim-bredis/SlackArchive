# Slack Archive Project — Claude Code 실행 프롬프트

> 이 파일을 Claude Code(EDA)에서 프로젝트 폴더를 열고 실행할 때 첫 프롬프트로 붙여넣으세요.
> 프로젝트 루트에 `CLAUDE.md`가 이미 있으므로, Claude Code가 자동으로 컨텍스트를 읽습니다.
> 이 프롬프트는 **Phase 1(데이터 아카이빙)** 작업을 시작시키는 용도입니다.

---

## 프롬프트 본문 (아래를 복사-붙여넣기)

```
이 프로젝트 폴더의 CLAUDE.md를 먼저 읽어줘.

지금부터 CLAUDE.md에 정의된 Phase 1(Slack 데이터 아카이빙)을 실행할 거야.
아래 작업 순서를 하나씩 따라가면서 나를 안내해줘.

각 단계가 끝나면 "다음 단계로 넘어갈까요?" 하고 물어봐.
내가 "응" 또는 "다음"이라고 하면 다음 단계로 넘어가.
문제가 생기면 내가 에러 메시지를 붙여넣을 테니, CLAUDE.md의 에러 대응 섹션을 참고해서 해결책을 알려줘.

---

### Step 0: 사전 확인

아래 항목을 하나씩 확인하고 결과를 보여줘:

1. `slackdump.exe`가 현재 폴더에 있는지 확인:
   ```powershell
   Test-Path ./slackdump.exe
   ```
2. 설치된 버전 확인:
   ```powershell
   ./slackdump.exe version
   ```
3. `slack_thread_archive.py`가 현재 폴더에 있는지 확인:
   ```powershell
   Test-Path ./slack_thread_archive.py
   ```
4. Python이 사용 가능한지 확인:
   ```powershell
   python --version
   ```
5. `backup/` 폴더가 없으면 생성:
   ```powershell
   New-Item -ItemType Directory -Force -Path ./backup
   ```

없는 파일이 있으면 나에게 알려줘. 내가 해결할게.

---

### Step 1: 인증 확인

⚠️ 중요: CLAUDE.md에 명시된 대로, **대화형(interactive) 명령은 절대 실행하지 마.**
`slackdump wiz`, `slackdump workspace new` 같은 명령은 쓰지 않는다.

먼저 이미 등록된 workspace가 있는지 확인해봐:
```powershell
./slackdump.exe workspace list
```

- **워크스페이스가 있으면**: 그 이름을 나에게 보여주고 Step 2로 넘어가.
- **워크스페이스가 없으면**: 나에게 아래 내용을 안내해줘:

  > 인증 정보가 필요합니다. 아래 방법으로 토큰과 쿠키를 가져와주세요:
  >
  > 1. 크롬 브라우저에서 Slack 웹앱(https://워크스페이스.slack.com)에 로그인
  > 2. F12 → Console 탭에서 아래 코드를 붙여넣고 Enter:
  >    ```js
  >    JSON.parse(localStorage.localConfig_v2).teams[
  >      document.location.pathname.match(/^\/client\/([A-Z0-9]+)/)[1]
  >    ].token
  >    ```
  >    → `xoxc-...`로 시작하는 값을 복사
  > 3. F12 → Application 탭 → Cookies → `d` 쿠키 값 복사
  >    → `xoxd-...`로 시작하는 값
  >
  > 두 값을 알려주시면 환경변수로 설정하겠습니다.

  내가 토큰과 쿠키를 제공하면, 환경변수로 설정해줘:
  ```powershell
  $env:SLACK_TOKEN = "사용자가_제공한_토큰"
  $env:COOKIE = "사용자가_제공한_쿠키"
  ```

  ⚠️ 이 값을 절대 파일에 저장하거나 CLAUDE.md에 기록하지 마.

---

### Step 2: 채널 목록 확인

접근 가능한 채널 목록을 가져와서 보여줘:
```powershell
./slackdump.exe list channels
```

결과를 아래 형식으로 요약해줘:
- Public 채널: N개
- Private 채널: N개
- DM: N개
- 그룹 DM: N개
- 총합: N개

---

### Step 3: 전체 메시지 Export

CLAUDE.md에 정의된 export 명령을 실행해줘:
```powershell
./slackdump.exe export -o ./backup/slack_export.zip
```

- 이 작업은 워크스페이스 규모에 따라 **수 분~수 시간** 걸릴 수 있어.
- 실행 중 출력되는 진행 상황을 나에게 보여줘.
- `ratelimited` 에러가 나면 slackdump가 자동 재시도하니까 기다려.
- `not_in_channel` 에러는 정상이야 (접근 불가 채널 건너뜀).

완료되면 파일 크기를 알려줘:
```powershell
Get-Item ./backup/slack_export.zip | Select-Object Length
```

---

### Step 4: Export 검증

내장 뷰어로 결과를 확인해줘:
```powershell
./slackdump.exe view ./backup/slack_export.zip
```

⚠️ `view` 명령도 대화형일 수 있다. 만약 대화형 프롬프트가 뜨면 중단하고,
대신 ZIP 내용을 직접 확인해줘:
```powershell
# ZIP 안의 파일 목록 확인
Add-Type -Assembly System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::OpenRead("./backup/slack_export.zip").Entries | Select-Object FullName, Length | Format-Table
```

확인 결과를 요약해줘:
- ZIP 안의 채널 폴더 수
- 전체 JSON 파일 수
- users.json 존재 여부
- channels.json 존재 여부

---

### Step 5: 스레드별 변환

`slack_thread_archive.py`로 스레드별 TXT/JSON을 생성해줘:
```powershell
python slack_thread_archive.py ./backup/slack_export.zip ./backup/thread_archive
```

완료되면 결과를 확인해줘:
```powershell
# summary.json 내용 출력
Get-Content ./backup/thread_archive/summary.json | ConvertFrom-Json | Format-Table
```

요약:
- 채널별 메시지 수
- 스레드(답글이 있는) 수
- 단독 메시지 수
- 총 메시지 수

---

### Step 6: 최종 보고

Phase 1 완료 보고를 아래 포맷으로 작성해줘:

```
## Phase 1 완료 보고

### Export 정보
- 실행 시간: YYYY-MM-DD HH:MM
- Export 파일: ./backup/slack_export.zip (XX MB)
- 백업 범위: public N개 / private N개 / DM N개 / 그룹DM N개

### 메시지 통계
| 채널명 | 메시지 수 | 스레드 수 | 단독 메시지 |
|--------|-----------|-----------|-------------|
| ...    | ...       | ...       | ...         |

### 결과물 위치
- JSON export: ./backup/slack_export.zip
- 스레드별 TXT: ./backup/thread_archive/txt/
- 스레드별 JSON: ./backup/thread_archive/json/
- 전체 요약: ./backup/thread_archive/summary.json

### Phase 2 준비사항
- 총 메시지 수: N개
- 권장 아키텍처: (메시지 수 기준으로 CLAUDE.md의 Option A/B/C 중 추천)
```

---

## 규칙

1. 각 단계가 끝나면 반드시 **"다음 단계로 넘어갈까요?"** 하고 물어볼 것
2. 에러 발생 시 나에게 에러 메시지를 보여주고 CLAUDE.md 에러 대응 표를 참고해 해결책 안내
3. **대화형(interactive) 명령은 절대 실행하지 말 것** (wiz, workspace new 등)
4. 토큰/쿠키를 파일에 저장하거나 출력하지 말 것
5. 모든 결과물은 ./backup/ 폴더에 저장
6. 한국어로 안내할 것
7. 명령어는 PowerShell 기준

Step 0부터 시작해줘!
```

---

## Phase 2 시작 프롬프트 (Phase 1 완료 후 사용)

Phase 1이 끝나고 웹앱 개발을 시작할 때 아래를 붙여넣으세요:

```
CLAUDE.md를 다시 읽고, Phase 2(아카이브 뷰어 웹앱 개발)를 시작하자.

먼저:
1. ./backup/thread_archive/summary.json을 읽어서 데이터 규모를 파악해줘
2. 총 메시지 수를 기준으로 CLAUDE.md에 정의된 Option A/B/C 중 적합한 아키텍처를 추천해줘
3. CLAUDE.md에 언급된 기존 오픈소스(slack-export-viewer, SlArchive 등)를 빠르게 검토하고,
   우리가 직접 만들어야 할 범위를 정리해줘

그 다음 CLAUDE.md의 Phase 2 실행 순서에 따라 진행하자.
한 단계씩, 내 확인을 받으면서 넘어가줘.
```
