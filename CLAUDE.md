# Slack Archive Project

## 프로젝트 목적
Slack 워크스페이스의 전체 메시지를 백업하고, 백업된 데이터를 Slack처럼 채널·스레드 단위로 탐색할 수 있는 셀프호스트 웹앱을 개발한다.

---

## Phase 구분

이 프로젝트는 2단계로 나뉜다. **반드시 Phase 1이 완료된 후 Phase 2를 시작할 것.**

### Phase 1: Slack 데이터 아카이빙
- slackdump로 전체 메시지를 Export (JSON)
- Export된 JSON을 스레드별로 재정리 (TXT + 구조화 JSON)

### Phase 2: 아카이브 뷰어 웹앱 개발
- Export된 데이터를 Slack과 유사한 UI로 브라우징할 수 있는 웹앱 구축
- 채널 목록, 스레드 뷰, 메시지 검색, 유저 프로필 매핑 지원

---

## 핵심 도구 및 파일

### slackdump (v3.x)
- 위치: `./slackdump.exe` (Windows 바이너리)
- GitHub: https://github.com/rusq/slackdump
- 용도: Slack 워크스페이스에서 메시지를 로컬로 내보내기
- 도움말: `slackdump.exe help` 또는 `slackdump.exe help quickstart`

### slack_thread_archive.py
- 위치: `./slack_thread_archive.py`
- 용도: slackdump export ZIP → 스레드별 재정리 (JSON + TXT)
- 의존성: Python 표준 라이브러리만 사용 (추가 설치 불필요)
- 사용법: `python slack_thread_archive.py <export.zip> <출력폴더>`

---

## ⚠️ slackdump 실행 시 필수 주의사항

### 1. 대화형(Interactive) 모드 금지
slackdump의 Wizard(`wiz`) 및 `workspace new` 명령은 대화형 프롬프트(화살표 키, 키보드 입력 대기)를 사용한다.
**Claude Code 터미널에서 대화형 프롬프트는 작동하지 않는다.**

→ 반드시 환경변수 또는 플래그 방식의 비대화형(non-interactive) 인증을 사용할 것.

### 2. 인증 방식 (비대화형)
slackdump는 환경변수로 토큰/쿠키를 전달하면 대화형 로그인을 건너뛴다.

```powershell
$env:SLACK_TOKEN = "xoxc-여기에-토큰"
$env:COOKIE = "xoxd-여기에-쿠키값"
```

**토큰과 쿠키는 사용자가 직접 제공해야 한다. Claude가 임의로 생성하거나 추측하지 말 것.**

사용자에게 토큰/쿠키를 요청할 때 안내 방법:
1. 브라우저에서 Slack 웹앱에 로그인
2. F12 → Application → Cookies → `d` 쿠키값 복사
3. F12 → Console → 아래 코드로 토큰 추출:
   ```js
   JSON.parse(localStorage.localConfig_v2).teams[
     document.location.pathname.match(/^\/client\/([A-Z0-9]+)/)[1]
   ].token
   ```

### 3. 워크스페이스가 이미 등록된 경우
사용자가 이전에 `slackdump workspace new`로 등록했다면 환경변수 없이도 바로 실행 가능.
확인: `slackdump.exe workspace list`

### 4. 인증 정보 보안 규칙
- 토큰/쿠키를 **파일에 하드코딩 금지**
- `.env` 파일 사용 시 `.gitignore`에 반드시 추가
- CLAUDE.md에 실제 토큰/쿠키 기록 금지

---

## Phase 1: 아카이빙 명령어 레퍼런스

### 채널/유저 목록 확인
```powershell
slackdump.exe list channels
slackdump.exe list users
```

### 전체 메시지 Export
```powershell
slackdump.exe export -o ./backup/slack_export.zip
```
- 범위: 접근 가능한 모든 public/private/DM/그룹DM
- 기간: 전체 (기본값)
- 파일: 링크만 JSON에 기록 (원본 다운로드 안 함)

### 특정 채널만 Export
```powershell
slackdump.exe export -o ./backup/partial.zip C01ABC1234 C05XYZ5678
```

### Export 결과 확인
```powershell
slackdump.exe view ./backup/slack_export.zip
```

### 스레드별 TXT/JSON 변환
```powershell
python slack_thread_archive.py ./backup/slack_export.zip ./backup/thread_archive
```

---

## Phase 2: 아카이브 뷰어 웹앱

### 목표
Slack export 데이터를 **Slack과 유사한 UI/UX**로 웹에서 탐색 가능하게 만든다.
서버 없이 로컬에서 실행하거나, 사내 서버에 배포할 수 있어야 한다.

