"""
risk_manager.py - 리스크 관리 모듈
포지션 사이징, 손절/익절, 포트폴리오 위험 지표 계산
"""
import logging
import numpy as np
import pandas as pd
from config import STRATEGY, RISK

logger = logging.getLogger(__name__)


class RiskManager:
    """포트폴리오 리스크 관리자"""

    def __init__(self):
        # STRATEGY["stop_loss_pct"] 등이 -3.0 같이 백분율로 되어 있으므로 소수로 변환 (예: 0.03)
        self.max_position = (1.0 / STRATEGY.get("max_positions", 3)) 
        self.stop_loss = abs(STRATEGY.get("stop_loss_pct", -3.0)) / 100.0
        self.take_profit = abs(STRATEGY.get("take_profit_pct", 5.0)) / 100.0
        self.kelly_fraction = STRATEGY.get("kelly_fraction", 0.5)

    # ── 포지션 사이징 ─────────────────────────────────────
    def kelly_position(self, win_prob: float = 0.55, win_ratio: float = 2.0, loss_ratio: float = 1.0) -> float:
        """켈리 공식 기반 포지션 비중 계산"""
        if win_ratio <= 0 or loss_ratio <= 0:
            return 0.0
        kelly = (win_prob / loss_ratio) - ((1 - win_prob) / win_ratio)
        # 풀 켈리의 절반(하프 켈리)으로 보수적 적용
        position = max(0.0, min(kelly * 0.5, self.max_position))
        position = max(0.0, min(position, self.max_position))
        logger.info(f"[켈리] 풀={kelly:.4f} → 적용={position:.4f}")
        return round(position, 4)

    def volatility_target_position(self, returns: pd.Series, target_volatility: float = 0.15) -> float:
        """
        변동성 타겟팅 기반 포지션 축소/확대 로직 (Volatility Targeting)
        target_volatility: 연간 목표 변동성 (예: 15%)
        반환값: 투자 비중 배수 (0.1 ~ 1.5)
        """
        if returns.empty or len(returns) < 20:
            return 1.0 # 데이터 부족으로 기본 비중
            
        current_vol = float(returns.tail(20).std() * np.sqrt(252))
        if current_vol == 0:
            return 1.0
            
        # 변동성이 타겟보다 크면 비중을 줄이고, 작으면 비중을 늘림
        vol_ratio = target_volatility / current_vol
        
        # 극단적인 레버리지 방지를 위해 범위 제한
        vol_ratio = max(0.1, min(vol_ratio, 1.5))
        logger.info(f"[변동성 타겟팅] 현재 위험도={current_vol*100:.1f}%, 타겟={target_volatility*100:.1f}% -> 비중 조절={vol_ratio:.2f}x")
        return round(vol_ratio, 4)

    # ── 손절/익절 레벨 ────────────────────────────────────
    def stop_levels(self, entry_price: float) -> dict:
        """손절·익절 가격 계산"""
        return {
            "entry": round(entry_price, 2),
            "stop_loss": round(entry_price * (1 - self.stop_loss), 2),
            "take_profit": round(entry_price * (1 + self.take_profit), 2),
        }

    # ── VaR (Value at Risk) ───────────────────────────────
    def calc_var(self, returns: pd.Series, confidence: float = 0.95, horizon: int = 1) -> float:
        """히스토리컬 VaR 계산"""
        if returns.empty:
            return 0.0
        var = float(np.percentile(returns.dropna(), (1 - confidence) * 100))
        var_h = var * np.sqrt(horizon)
        logger.info(f"[VaR] {confidence*100:.0f}% {horizon}일 VaR: {var_h:.4f}")
        return round(var_h, 6)

    # ── 샤프 비율 ─────────────────────────────────────────
    def sharpe_ratio(self, returns: pd.Series, risk_free: float = 0.035) -> float:
        """연율화 샤프 비율 계산"""
        if returns.std() == 0:
            return 0.0
        excess = returns.mean() * 252 - risk_free
        vol = returns.std() * np.sqrt(252)
        sr = excess / vol
        logger.info(f"[샤프] {sr:.4f}")
        return round(float(sr), 4)

    # ── 최대낙폭 ──────────────────────────────────────────
    def max_drawdown(self, prices: pd.Series) -> float:
        """최대낙폭(MDD) 계산"""
        cum_max = prices.cummax()
        drawdown = (prices - cum_max) / cum_max
        mdd = float(drawdown.min())
        logger.info(f"[MDD] {mdd:.4f}")
        return round(mdd, 6)

    # ── 몬테카를로 시뮬레이션 ──────────────────────────────
    def monte_carlo_simulation(self, returns: pd.Series, start_price: float, days: int = 252, simulations: int = 1000) -> dict:
        """기하학적 브라운 운동(GBM) 기반 향후 주가 경로 시뮬레이션"""
        if returns.empty or len(returns) < 30:
            return {}
        
        mu = returns.mean()
        sigma = returns.std()
        
        # GBM 시뮬레이션: S_t = S_{t-1} * exp((mu - sigma^2/2) + sigma * dt * Z)
        sim_results = np.zeros((days, simulations))
        sim_results[0] = start_price
        
        for t in range(1, days):
            Z = np.random.standard_normal(simulations)
            sim_results[t] = sim_results[t-1] * np.exp((mu - 0.5 * sigma**2) + sigma * Z)
        
        final_prices = sim_results[-1]
        
        return {
            "expected_price": float(np.mean(final_prices)),
            "median_price": float(np.median(final_prices)),
            "price_95th": float(np.percentile(final_prices, 95)),
            "price_5th": float(np.percentile(final_prices, 5)),
            "prob_profit": float(np.mean(final_prices > start_price)),
        }

    # ── 종합 리스크 보고서 ────────────────────────────────
    def risk_report(self, df: pd.DataFrame) -> dict:
        """주요 리스크 지표 종합 보고"""
        returns = df["Daily_Return"].dropna() if "Daily_Return" in df.columns else pd.Series()
        close = df["Close"].squeeze() if "Close" in df.columns else pd.Series()

        return {
            "var_95_1d": self.calc_var(returns, 0.95, 1),
            "var_99_1d": self.calc_var(returns, 0.99, 1),
            "sharpe":    self.sharpe_ratio(returns),
            "mdd":       self.max_drawdown(close) if not close.empty else 0.0,
            "volatility_annual": round(float(returns.std() * np.sqrt(252)), 6) if not returns.empty else 0.0,
        }
