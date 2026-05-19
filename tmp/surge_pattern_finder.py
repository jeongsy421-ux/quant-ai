import sys
import os
import pandas as pd
import yfinance as yf
import numpy as np
from typing import List, Dict

# 백엔드 경로 추가
sys.path.append(os.path.join(os.getcwd(), 'backend'))
from screener import UNIVERSE

def find_mega_surge_patterns():
    print("=== [대급등 패턴 분석] 최근 30일간 +10% 이상 급등 사례 전수 조사 ===")
    
    # 분석 대상 종목 (변동성 큰 KOSDAQ 종목 포함)
    target_tickers = UNIVERSE[:15] # 상위 15개 종목 우선 분석
    
    surge_cases = []
    
    for ticker in target_tickers:
        try:
            # 5분봉 데이터 1개월치 수집
            df = yf.download(ticker, period="1mo", interval="5m", progress=False)
            if df.empty or len(df) < 100: continue
            
            # 일일 변동성 계산 (당일 저가 대비 고가 또는 전일 종가 대비 당일 고가)
            # 여기서는 '단기 슈팅' 패턴을 찾기 위해 2시간 내 7% 이상 급등 사례 탐색
            df['Return_2h'] = df['Close'].pct_change(periods=24) # 5분 * 24 = 120분
            
            # 급등 시점 포착 (2시간 수익률 7% 이상인 경우 대급등주 후보)
            surge_points = df[df['Return_2h'] >= 0.07].index
            
            if not surge_points.empty:
                print(f"[{ticker}] 급등 사례 {len(surge_points)}건 발견")
                
                for pt in surge_points:
                    # 급등 직전(30분 전) 데이터 추출
                    idx = df.index.get_loc(pt)
                    if idx < 6: continue
                    
                    pre_surge = df.iloc[idx-6:idx] # 급등 직전 30분
                    avg_vol = df['Volume'].rolling(window=50).mean().iloc[idx-6]
                    curr_vol = pre_surge['Volume'].mean()
                    
                    vol_multiplier = curr_vol / avg_vol if avg_vol > 0 else 0
                    price_slope = (pre_surge['Close'].iloc[-1] - pre_surge['Close'].iloc[0]) / pre_surge['Close'].iloc[0]
                    
                    surge_cases.append({
                        "ticker": ticker,
                        "time": pt,
                        "vol_multiplier": vol_multiplier,
                        "pre_slope": price_slope,
                        "final_gain": df['Return_2h'].loc[pt] * 100
                    })
        except Exception as e:
            continue

    if not surge_cases:
        print("최근 30일 내 분석 조건에 맞는 대급등 사례가 없습니다.")
        return

    # 통계 분석
    cases_df = pd.DataFrame(surge_cases)
    print("\n" + "="*50)
    print("        [대급등주 직전 공통 데이터 특성]")
    print("-" * 50)
    print(f"1. 평균 거래량 폭증 정도: {cases_df['vol_multiplier'].mean():.2f}배")
    print(f"2. 급등 전 예비 상승(Slope): {cases_df['pre_slope'].mean()*100:.2f}%")
    print(f"3. 평균 최종 수익률: {cases_df['final_gain'].mean():.2f}%")
    print("="*50)
    
    # 이를 바탕으로 최적의 임계값 도출
    opt_vol = cases_df['vol_multiplier'].quantile(0.5) # 중간값
    opt_slope = cases_df['pre_slope'].quantile(0.3)
    
    print(f"\n💡 시스템 반영 권장 임계값:")
    print(f"- Volume Multiplier > {opt_vol:.1f}")
    print(f"- Pre-Surge Slope > {opt_slope*100:.2f}%")

if __name__ == "__main__":
    find_mega_surge_patterns()
