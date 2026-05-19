<<<<<<< HEAD
# Quant AI Project

이 프로젝트는 주가 데이터 수집, 거시경제 지표 분석, 뉴스 수집 및 AI 모델을 활용한 매매 시그널 생성 시스템입니다.

## 프로젝트 구조

- `backend/`: Flask 기반 API 서버 및 핵심 분석 로직
  - `app.py`: 메인 엔트리포인트 (Flask 서버 및 스케줄러)
  - `stock_data.py`: 주가 및 기술적 지표 계산
  - `macro_data.py`: FRED 거시경제 지표 수집
  - `news_collector.py`: 뉴스 및 공시 수집
  - `ai_analyzer.py`: XGBoost 기반 주가 방향성 예측
  - `signal_maker.py`: 복합 매매 시그널 생성
  - `risk_manager.py`: 리스크 지표 및 포지션 사이징
  - `kakao_alert.py`: 카카오톡 알림 발송
- `frontend/`: (향후 구현 예정) 웹 인터페이스
- `data/`: 수집된 데이터(CSV) 저장 폴더
- `logs/`: 시스템 로그 저장 폴더

## 시작하기

1. **패키지 설치**
   ```bash
   pip install -r requirements.txt
   ```

2. **환경 변수 설정**
   `.env` 파일을 열어 API 키들을 설정하세요.
   - `KAKAO_REST_API_KEY`: 카카오 REST API 키
   - `FRED_API_KEY`: FRED API 키
   - `DART_API_KEY`: DART API 키

3. **서버 실행**
   ```bash
   python backend/app.py
   ```

## 주요 API 엔드포인트

- `GET /api/signals`: 전체 종목의 매매 시그널 확인
- `GET /api/stock/<ticker>`: 특정 종목의 가격 데이터 조회
- `GET /api/macro`: 최신 거시경제 지표 확인
- `POST /api/update`: 데이터 즉시 업데이트 트리거
=======
# quant-ai
>>>>>>> 2de1e47cf66b4e597550f422de1a94cb4002423c