### 기능 요구사항

#### 필수 (MVP)
- [ ] **채널 사이드바**: public/private/DM/그룹DM 채널 목록을 왼쪽 패널에 표시. 채널 유형별 아이콘 구분(#, 🔒, 💬).
- [ ] **메시지 타임라인**: 채널 선택 시 메시지를 시간순으로 표시. 날짜 구분선 포함.
- [ ] **스레드 뷰**: 메시지 클릭/탭 시 해당 스레드의 답글을 오른쪽 패널(또는 인라인)에 표시. 답글 수 표시.
- [ ] **유저 프로필 매핑**: `users.json` 기반으로 유저 ID를 이름·아바타로 변환 표시.
- [ ] **멘션 파싱**: `<@U12345>` 형식의 멘션을 유저 이름으로 변환.
- [ ] **마크다운/서식 렌더링**: Slack의 *bold*, _italic_, `code`, ```코드블록```, >인용, 링크 등 기본 서식 렌더링.
- [ ] **전체 검색**: 채널명, 유저명, 메시지 텍스트 기반 키워드 검색.

#### 선택 (향후 확장)
- [ ] 날짜 범위 필터
- [ ] 메시지 북마크/하이라이트
- [ ] 이모지 리액션 표시
- [ ] 첨부파일 메타정보 표시 (파일명, 크기 — 실제 파일은 없음)
- [ ] 다크모드/라이트모드 토글
- [ ] 채널별 메시지 통계 대시보드

### 기술 스택

#### 권장 구성 (사용자가 Python/Django에 익숙함)
- **프론트엔드**: React 또는 Next.js + Tailwind CSS
- **백엔드**: 아래 중 하나 선택
  - **Option A (경량)**: 백엔드 없이 클라이언트 사이드에서 JSON 직접 로드 (소규모 워크스페이스에 적합)
  - **Option B (중규모)**: FastAPI 또는 Django REST로 JSON 데이터를 서빙하는 API 서버
  - **Option C (대규모)**: Export JSON → SQLite/PostgreSQL로 파싱 후 DB 기반 API
- **검색**: 소규모 → 클라이언트 JS 검색 (Fuse.js 등), 대규모 → SQLite FTS5 또는 별도 인덱스

#### 기술 선택 시 고려사항
- 사용자가 Django/Python에 능숙하므로, 백엔드가 필요하면 Django/FastAPI 우선
- 프론트엔드 코드를 직접 작성할 수도 있고, Claude Code에 맡길 수도 있음
- **워크스페이스 규모를 먼저 확인할 것**: Phase 1의 summary.json에서 총 메시지 수 확인 후 아키텍처 결정

### 데이터 흐름

```
[Phase 1 결과물]                    [Phase 2 웹앱]

slack_export.zip                    ┌─────────────────────┐
  ├── channels.json  ──────────►   │  채널 사이드바        │
  ├── users.json     ──────────►   │  유저 프로필 매핑      │
  ├── #general/                    │                     │
  │   ├── 2025-01-01.json ─────►   │  메시지 타임라인       │
  │   ├── 2025-01-02.json          │  + 스레드 뷰          │
  │   └── ...                      │  + 검색              │
  └── #project/                    └─────────────────────┘
      └── ...

thread_archive/                    (선택: 이미 정리된 스레드
  ├── json/  ──────────────────►    구조를 직접 사용 가능)
  └── txt/
```

### 디자인 참고
- 레이아웃: Slack 데스크톱 앱과 유사한 3-패널 (사이드바 | 메시지 | 스레드)
- 색상/폰트: Slack 기본 테마 참고하되, 커스텀 가능하게
- 반응형: 데스크톱 우선, 태블릿/모바일은 향후 확장

### 기존 오픈소스 참고 (직접 개발 전 검토 권장)
- `slack-export-viewer` (Python/Flask 기반, pip 설치): https://github.com/hfaran/slack-export-viewer
- `SlArchive` (단일 HTML, 클라이언트 사이드): https://github.com/devrelopers/slarchive
- `SlackLogViewer` (C++ 데스크톱 뷰어): GitHub에서 검색

이 프로젝트들을 먼저 살펴보고, 부족한 부분(스레드 뷰, 검색, UI 등)을 자체 개발로 보완하는 전략이 효율적일 수 있다.

---

## 폴더 구조

```
project-root/
├── CLAUDE.md                      ← 이 파일
├── slackdump.exe                  ← slackdump 바이너리
├── slack_thread_archive.py        ← 스레드별 변환 스크립트
├── .gitignore                     ← backup/, .env, node_modules/ 등
│
├── backup/                        ← [Phase 1] 백업 결과물 (gitignore 대상)
│   ├── slack_export.zip           ← slackdump export 결과
│   └── thread_archive/            ← 스레드별 변환 결과
│       ├── txt/
│       ├── json/
│       └── summary.json
│
└── viewer/                        ← [Phase 2] 웹앱 소스코드
    ├── package.json               ← (React/Next.js인 경우)
    ├── src/
    │   ├── components/
    │   │   ├── Sidebar.tsx        ← 채널 목록
    │   │   ├── MessageList.tsx    ← 메시지 타임라인
    │   │   ├── ThreadPanel.tsx    ← 스레드 뷰
    │   │   ├── SearchBar.tsx      ← 검색
    │   │   └── UserAvatar.tsx     ← 유저 프로필
    │   ├── lib/
    │   │   ├── parseExport.ts     ← Slack export JSON 파서
    │   │   ├── search.ts          ← 검색 인덱스
    │   │   └── types.ts           ← TypeScript 타입 정의
    │   └── app/
    │       └── page.tsx           ← 메인 페이지
    └── public/
        └── data/                  ← export JSON을 여기에 배치 (또는 API 서빙)
```

---

## 작업 워크플로우

### Phase 1 실행 순서
1. **인증 확인**: 환경변수(SLACK_TOKEN, COOKIE) 또는 등록된 workspace 확인
2. **채널 목록**: `slackdump.exe list channels` 로 접근 가능 채널 확인
3. **Export**: `slackdump.exe export -o ./backup/slack_export.zip`
4. **검증**: `slackdump.exe view ./backup/slack_export.zip`
5. **변환**: `python slack_thread_archive.py ./backup/slack_export.zip ./backup/thread_archive`
6. **보고**: summary.json 내용을 사용자에게 보여주기 (총 채널 수, 메시지 수, 스레드 수)

### Phase 2 실행 순서
1. **규모 파악**: summary.json에서 총 메시지 수 확인 → 아키텍처 결정 (클라이언트 전용 vs API 서버)
2. **기존 도구 평가**: slack-export-viewer 등 설치해서 기능 비교 → 자체 개발 범위 확정
3. **프로젝트 초기화**: viewer/ 폴더에 프레임워크 셋업
4. **데이터 파서 개발**: Slack export JSON 구조를 앱 내부 타입으로 변환하는 로직
5. **UI 컴포넌트 개발**: 사이드바 → 메시지 리스트 → 스레드 패널 → 검색 순서로
6. **통합 테스트**: 실제 export 데이터로 전체 플로우 검증
7. **배포 설정**: 로컬 실행 또는 사내 서버 배포

---

## 에러 대응

### slackdump 관련
| 에러 | 원인 | 대응 |
|------|------|------|
| `invalid_auth` | 토큰/쿠키 만료 | 브라우저에서 다시 추출하도록 사용자에게 안내 |
| `ratelimited` | Slack API 제한 | 자동 재시도 대기. 보통 자동 복구됨 |
| `not_in_channel` | 접근 권한 없는 채널 | 정상 동작. 해당 채널은 건너뜀 |
| ZIP이 비어있음 | 인증 실패 | `workspace list`로 연결 상태 확인 |
| "알 수 없는 게시자" | 코드 서명 없음 (Windows) | Claude Code 터미널에서는 무시 가능 |

### 웹앱 관련
| 문제 | 대응 |
|------|------|
| JSON 파일이 너무 커서 로드 느림 | SQLite 변환 또는 페이지네이션 도입 |
| 유저 ID가 이름으로 안 바뀜 | users.json 파싱 로직 확인 |
| 스레드 답글이 누락됨 | thread_ts 필드 매핑 로직 확인 (ts == thread_ts이면 부모, ts != thread_ts이면 답글) |
| 한글 깨짐 | JSON 파싱 시 UTF-8 인코딩 확인 |

---

## 제약사항

- slackdump는 **Slack 공식 도구가 아닌** 오픈소스(GPL-3.0) 프로젝트임
- Pro 플랜에서 API로 접근 가능한 메시지만 백업됨 (보존 정책에 의해 삭제된 메시지는 복구 불가)
- **대화형 명령(wiz, workspace new)은 Claude Code 터미널에서 실행하지 말 것**
- Export 시간은 워크스페이스 규모에 따라 수 분~수 시간 소요
- backup/ 폴더는 민감한 대화 내용 포함 → Git 커밋 금지
- 웹앱에서 첨부파일 원본은 표시 불가 (메타정보만 표시 가능)
