import sys
import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# 백엔드 경로 추가
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from scalper import Scalper
from screener import UNIVERSE, UNIVERSE_MAP

def run_validation():
    print("=== [초단타 로직 검증] 목요일 데이터 분석 -> 금요일 성과 확인 ===")
    
    # 1. 데이터 수집 (최근 5일분 5분봉)
    # 목요일: 2026-04-09, 금요일: 2026-04-10
    scalper = Scalper()
    target_stocks = ["005930.KS", "000660.KS", "005380.KS", "068270.KS", "247540.KQ", "086520.KQ", "035420.KS", "000270.KS"]
    
    recommendations = []
    
    for ticker in target_stocks:
        try:
            # 전체 데이터 다운로드
            df_full = yf.download(ticker, period="5d", interval="5m", progress=False)
            if df_full.empty: continue
            
            # 목요일(04-09) 데이터만 분리하여 분석 (KST 기준 09:00 ~ 15:30)
            # yfinance는 UTC 기준이므로 시간 보정 필요 (UTC 00:00~06:30이 KST 09:00~15:30)
            df_thu = df_full[df_full.index < '2026-04-10']
            
            if len(df_thu) < 20: continue
            
            # 목요일 종가 시점의 시그널 분석
            # Scalper의 내부 지표 계산 로직을 수동 적용
            df_thu_processed = scalper._add_scalping_indicators(df_thu.copy())
            latest = df_thu_processed.iloc[-1]
            
            # 간단한 점수 계산 (Scalper.analyze_ticker 로직 참조)
            v_ratio = float(latest["V_Ratio"].squeeze())
            price_change = float(latest["Price_Change"].squeeze())
            
            # 목요일 종가 기준 거래량이 터졌거나 강한 추세인 종목 선정
            if v_ratio > 1.5 or price_change > 0.005:
                recommendations.append({
                    "ticker": ticker,
                    "name": UNIVERSE_MAP.get(ticker, ticker),
                    "thu_close": float(latest["Close"].squeeze()),
                    "v_ratio": v_ratio
                })
        except Exception as e:
            print(f"Error analyzing {ticker}: {e}")

    print(f"\n[목요일 추천 리스트] 분석 대상 중 {len(recommendations)}개 포착됨")
    
    results = []
    for rec in recommendations:
        ticker = rec["ticker"]
        df_fri = yf.download(ticker, start="2026-04-10", end="2026-04-11", interval="5m", progress=False)
        
        if not df_fri.empty:
            fri_open = float(df_fri["Open"].iloc[0].squeeze())
            fri_high = float(df_fri["High"].max().squeeze())
            
            # 목요일 종가 대비 금요일 장중 최고가 수익률
            profit_potential = (fri_high - rec["thu_close"]) / rec["thu_close"] * 100
            # 목요일 종가 대비 금요일 시가 갭 수익률
            gap_return = (fri_open - rec["thu_close"]) / rec["thu_close"] * 100
            
            results.append({
                "name": rec["name"],
                "thu_close": rec["thu_close"],
                "fri_high": fri_high,
                "profit": profit_potential,
                "gap": gap_return
            })

    # 결과 출력
    print("\n" + "="*60)
    print(f"{'종목명':<15} | {'목요일종가':>10} | {'금요일고가':>10} | {'수익률(%)':>10}")
    print("-" * 60)
    for res in sorted(results, key=lambda x: x['profit'], reverse=True):
        print(f"{res['name']:<15} | {res['thu_close']:>12,.0f} | {res['fri_high']:>12,.0f} | {res['profit']:>10.2f}%")
    print("="*60)
    print("* 수익률(%)은 목요일 종가 대비 금요일 장중 최고가 기준 (초단타 매도 기회)")

if __name__ == "__main__":
    run_validation()
