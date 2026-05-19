import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import sys
import logging
import schedule
import time
import threading
from datetime import datetime

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

from flask_cors import CORS
import FinanceDataReader as fdr

# 외부 라이브러리 에러 로그 억제
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
logging.getLogger('peewee').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# yfinance 경고 무시
import warnings
warnings.filterwarnings('ignore', category=FutureWarning, module='yfinance')

# 백엔드 모듈 경로 설정
sys.path.insert(0, os.path.dirname(__file__))

from config import GLOBAL_TICKERS, MACRO_TICKERS, SYSTEM, THEME_KEYWORDS

TICKER_MAP = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "005380.KS": "현대차",
    "035420.KS": "NAVER",
    "000270.KS": "기아",
    "012450.KS": "한화에어로",
    "034020.KS": "두산에너빌리티",
    "329180.KS": "HD현대중공업",
    "000001.SS": "상해종합",
}
from stock_data import StockDataCollector
from macro_data import MacroDataCollector
from news_collector import NewsCollector
from ai_analyzer import AIAnalyzer
from signal_maker import SignalMaker
from risk_manager import RiskManager
from kakao_alert import KakaoAlert
from screener import MarketScreener
from scalper import Scalper
from theme_scanner import ThemeScanner
from external_data import get_all_external_data
from auto_learner import start_scheduler, get_learning_status
from analysis import get_full_analysis
from kis_api import get_realtime_price, get_orderbook
from dart_monitor import (

    get_today_disclosures,
    analyze_disclosures,
    get_earnings_disclosures,
    get_upcoming_earnings,
)




# ── 로깅 설정 ─────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Flask 앱 초기화 ───────────────────────────────────────
_cache_ready = False
app = Flask(__name__, static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'build'), static_url_path='')
CORS(app, origins=["http://localhost:5173"])

@app.route('/')
def index():
    """메인 페이지 라우트"""
    return send_from_directory(app.static_folder, 'index.html')


import numpy as np
from flask.json.provider import DefaultJSONProvider

class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.floating)):
            val = obj.item()
            # NaN, Inf 처리 추가
            if np.isnan(val) or np.isinf(val):
                return None
            return val
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):  # pandas NA 처리
            return None
        return super().default(obj)

app.json_provider_class = NumpyJSONProvider
app.json = NumpyJSONProvider(app)

# KRX 전종목 캐시 (앱 시작 시 1회 로드)
_krx_cache = None

def get_krx_all():
    global _krx_cache
    if _krx_cache is None:
        try:
            logger.info("KRX 전종목 로딩 중...")
            kospi  = fdr.StockListing("KOSPI")
            kosdaq = fdr.StockListing("KOSDAQ")
            konex  = fdr.StockListing("KONEX")
            
            kospi["Market"]  = "KOSPI"
            kosdaq["Market"] = "KOSDAQ"
            konex["Market"]  = "KONEX"
            
            all_stocks = pd.concat([kospi, kosdaq, konex], ignore_index=True)
            all_stocks["Code"] = all_stocks["Code"].astype(str).str.zfill(6)
            
            _krx_cache = all_stocks
            logger.info(f"✅ KRX 전종목 로딩 완료: {len(all_stocks)}개")
        except Exception as e:
            logger.error(f"KRX 로딩 실패: {e}")
            _krx_cache = pd.DataFrame()
    return _krx_cache

# ── 서비스 인스턴스 ───────────────────────────────────────
# 지수(GLOBAL_TICKERS)와 개별 종목(TICKER_MAP)을 모두 수집 대상에 포함
monitoring_tickers = list(GLOBAL_TICKERS.values()) + list(TICKER_MAP.keys())
stock_collector = StockDataCollector(list(set(monitoring_tickers)))
macro_collector = MacroDataCollector()
import config as app_config
news_collector  = NewsCollector(app_config)
ai_analyzer     = AIAnalyzer()
signal_maker    = SignalMaker()
risk_manager    = RiskManager()
kakao_alert     = KakaoAlert()
from screener import MarketScreener
market_screener = MarketScreener()
scalper         = Scalper()
theme_scanner   = ThemeScanner()

