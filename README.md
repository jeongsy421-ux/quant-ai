# Quant AI

주가 데이터 수집·분석과 매매 시그널 생성, 그리고 **개인 금융 컨설팅**을 함께 제공하는 프로젝트입니다.

## 프로젝트 구조

- `backend/` — Flask API 서버 및 핵심 분석 로직
  - `stock_data.py` — 주가 및 기술적 지표 계산
  - `external_data.py` — 거시지표·시장심리 수집
  - `news_collector.py` — 뉴스 및 공시 수집
  - `ai_analyzer.py` — 주가 방향성 예측
  - `risk_manager.py` — 리스크 지표 및 포지션 사이징
  - `kakao_alert.py` — 카카오톡 알림 발송
  - **`finance/`** — 개인 금융 컨설팅 모듈 (가계부·소비계획·투자배분)
- `frontend/` — React/Vite 대시보드
- `data/`, `logs/` — 수집 데이터와 로그
- `tests/` — 테스트
- `docs/` — 문서

## 시작하기

```bash
pip install -r requirements.txt
cp .env.example .env    # 없다면 .env 를 직접 작성
python flask_app.py     # http://localhost:5000
```

`.env` 에 필요한 키: `KAKAO_REST_API_KEY`, `FRED_API_KEY`, `DART_API_KEY`,
`GEMINI_API_KEY` / `GROQ_API_KEY` 등.

## 주요 엔드포인트

### 퀀트

- `GET /` — 백테스트 실행 UI
- `POST /api/run` — 백테스트 시작
- `GET /api/status` — 실행 상태
- `GET /api/download` — 결과 CSV 다운로드

### 개인 금융 컨설팅

- `GET /finance` — 컨설팅 리포트 대시보드
- `GET /api/finance/summary` — 현금흐름 요약
- `GET /api/finance/budget` — 다음 달 소비 계획
- `GET /api/finance/advice` — 저축·투자 배분과 종목 제안
- `POST /api/finance/webhook/sms` — 카드 승인 문자 실시간 수집

## 개인 금융 컨설팅 모듈

가계부 자동 수집 → 소비 분석 → 소비 계획 → 저축·투자 배분까지 한 번에 처리합니다.
표준 라이브러리만으로 동작합니다.

```bash
python -m backend.finance.cli demo      # 샘플 데이터로 체험
python -m backend.finance.cli report    # 컨설팅 리포트

python -m backend.finance.cli import ~/Downloads/신한은행_거래내역.csv
python -m backend.finance.cli sync-email --days 30
python -m backend.finance.cli budget --rate 30
python -m backend.finance.cli advise
```

거래내역 수집 경로는 네 가지입니다 — 카드 승인 알림 **메일(IMAP)**, 문자 알림 **웹훅**,
은행/카드 내역 **파일 폴더 감시**, **오픈뱅킹 API**(이용기관 자격 필요).
은행 계정으로 대신 로그인해 화면을 긁는 스크래핑은 약관 위반이라 구현하지 않았습니다.

설정과 사용법: **[docs/PERSONAL_FINANCE.md](docs/PERSONAL_FINANCE.md)**

> 투자 관련 출력은 정보 제공이며 투자자문이 아닙니다. 최종 판단과 책임은 본인에게 있습니다.

## 테스트

```bash
python -m unittest discover tests -v
```
