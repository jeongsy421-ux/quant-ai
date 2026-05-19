"""
screener.py - 시장 전종목 스크리닝 모듈
우량 종목들 스캔, 알고리즘 필터링 후 1위 종목 추출
"""
import logging
import time
import pandas as pd

from typing import List

from stock_data import StockDataCollector
from signal_maker import SignalMaker
from risk_manager import RiskManager
from macro_data import MacroDataCollector
from config import GLOBAL_TICKERS, ETF_UNIVERSE

logger = logging.getLogger(__name__)

# 코스피/코스닥 주요 우량주 및 모멘텀 테마주 매핑
UNIVERSE_MAP = {
    # 우량주
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "068270.KS": "셀트리온",
    "000270.KS": "기아", "051910.KS": "LG화학", "005490.KS": "POSCO홀딩스",
    "035420.KS": "NAVER", "105560.KS": "KB금융", "028260.KS": "삼성물산",
    "012330.KS": "현대모비스", "066570.KS": "LG전자", "032830.KS": "삼성생명",
    "033780.KS": "KT&G", "003670.KS": "포스코퓨처엠", "034730.KS": "SK",
    "018260.KS": "삼성SDS", "055550.KS": "신한지주",
    # 건설/급등 테마 우선 편입
    "047040.KS": "대우건설", "000720.KS": "현대건설", "028050.KS": "삼성엔지니어링",
    "012630.KS": "HDC", "294870.KS": "HDC현대산업개발", "001040.KS": "CJ",
    # 방산/원전
    "012450.KS": "한화에어로", "034020.KS": "두산에너빌리티", "329180.KS": "HD현대중공업",
    "036490.KS": "한국가스공사", "015760.KS": "한국전력", "017670.KS": "SK텔레콤",
    # KOSDAQ 대표주
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "066970.KQ": "엘앤에프",
    "022100.KQ": "포스코DX", "196170.KQ": "알테오젠", "091990.KQ": "셀트리온헬스케어",
    "278280.KQ": "천보", "035900.KQ": "JYP Ent.", "005290.KQ": "동진쎄미켐", "214150.KQ": "클래시스"
}
UNIVERSE = list(UNIVERSE_MAP.keys())


