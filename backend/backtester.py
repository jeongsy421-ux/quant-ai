"""
backtester.py - 퀀트 전략 백테스팅 모듈
과거 데이터를 기반으로 기술적 시그널의 수익률을 시뮬레이션하고 검증
"""
import os
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# 기존 수집 로직과 시그널을 재사용합니다.
from stock_data import StockDataCollector
from signal_maker import SignalMaker
from config import SYSTEM

logger = logging.getLogger(__name__)

class Backtester:
    def __init__(self, ticker: str, initial_capital: float = 10000000.0, fee_rate: float = 0.0015):
        """
        초기 자본금 및 거래 수수료 기본값 설정
        fee_rate: 0.15% (매수/매도 수수료 및 슬리피지 감안)
        """
        self.ticker = ticker
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        # KOSPI 데이터도 수집하여 마켓 타이밍 필터에 사용
        self.collector = StockDataCollector([ticker, "^KS11"])
        self.signal_maker = SignalMaker()
        
    def run(self, period: str = "3y", custom_rsi: int = 30) -> pd.DataFrame:
        """지정된 기간 동안의 백테스트를 실행합니다."""
        logger.info(f"[{self.ticker}] 과거 {period}치 데이터 로드 중... (RSI 설정값: {custom_rsi})")
        
        all_data = {t: self.collector.fetch_ohlcv(t, period=period) for t in self.collector.tickers}
        df = all_data.get(self.ticker)
        macro_df = all_data.get("^KS11")
        
        if df.empty or len(df) < 50:
            logger.error("데이터가 부족하여 백테스트를 진행할 수 없습니다.")
            return pd.DataFrame()
            
        # 백테스트 기록용 리스트 및 변수
        cash = self.initial_capital
        holdings = 0.0
        portfolio_values = []
        signals_recorded = []
        
        # 1. 시그널 추출. 속도를 위해 벡터 연산보다는 순차적인 루프로 시뮬레이션 진행
        logger.info("시뮬레이션 시작 (일별 시그널 평가 및 거래 반영)...")
        
        # 시그널 생성을 위한 지표 계산은 fetch_ohlcv에서 이미 진행됨 (RSI, MACD, MA 등)
        # 하지만 signal_maker.technical_signal()은 과거 데이터프레임의 끝부분을 기준으로 하므로,
        # 과거 각 시점마다의 row를 평가하도록 조정이 필요합니다.
        
        # 편의상 루프로 매일매일을 시뮬레이션합니다. 
        # (실제 대규모 백테스트에서는 벡터화하는 것이 속도에 유리합니다.)
        close_prices = df['Close'].values.flatten()
        rsi_values = df['RSI'].values.flatten()
        macd = df['MACD'].values.flatten()
        macd_signal = df['MACD_Signal'].values.flatten()
        ma5 = df['MA5'].values.flatten()
        ma20 = df['MA20'].values.flatten()
        ma60 = df['MA60'].values.flatten()
        dates = df.index
        
        for i in range(len(df)):
            current_price = float(close_prices[i])
            date = dates[i]
            
            # 지표가 생성되기 전(Nan)이면 관망
            if i < 60 or np.isnan(rsi_values[i]):
                portfolio_values.append(cash)
                signals_recorded.append("HOLD")
                continue
                
            # 시점 i에서의 기술적 시그널 생성 (최적화를 위해 단순 이식)
            signal = "HOLD"
            buy_score = 0
            sell_score = 0
            
            # RSI 로직 (파라미터화 적용)
            curr_rsi = rsi_values[i]
            if curr_rsi < custom_rsi:
                buy_score += 1
            elif curr_rsi > (100 - custom_rsi):
                sell_score += 1
                
            # MACD 골든/데드크로스 로직
            if i > 0:
                prev_macd = macd[i-1]
                prev_sig = macd_signal[i-1]
                curr_macd = macd[i]
                curr_sig = macd_signal[i]
                if prev_macd < prev_sig and curr_macd > curr_sig:
                    buy_score += 1
                elif prev_macd > prev_sig and curr_macd < curr_sig:
                    sell_score += 1
                    
            # 이동평균 배열 로직
            c_ma5, c_ma20, c_ma60 = ma5[i], ma20[i], ma60[i]
            if c_ma5 > c_ma20 > c_ma60:
                buy_score += 1
            elif c_ma5 < c_ma20 < c_ma60:
                sell_score += 1
                
            if buy_score > sell_score:
                signal = "BUY"
            elif sell_score > buy_score:
                signal = "SELL"
                
            # 마켓 타이밍 필터 적용: 폭락장이면 매수 취소
            if signal == "BUY" and macro_df is not None and not macro_df.empty:
                try:
                    # macro_df는 날짜가 다를 수 있으므로 iloc보다 가까운 시점을 쓰는게 좋으나 단순화
                    macro_row = macro_df[macro_df.index <= date].iloc[-1]
                    m_close = float(macro_row["Close"])
                    m_ma200 = float(macro_row["MA200"])
                    if m_close < m_ma200:
                        signal = "HOLD"  # 방어 진입
                except:
                    pass
                
            signals_recorded.append(signal)
            
            # 매매 로직 반영
            if signal == "BUY" and cash > 0:
                # 전액 매수 (단순화: 100% 매수. 실제로는 켈리 등 적용 가능)
                shares_to_buy = cash / current_price
                cost = shares_to_buy * current_price * self.fee_rate
                holdings += shares_to_buy
                cash = cash - (shares_to_buy * current_price) - cost
                
            elif signal == "SELL" and holdings > 0:
                # 전액 매도
                proceeds = holdings * current_price
                cost = proceeds * self.fee_rate
                cash = cash + proceeds - cost
                holdings = 0.0
                
            # 해당 일자 종료 후 포트폴리오 가치
            daily_val = cash + (holdings * current_price)
            portfolio_values.append(daily_val)
            
        # 결과를 DataFrame에 추가
        df['Portfolio_Value'] = portfolio_values
        df['Signal'] = signals_recorded
        
        # 벤치마크 (바인딩 앤 홀드) 비교용 - 첫날 전액 매수했다고 가정
        first_valid_idx = 60
        benchmark_shares = self.initial_capital / float(close_prices[first_valid_idx])
        df['Benchmark_Value'] = close_prices * benchmark_shares
        
        return df
        
    def evaluate(self, df: pd.DataFrame):
        """백테스트 결과를 요약, 평가하고 그래프를 생성합니다."""
        if df.empty:
            return
            
        start_val = self.initial_capital
        end_val = df['Portfolio_Value'].iloc[-1]
        bench_end = df['Benchmark_Value'].iloc[-1]
        
        algo_return = ((end_val - start_val) / start_val) * 100
        bench_return = ((bench_end - start_val) / start_val) * 100
        
        # MDD 계산
        rolling_max = df['Portfolio_Value'].cummax()
        drawdown = df['Portfolio_Value'] / rolling_max - 1.0
        mdd = drawdown.min() * 100
        
        logger.info(f"========== 백테스트 결과 요약 ==========")
        logger.info(f"초기 자본: {start_val:,.0f}원")
        logger.info(f"최종 자본: {end_val:,.0f}원")
        logger.info(f"알고리즘 누적 수익률: {algo_return:.2f}%")
        logger.info(f"단순 보유(Benchmark) 수익률: {bench_return:.2f}%")
        logger.info(f"최대 낙폭(MDD): {mdd:.2f}%")
        logger.info(f"총 거래일 수: {len(df)}")
        
        self.plot_results(df, algo_return, bench_return, mdd)
        
    def plot_results(self, df: pd.DataFrame, algo_ret: float, bench_ret: float, mdd: float):
        """수익률 곡선을 시각화하고 이미지로 저장합니다."""
        # Pandas Index(Datetime)를 이용해 시각화
        plt.figure(figsize=(12, 6))
        plt.plot(df.index, df['Portfolio_Value'], label=f"Algorithm (Return: {algo_ret:.2f}%)", color="blue")
        plt.plot(df.index, df['Benchmark_Value'], label=f"Buy & Hold (Return: {bench_ret:.2f}%)", color="gray", alpha=0.6)
        
        plt.title(f"Backtest Result: {self.ticker} (MDD: {mdd:.2f}%)")
        plt.xlabel("Date")
        plt.ylabel("Portfolio Value (KRW)")
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # 데이터 디렉토리에 저장
        data_dir = SYSTEM.get("data_dir", "data")
        os.makedirs(data_dir, exist_ok=True)
        save_path = os.path.join(data_dir, f"backtest_{self.ticker.replace('.', '_')}.png")
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"백테스트 그래프 저장 완료: {save_path}")
        plt.close()

    def optimize_parameters(self, rsi_range: list = [20, 25, 30, 35, 40], period: str = "3y"):
        """그리드 서치를 통해 최적의 RSI 파라미터를 찾습니다."""
        logger.info(f"파라미터 최적화(Grid Search) 시작: RSI 관측 구간 = {rsi_range}")
        
        results = []
        # 조용히 수행하도록 로그레벨 임시 조정
        old_level = logger.level
        logger.setLevel(logging.WARNING)
        
        for rsi in rsi_range:
            df = self.run(period=period, custom_rsi=rsi)
            if df.empty:
                continue
            
            start_val = self.initial_capital
            end_val = df['Portfolio_Value'].iloc[-1]
            ret = ((end_val - start_val) / start_val) * 100
            
            rolling_max = df['Portfolio_Value'].cummax()
            drawdown = df['Portfolio_Value'] / rolling_max - 1.0
            mdd = drawdown.min() * 100
            
            results.append({
                "RSI": rsi,
                "Return(%)": round(ret, 2),
                "MDD(%)": round(mdd, 2),
                "Score": round(ret / abs(mdd if mdd != 0 else 1), 2) # 샤프유사 단순 스코어
            })
            
        logger.setLevel(old_level)
        
        res_df = pd.DataFrame(results).sort_values("Score", ascending=False).reset_index(drop=True)
        logger.info("\n========== 파라미터 최적화(Grid Search) 결과 ==========")
        print(res_df.to_string())
        
        best_rsi = res_df.iloc[0]['RSI']
        logger.info(f" 최적의 선택: RSI = {best_rsi}")
        return best_rsi


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # 삼성전자 (005930.KS)에 대한 3년 백테스트 진행
    tester = Backtester(ticker="005930.KS", initial_capital=10000000.0)
    
    # 그리드 서치 구동 (수익률 극대화 팩터 찾기)
    best_rsi = tester.optimize_parameters(period="3y")
    
    # 최적의 결과로 재구동 및 그래프 출력
    result_df = tester.run(period="3y", custom_rsi=best_rsi)
    tester.evaluate(result_df)
