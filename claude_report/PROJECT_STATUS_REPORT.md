# 📊 Quant AI Dashboard — 프로젝트 진행상황 보고서

> **작성 기준일:** 2026-05-19  
> **작성자:** Antigravity (AI 어시스턴트)  
> **목적:** Claude에게 전달할 전체 구현 현황 및 구조 정리

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **프로젝트명** | Quant AI Dashboard |
| **목적** | 한국 주식(코스피/코스닥) AI 기반 실시간 매매 시그널 및 종목 분석 플랫폼 |
| **스택** | Backend: Flask (Python) / Frontend: React + Vite |
| **투자 규모** | 200만원 단타 기준 (1~3일 보유) |
| **경로** | `C:\Users\jihun\Desktop\quant_ai` |

---

## 2. 디렉터리 구조

```
quant_ai/
├── backend/                  # Flask 백엔드
│   ├── app.py               # 메인 서버 (873줄) — Flask 앱 + API 엔드포인트
│   ├── config.py            # 전역 설정 (API키, 전략, 유니버스, ETF 등)
│   ├── stock_data.py        # OHLCV 수집 (yfinance + FDR + KIS API 폴백)
│   ├── macro_data.py        # 거시경제 데이터 수집
│   ├── news_collector.py    # 뉴스 수집 (네이버 API + 신뢰도 분류)
│   ├── ai_analyzer.py       # XGBoost + RandomForest + GradientBoosting 앙상블
│   ├── signal_maker.py      # 매매 시그널 생성 (기술+AI+매크로 결합)
│   ├── risk_manager.py      # 리스크 관리 (켈리, VaR, 몬테카를로, MDD)
│   ├── screener.py          # 시장 전종목 스크리닝 (KOSPI+KOSDAQ)
│   ├── scalper.py           # 초단타 급등주 감지 모듈
│   ├── theme_scanner.py     # 테마별 실시간 주가 스캔 (22개 테마, 100여개 종목)
│   ├── theme_data.py        # 테마 데이터 정의 (30,376 bytes)
│   ├── analysis.py          # 종목 전체 분석 (기술지표 + 밸류에이션 + 수급 + DART)
│   ├── kis_api.py           # 한국투자증권 API (실시간 현재가, 호가, 일봉, 기본정보)
│   ├── dart_monitor.py      # DART 공시 모니터링
│   ├── external_data.py     # 외부 데이터 (CNN F&G, FedWatch 등 14개 소스)
│   ├── auto_learner.py      # AI 자동학습 (퀀트 사이트 크롤링 → Gemini 분석 → DB 저장)
│   ├── backtester.py        # 백테스팅 모듈
│   ├── kakao_alert.py       # 카카오 알림 발송
│   └── data/
│       └── learning.db      # SQLite (자동학습 결과 저장)
│
├── frontend/                 # React + Vite 프론트엔드
│   └── src/
│       ├── App.jsx           # 메인 앱 (1,188줄) — 전체 UI
│       ├── App.css           # 스타일
│       └── index.css         # 전역 스타일
│
├── data/                     # 캐시 데이터 (CSV, DB)
│   ├── learning.db
│   ├── macro_*.csv           # 거시경제 데이터 캐시
│   └── stock_*.csv           # 종목별 주가 데이터 캐시 (100+ 파일)
│
├── logs/                     # 로그 파일
├── .env                      # API 키 환경변수
├── requirements.txt          # Python 의존성
└── claude.md                 # 기존 이슈 노트 (참조)
```

---

## 3. 핵심 백엔드 모듈 상세

### 3.1 `app.py` — Flask 메인 서버

**포트:** `5000` (기본값, `.env`에서 변경 가능)  
**CORS:** `http://localhost:5173` (Vite 개발 서버)  
**데이터 흐름:**
1. 앱 시작 시 `_update_all()` 백그라운드 스레드 실행
2. 이후 **1시간 주기** 자동 갱신 (schedule 라이브러리)
3. 데이터는 `_cache` 딕셔너리에 인메모리 저장

**핵심 함수:**
```python
def _update_all():
    # 1. 주가/지수 데이터 수집 (StockDataCollector)
    # 2. 거시경제 스냅샷 (MacroDataCollector)
    # 3. 마켓 컨텍스트 + 뉴스 수집
    # 4. 외부 데이터 (CNN F&G, FedWatch 등)
    # 5. 개별 종목 AI 분석 + 시그널 생성
    # 6. 카카오 BUY/SELL 알림 발송
```