class MarketScreener:
    def __init__(self):
        self.signal_maker = SignalMaker()
        self.risk_manager = RiskManager()
        self.macro_collector = MacroDataCollector()

        # 유니버스 구성: 기존 UNIVERSE + 글로벌 지수 + ETF
        self.full_universe = list(set(
            UNIVERSE +
            list(GLOBAL_TICKERS.values()) +
            [v["ticker"] for v in ETF_UNIVERSE.values()]
        ))

        self.collector = StockDataCollector(self.full_universe)

    def _evaluate_ticker(self, ticker: str, df: pd.DataFrame, is_risk_on: bool, capital: float) -> dict:
        """개별 종목 평가 결론 도출"""
        if df.empty or len(df) < 50:
            return None

        def _get_val(series):
            if hasattr(series, 'item'): return series.item()
            if hasattr(series, 'values'): return series.values[0]
            return series

        try:
            current_price = float(_get_val(df['Close'].iloc[-1]))
            if pd.isna(current_price):
                current_price = 0.0
        except:
            current_price = 0.0

        sig = self.signal_maker.technical_signal(df, is_risk_on=is_risk_on, custom_rsi=25)

        if sig.get("signal") != "BUY":
            return {
                "name": UNIVERSE_MAP.get(ticker, ticker),
                "ticker": ticker,
                "signal": sig.get("signal"),
                "reasons": sig.get("reasons"),
                "score": 0,
                "allocation": 0,
                "shares": 0,
                "current_price": current_price
            }

        returns = df['Daily_Return'].dropna()
        vol_ratio = self.risk_manager.volatility_target_position(returns)
        kelly = self.risk_manager.kelly_position()
        final_pos = min(kelly * vol_ratio, self.risk_manager.max_position)

        buy_amount = capital * final_pos
        if pd.isna(buy_amount):
            buy_amount = 0.0

        shares = int(buy_amount // current_price) if current_price > 0 else 0
        score = float(sig.get('buy_count', 0) * 10 + vol_ratio * 5)

        reasons_str = str(sig.get("reasons", []))
        if "" in reasons_str:
            score += 100.0

        if pd.isna(score):
            score = 0.0

        return {
            "name": UNIVERSE_MAP.get(ticker, ticker),
            "ticker": ticker,
            "signal": "BUY",
            "reasons": sig.get("reasons"),
            "score": score,
            "allocation": float(buy_amount),
            "shares": int(shares),
            "current_price": float(current_price)
        }

    def run_screen(self, capital: float = 2000000.0) -> dict:
        """종목 고속 스캔 및 1순위 추천 도출"""
        logger.info(f"스크리너 가동 시작 (대상 종목수: {len(self.full_universe)}개)")

        all_data = self.collector.fetch_all()

        macro_snapshot = self.macro_collector.get_latest_snapshot()
        macro_score = self.signal_maker.get_market_sentiment_score(macro_snapshot)

        kospi_df = all_data.get("^KS11")
        is_risk_on = self.signal_maker.market_regime_filter(kospi_df, macro_score)

        results = []
        for ticker in self.full_universe:
            df = all_data.get(ticker)
            if df is not None:
                res = self._evaluate_ticker(ticker, df, is_risk_on, capital)
                if res:
                    results.append(res)

        buy_candidates = [r for r in results if r["signal"] == "BUY"]

        if not buy_candidates:
            return {
                "status": "HOLD_ALL",
                "is_risk_on": is_risk_on,
                "top_pick": None,
                "all_results": results
            }

        buy_candidates.sort(key=lambda x: x["score"], reverse=True)
        best_pick = buy_candidates[0]

        logger.info(f"스크리너 추천 완료! 1위 종목: {best_pick['ticker']} (점수: {best_pick['score']})")

        return {
            "status": "BUY_RECOMMENDED",
            "is_risk_on": is_risk_on,
            "top_pick": best_pick,
            "all_results": results
        }

    def scan_momentum_stocks(self, limit: int = 50) -> list:
        """
        KRX 전종목 모멘텀 스캔
        조건: 거래량 1.5배↑ + RSI 30~65 + 당일 등락률 +1%↑
        """
        import FinanceDataReader as fdr
        import time

        # KRX 전종목 가져오기
        try:
            kospi  = fdr.StockListing("KOSPI")[["Code","Name"]].dropna()
            kosdaq = fdr.StockListing("KOSDAQ")[["Code","Name"]].dropna()
            kospi["suffix"]  = ".KS"
            kosdaq["suffix"] = ".KQ"
            all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)
            all_stocks["Code"] = all_stocks["Code"].astype(str).str.zfill(6)
            logger.info(f"[전종목스캔] KRX 전종목 {len(all_stocks)}개 로드")
        except Exception as e:
            logger.error(f"KRX 목록 로드 실패: {e}")
            # fallback: 기존 UNIVERSE_MAP 사용
            all_stocks_list = [(k, v, ".KS" if k.endswith(".KS") else ".KQ")
                               for k, v in UNIVERSE_MAP.items()]
            all_stocks = pd.DataFrame(all_stocks_list, columns=["Code","Name","suffix"])
            all_stocks["Code"] = all_stocks["Code"].str.replace(".KS","").str.replace(".KQ","")

        results = []
        total = len(all_stocks)
        logger.info(f"[전종목스캔] 스캔 시작: {total}개 종목")

        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        end   = datetime.now().strftime("%Y-%m-%d")

        for i, row in all_stocks.iterrows():
            code   = str(row["Code"]).zfill(6)
            name   = str(row["Name"])
            suffix = str(row.get("suffix", ".KS"))

            try:
                df = fdr.DataReader(code, start, end)
                if df is None or df.empty or len(df) < 5:
                    continue

                # 컬럼 정리
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # Close 컬럼 찾기
                close_col = None
                for c in ["Close", "close", "Adj Close"]:
                    if c in df.columns:
                        close_col = c
                        break
                if close_col is None:
                    continue

                close   = float(df[close_col].iloc[-1])
                prev    = float(df[close_col].iloc[-2]) if len(df) >= 2 else close
                if prev == 0:
                    continue
                chg = (close - prev) / prev * 100

                # 거래량
                vol_col = "Volume" if "Volume" in df.columns else "volume"
                if vol_col not in df.columns:
                    continue
                vol     = float(df[vol_col].iloc[-1])
                avg_vol = float(df[vol_col].rolling(20).mean().iloc[-1])
                vol_ratio = vol / avg_vol if avg_vol > 0 else 0

                # RSI
                delta = df[close_col].diff()
                gain  = delta.clip(lower=0).rolling(14).mean()
                loss  = (-delta.clip(upper=0)).rolling(14).mean()
                rsi   = float((100 - 100 / (1 + gain / (loss + 1e-10))).iloc[-1])

                # 조건 필터
                if chg >= 1.0 and vol_ratio >= 1.5 and 30 <= rsi <= 65:
                    score = round(chg * vol_ratio * (65 - rsi) / 100, 3)
                    results.append({
                        "ticker":       code + suffix,
                        "name":         name,
                        "price":        round(close, 0),
                        "change_pct":   round(chg, 2),
                        "volume_ratio": round(vol_ratio, 2),
                        "rsi":          round(rsi, 1),
                        "signal":       "BUY",
                        "score":        score,
                    })

                time.sleep(0.05)

            except Exception as e:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[전종목스캔] 완료: {len(results)}개 조건 충족 / {total}개 스캔")
        return results[:limit]

    def scan_all_stocks(self, limit: int = 100) -> list:
        """
        KRX 전종목 스캔 - 조건 없이 전체 분석
        기간별 예상수익률 계산
        """
        import FinanceDataReader as fdr
        import time
        from datetime import datetime, timedelta

        def get_krx_list():
            df = fdr.StockListing("KRX").dropna(subset=["Marcap", "Volume"])
            df["Code"] = df["Code"].astype(str).str.zfill(6)
            df = df.set_index("Code")
            return df

        try:
            krx = get_krx_list()

            # 성능 최적화: 상위 200개 종목만 스캔 (시총 1000억 이상, 거래량 5만주 이상)
            universe = krx[
                (krx['Marcap'] >= 100_000_000_000) &
                (krx['Volume'] >= 50_000)
            ].nlargest(200, 'Marcap')
            
            logger.info(f"🎯 스캔 대상: {len(universe)}개 종목 (전체 {len(krx)}개 중)")
        except Exception as e:
            logger.error(f"KRX 목록 로드 실패: {e}")
            return []

        # TODO: 추후 aiohttp + asyncio로 비동기 처리 전환 시 3~5배 성능 향상 가능

        results = []
        start = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")
        end   = datetime.now().strftime("%Y-%m-%d")

        for ticker in universe.index:
            row = universe.loc[ticker]
            code   = str(ticker).zfill(6)
            name   = str(row["Name"])
            suffix = ".KQ" if "KOSDAQ" in str(row.get("Market", "")) else ".KS"

            try:
                df = fdr.DataReader(code, start, end)
                if df is None or df.empty or len(df) < 20:
                    continue

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # Close 컬럼
                close_col = next((c for c in ["Close","close","Adj Close"] if c in df.columns), None)
                if not close_col:
                    continue
                vol_col = next((c for c in ["Volume","volume"] if c in df.columns), None)

                closes = df[close_col].dropna()
                if len(closes) < 5:
                    continue

                price = float(closes.iloc[-1])

                # ── 실제 과거 수익률 계산 ──
                def past_return(n):
                    if len(closes) <= n:
                        return 0.0
                    p = float(closes.iloc[-1-n])
                    return round((price - p) / p * 100, 2) if p > 0 else 0.0

                ret_1d  = past_return(1)
                ret_7d  = past_return(5)   # 거래일 기준
                ret_1m  = past_return(22)
                ret_3m  = past_return(66)
                ret_1y  = past_return(252) if len(closes) >= 252 else past_return(len(closes)-1)

                # ── 기술 지표 ──
                delta = closes.diff()
                gain  = delta.clip(lower=0).rolling(14).mean()
                loss  = (-delta.clip(upper=0)).rolling(14).mean()
                rsi   = float((100 - 100/(1+gain/(loss+1e-10))).iloc[-1])

                ma5   = float(closes.rolling(5).mean().iloc[-1])
                ma20  = float(closes.rolling(20).mean().iloc[-1])
                ma60  = float(closes.rolling(60).mean().iloc[-1]) if len(closes)>=60 else ma20

                # 이동평균 위/아래
                ma_score = (1 if price > ma5 else 0) + (1 if price > ma20 else 0) + (1 if price > ma60 else 0)

                # 거래량 비율
                vol_ratio = 1.0
                if vol_col:
                    vol     = float(df[vol_col].iloc[-1])
                    avg_vol = float(df[vol_col].rolling(20).mean().iloc[-1])
                    vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 1.0

                # 모멘텀 점수 (RSI 40~60 최적)
                rsi_score  = max(0, 30 - abs(rsi - 50)) / 30 * 100
                vol_score  = min(vol_ratio * 20, 100)
                ma_score_n = ma_score / 3 * 100

                # ── 기간별 예상수익률 추정 ──
                # 과거 수익률 모멘텀 + 기술 지표 혼합
                def est_return(past_ret, weight_momentum=0.6, weight_tech=0.4):
                    tech = (rsi_score * 0.4 + vol_score * 0.3 + ma_score_n * 0.3) / 100 * 10
                    return round(past_ret * weight_momentum + tech * weight_tech, 2)

                est_1d  = est_return(ret_1d,  0.7, 0.3)
                est_7d  = est_return(ret_7d,  0.6, 0.4)
                est_1m  = est_return(ret_1m,  0.5, 0.5)
                est_3m  = est_return(ret_3m,  0.4, 0.6)
                est_1y  = est_return(ret_1y,  0.3, 0.7)

                # 모멘텀 조건 충족 여부
                is_momentum = (ret_1d >= 1.0 and vol_ratio >= 1.5 and 30 <= rsi <= 65)

                results.append({
                    "ticker":       code + suffix,
                    "name":         name,
                    "price":        round(price, 0),
                    "rsi":          round(rsi, 1),
                    "vol_ratio":    vol_ratio,
                    "ma_score":     ma_score,
                    "is_momentum":  is_momentum,
                    # 실제 과거 수익률
                    "ret_1d":   ret_1d,
                    "ret_7d":   ret_7d,
                    "ret_1m":   ret_1m,
                    "ret_3m":   ret_3m,
                    "ret_1y":   ret_1y,
                    # 예상 수익률
                    "est_1d":   est_1d,
                    "est_7d":   est_7d,
                    "est_1m":   est_1m,
                    "est_3m":   est_3m,
                    "est_1y":   est_1y,
                    # 신호
                    "signal": "BUY" if rsi < 40 and ret_1d > 0 else "SELL" if rsi > 70 else "HOLD",
                })

                time.sleep(0.03)

            except Exception as e:
                continue

        logger.info(f"[전체스캔] 완료: {len(results)}개")
        return results
