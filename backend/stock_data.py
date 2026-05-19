"""
stock_data.py - 주식 데이터 수집 모듈
KIS API(한국 주식) + FinanceDataReader(글로벌 지수)를 이용한 주가/거래량 데이터 수집 및 기술적 지표 계산
"""
import os
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from config import GLOBAL_TICKERS, MACRO_TICKERS, SYSTEM, ETF_UNIVERSE

logger = logging.getLogger(__name__)

KRX_API_KEY = os.getenv("KRX_API_KEY", "")
KRX_BASE = "https://openapi.krx.co.kr/contents/COM/GenerateOTP.jspx"
KRX_DATA = "https://openapi.krx.co.kr/contents/SRT/99/SRT990201T3.jspx"

def krx_get_otp(api_id: str) -> str:
    """KRX OTP 발급"""
    params = {
        "bld": f"dbms/MDC/STAT/standard/{api_id}",
        "name": "fileDown",
        "key": KRX_API_KEY,
    }
    res = requests.get(KRX_BASE, params=params, timeout=10)
    res.encoding = "utf-8"
    return res.text.strip()

def krx_fetch(api_id: str, params: dict) -> list:
    """KRX 데이터 조회"""
    otp = krx_get_otp(api_id)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://openapi.krx.co.kr",
    }
    data = {"code": otp, **params}
    res = requests.post(KRX_DATA, data=data, headers=headers, timeout=15)
    res.encoding = "utf-8"
    try:
        json_data = res.json()
        return json_data.get("output", json_data.get("OutBlock_1", []))
    except:
        return []

def get_krx_stock_list(market: str = "STK") -> list:
    """KRX 전종목 리스트 (API 실패 시 FinanceDataReader 백업)"""
    if not KRX_API_KEY or "발급" in KRX_API_KEY:
        try:
            import FinanceDataReader as fdr
            logger.info(f"[백업] FDR을 통해 {market} 종목 리스트 수집")
            m_map = {"STK": "KOSPI", "KSQ": "KOSDAQ", "KNX": "KONEX"}
            df = fdr.StockListing(m_map.get(market, "KOSPI"))
            return [{"code": r["Code"], "name": r["Name"], "market": market, "sector": r.get("Sector", "")} for _, r in df.iterrows()]
        except Exception as e:
            logger.error(f"[백업실패] {e}")
            return []

    api_map = {"STK": "stk_isu_base_info", "KSQ": "ksq_isu_base_info", "KNX": "knx_isu_base_info"}
    api_id = api_map.get(market, "stk_isu_base_info")
    today = datetime.now().strftime("%Y%m%d")
    rows = krx_fetch(api_id, {"trdDd": today, "mktId": market, "share": "1", "money": "1"})

    if not rows:
        return get_krx_stock_list_fdr(market)

    result = []
    for row in rows:
        result.append({
            "code": row.get("ISU_SRT_CD", ""), "name": row.get("ISU_ABBRV", ""),
            "market": market, "sector": row.get("SECT_TP_NM", ""),
            "per": row.get("PER", ""), "pbr": row.get("PBR", ""),
        })
    return result

def get_krx_stock_list_fdr(market):
    try:
        import FinanceDataReader as fdr
        m_map = {"STK": "KOSPI", "KSQ": "KOSDAQ", "KNX": "KONEX"}
        df = fdr.StockListing(m_map.get(market, "KOSPI"))
        return [{"code": r["Code"], "name": r["Name"], "market": market, "sector": r.get("Sector", "")} for _, r in df.iterrows()]
    except:
        return []

def get_krx_daily(code: str, market: str = "STK", days: int = 60) -> list:
    """
    KRX 일별 매매정보
    code: 종목코드 (예: 005930)
    """
    api_map = {
        "STK": "stk_bydd_trd",
        "KSQ": "ksq_bydd_trd",
        "KNX": "knx_bydd_trd",
    }
    api_id = api_map.get(market, "stk_bydd_trd")

    end   = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")

    rows = krx_fetch(api_id, {
        "isuCd": code,
        "strtDd": start,
        "endDd": end,
    })

    result = []
    for row in rows:
        try:
            result.append({
                "Date":   row.get("TRD_DD","").replace("/","-"),
                "Open":   int(str(row.get("OPNPRC","0")).replace(",","")),
                "High":   int(str(row.get("HGPRC","0")).replace(",","")),
                "Low":    int(str(row.get("LWPRC","0")).replace(",","")),
                "Close":  int(str(row.get("CLSPRC","0")).replace(",","")),
                "Volume": int(str(row.get("ACC_TRDVOL","0")).replace(",","")),
                "change_pct": float(str(row.get("FLUC_RT","0")).replace(",","")),
            })
        except:
            continue

    return sorted(result, key=lambda x: x["Date"])[-days:]