**NaN/Inf 처리:** `NumpyJSONProvider` 커스텀 클래스로 JSON 직렬화 시 null 변환

**KRX 전종목 캐시:** 앱 시작 시 1회 로드 → `_krx_cache` 전역 변수

---

### 3.2 API 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 서버 상태 확인 |
| GET | `/api/dashboard` | 대시보드 통합 데이터 |
| GET | `/api/signals` | 전체 종목 시그널 |
| GET | `/api/signal/<ticker>` | 특정 종목 시그널 |
| GET | `/api/macro` | 거시경제 지표 |
| GET | `/api/stock/<ticker>` | 주가 + 기술지표 (OHLCV + MA5/20/60) |
| GET | `/api/risk/<ticker>` | 리스크 지표 (Sharpe, MDD, VaR) |
| GET | `/api/screener/recommend` | 종목 추천 (mode=long/short) |
| GET | `/api/screener/full_scan` | KRX 전종목 모멘텀 스캔 |
| GET | `/api/scan/all` | 전종목 기대수익률 분석 (period=1d/7d/1m/3m/1y) |
| GET | `/api/simulation/<ticker>` | 몬테카를로 시뮬레이션 |
| GET | `/api/kelly/<ticker>` | 켈리 공식 비중 산출 |
| GET | `/api/search/<ticker>` | 종목 코드 검색 |
| GET | `/api/search/name/<query>` | 종목명 검색 |
| GET | `/api/krx/all` | KRX 전종목 리스트 |
| GET | `/api/news` | 실시간 뉴스 |
| GET | `/api/themes` | 테마별 분석 데이터 |
| GET | `/api/themes/search` | 테마/종목 검색 |
| GET | `/api/analysis/<ticker>` | 종목 전체 분석 (기술+밸류+수급+DART) |
| GET | `/api/fundamental/<ticker>` | 가치 지표 (PER, PBR 등) |
| GET | `/api/kis/price/<code>` | KIS 실시간 현재가 |
| GET | `/api/kis/orderbook/<code>` | KIS 실시간 호가창 |
| GET | `/api/dart/today` | 오늘 공시 목록 |
| GET | `/api/dart/earnings` | 실적 공시 |
| GET | `/api/scalper/surging` | 급등주 리스트 |
| GET | `/api/learning/status` | AI 자동학습 현황 |
| GET | `/api/events` | 이벤트 확률 (Polymarket 스타일) |
| POST | `/api/update` | 수동 업데이트 트리거 |
| GET | `/api/kakao/history` | 카카오 알림 이력 |

---

### 3.3 `signal_maker.py` — 하이브리드 시그널 생성

**시그널 공식:**
```
final_score = (기술지표 × 0.4) + (AI예측 × 0.4) + (매크로심리 × 0.1) + (섹터보정 × 0.1)

BUY  if final_score > 0.15
SELL if final_score < -0.15
HOLD otherwise
```

**매크로 심리 점수 구성 (−1.0 ~ +1.0):**
- Fear & Greed Index → 가중치 40%
- VIX → 가중치 30%
- 장단기 금리차(Yield Spread) → 가중치 30%

**마켓 레짐 필터:**
- KOSPI < MA200 AND 매크로 < -0.3 → 매수 차단 (HOLD 강제)

**초단타 급등 감지:**
- 거래량 2.5배 이상 + (MA20 돌파 OR 일간 수익률 5% 이상) → BUY 시그널 우선

---

### 3.4 `screener.py` — 시장 스크리닝

**대상 유니버스:** KOSPI 대형주 30개 + KOSDAQ 10개 + 글로벌 지수 + ETF 5개

**모멘텀 스캔 조건:**
- 당일 등락률 ≥ +1.0%
- 거래량 비율 ≥ 1.5배 (20일 평균 대비)
- RSI 30~65 구간

**전체 스캔(`scan_all_stocks`):**
- KRX 전종목 FDR DataReader 조회
- 기간별 과거 수익률 계산 (1d/5d/22d/66d/252d)
- 모멘텀 점수 = RSI 점수(40%) + 거래량 점수(30%) + MA 위치(30%)
- 기대수익률 = 과거수익률 모멘텀 × 0.3~0.7 + 기술지표 점수 × 0.3~0.7

---

### 3.5 `theme_scanner.py` — 테마 분석