# ── 캐시 ──────────────────────────────────────────────────
_cache: dict = {}


def _update_all():
    """전체 데이터 업데이트 및 시그널 갱신 (Macro/Sector Aware)"""
    logger.info("=== 전체 업데이트 시작 ===")
    global _cache
    try:
        # 1. 기초 데이터 수집
        stock_data = stock_collector.fetch_all()

        index_map = {
            "^KS11": "KOSPI",
            "^KQ11": "KOSDAQ",
            "^GSPC": "S&P500",
            "^VIX":  "VIX",
            "USDKRW=X": "USD/KRW",
        }
        indices = {}
        for ticker, name in index_map.items():
            df = stock_data.get(ticker)
            if df is not None and not df.empty and len(df) >= 2:
                try:
                    close = float(df["Close"].iloc[-1].item() if hasattr(df["Close"].iloc[-1], 'item') else df["Close"].iloc[-1])
                    prev  = float(df["Close"].iloc[-2].item() if hasattr(df["Close"].iloc[-2], 'item') else df["Close"].iloc[-2])
                    chg = (close - prev) / prev * 100 if prev != 0 else 0
                    indices[name] = {
                        "value": round(close, 2),
                        "change_pct": round(chg, 2),
                        "up": chg >= 0,
                    }
                except Exception as e:
                    logger.error(f"[지수] {name} 오류: {e}")

        logger.info(f"[지수디버그] stock_data 키: {list(stock_data.keys())}")
        logger.info(f"[지수] indices 결과: {indices}")

        macro_snap = macro_collector.get_latest_snapshot()
        market_ctx = stock_collector.fetch_market_context()
        news_res = news_collector.collect()
        
        # 외부 데이터 및 이벤트 확률 계산
        external = get_all_external_data(macro_snap, news_res.get("news", {}).get("trusted", []))
        
        # 코스피 데이터 (마켓 필터용)
        kospi_df = stock_data.get("^KS11", pd.DataFrame())

        # 2. 개별 종목 분석 및 시그널 생성
        signals = {}
        for ticker, df in stock_data.items():
            if df.empty or ticker.startswith("^"):
                continue
            
            res = _analyze_single_ticker(ticker, df, kospi_df, macro_snap, market_ctx, news_res)
            if res:
                signals[ticker] = res
                
                # 시그널 알림 발송
                sig = res.get("signal", {})
                if sig.get("signal") in ("BUY", "SELL"):
                    try:
                        kakao_alert.send_signal_alert(ticker, sig)
                    except Exception as e:
                        logger.error(f"[알림 발송 실패] {ticker}: {e}")

        _cache = {
            "updated_at": datetime.now().isoformat(),
            "signals": signals,
            "macro": macro_snap or {},
            "market_indices": indices,
            "market_context": market_ctx or {},
            "news": news_res or {},
            "external": external or {},
            "status": "active"
        }
        logger.info(f"=== 전체 업데이트 완료 ({len(signals)}개 종목) ===")
        global _cache_ready
        _cache_ready = True
        logger.info("✅ 초기 캐시 로딩 완료")
    except Exception as e:
        logger.error(f"[업데이트 오류] {e}")


def _analyze_single_ticker(ticker, df, kospi_df, macro_snap, market_ctx, news_res):
    """단일 종목에 대해 AI 분석 및 시그널 데이터 생성 (실시간 추가 지원)"""
    try:
        ai_analyzer.train(df)
        ai_res = ai_analyzer.predict(df)
        
        sig = signal_maker.combined_signal(
            ticker=ticker,
            stock_df=df,
            market_df=kospi_df,
            macro_snapshot=macro_snap,
            market_context=market_ctx,
            ai_result=ai_res
        )
        
        risk = risk_manager.risk_report(df)
        
        # 데이터 안전 변환
        def _get_val(series):
            if hasattr(series, 'item'): 
                val = series.item()
            elif hasattr(series, 'values'): 
                val = series.values[0]
            else: 
                val = series
            return float(val) if val is not None else 0.0

        price = _get_val(df["Close"].iloc[-1])
        prev = _get_val(df["Close"].iloc[-2])
        change_pct = (price - prev) / prev * 100 if prev != 0 else 0.0

        rsi_val = 0.0
        if "RSI" in df.columns:
            rsi_val = _get_val(df["RSI"].iloc[-1])

        return {
            "name": TICKER_MAP.get(ticker, ticker),
            "signal": sig,
            "risk": risk,
            "price": price,
            "change_pct": round(change_pct, 2),
            "rsi": rsi_val,
            "news_count": len((news_res.get("news") or {}).get("trusted", []))
        }
    except Exception as e:
        logger.error(f"[실시간 분석 실패] {ticker}: {e}")
        return None


