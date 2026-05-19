"""
macro_data.py - 거시경제 데이터 수집 모듈
FRED API를 통한 주요 거시경제 지표 수집
"""
import os
import logging
import pandas as pd
from datetime import datetime
from fredapi import Fred
from config import FRED_API_KEY, SYSTEM

# config.py에서 누락된 경우를 위한 기본 FRED 시리즈 코드
FRED_SERIES = {
    "US_FED_FUNDS": "FEDFUNDS",
    "KR_INT_RATE":  "INTDSRKRM193N",
    "US_10Y":       "DGS10",
    "US_2Y":        "DGS2",
    "VIX":          "VIXCLS",
    "CPI":          "CPIAUCSL",
    "UNRATE":       "UNRATE",
    "DXY":          "DTWEXBGS"
}

logger = logging.getLogger(__name__)


class MacroDataCollector:
    """FRED 거시경제 데이터 및 시장 심리 지표 수집기"""

    def __init__(self):
        if not FRED_API_KEY:
            logger.warning("[FRED] API 키가 설정되지 않았습니다.")
            self.fred = None
        else:
            self.fred = Fred(api_key=FRED_API_KEY)

    def fetch_series(self, series_id: str, start: str = "2020-01-01") -> pd.Series:
        """단일 FRED 시리즈 수집"""
        if self.fred is None:
            logger.error("[FRED] API 키 없음 - 데이터 수집 불가")
            return pd.Series(dtype=float)
        try:
            data = self.fred.get_series(series_id, observation_start=start)
            logger.info(f"[FRED] {series_id}: {len(data)}개 데이터")
            return data
        except Exception as e:
            logger.error(f"[FRED 오류] {series_id}: {e}")
            return pd.Series(dtype=float)

    def get_fear_and_greed_index(self, df: pd.DataFrame) -> float:
        """
        시장 심리 지표(Fear & Greed) 정교화 (0~100)
        VIX, 장단기 금리차, 달러 인덱스, CPI 추세를 결합
        """
        if df.empty or "VIX" not in df.columns:
            return 50.0
            
        try:
            # 1. VIX 기반 심리 (VIX가 높을수록 공포)
            vix = float(df["VIX"].iloc[-1])
            vix_score = max(0, min(100, 100 - (vix - 12) * 3)) 
            
            # 2. 장단기 금리차 (역전 시 공포)
            if "US_10Y" in df.columns and "US_2Y" in df.columns:
                yield_spread = float(df["US_10Y"].iloc[-1] - df["US_2Y"].iloc[-1])
                spread_score = 50 + (yield_spread * 50) 
            else:
                spread_score = 50
            
            # 3. 달러 인덱스 추세 (달러 강세 시 공포)
            if "DXY" in df.columns:
                dxy_curr = float(df["DXY"].iloc[-1])
                dxy_ma = float(df["DXY"].rolling(20).mean().iloc[-1])
                dxy_score = 50 - (dxy_curr - dxy_ma) * 10
            else:
                dxy_score = 50
            
            # 4. 인플레이션 압력 (CPI 상승 시 공포)
            if "CPI" in df.columns:
                cpi_change = df["CPI"].pct_change(12).iloc[-1] # YoY
                infl_score = max(0, min(100, 100 - (cpi_change - 0.02) * 1000))
            else:
                infl_score = 50

            fear_greed = (vix_score * 0.4) + (spread_score * 0.3) + (dxy_score * 0.2) + (infl_score * 0.1)
            return round(max(0, min(100, fear_greed)), 2)
        except:
            return 50.0

    def fetch_all_macro(self, start: str = "2020-01-01") -> pd.DataFrame:
        """주요 거시경제 지표 전체 수집 후 DataFrame 반환"""
        frames = {}
        for name, sid in FRED_SERIES.items():
            s = self.fetch_series(sid, start)
            if not s.empty:
                frames[name] = s

        if not frames:
            return pd.DataFrame()

        df = pd.DataFrame(frames)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().ffill()
        
        # 장단기 금리차 계산
        if "US_10Y" in df.columns and "US_2Y" in df.columns:
            df["YIELD_SPREAD"] = df["US_10Y"] - df["US_2Y"]

        # Fear & Greed Index 추가
        df["FEAR_GREED"] = [self.get_fear_and_greed_index(df.loc[:idx]) for idx in df.index]

        self._save(df)
        return df

    def get_latest_snapshot(self) -> dict:
        """최신 거시경제 지표 스냅샷 반환"""
        df = self.fetch_all_macro()
        if df.empty:
            return {}
        return df.iloc[-1].to_dict()

    def _save(self, df: pd.DataFrame) -> None:
        data_dir = SYSTEM.get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        fname = os.path.join(data_dir, f"macro_{datetime.now().strftime('%Y%m%d')}.csv")
        df.to_csv(fname, encoding="utf-8-sig")
        logger.info(f"[저장] {fname}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=== 거시경제 지표 수집 테스트 시작 ===")
    collector = MacroDataCollector()
    df = collector.fetch_all_macro()
    if not df.empty:
        print("\n[최근 5일 거시경제 지표]")
        cols = ["US_FED_FUNDS", "KR_INT_RATE", "VIX", "FEAR_GREED"]
        available_cols = [c for c in cols if c in df.columns]
        print(df[available_cols].tail(5))
    else:
        print("데이터 수집 실패")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=== 거시경제 지표 수집 테스트 시작 ===")
    collector = MacroDataCollector()
    df = collector.fetch_all_macro()
    if not df.empty:
        print("\n[최근 5일 거시경제 지표 - 환율, 금리, VIX 포함]")
        cols = [c for c in ["us_10y_yield", "vix", "krw_usd"] if c in df.columns]
        if cols:
            print(df[cols].tail(5))
        else:
            print(df.tail(5))
    else:
        print("데이터 수집 실패")