**커버리지:** 22개 테마, 100여개 종목 (theme_data.py 정의)  
**캐시 TTL:** 5분  
**데이터 소스:** FinanceDataReader (FDR)  

**각 테마별 수집 지표:**
- 현재가, 등락률, 1주/1달 수익률
- 거래량 비율 (20일 평균 대비)
- RSI
- 급등 여부 (거래량 비율 ≥ 2.0)

**테마 카테고리:** 정치/정책, 기술/산업, 지정학/글로벌, 사회이슈, 자연재해/계절, 에너지

---

### 3.6 `analysis.py` — 종목 전체 분석

**분석 구성 4개 축:**

1. **기술지표 (`get_technical`):** MA5/20/60/120, RSI, MACD, 볼린저밴드, 거래량비율, 52주 고/저, MDD
2. **밸류에이션 (`get_valuation_naver`):** PER, PBR, ROE, 시가총액 (네이버 금융 크롤링 + FDR)
3. **수급 (`get_supply_naver`):** 개인/외국인/기관 5일 누적 순매수 (네이버 모바일 API)
4. **DART (`get_dart_financials`):** 매출액, 영업이익, 당기순이익, 부채비율 (공시 API)

**종합 점수:** 이동평균(25%), RSI(25%), MACD(25%), 볼린저밴드(25%), PER, ROE 반영

---

### 3.7 `kis_api.py` — 한국투자증권 API

**기능:**
- OAuth2 Bearer 토큰 발급 (23시간 캐시)
- 실시간 현재가 (`FHKST01010100`)
- 실시간 호가창 (`FHKST01010200`) — 매도/매수 10호가
- 분봉 데이터 (`FHKST03010200`)
- 일봉 데이터 (`FHKST03010100`) — FDR 폴백용
- 기본정보/가치지표 (`FHKST01010300`) — PER, PBR, EPS, BPS

**환경변수:** `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT` (.env)

---

### 3.8 `auto_learner.py` — AI 자동학습

**실행 주기:** 매일 새벽 6시 (schedule)  
**학습 소스:** Quantocracy, Ernest Chan Blog, QuantInsti, QuantStart  

**학습 파이프라인:**
1. 사이트 크롤링 → BeautifulSoup 파싱
2. SQLite DB 저장 (`articles`, `analysis_results`, `strategy_updates`, `learning_reports`)
3. Gemini 2.0 Flash로 전략 분석 → JSON 인사이트 추출
4. 파라미터 업데이트 제안 → `config.py` 자동 수정 가능

**AI 모델:** `gemini-2.0-flash` (google.generativeai)

---

### 3.9 `config.py` — 전역 설정

**주요 설정값:**

```python
STRATEGY = {
    "total_capital":    2_000_000,  # 200만원
    "buy_threshold":    65,
    "sell_threshold":   65,
    "stop_loss_pct":    -3.0,       # 손절 -3%
    "take_profit_pct":  5.0,        # 익절 +5%
    "max_positions":    3,
    "kelly_fraction":   0.5,        # 하프 켈리
    "max_hold_days":    3,
}

SCAN_FILTER = {
    "min_market_cap":    50_000_000_000,  # 시총 최소 500억
    "min_volume":        100_000,
    "min_trade_amount":  3_000_000_000,   # 거래대금 30억+
    "max_rsi":           45,
    "min_volume_ratio":  1.3,
}

GLOBAL_TICKERS = {
    "S&P500", "NASDAQ", "KOSPI", "KOSDAQ",
    "NIKKEI", "상해", "대만", "DAX", "VIX", "USD/KRW"
}

ETF_UNIVERSE = {
    "KODEX200", "TIGER미국S&P500", "KODEX국채", "TIGER금선물", "KODEX리츠"
}

EVENTS = [  # Polymarket 스타일 이벤트 예측
    "이번 FOMC 금리 동결 (기본 확률 78%)",
    "삼성전자 실적 서프라이즈 (62%)",
    "반도체 관세 실제 시행 (45%)",
]
```

---

## 4. 프론트엔드 구조 (`App.jsx`, 1188줄)

**기술 스택:** React (Vite), recharts, lucide-react  
**API 연결:** 동일 호스트 상대경로 (`API_URL = ""` → 프록시 사용)  
**자동 갱신:** 30초 interval

**네비게이션 메뉴:**

