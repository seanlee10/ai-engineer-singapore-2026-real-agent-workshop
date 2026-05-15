# Legal RAG UI

법률 문서 기반 RAG(Retrieval-Augmented Generation) 챗봇의 웹 인터페이스입니다. LangGraph 백엔드와 연동하여 법률 관련 질의응답을 제공합니다.

## 기술 스택

- **Next.js 16** (App Router, Turbopack)
- **React 19** + **TypeScript**
- **@assistant-ui/react** — 대화형 UI 프레임워크
- **LangGraph SDK** — 백엔드 API 연동
- **Tailwind CSS 4** + **shadcn/ui** — 스타일링 및 UI 컴포넌트
- **Zustand** — 상태 관리

## 시작하기

### 1. 환경 변수 설정

`.env.local` 파일을 생성하고 다음 변수를 설정하세요:

```
LANGCHAIN_API_KEY=your_api_key
LANGGRAPH_API_URL=your_langgraph_api_url
NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID=your_assistant_id
```

### 2. 의존성 설치

```bash
npm install
```

### 3. 개발 서버 실행

```bash
npm run dev
```

브라우저에서 [http://localhost:3000](http://localhost:3000)을 열어 확인하세요.

## 주요 명령어

| 명령어 | 설명 |
|--------|------|
| `npm run dev` | 개발 서버 실행 (Turbopack) |
| `npm run build` | 프로덕션 빌드 |
| `npm run start` | 프로덕션 서버 실행 |
| `npm run lint` | ESLint 검사 |
| `npm run prettier` | 코드 포맷 검사 |
| `npm run prettier:fix` | 코드 포맷 자동 수정 |

## 프로젝트 구조

```
app/
├── assistant.tsx          # 메인 챗봇 컴포넌트 (LangGraph 런타임 연동)
├── api/[..._path]/route.ts # LangGraph API 프록시
├── globals.css            # Tailwind 테마 및 디자인 토큰
└── layout.tsx             # 루트 레이아웃

components/
├── assistant-ui/          # 채팅 UI 컴포넌트 (메시지, 마크다운, 첨부파일 등)
└── ui/                    # shadcn/ui 기본 컴포넌트

lib/
├── chatApi.ts             # LangGraph SDK 클라이언트
└── utils.ts               # 유틸리티 함수
```
