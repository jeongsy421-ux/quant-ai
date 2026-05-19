"""
signal_maker.py - 고도화된 매매 시그널 생성 모듈
기술 지표 + AI 예측 + 거시경제(Macro) + 섹터 지표 결합
"""
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SignalMaker:
    """하이브리드 매매 시그널 생성기 (Macro-Aware)"""

    def __init__(self):
        self.signal_history: List[Dict] = []

    def get_market_sentiment_score(self, macro_snapshot: Dict) -> float:
        """
        거시경제 데이터를 기반으로 시장 심리 점수 산출 (-1.0 ~ 1.0)
        - Fear & Greed, VIX, 장단기 금리차 반영
        """
        score = 0.0
        try:
            # 1. Fear & Greed Index (0~100) -> -1.0~1.0 변환
            fg = macro_snapshot.get("FEAR_GREED", 50.0)
            score += (fg - 50.0) / 50.0 * 0.4  # 가중치 40%

            # 2. VIX (낮을수록 Risk-On)
            vix = macro_snapshot.get("VIX", 20.0)
            vix_score = max(-1.0, min(1.0, (20.0 - vix) / 10.0))
            score += vix_score * 0.3  # 가중치 30%

            # 3. 장단기 금리차 (양수일수록 Risk-On)
            spread = macro_snapshot.get("YIELD_SPREAD", 0.1)
            spread_score = max(-1.0, min(1.0, spread * 2.0))
            score += spread_score * 0.3  # 가중치 30%
            
            return round(score, 4)
        except Exception as e:
            logger.error(f"[심리 점수 오류] {e}")
            return 0.0

    def market_regime_filter(self, market_df: pd.DataFrame, macro_score: float) -> bool:
        """
        지수 추세 + 매크로 심리를 결합한 최종 마켓 필터
        """
        if market_df is None or market_df.empty:
            return True
            
        try:
            latest = market_df.iloc[-1]
            close = float(latest["Close"].squeeze())
            ma200 = float(latest["MA200"].squeeze()) if "MA200" in latest else close
            
            # 기술적 하락장 + 매크로 부정적이면 매수 차단
            if close < ma200 and macro_score < -0.3:
                logger.warning(f"[마켓 필터] 하락장 & 부정적 매크로 -> 매수 금지 (Score: {macro_score})")
                return False
            return True
        except Exception as e:
            logger.error(f"[마켓 필터 오류] {e}")
            return True

    def get_sector_signal_weight(self, ticker: str, sector_context: Dict) -> float:
        """
        종목별 섹터 원자재/지수 추세에 따른 가중치 조정
        예: 반도체 종목 + DRAM 가격 상승 -> BUY 가중치 증가
        """
        weight = 0.0
        try:
            # 반도체 섹터 (삼성전자, SK하이닉스)
            if ticker in ["005930.KS", "000660.KS"]:
                dram_change = sector_context.get("DRAM", {}).get("change", 0.0)
                sox_change = sector_context.get("SOX", {}).get("change", 0.0)
                weight += (dram_change * 2.0) + (sox_change * 1.5)
                
            # 해운 섹터 (HMM 등)
            elif ticker in ["011200.KS"]:
                bdi_change = sector_context.get("BDI", {}).get("change", 0.0)
                weight += (bdi_change * 3.0)
                
            return max(-0.2, min(0.2, weight)) # 최대 ±20% 영향
        except:
            return 0.0

    def technical_signal(self, df: pd.DataFrame, is_risk_on: bool = True, custom_rsi: float = 30.0) -> Dict:
        """기술적 지표 기반 시그널 생성 (기존 로직 유지 및 강화)"""
        if df.empty or len(df) < 30:
            return {"signal": "HOLD", "reasons": ["데이터 부족"]}

        latest = df.iloc[-1]
        signals = []
        
        # Helper to get scalar value from potential Series
        def get_val(key, default=0.0):
            val = latest.get(key, default)
            if isinstance(val, pd.Series):
                return float(val.iloc[0])
            return float(val)

        # ───  [NEW] 초단타 급등/모멘텀 돌파 로직 ───
        vol_ratio = get_val("Volume_Ratio", 0.0)
        daily_ret = get_val("Daily_Return", 0.0)
        close = get_val("Close", 0.0)
        ma20 = get_val("MA20", close)
        
        # 조건: 거래량 2.5배 폭증 + (20일선 돌파 OR 5% 이상 급등)
        is_surge = False
        if vol_ratio >= 2.5:
            if close > ma20 or daily_ret >= 0.05:
                is_surge = True
                signals.append(("BUY", " 초단타 급등 포착 (거래량+모멘텀)"))

        # RSI (과매도 custom_rsi, 과매수 70)
        rsi = get_val("RSI", 50.0)
        if rsi < custom_rsi: signals.append(("BUY", f"RSI 과매도({rsi:.1f})"))
        elif rsi > 70: signals.append(("SELL", f"RSI 과매수({rsi:.1f})"))

        # MACD 크로스
        macd = get_val("MACD", 0.0)
        macd_sig = get_val("MACD_Signal", 0.0)
        
        def get_series_val(column, idx):
            s = df[column]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            return s.iloc[idx]

        if "MACD" in latest and "MACD_Signal" in latest:
            prev_macd = get_series_val("MACD", -2)
            prev_macd_sig = get_series_val("MACD_Signal", -2)
            
            if macd > macd_sig and prev_macd <= prev_macd_sig:
                signals.append(("BUY", "MACD 골든크로스"))
            elif macd < macd_sig and prev_macd >= prev_macd_sig:
                signals.append(("SELL", "MACD 데드크로스"))

        # 일반 거래량 폭발 (기존 200% 상향)
        if vol_ratio > 2.0 and not is_surge:
            signals.append(("BUY", "거래량 폭증(200%↑)"))

        buy_cnt = sum(1 for s, _ in signals if s == "BUY")
        sell_cnt = sum(1 for s, _ in signals if s == "SELL")
        
        final = "BUY" if buy_cnt > sell_cnt else ("SELL" if sell_cnt > buy_cnt else "HOLD")
        if final == "BUY" and not is_risk_on:
            final = "HOLD"
            signals.append(("HOLD", "마켓필터로 인한 매수 제한"))

        return {"signal": final, "reasons": [r for _, r in signals], "buy_count": buy_cnt}

    def combined_signal(
        self,
        ticker: str,
        stock_df: pd.DataFrame,
        market_df: pd.DataFrame,
        macro_snapshot: Dict,
        market_context: Dict,
        ai_result: Optional[Dict] = None
    ) -> Dict:
        """전체 데이터를 결합한 최종 하이브리드 시그널 생성"""
        
        # 1. 매크로 심리 및 마켓 필터
        macro_score = self.get_market_sentiment_score(macro_snapshot)
        is_risk_on = self.market_regime_filter(market_df, macro_score)
        
        # 2. 기술적 시그널
        tech = self.technical_signal(stock_df, is_risk_on=is_risk_on)
        
        # 3. 섹터별 보정
        sector_adj = self.get_sector_signal_weight(ticker, market_context.get("etf", {}))
        
        # 4. 종합 점수 산출
        tech_val = {"BUY": 0.5, "HOLD": 0, "SELL": -0.5}[tech["signal"]]
        ai_val = (ai_result.get("ensemble_prob", 0.5) - 0.5) if ai_result else 0
        
        final_score = (tech_val * 0.4) + (ai_val * 0.4) + (macro_score * 0.1) + (sector_adj * 0.1)
        
        final_signal = "BUY" if final_score > 0.15 else ("SELL" if final_score < -0.15 else "HOLD")
        
        # 하락장 방어 (최종)
        if final_signal == "BUY" and not is_risk_on:
            final_signal = "HOLD"

        result = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "signal": final_signal,
            "score": round(final_score, 4),
            "macro_score": macro_score,
            "sector_adjustment": round(sector_adj, 4),
            "technical": tech,
            "ai_predict": ai_result
        }
        self.signal_history.append(result)
        return result