# ── API 엔드포인트 ────────────────────────────────────────

@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    """프론트엔드 대시보드용 통합 데이터 반환"""
    if not _cache_ready:
        return jsonify({
            "status": "loading",
            "message": "초기 데이터 로딩 중... 잠시만 기다려주세요"
        }), 202
    try:
        signals = _cache.get("signals", {})
        # 상위 시그널 추출 (점수 순 정렬)
        top_picks = dict(sorted(signals.items(), key=lambda x: (x[1].get("signal") or {}).get("score") or 0, reverse=True)[:10])
        
        # 캐시된 지수 데이터 가져오기
        indices = _cache.get("market_indices", {})

        dashboard_data = {
            "updated_at": _cache.get("updated_at", datetime.now().isoformat()),
            "market_indices": indices,
            "market_macro": _cache.get("market_context", {}).get("macro", {}),
            "macro": _cache.get("macro", {}),
            "top_signals": top_picks,
            "news_feed": _cache.get("news", {}),
            "status": "active" if "updated_at" in _cache else "updating"
        }
        
        # NaN을 None으로 변환
        if 'market_macro' in dashboard_data and dashboard_data['market_macro']:
            for key, value in dashboard_data['market_macro'].items():
                if isinstance(value, dict):
                    for k, v in value.items():
                        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                            dashboard_data['market_macro'][key][k] = None
                            
        return jsonify(dashboard_data)
    except Exception as e:
        logger.error(f"[Dashboard API] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """서버 상태 확인"""
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/api/signals", methods=["GET"])
def get_signals():
    """전체 종목 시그널 반환"""
    return jsonify(_cache.get("signals", {}))


@app.route("/api/signal/<ticker>", methods=["GET"])
def get_signal(ticker: str):
    """특정 종목 시그널 반환"""
    signals = _cache.get("signals", {})
    if ticker not in signals:
        return jsonify({"error": f"{ticker} 데이터 없음"}), 404
    return jsonify(signals[ticker])


@app.route("/api/macro", methods=["GET"])
def get_macro():
    """거시경제 지표 스냅샷 반환"""
    return jsonify(_cache.get("macro", {}))


@app.route("/api/stock/<ticker>", methods=["GET"])
def get_stock(ticker: str):
    """주가 데이터 및 기술적 지표 반환 (자동 수집 대상 추가 로직 포함)"""
    period = request.args.get("period", "3mo")
    df = stock_collector.fetch_ohlcv(ticker, period=period)
    if df.empty:
        return jsonify({"error": f"{ticker} 데이터 없음"}), 404
    
    # ── [핵심] 검색된 종목 분석 리스트(스크리너)에 실시간 추가 ──
    global _cache
    if "signals" in _cache and ticker not in _cache["signals"]:
        logger.info(f"[실시간 추가] {ticker} 분석 중...")
        # 필요한 컨텍스트 확보
        kospi_df = stock_collector.fetch_ohlcv("^KS11", period="1y")
        macro_snap = macro_collector.get_latest_snapshot()
        market_ctx = stock_collector.fetch_market_context()
        news_res = news_collector.collect()
        
        realtime_res = _analyze_single_ticker(ticker, df, kospi_df, macro_snap, market_ctx, news_res)
        if realtime_res:
            _cache["signals"][ticker] = realtime_res
            # 정기 수집 목록에도 추가
            if ticker not in stock_collector.tickers:
                stock_collector.tickers.append(ticker)
                logger.info(f"[수집 목록 추가] {ticker}가 추적 대상에 등록되었습니다.")

    df = df.reset_index()
    df["Date"] = df["Date"].astype(str)
    
    # MA 계산 추가
    if "Close" in df.columns:
        df["MA5"]  = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()

    # 필수 컬럼
    req_cols = ["Date", "Open", "High", "Low", "Close", "Volume", "MA5", "MA20", "MA60"]
    actual_cols = [c for c in req_cols if c in df.columns]
    
    df = df[actual_cols]
    df = df.tail(60)
    df = df.fillna(0)
    result = df.to_dict(orient="records")
    
    return jsonify(result)


@app.route("/api/risk/<ticker>", methods=["GET"])
def get_risk(ticker: str):
    """특정 종목 리스크 지표 반환"""
    df = stock_collector.fetch_ohlcv(ticker, period="1y")
    if df.empty:
        return jsonify({"error": f"{ticker} 데이터 없음"}), 404
    report = risk_manager.risk_report(df)
    return jsonify(report)


@app.route("/api/screener/recommend", methods=["GET"])
def recommend_stock():
    """스크리너를 구동하여 최고의 주식을 추천"""
    capital_str = request.args.get('capital', '2000000')
    mode = request.args.get('mode', 'long') # 'short' (단타) 또는 'long' (장기)
    
    try:
        capital = float(capital_str)
    except:
        capital = 2000000.0
        
    try:
        # 단타 모드일 경우 Scalper를 사용하여 대급등주 추천
        if mode == 'short':
            surging = scalper.get_surging_stocks(limit=3)
            if surging:
                best = surging[0]
                # 리스크 매니저를 통한 비중 계산 보완
                best['allocation'] = (capital or 0) * 0.1 # 단타는 보수적으로 10% 고정
                best['shares'] = int((best.get('allocation') or 0) // (best.get('price') or 1)) if (best.get('price') or 0) > 0 else 0
                return jsonify({
                    "status": "BUY_RECOMMENDED",
                    "mode": "short",
                    "top_pick": best,
                    "all_results": surging
                })
        
        # 기본 장기/스윙 모드 (기존 MarketScreener 활용)
        result = market_screener.run_screen(capital=capital)
        result["mode"] = "long"
        return jsonify(result)
    except Exception as e:
        logger.error(f"[Screener API] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/intraday/recommendations', methods=['GET'])
def get_intraday_recommendations():
    """단타용 종목 추천 (1일 기대수익률 기준)"""
    try:
        # 1. 전체 스캔에서 1d 기대수익률(est_1d) 상위 3개
        # market_screener.scan_all_stocks는 limit을 매개변수로 받아 리스트를 직접 반환합니다.
        # 응답 지연을 방지하기 위해 상위 50개 정도로 모수를 제한하여 가볍게 가동합니다.
        scan_result = market_screener.scan_all_stocks(limit=50)
        if not scan_result:
            return jsonify({
                'status': 'success',
                'market_condition': '양호',
                'recommendations': [],
                'timestamp': datetime.now().isoformat()
            })
            
        top3 = sorted(scan_result, 
                     key=lambda x: x.get('est_1d', 0.0), 
                     reverse=True)[:3]
        
        # 2. 각 종목별 상세 분석
        recommendations = []
        krx_cache = get_krx_all()
        for stock in top3:
            ticker = stock['ticker']
            cached_data = _cache.get('signals', {}).get(ticker, {})
            
            price = stock.get('price', 0.0)
            rsi = stock.get('rsi', 0.0)
            vol_ratio = stock.get('vol_ratio', 1.0)
            ma_score = stock.get('ma_score', 0)
            
            sig_obj = cached_data.get('signal', {})
            risk_obj = cached_data.get('risk', {})
            
            # AI 앙상블 확률 추출
            ai_ensemble_prob = 0.0
            if sig_obj and 'ai_predict' in sig_obj and sig_obj['ai_predict']:
                ai_ensemble_prob = sig_obj['ai_predict'].get('ensemble_prob', 0.0)
            
            # 종목명이 비어있으면 KRX에서 조회
            name = stock.get('name', '')
            if not name or name == ticker:
                code = ticker.replace('.KS', '').replace('.KQ', '')
                krx_match = krx_cache[krx_cache['Code'] == code]
                if not krx_match.empty:
                    name = krx_match.iloc[0]['Name']
            if not name:
                name = ticker
            
            recommendations.append({
                'ticker': ticker,
                'name': name,
                'expected_return': stock.get('est_1d', 0.0),
                'entry_price': price,
                'stop_loss': price * 0.98,  # -2%
                'take_profit': price * 1.05,  # +5%
                'signal_score': sig_obj.get('score', 0.0),
                'ai_probability': ai_ensemble_prob,
                'risk_score': risk_obj.get('sharpe', 0.0),
                'reasoning': f"RSI {rsi}, 거래량 {vol_ratio}배, 모멘텀 점수 {ma_score}"
            })
        
        # VIX 심리 파악
        macro_vix = 20.0
        if 'macro' in _cache and _cache['macro']:
            macro_vix = _cache['macro'].get('VIX', 20.0)
            if 'vix' in _cache['macro']:
                macro_vix = _cache['macro'].get('vix', 20.0)
        
        return jsonify({
            'status': 'success',
            'market_condition': '주의' if macro_vix > 25 else '양호',
            'recommendations': recommendations,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[Intraday Recommendations API Error] {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/realtime/<ticker>')
def get_realtime(ticker):
    """KIS API로 실시간 현재가 조회 (단타용)"""
    try:
        code = ticker.replace('.KS', '').replace('.KQ', '')
        
        # 1차: KIS API (실시간)
        try:
            from kis_api import KISApi
            kis = KISApi()
            price_data = kis.get_current_price(code)
            if price_data and price_data.get('price'):
                return jsonify({
                    'ticker': ticker,
                    'price': float(price_data['price']),
                    'change_pct': float(price_data.get('change_pct', 0)),
                    'volume': float(price_data.get('volume', 0)),
                    'source': 'KIS',
                    'timestamp': datetime.now().isoformat()
                })
        except Exception as e:
            logger.warning(f"[실시간 KIS 실패] {ticker}: {e}")
        
        # 2차: FDR 폴백 (지연 5~15분)
        import FinanceDataReader as fdr
        df = fdr.DataReader(code, '2026-01-01')
        if not df.empty:
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            change_pct = ((latest['Close'] - prev['Close']) / prev['Close']) * 100
            return jsonify({
                'ticker': ticker,
                'price': float(latest['Close']),
                'change_pct': float(change_pct),
                'volume': float(latest['Volume']),
                'source': 'FDR',
                'timestamp': datetime.now().isoformat()
            })
        
        return jsonify({'error': '데이터 없음'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market/indices')
def get_market_indices():
    """캐시에서 시장 지수만 빠르게 반환 (5초 갱신용)"""
    return jsonify(_cache.get('market_indices', {}))

@app.route("/api/screener/full_scan")
def full_scan():
    """모든 종목에 대해 모멘텀 스캔 최적화 구동"""
    try:
        results = market_screener.scan_momentum_stocks(limit=20)
        return jsonify({
            "count": len(results),
            "results": results,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[전종목스캔 API] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/scan/all")
def scan_all():
    try:
        period = request.args.get("period", "1m")
        results = market_screener.scan_all_stocks(limit=200)

        # 기간별 정렬
        sort_key = {
            "1d":  "est_1d",
            "7d":  "est_7d",
            "1m":  "est_1m",
            "3m":  "est_3m",
            "1y":  "est_1y",
        }.get(period, "est_1m")

        results.sort(key=lambda x: x.get(sort_key, 0), reverse=True)

        return jsonify({
            "period":  period,
            "total":   len(results),
            "results": results[:100],
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[전체스캔] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/simulation/<ticker>", methods=["GET"])
def get_simulation(ticker: str):
    """특정 종목의 몬테카를로 시뮬레이션 결과 반환"""
    df = stock_collector.fetch_ohlcv(ticker, period="1y")
    if df.empty:
        return jsonify({"error": "데이터 없음"}), 404
    
    returns = df["Daily_Return"].dropna()
    curr_price = float(df["Close"].iloc[-1].squeeze())
    
    sim_data = risk_manager.monte_carlo_simulation(returns, curr_price)
    return jsonify({
        "ticker": ticker,
        "current_price": curr_price,
        "simulation": sim_data,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/api/kelly/<ticker>", methods=["GET"])
def get_kelly(ticker: str):
    """켈리 공식 기반 최적 비중 산출"""
    df = stock_collector.fetch_ohlcv(ticker, period="1y")
    if df.empty: return jsonify({"error": "데이터 없음"}), 404
    
    # 임의의 승률/손익비 (실제로는 백테스트 결과에서 가져와야 함)
    # 여기서는 예시로 고정값 또는 단순 계산값 사용
    win_prob = 0.55 # 55% 승률 가정
    win_ratio = 1.5 # 손익비 1.5 가정
    
    pos_size = risk_manager.kelly_position(win_prob, win_ratio)
    return jsonify({
        "ticker": ticker,
        "kelly_position": pos_size,
        "win_probability": win_prob,
        "reward_risk_ratio": win_ratio
    })

@app.route("/api/kakao/history", methods=["GET"])
def get_kakao_history():
    """카카오 알림 이력 반환"""
    return jsonify(kakao_alert.get_history())

@app.route("/api/scalper/surging", methods=["GET"])
def get_surging_stocks():
    """초단타 급등주 추천 리스트 반환"""
    limit = request.args.get('limit', 5, type=int)
    try:
        results = scalper.get_surging_stocks(limit=limit)
        return jsonify({
            "status": "success",
            "count": len(results),
            "data": results,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[Scalper API] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/search/<path:ticker>")
def search_ticker(ticker: str):
    try:
        import FinanceDataReader as fdr
        import pandas as pd
        from datetime import datetime, timedelta

        df   = None
        name = ticker

        # 종목코드 추출 (292150.KQ → 292150)
        code = ticker.replace(".KQ","").replace(".KS","").replace(".KP","").replace(".KN","")

        # 1차: FinanceDataReader
        try:
            start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
            df    = fdr.DataReader(code, start)
            if df is not None and not df.empty:
                try:
                    krx   = fdr.StockListing("KRX")
                    match = krx[krx["Code"] == code]
                    if not match.empty:
                        name = str(match.iloc[0]["Name"])
                except:
                    pass
                logger.info(f"[검색] FDR 성공: {code} ({name}), {len(df)}행")
        except Exception as e:
            logger.warning(f"[검색] FDR 실패: {e}")
            df = None

        # 2차: KIS 일봉 fallback (한국 주식)
        if (df is None or df.empty) and code.isdigit() and len(code) == 6:
            try:
                from kis_api import get_daily_ohlcv
                start_fmt = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
                end_fmt   = datetime.now().strftime("%Y%m%d")
                rows = get_daily_ohlcv(code, start_fmt, end_fmt)
                if rows:
                    df = pd.DataFrame(rows)
                    df["Date"] = pd.to_datetime(df["Date"])
                    df = df.set_index("Date")
                    logger.info(f"[검색] KIS 일봉 성공: {code}, {len(df)}행")
            except Exception as e:
                logger.warning(f"[검색] KIS 일봉 실패: {e}")

        if df is None or df.empty:
            return jsonify({"error": f"'{ticker}' 데이터를 찾을 수 없습니다"}), 404

        # 컬럼 정리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        rename_map = {
            "Adj Close": "Close", "adj close": "Close",
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        if "Close" not in df.columns:
            return jsonify({"error": f"'{ticker}' Close 데이터 없음"}), 404

        # 이동평균선
        df["MA5"]  = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()

        # RSI
        delta = df["Close"].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["RSI"] = 100 - (100 / (1 + gain / (loss + 1e-10)))

        close = float(df["Close"].iloc[-1])
        prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else close
        chg   = (close - prev) / prev * 100 if prev != 0 else 0
        rsi   = float(df["RSI"].iloc[-1]) if not pd.isna(df["RSI"].iloc[-1]) else 50.0

        # 차트 데이터
        df_reset = df.reset_index()
        date_col = next((c for c in df_reset.columns if "date" in str(c).lower()), None)
        if date_col:
            df_reset = df_reset.rename(columns={date_col: "Date"})
        df_reset["Date"] = df_reset["Date"].astype(str).str[:10]

        chart_cols = ["Date","Open","High","Low","Close","Volume","MA5","MA20","MA60"]
        avail      = [c for c in chart_cols if c in df_reset.columns]
        chart_data = df_reset[avail].tail(60).fillna(0).to_dict(orient="records")

        # 가치지표 (KIS API)
        fundamentals = {}
        if code.isdigit() and len(code) == 6:
            try:
                from kis_api import get_fundamentals as kis_fundamentals
                fundamentals = kis_fundamentals(code)
                # 52주 고/저는 로컬 계산
                if len(df) >= 1:
                    fundamentals["52w_high"] = float(df["Close"].rolling(min(252, len(df))).max().iloc[-1])
                    fundamentals["52w_low"]  = float(df["Close"].rolling(min(252, len(df))).min().iloc[-1])
            except:
                pass

        # 리스크
        returns = df["Close"].pct_change().dropna()
        risk = {
            "sharpe":            round(float(returns.mean() / (returns.std() + 1e-10) * (252**0.5)), 2),
            "mdd":               round(float((df["Close"] / df["Close"].cummax() - 1).min()), 4),
            "var_95_1d":         round(float(returns.quantile(0.05)), 4),
            "volatility_annual": round(float(returns.std() * (252**0.5)), 4),
        }

        return jsonify({
            "ticker":       ticker,
            "name":         name,
            "price":        round(close, 0),
            "change_pct":   round(chg, 2),
            "rsi":          round(rsi, 1),
            "chart":        chart_data,
            "fundamentals": fundamentals,
            "risk":         risk,
            "signal": {
                "signal": "BUY" if rsi < 40 else "SELL" if rsi > 70 else "HOLD",
                "score":  round((50 - rsi) / 100, 3),
                "ai_predict": {
                    "ensemble_prob": round(max(0.1, min(0.9, (70 - rsi) / 100)), 2)
                },
                "technical": {"reasons": [
                    f"RSI {round(rsi,1)} — {'과매도 구간 (매수 관심)' if rsi<30 else '과매수 구간 (매도 주의)' if rsi>70 else '중립 구간'}",
                    f"전일 대비 {'+' if chg>=0 else ''}{round(chg,2)}%",
                ]}
            },
        })

    except Exception as e:
        logger.error(f"[종목검색] {ticker}: {e}")
        return jsonify({"error": str(e)}), 500




@app.route("/api/search/name/<query>")
def search_by_name(query: str):
    try:
        query = query.strip()
        krx = get_krx_all()
        
        if krx.empty:
            return jsonify({"error": "종목 데이터 로딩 실패"}), 500

        # 종목명 검색 (부분 일치, 대소문자 무시)
        mask = krx["Name"].str.contains(query, na=False, case=False)
        matched = krx[mask].head(20)

        results = []
        for _, row in matched.iterrows():
            code   = str(row["Code"]).zfill(6)
            market = str(row.get("Market", ""))
            suffix = ".KQ" if market == "KOSDAQ" else ".KN" if market == "KONEX" else ".KS"
            results.append({
                "ticker":   code + suffix,
                "code":     code,
                "name":     str(row["Name"]),
                "market":   market,
                "sector":   str(row.get("Sector", "") or ""),
                "industry": str(row.get("Industry", "") or ""),
            })

        return jsonify({
            "results": results,
            "total":   int(len(krx)),
            "query":   query,
        })

    except Exception as e:
        logger.error(f"[종목명검색] {query}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/krx/all")
def krx_all():
    try:
        krx = get_krx_all()
        if krx.empty:
            return jsonify({"error": "데이터 없음"}), 500
        
        result = []
        for _, row in krx.iterrows():
            code   = str(row["Code"]).zfill(6)
            market = str(row.get("Market",""))
            suffix = ".KQ" if market=="KOSDAQ" else ".KN" if market=="KONEX" else ".KS"
            result.append({
                "code":     code,
                "ticker":   code + suffix,
                "name":     str(row["Name"]),
                "market":   market,
                "sector":   str(row.get("Sector","") or ""),
            })
        
        return jsonify({
            "stocks": result,
            "total":  len(result),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/update", methods=["POST"])
def trigger_update():
    """수동 업데이트 트리거"""
    thread = threading.Thread(target=_update_all, daemon=True)
    thread.start()
    return jsonify({"message": "업데이트 시작됨"}), 202


@app.route("/api/news", methods=["GET"])
def get_news():
    """고도화된 뉴스 및 공시 데이터 반환"""
    news_data = _cache.get("news", {})
    if not news_data:
        # 캐시가 없으면 즉시 수집 시도
        news_data = news_collector.collect()
    return jsonify(news_data)


@app.route("/api/learning/status")
def learning_status():
    from auto_learner import get_learning_status
    return jsonify(get_learning_status())

@app.route("/api/events")
def get_events():
    from external_data import calculate_event_probs
    macro = (_cache.get("macro") or {})
    news = ((_cache.get("news") or {}).get("news") or {}).get("trusted", [])
    return jsonify(calculate_event_probs(macro, news))

@app.route("/api/themes")
def get_themes():
    """테마별 실시간 분석 데이터 반환"""
    data = theme_scanner.scan_all_themes()
    return jsonify(data)

@app.route("/api/themes/search")
def search_themes():
    """테마 및 종목 검색 서비스"""
    query = request.args.get("q", "")
    return jsonify(theme_scanner.search_theme(query))

@app.route("/api/fundamental/<ticker>")
def get_fundamental(ticker):
    """종목의 주요 가치 지표(PER, PBR 등) 제공"""
    result = stock_collector.get_fundamentals(ticker)
    return jsonify(result)

@app.route("/api/analysis/<path:ticker>")
def full_analysis(ticker):
    try:
        result = get_full_analysis(ticker)
        return jsonify(result)
    except Exception as e:
        logger.error(f"[전체분석] {ticker}: {e}")
        return jsonify({"error": str(e)}), 500



@app.route("/api/kis/price/<code>")
def kis_price(code):
    try:
        result = get_realtime_price(code)
        if not result:
            return jsonify({"error": "데이터 없음"}), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/kis/orderbook/<code>")
def kis_orderbook(code):
    try:
        result = get_orderbook(code)
        if not result:
            return jsonify({"error": "데이터 없음"}), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dart/today")

def dart_today():
    try:
        disclosures = get_today_disclosures()
        analyzed    = analyze_disclosures(disclosures)
        return jsonify({
            "total":     len(disclosures),
            "analyzed":  analyzed[:30],
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/dart/earnings")
def dart_earnings():
    try:
        earnings  = get_earnings_disclosures()
        upcoming  = get_upcoming_earnings()
        return jsonify({
            "recent_earnings": earnings[:20],
            "upcoming":        upcoming,
            "timestamp":       datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 스케줄러 ──────────────────────────────────────────────

def _run_scheduler():
    schedule.every(1).hours.do(_update_all)
    while True:
        schedule.run_pending()
        time.sleep(60)

def _schedule_updates():
    try:
        start_scheduler()
    except Exception as e:
        logger.error(f"start_scheduler 오류: {e}")
    _run_scheduler()

if __name__ == '__main__':
    logger.info("="*50)
    logger.info("🔄 Quant AI Dashboard 시작")
    logger.info("="*50)
    
    # 초기 데이터 동기식 로딩
    logger.info("📊 초기 데이터 수집 중...")
    _update_all()
    
    # 백그라운드 갱신 스레드 시작
    logger.info("⏰ 1시간 주기 자동 갱신 시작")
    thread = threading.Thread(target=_schedule_updates, daemon=True)
    thread.start()
    
    # 서버 시작
    port = int(os.getenv('PORT', 5000))
    logger.info(f"🚀 서버 시작: http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)