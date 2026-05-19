import sys
import logging
import pandas as pd
import math
sys.path.append(r'c:\Users\jihun\Desktop\quant_ai\backend')
from app import stock_collector, signal_maker, risk_manager

logging.basicConfig(level=logging.WARNING)

kospi = stock_collector.fetch_ohlcv('^KS11', period='1y')
is_risk_on = True
if not kospi.empty:
    try:
        latest = kospi.iloc[-1]
        is_risk_on = float(latest['Close']) >= float(latest['MA200'])
    except: pass

capital = 2000000

print(f"--- 200만원 포트폴리오 제안 (Risk On: {is_risk_on}) ---")
for ticker in ['005930.KS', '000660.KS', '035420.KS']:
    df = stock_collector.fetch_ohlcv(ticker, period='1y')
    if df.empty: continue
    
    # AI 앙상블은 모형 학습 시간이 오래 걸릴 수 있으므로 일단 단순 기술적 시그널로 체크
    tech_sig = signal_maker.technical_signal(df, is_risk_on=is_risk_on, custom_rsi=25)
    
    # 3. Position Size
    returns = df['Daily_Return'].dropna()
    vol_ratio = risk_manager.volatility_target_position(returns)
    kelly = risk_manager.kelly_position(win_prob=0.55, win_ratio=1.5)
    final_pos = min(kelly * vol_ratio, risk_manager.max_position)
    
    buy_amount = capital * final_pos
    current_price = float(df['Close'].iloc[-1].squeeze())
    
    if pd.isna(buy_amount) or pd.isna(current_price) or current_price == 0:
        shares = 0
        buy_amount = 0
    else:
        shares = int(buy_amount // current_price)
        
    print(f"[{ticker}] 시그널: {tech_sig.get('signal')}, 사유: {', '.join(tech_sig.get('reasons', []))}")
    if tech_sig.get('signal') == 'BUY':
        print(f"  -> 제안: 약 {shares}주 매수 (할당금액: {buy_amount:.0f}원)")
    else:
        print(f"  -> 제안: 관망 (현금 대기)")