| 메뉴 | 컴포넌트/기능 |
|------|--------------|
| 대시보드 | 시장 지수, Top3 종목 추천, 전체 종목 표 |
| 종목 스캔 | KRX 전종목 기대수익률 분석 (기간별: 1d/7d/1m/3m/1y) |
| 테마 분석 | 22개 테마 스캔, 거래량 급등 종목 |
| 뉴스 분석 | 실시간 뉴스 피드 |
| 포트폴리오 | 저장된 전략, 종목 비교 (최대 4개) |
| AI 자동학습 | 학습 현황 표시 |

**종목 상세 팝업 기능:**
- 60일 캔들차트 (ComposedChart + Bar로 OHLC 표현)
- MA5/MA20/MA60 이동평균선 overlay
- 매매 신호 + AI 앙상블 확률
- 리스크 지표 (Sharpe, MDD, VaR)
- 종합 분석 (기술지표 스코어카드, 수급, DART 재무)

**종목 검색 기능:**
- 코드 입력 → `/api/search/<code>` 직접 조회
- 종목명 입력 → `/api/search/name/<query>` → 상위 10개 상세 조회 → 예상수익률 순 정렬

---

## 5. 데이터 소스 및 의존성

**Python 패키지:**
```
flask, flask-cors, schedule, pandas, numpy, scipy
yfinance, FinanceDataReader
scikit-learn, xgboost
google-generativeai (Gemini 2.0 Flash)
dart-fss, fredapi
requests, beautifulsoup4
sqlite3 (내장)
```

**외부 API:**
| API | 용도 | 키 변수 |
|-----|------|---------|
| 한국투자증권 (KIS) | 실시간 현재가, 호가, 일봉, 기본정보 | `KIS_APP_KEY`, `KIS_APP_SECRET` |
| Gemini AI | AI 분석 + 자동학습 | `GEMINI_API_KEY` |
| DART 공시 | 재무정보, 공시 | `DART_API_KEY` |
| FRED | 미국 금리, 경제지표 | `FRED_API_KEY` |
| Naver 뉴스 | 한국 뉴스 수집 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| Kakao | 매매 알림 발송 | `KAKAO_REST_API_KEY`, `KAKAO_ACCESS_TOKEN` |
| FinanceDataReader | KRX 전종목 주가 | 무료 |
| yfinance | 글로벌 지수, 선물 | 무료 |

---

## 6. 알려진 이슈 및 현재 상태

### 6.1 과거 오류 (기존 claude.md 기준)

| 오류 | 원인 | 해결 현황 |
|------|------|-----------|
| `unsupported operand type(s) for /: 'NoneType' and 'int'` | `external_data.py` NoneType 나눗셈 | ✅ `(value or 0) / (count or 1)` 방어코드 추가 |
| `Cannot set a DataFrame with multiple columns to the single column MA5` | yfinance MultiIndex 컬럼 | ✅ `df.columns.get_level_values(0)` 처리 |
| 카카오 알림 401 오류 | 액세스 토큰 만료 | ⚠️ `.env` 토큰 갱신 필요 |
| 대시보드 빈 화면 | `_cache` 초기 로딩 지연 | ✅ 앱 시작 시 `_update_all()` 즉시 실행 |
| React activeNav 라우팅 미작동 | `renderContent()` 조건 누락 | ✅ 수정 완료 |

### 6.2 현재 진행 중인 이슈

1. **KIS API 실시간 데이터:** 토큰은 발급되나, 일부 TR_ID 응답 불일치 가능성 있음
2. **requirements.txt 인코딩 오류:** 파일 일부 바이트가 깨져 있음 (`\u0000` 포함) — 재작성 필요
3. **전종목 스캔 속도:** `scan_all_stocks`가 FDR API를 종목별로 순차 호출하여 3~5분 소요

---

## 7. 구현된 핵심 기능 체크리스트

