"""
theme_scanner.py - 테마별 실시간 주가 스캔 (FinanceDataReader 기반)
"""
import logging
import time
import pandas as pd
from datetime import datetime, timedelta
from theme_data import THEMES, CATEGORIES, get_all_tickers, get_ticker_themes

logger = logging.getLogger(__name__)


class ThemeScanner:

    def __init__(self):
        self._cache = {}
        self._cache_time = None
        self._cache_ttl = 300  # 5분 캐시

    def _fetch_ticker_data(self, ticker: str) -> dict:
        """단일 종목 데이터 수집 (FDR 기반)"""
        try:
            import FinanceDataReader as fdr
            code  = ticker.replace(".KS", "").replace(".KQ", "").replace(".KN", "")
            start = (datetime.now() - timedelta(days=70)).strftime("%Y-%m-%d")
            df    = fdr.DataReader(code, start)
            if df is None or df.empty or len(df) < 2:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            close_col = next((c for c in ["Close", "Adj Close", "close"] if c in df.columns), None)
            if close_col is None:
                return None
            close   = float(df[close_col].iloc[-1])
            prev    = float(df[close_col].iloc[-2])
            vol_col = next((c for c in ["Volume", "volume"] if c in df.columns), None)
            vol     = float(df[vol_col].iloc[-1])     if vol_col else 0
            avg_vol = float(df[vol_col].rolling(20).mean().iloc[-1]) if vol_col else 1
            chg       = (close - prev) / prev * 100 if prev != 0 else 0
            vol_ratio = vol / avg_vol if avg_vol > 0 else 1
            w1_close  = float(df[close_col].iloc[-6])  if len(df) >= 6  else prev
            m1_close  = float(df[close_col].iloc[-22]) if len(df) >= 22 else prev
            chg_1w = (close - w1_close) / w1_close * 100 if w1_close != 0 else 0
            chg_1m = (close - m1_close) / m1_close * 100 if m1_close != 0 else 0
            closes = df[close_col]
            delta  = closes.diff()
            gain   = delta.clip(lower=0).rolling(14).mean()
            loss   = (-delta.clip(upper=0)).rolling(14).mean()
            rsi    = float((100 - 100 / (1 + gain / (loss + 1e-10))).iloc[-1])
            return {
                "price":        round(close, 0),
                "change_pct":   round(chg, 2),
                "chg_1w":       round(chg_1w, 2),
                "chg_1m":       round(chg_1m, 2),
                "volume_ratio": round(vol_ratio, 2),
                "rsi":          round(rsi, 1),
                "volume":       int(vol),
                "is_surge":     vol_ratio >= 2.0,
                "is_up":        chg >= 0,
            }
        except Exception as e:
            logger.error(f"[테마스캔] {ticker} 오류: {e}")
            return None


    def scan_all_themes(self) -> dict:
        """전체 테마 스캔 (캐시 적용)"""
        now = datetime.now()
        if self._cache_time and (now - self._cache_time).seconds < self._cache_ttl:
            return self._cache

        logger.info("🎯 테마별 전체 스캔 시작")
        all_tickers = get_all_tickers()
        ticker_data = {}

        for ticker in all_tickers:
            data = self._fetch_ticker_data(ticker)
            if data:
                ticker_data[ticker] = data
            time.sleep(0.08)

        # 테마별 집계
        theme_results = {}
        for theme_name, theme_info in THEMES.items():
            stocks = []
            changes = []
            surge_count = 0

            for ticker, stock_info in theme_info["stocks"].items():
                t_data = ticker_data.get(ticker, {})
                chg = t_data.get("change_pct", 0)
                changes.append(chg)
                if t_data.get("is_surge"):
                    surge_count += 1

                stocks.append({
                    "ticker":      ticker,
                    "name":        stock_info["name"],
                    "role":        stock_info["role"],
                    "reason":      stock_info["reason"],
                    "price":       t_data.get("price", 0),
                    "change_pct":  chg,
                    "chg_1w":      t_data.get("chg_1w", 0),
                    "chg_1m":      t_data.get("chg_1m", 0),
                    "volume_ratio": t_data.get("volume_ratio", 1),
                    "rsi":         t_data.get("rsi", 50),
                    "is_surge":    t_data.get("is_surge", False),
                    "is_up":       chg >= 0,
                })

            avg_chg = sum(changes) / len(changes) if changes else 0
            leader_data = ticker_data.get(theme_info["leader"], {})

            theme_results[theme_name] = {
                "name":        theme_name,
                "category":    theme_info["category"],
                "emoji":       theme_info["emoji"],
                "description": theme_info["description"],
                "avg_change":  round(avg_chg, 2),
                "surge_count": surge_count,
                "leader_price":  leader_data.get("price", 0),
                "leader_change": leader_data.get("change_pct", 0),
                "leader_chg_1w": leader_data.get("chg_1w", 0),
                "leader_chg_1m": leader_data.get("chg_1m", 0),
                "stocks":      stocks,
                "is_hot":      avg_chg >= 1.5 or surge_count >= 2,
            }

        self._cache = {
            "themes":     theme_results,
            "categories": CATEGORIES,
            "updated_at": now.isoformat(),
            "surge_stocks": self._get_surge_stocks(ticker_data),
        }
        self._cache_time = now
        logger.info(f"✅ 테마 스캔 완료: {len(theme_results)}개 테마")
        return self._cache

    def _get_surge_stocks(self, ticker_data: dict) -> list:
        """거래량 급등 종목 추출"""
        ticker_themes = get_ticker_themes()
        surge = []
        for ticker, data in ticker_data.items():
            if data.get("is_surge") and data.get("change_pct", 0) > 0:
                themes = ticker_themes.get(ticker, [])
                # 종목명 찾기
                name = ticker
                for theme in THEMES.values():
                    if ticker in theme["stocks"]:
                        name = theme["stocks"][ticker]["name"]
                        break
                surge.append({
                    "ticker":       ticker,
                    "name":         name,
                    "themes":       themes,
                    "price":        data["price"],
                    "change_pct":   data["change_pct"],
                    "volume_ratio": data["volume_ratio"],
                    "rsi":          data["rsi"],
                })
        return sorted(surge, key=lambda x: x["volume_ratio"], reverse=True)[:20]

    def search_theme(self, query: str) -> dict:
        """테마/종목 검색"""
        query = query.strip().lower()
        results = {"themes": [], "stocks": []}

        for theme_name, theme_info in THEMES.items():
            # 테마명 검색
            if query in theme_name.lower() or query in theme_info["description"].lower():
                results["themes"].append(theme_name)
                continue
            # 키워드 검색
            for kw in theme_info["keywords"]:
                if query in kw.lower():
                    results["themes"].append(theme_name)
                    break
            # 종목명 검색
            for ticker, stock_info in theme_info["stocks"].items():
                if query in stock_info["name"].lower() or query in ticker.lower():
                    if theme_name not in results["themes"]:
                        results["themes"].append(theme_name)
                    if ticker not in [s["ticker"] for s in results["stocks"]]:
                        results["stocks"].append({
                            "ticker": ticker,
                            "name":   stock_info["name"],
                            "theme":  theme_name,
                        })

        return results
