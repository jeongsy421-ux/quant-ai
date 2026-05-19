"""
scalper.py - 대급등주(Mega-Surge) 분석 모듈
KIS API 분봉 데이터를 활용하여 +10% 이상의 폭발적 수익 기회를 포착합니다.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict

from stock_data import StockDataCollector
from screener import UNIVERSE, UNIVERSE_MAP

logger = logging.getLogger(__name__)

class Scalper:
    def __init__(self):
        self.collector = StockDataCollector()
        self.universe  = UNIVERSE

    def fetch_intraday_data(self, ticker: str) -> pd.DataFrame:
        """KIS API 분봉 데이터 수집"""
        try:
            from kis_api import get_minute_chart
            # 종목코드 추출 (005930.KS → 005930)
            code = ticker.replace(".KS", "").replace(".KQ", "").replace(".KN", "")
            if not (code.isdigit() and len(code) == 6):
                return pd.DataFrame()

            rows = get_minute_chart(code)
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            # time 컬럼 → datetime 인덱스
            df["datetime"] = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S", errors="coerce")
            df = df.dropna(subset=["datetime"]).set_index("datetime")
            df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
            df = df.sort_index()
            df = df[df["Close"] > 0]

            if len(df) < 5:
                return pd.DataFrame()

            df = self._add_scalping_indicators(df)
            return df
        except Exception as e:
            logger.error(f"[Scalper 데이터 수집 오류] {ticker}: {e}")
            return pd.DataFrame()

    def fetch_intraday_fdr(self, ticker: str) -> pd.DataFrame:
        """FDR 일봉으로 폴백 (분봉 실패 시)"""
        try:
            import FinanceDataReader as fdr
            code = ticker.replace(".KS", "").replace(".KQ", "")
            start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start)
            if df is None or df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.loc[:, ~df.columns.duplicated()].copy()
            df = self._add_scalping_indicators(df)
            return df
        except Exception as e:
            logger.error(f"[FDR 일봉 폴백 오류] {ticker}: {e}")
            return pd.DataFrame()

    def _add_scalping_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """대급등주 분석을 위한 고도화된 지표 추가"""
        close = df["Close"].squeeze()
        vol   = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series([1] * len(df), index=df.index)

        # 1. 단기 이동평균선
        df["MA5"]  = close.rolling(5).mean()
        df["MA20"] = close.rolling(20).mean()
        df["MA60"] = close.rolling(60).mean()

        # 2. 거래량 쇼크 (Volume Shock)
        df["Vol_Avg50"] = vol.rolling(50).mean()
        df["Vol_Shock"] = vol / df["Vol_Avg50"].replace(0, 1)

        # 3. 볼린저 밴드
        df["BB_Mid"]   = close.rolling(20).mean()
        std            = close.rolling(20).std()
        df["BB_Upper"] = df["BB_Mid"] + 2 * std
        df["BB_Width"] = (df["BB_Upper"] - (df["BB_Mid"] - 2 * std)) / df["BB_Mid"].replace(0, 1)

        # 4. 가격 변동성 및 RSI
        df["Price_Change"] = close.pct_change()
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(9).mean()
        loss  = (-delta.clip(upper=0)).rolling(9).mean()
        df["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

        return df

    def analyze_ticker(self, ticker: str) -> Dict:
        """개별 종목의 '대급등' 가능성을 분석합니다."""
        df = self.fetch_intraday_data(ticker)
        if df.empty or len(df) < 10:
            # 분봉 실패 시 일봉으로 폴백
            df = self.fetch_intraday_fdr(ticker)
            if df.empty or len(df) < 10:
                return None

        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        score   = 0
        reasons = []

        def _get_val(series):
            if hasattr(series, 'item'): return series.item()
            if hasattr(series, 'values'): return series.values[0]
            return series

        curr_price   = float(_get_val(latest["Close"]))
        vol_shock    = float(_get_val(latest.get("Vol_Shock", 1)))
        bb_width     = float(_get_val(latest.get("BB_Width", 0)))
        rsi          = float(_get_val(latest.get("RSI", 50)))
        price_change = float(_get_val(latest.get("Price_Change", 0)))
        bb_upper     = float(_get_val(latest.get("BB_Upper", curr_price)))
        ma5          = float(_get_val(latest.get("MA5", curr_price)))
        ma20         = float(_get_val(latest.get("MA20", curr_price)))
        ma60         = float(_get_val(latest.get("MA60", curr_price)))
        prev_ma5     = float(_get_val(prev.get("MA5", ma5)))
        prev_ma20    = float(_get_val(prev.get("MA20", ma20)))

        # [패턴 1] 거래량 쇼크
        if vol_shock > 5.0:
            score += 50
            reasons.append(f"🚀 거래량 쇼크! ({vol_shock:.1f}배 폭발)")
        elif vol_shock > 3.0:
            score += 30
            reasons.append("📈 거래량 급증 중")

        # [패턴 2] 볼린저 밴드 상단 돌파
        if curr_price > bb_upper:
            score += 30
            reasons.append("💥 볼린저 밴드 상단 강력 돌파")

        # [패턴 3] 이평선 정배열
        if ma5 > ma20 > ma60:
            if prev_ma5 <= prev_ma20:
                score += 20
                reasons.append("⭐ 이평선 정배열 골든크로스 발생")
            else:
                score += 10
                reasons.append("✅ 이평선 완벽 정배열 유지")

        # [패턴 4] RSI 모멘텀
        if 50 < rsi < 75:
            score += 10
            reasons.append("⚡ 강력한 매수 모멘텀 (RSI 50+)")

        if score >= 60:
            return {
                "ticker":       ticker,
                "name":         UNIVERSE_MAP.get(ticker, ticker),
                "score":        score,
                "price":        curr_price,
                "change":       price_change,
                "vol_shock":    vol_shock,
                "bb_width":     bb_width,
                "reasons":      reasons,
                "timestamp":    datetime.now().isoformat(),
                "is_mega_surge": score >= 80
            }
        return None

    def get_surging_stocks(self, limit: int = 5) -> List[Dict]:
        """시장에서 대급등 징후가 포착된 종목들을 스캔합니다."""
        logger.info("대급등주 실시간 스캔 가동...")
        candidates = []

        for ticker in self.universe:
            res = self.analyze_ticker(ticker)
            if res:
                candidates.append(res)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scalper = Scalper()
    print("=== 실시간 초단타 급등주 추천 테스트 ===")
    results = scalper.get_surging_stocks()
    for i, res in enumerate(results):
        print(f"{i+1}. {res['name']} ({res['ticker']}) - 점수: {res['score']}")
        print(f"   현재가: {res['price']:,}원 ({res['change']*100:+.2f}%)")
        print(f"   이유: {', '.join(res['reasons'])}")
        print("-" * 30)
