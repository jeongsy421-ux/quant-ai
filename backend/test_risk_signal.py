import logging
from stock_data import StockDataCollector
from risk_manager import RiskManager
from signal_maker import SignalMaker

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("TestRiskSignal")
    logger.info("=== 리스크 및 시그널 통합 테스트 시작 ===")
    
    # 삼성전자 데이터 가져오기
    collector = StockDataCollector(["005930.KS"])
    df = collector.fetch_ohlcv("005930.KS", period="1y")
    
    if df.empty:
        logger.error("데이터 수집 실패")
    else:
        # 리스크 매니저 테스트
        rm = RiskManager()
        
        # 켈리 공식 테스트 (승률 55%, 손익비 1.5 가정)
        kelly = rm.kelly_position(win_prob=0.55, win_ratio=1.5)
        logger.info(f"[테스트] 계산된 켈리 투자 비중: {kelly}")
        
        # VaR 테스트
        returns = df["Daily_Return"].dropna()
        var_1d = rm.calc_var(returns)
        logger.info(f"[테스트] 95% 신뢰구간 1일 VaR: {var_1d}")
        
        # 몬테카를로 시뮬레이션
        current_price = float(df["Close"].iloc[-1].squeeze())
        logger.info(f"현재주가: {current_price}")
        mc_res = rm.monte_carlo_simulation(returns, current_price, days=60, simulations=1000)
        logger.info(f"[테스트] 60일 몬테카를로 시뮬레이션 결과: {mc_res}")
        
        # 시그널 메이커 테스트
        sm = SignalMaker()
        tech_signal = sm.technical_signal(df)
        logger.info(f"[테스트] 기술적 지표 시그널: {tech_signal}")