### 백엔드
- [x] Flask REST API 서버 (25+ 엔드포인트)
- [x] 1시간 주기 자동 데이터 갱신 (백그라운드 스레드)
- [x] KRX 전종목 주가 수집 (FinanceDataReader)
- [x] 글로벌 지수 수집 (yfinance: S&P500, NASDAQ, VIX 등)
- [x] AI 앙상블 모델 (XGBoost + RandomForest + GradientBoosting)
- [x] 하이브리드 시그널 (기술 40% + AI 40% + 매크로 10% + 섹터 10%)
- [x] 마켓 레짐 필터 (하락장 시 BUY 차단)
- [x] 리스크 관리 (켈리 공식, 변동성 타겟, VaR, 몬테카를로)
- [x] 종목 스크리너 (모멘텀 + 전종목 기대수익률 스캔)
- [x] 테마 스캐너 (22개 테마, 5분 캐시)
- [x] 종목 전체 분석 (기술+밸류+수급+DART)
- [x] KIS API 연동 (실시간 현재가, 호가, 일봉, 기본정보)
- [x] DART 공시 모니터링
- [x] 뉴스 수집 + 신뢰도 분류
- [x] Gemini AI 자동학습 (매일 새벽 6시)
- [x] 카카오 BUY/SELL 알림
- [x] SQLite 학습 결과 영속화

### 프론트엔드
- [x] React + Vite SPA
- [x] 대시보드 (시장 지수, Top3 추천, 전체 종목 표)
- [x] 종목 상세 팝업 (60일 캔들차트 + MA 오버레이)
- [x] KRX 전종목 기대수익률 스캔 (기간별 5종)
- [x] 22개 테마 분석 화면
- [x] 뉴스 피드
- [x] 종목 검색 (코드/종목명)
- [x] 종목 비교 (최대 4개)
- [x] 전략 저장/불러오기 (localStorage)
- [x] AI 자동학습 현황 표시
- [x] 30초 자동 갱신

---

## 8. Claude에게 전달할 주요 질문 및 검토 요청

### Q1. `_cache` 빈 화면 문제 (재현 가능성)
`_update_all()`이 백그라운드 스레드로 실행되는데, 완료 전에 `/api/dashboard`를 호출하면 빈 캐시를 반환합니다. 프론트엔드에서 `status: "updating"` 처리는 있지만, 첫 로드 시 빈 화면이 수 분간 지속될 수 있습니다.

→ **초기 로딩 상태 표시 개선 방법** 또는 **캐시 미리 채우기 전략** 제안 요청

### Q2. KRX 전종목 스캔 성능 병목
`scan_all_stocks()`에서 FDR DataReader를 종목별 순차 호출 + `time.sleep(0.03)` 적용 중. KOSPI+KOSDAQ 약 2,500개 종목 기준 약 75초+ 소요.

→ **비동기 처리(asyncio/aiohttp)** 또는 **분산 큐(Celery)** 전환 적합성 검토 요청

### Q3. yfinance vs FinanceDataReader 이중화 전략
현재 글로벌 지수는 yfinance, 한국 종목은 FDR + KIS API 폴백 구조.

→ **데이터 소스 우선순위 및 폴백 로직 최적화** 방안 제안 요청

### Q4. requirements.txt 파일 손상
현재 파일에 UTF-16 인코딩 잔재 (`\u0000` 바이트)로 일부 패키지명이 깨져 있음.

→ 정상적인 requirements.txt 재작성 버전 제안 요청

---

## 9. 실행 방법

```bash
# 백엔드 (터미널 1)
cd C:\Users\jihun\Desktop\quant_ai\backend
python app.py
# → http://localhost:5000

# 프론트엔드 (터미널 2)
cd C:\Users\jihun\Desktop\quant_ai\frontend
npm run dev
# → http://localhost:5173
```

---

## 10. 참고 파일 목록 (전달 권장)

| 파일 | 크기 | 중요도 |
|------|------|--------|
| `backend/app.py` | 873줄 / 31KB | ⭐⭐⭐ |
| `frontend/src/App.jsx` | 1188줄 / 80KB | ⭐⭐⭐ |
| `backend/config.py` | 232줄 / 10KB | ⭐⭐⭐ |
| `backend/signal_maker.py` | 199줄 / 8KB | ⭐⭐⭐ |
| `backend/screener.py` | 394줄 / 16KB | ⭐⭐ |
| `backend/analysis.py` | 294줄 / 13KB | ⭐⭐ |
| `backend/auto_learner.py` | 768줄 / 27KB | ⭐⭐ |
| `backend/kis_api.py` | 277줄 / 9KB | ⭐⭐ |
| `backend/theme_scanner.py` | 191줄 / 8KB | ⭐ |
| `.env` | 2.9KB | ⭐⭐⭐ (키 확인용) |

---

*이 보고서는 Antigravity AI 어시스턴트가 코드베이스 전수 분석 후 자동 생성했습니다.*