def get_krx_index() -> dict:
    """지수 정보 수집 (FDR 백업)"""
    return get_krx_index_fdr()

def get_krx_index_fdr() -> dict:
    """지수 정보 수집 (FinanceDataReader 기반)"""
    result = {}
    mapping = {
        "KOSPI":   "^KS11",
        "KOSDAQ":  "^KQ11",
        "S&P500":  "^GSPC",
        "VIX":     "^VIX",
        "USD/KRW": "USDKRW=X",
    }
    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.error("[FDR] FinanceDataReader 미설치")
        return result

    for name, ticker in mapping.items():
        try:
            df = fdr.DataReader(ticker, datetime.now() - timedelta(days=7))
            if df is not None and not df.empty and len(df) >= 2:
                curr = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                chg  = round((curr / prev - 1) * 100, 2)
                result[name] = {"value": round(curr, 2), "change_pct": chg, "up": chg >= 0}
            elif df is not None and not df.empty:
                curr = float(df["Close"].iloc[-1])
                result[name] = {"value": round(curr, 2), "change_pct": 0, "up": True}
        except Exception as e:
            logger.debug(f"[FDR 지수] {name}({ticker}) 실패: {e}")
    return result


class StockDataCollector:
    """주식 데이터 수집 및 기술 지표 계산기 (KIS API + FDR 기반)"""

    def __init__(self, tickers: list = None):
        base_tickers = tickers or list(GLOBAL_TICKERS.values())
        required_indices = {"^KS11", "^KQ11", "^GSPC", "^VIX", "USDKRW=X"}
        self.tickers = list(set(base_tickers) | required_indices)

    # ── 주가 데이터 수집 ──────────────────────────────────
    def fetch_ohlcv(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        """
        OHLCV 데이터 수집
        - 한국 주식 (6자리 코드, .KS/.KQ 접미사): KIS API 우선, FDR 백업
        - 글로벌 지수 (^로 시작하거나 =X): FDR 사용
        """
        # 기간 → 일수 변환
        period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "3y": 1095}
        days = period_map.get(period, 365)
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end   = datetime.now().strftime("%Y-%m-%d")

        # 글로벌 지수는 FDR로
        if ticker.startswith("^") or ticker.endswith("=X") or "." in ticker and not ticker.endswith((".KS", ".KQ", ".KN")):
            return self._fetch_fdr(ticker, start, end)

        # 한국 주식: 종목코드 추출
        code = ticker.replace(".KS", "").replace(".KQ", "").replace(".KN", "").replace(".KP", "")
        if code.isdigit() and len(code) == 6:
            # 1차: KIS API
            df = self._fetch_kis(code, start, end)
            if df is not None and not df.empty:
                return df
            # 2차: FDR 백업
            logger.warning(f"[KIS 실패] {code} → FDR 백업 사용")

        return self._fetch_fdr(code, start, end)

    def _fetch_kis(self, code: str, start: str, end: str) -> pd.DataFrame:
        """KIS API로 일봉 데이터 수집"""
        try:
            from kis_api import get_daily_ohlcv
            start_fmt = start.replace("-", "")
            end_fmt   = end.replace("-", "")
            rows = get_daily_ohlcv(code, start_fmt, end_fmt)
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
            df = df[df["Close"] > 0].dropna(subset=["Close"])
            df = self._add_technical_indicators(df)
            self._save(df, code)
            logger.info(f"[KIS 수집 완료] {code}: {len(df)}행")
            return df
        except Exception as e:
            logger.error(f"[KIS 일봉 오류] {code}: {e}")
            return pd.DataFrame()

    def _fetch_fdr(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """FinanceDataReader로 OHLCV 수집"""
        try:
            import FinanceDataReader as fdr
            df = fdr.DataReader(ticker, start, end)
            if df is None or df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.copy()
            # Close 컬럼 통일
            for col in ["Adj Close", "adj close"]:
                if col in df.columns and "Close" not in df.columns:
                    df["Close"] = df[col]
            if "Close" not in df.columns:
                return pd.DataFrame()
            df = df[df["Close"] > 0].dropna(subset=["Close"])
            if df.empty:
                return pd.DataFrame()
            df = self._add_technical_indicators(df)
            self._save(df, ticker)
            logger.info(f"[FDR 수집 완료] {ticker}: {len(df)}행")
            return df
        except Exception as e:
            logger.error(f"[FDR 수집 오류] {ticker}: {e}")
            return pd.DataFrame()

    def fetch_all(self, period: str = "1y") -> dict:
        """등록된 전체 종목 수집"""
        return {t: self.fetch_ohlcv(t, period) for t in self.tickers}

    def get_fundamentals(self, ticker: str) -> dict:
        """종목의 가치 지표 수집 (KIS API)"""
        code = ticker.replace(".KS", "").replace(".KQ", "").replace(".KN", "")
        if not (code.isdigit() and len(code) == 6):
            return {}
        try:
            from kis_api import get_fundamentals as kis_fundamentals
            return kis_fundamentals(code)
        except Exception as e:
            logger.error(f"[가치지표 오류] {ticker}: {e}")
            return {}

    # ── 기술적 지표 ───────────────────────────────────────
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """RSI, MACD, 볼린저밴드 등 지표 추가"""
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.loc[:, ~df.columns.duplicated()]

        if isinstance(df["Close"], pd.DataFrame):
            close = df["Close"].iloc[:, 0].copy()
        else:
            close = df["Close"].copy()

        # 이동평균
        for w in [5, 20, 60, 120, 200]:
            df[f"MA{w}"] = close.rolling(w).mean()

        # 52주 신고가/신저가
        df["High_52W"] = close.rolling(min(252, len(df))).max()
        df["Low_52W"]  = close.rolling(min(252, len(df))).min()
        df["Dist_High_52W"] = (close / df["High_52W"].replace(0, np.nan)) - 1
        df["Dist_Low_52W"]  = (close / df["Low_52W"].replace(0, np.nan)) - 1

        # RSI (14)
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        df["RSI"] = 100 - 100 / (1 + rs.fillna(0))

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["MACD"]        = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]

        # 볼린저밴드
        df["BB_Mid"]   = close.rolling(20).mean()
        std            = close.rolling(20).std()
        df["BB_Upper"] = df["BB_Mid"] + 2 * std
        df["BB_Lower"] = df["BB_Mid"] - 2 * std
        df["BB_Width"] = df["BB_Upper"] - df["BB_Lower"]
        df["BB_Pct"]   = (close - df["BB_Lower"]) / (df["BB_Width"] + 1e-10)

        # 거래량 이동평균
        if "Volume" in df.columns:
            vol = df["Volume"].iloc[:, 0].copy() if isinstance(df["Volume"], pd.DataFrame) else df["Volume"].copy()
            df["Volume_MA20"]  = vol.rolling(20).mean()
            df["Volume_Ratio"] = vol / df["Volume_MA20"].replace(0, np.nan)

        # 변동성
        df["Daily_Return"] = close.pct_change()
        df["Volatility_20"] = df["Daily_Return"].rolling(20).std() * np.sqrt(252)

        return df.fillna(0)

    def fetch_market_context(self) -> dict:
        """글로벌 지수, 매크로 현황 종합 수집 (FDR 기반)"""
        context = {
            "indices": self._fetch_group_fdr(GLOBAL_TICKERS),
            "macro":   self._fetch_group_fdr(MACRO_TICKERS),
            "etf":     self._fetch_group_fdr({k: v["ticker"] for k, v in ETF_UNIVERSE.items()})
        }
        return context

    def _fetch_group_fdr(self, group_dict: dict) -> dict:
        """티커 그룹에 대한 현재가 및 등락률 수집 (FDR 기반)"""
        import FinanceDataReader as fdr
        results = {}
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        for name, ticker in group_dict.items():
            try:
                data = fdr.DataReader(ticker, start)
                if data is not None and not data.empty:
                    close_col = "Close" if "Close" in data.columns else data.columns[0]
                    results[name] = {
                        "price":  float(data[close_col].iloc[-1]),
                        "change": float(data[close_col].pct_change().iloc[-1])
                    }
            except Exception as e:
                logger.debug(f"[수집 건너뜀] {name}({ticker}): {e}")
        return results

    # ── 저장 ──────────────────────────────────────────────
    def _save(self, df: pd.DataFrame, ticker: str) -> None:
        data_dir = SYSTEM.get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        safe  = ticker.replace(".", "_")
        fname = os.path.join(data_dir, f"stock_{safe}_{datetime.now().strftime('%Y%m%d')}.csv")
        df.to_csv(fname, encoding="utf-8-sig")
        logger.info(f"[저장] {fname}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=== 종합 시장 데이터 수집 테스트 시작 ===")
    collector = StockDataCollector()

    print("\n[글로벌 시장 컨텍스트 수집 중...]")
    ctx = collector.fetch_market_context()
    for category, items in ctx.items():
        print(f"\n▶ {category.upper()}")
        for name, info in items.items():
            print(f"  - {name}: {info['price']:.2f} ({info['change']*100:+.2f}%)")
