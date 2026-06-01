import os
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from pykrx import stock
import FinanceDataReader as fdr
import warnings

warnings.filterwarnings('ignore')

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

def is_bearish_divergence(prices, rsi_values):
    if len(prices) < 15 or len(rsi_values) < 15:
        return False
    
    curr_price = prices[-1]
    prev_max_price = max(prices[-14:-1])
    curr_rsi = rsi_values[-1]
    prev_max_rsi = max(rsi_values[-14:-1])
    
    price_higher_high = curr_price >= prev_max_price
    rsi_lower_high = curr_rsi < prev_max_rsi
    return price_higher_high and rsi_lower_high

def get_safe_ticker_list():
    """FDR을 사용하여 안정적으로 종목 리스트 확보"""
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        df = pd.concat([kospi, kosdaq])
        return df[['Code', 'Name']]
    except:
        return pd.DataFrame()

def main():
    print(f">>> [데이터 수집] 시스템 통합 스캔 시작 ({datetime.now().strftime('%H:%M:%S')})")
    
    # 1. 종목 리스트 및 기본 시세 (FDR 사용 - pykrx 장애 대비)
    ticker_df = get_safe_ticker_list()
    if ticker_df.empty:
        print("    [ERROR] 종목 리스트를 가져오지 못했습니다.")
        return

    target_date = datetime.now().strftime("%Y-%m-%d")
    print(f"    기준일: {target_date}")

    # 2. 수급 데이터 (pykrx 사용)
    # pykrx의 get_market_net_purchases_of_equities_by_ticker는 수급 분석에 필수적임
    start_date_5d = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    end_date_fmt = datetime.now().strftime("%Y%m%d")
    
    try:
        df_investor = stock.get_market_net_purchases_of_equities_by_ticker(start_date_5d, end_date_fmt, "ALL")
    except:
        print("    [WARNING] 수급 데이터를 가져오지 못했습니다. 수급 필터 제외하고 진행.")
        df_investor = pd.DataFrame()

    results = []
    overheated_list = []
    missing_count = 0
    
    # 분석 대상 종목 제한 (거래대금 상위 종목 우선 - 속도 및 퀄리티 확보)
    # 실제 운영 시에는 전체를 돌리되, 여기서는 테스트를 위해 상위 200개 종목으로 시연
    print(f">>> [정밀 분석] 주요 종목 스캔 중... (안정성을 위해 FDR/pykrx 혼용)")
    
    # 시총 상위 위주로 샘플링 (실제는 전체 루프 가능)
    top_tickers = ticker_df.head(300) 

    for idx, row in top_tickers.iterrows():
        ticker = row['Code']
        name = row['Name']
        
        try:
            # 최근 100일 데이터 (RSI, MA 계산용)
            df = fdr.DataReader(ticker, (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d"))
            if len(df) < 60:
                missing_count += 1
                continue
                
            # 컬럼 표준화
            df.columns = [c.capitalize() for c in df.columns]
            prices = df['Close']
            
            # 기술 지표
            ma20 = prices.rolling(20).mean()
            ma60 = prices.rolling(60).mean()
            rsi = calculate_rsi(prices)
            
            curr_price = prices.iloc[-1]
            curr_rsi = rsi.iloc[-1]
            curr_ma20 = ma20.iloc[-1]
            curr_ma60 = ma60.iloc[-1]
            
            disparity = (curr_price - curr_ma20) / (curr_ma20 + 1e-10) * 100
            ret_20d = (curr_price / prices.iloc[-20] - 1) * 100
            
            # 거래대금 비율
            df['Amount'] = df['Close'] * df['Volume']
            amount_today = df['Amount'].iloc[-1]
            avg_amount_20d = df['Amount'].tail(20).mean()
            amount_ratio = (amount_today / (avg_amount_20d + 1e-10)) * 100
            
            # 수급 (pykrx 데이터 매칭)
            net_foreign = 0
            net_inst = 0
            if not df_investor.empty and ticker in df_investor.index:
                net_foreign = df_investor.loc[ticker, '외국인']
                net_inst = df_investor.loc[ticker, '기관']
            
            has_supply = net_foreign > 0 or net_inst > 0
            is_bearish = is_bearish_divergence(prices.values, rsi.values)
            
            stock_data = {
                'name': name, 'ticker': ticker, 'price': curr_price, 'rsi': curr_rsi,
                'disparity': disparity, 'ret_20d': ret_20d,
                'amount_ratio': amount_ratio, 'net_foreign': net_foreign, 'net_inst': net_inst,
                'is_bearish': is_bearish, 'ma20': curr_ma20, 'ma60': curr_ma60
            }
            
            # 과열 제외 필터
            overheat_reasons = []
            if is_bearish: overheat_reasons.append("베어리시 다이버전스")
            if disparity > 20: overheat_reasons.append(f"이격 과다({disparity:.1f}%)")
            if ret_20d > 30: overheat_reasons.append(f"20일 급등({ret_20d:.1f}%)")
            if curr_rsi >= 65 and amount_ratio < 100: overheat_reasons.append("거래 미동반 강세")
            
            if overheat_reasons:
                overheated_list.append({**stock_data, 'reason': ", ".join(overheat_reasons)})
                continue

            # 트랙 A — 평균회귀
            if (35 <= curr_rsi <= 50) and (ret_20d < 10) and (curr_price > curr_ma60 * 0.97) and (amount_ratio >= 100) and has_supply:
                rsi_score = 40 if curr_rsi <= 40 else (40 - (curr_rsi - 40) * 4)
                ma_pos_score = min(30, max(0, -disparity * 2 + 15))
                stock_data['score_MR'] = rsi_score + ma_pos_score + 30
                stock_data['track'] = 'A'
                results.append(stock_data)

            # 트랙 B — 추세지속
            elif (curr_rsi >= 65) and not is_bearish and (curr_price > curr_ma20 > curr_ma60) and (disparity <= 15) and (amount_ratio >= 100) and has_supply:
                if 5 <= disparity <= 10: trend_score = 40
                else: trend_score = 40 - abs(disparity - 7.5) * 4
                vol_score = min(30, amount_ratio / 10)
                stock_data['score_TF'] = trend_score + 30 + vol_score
                stock_data['track'] = 'B'
                results.append(stock_data)

        except Exception:
            continue

    # 결과 출력
    df_res = pd.DataFrame(results)
    print("\n" + "="*100)
    print(f" 🚀 실데이터 스캔 리포트 ({target_date} 기준)")
    print("="*100)
    
    if not df_res.empty:
        track_a = df_res[df_res['track'] == 'A'].sort_values('score_MR', ascending=False).head(10)
        track_b = df_res[df_res['track'] == 'B'].sort_values('score_TF', ascending=False).head(10)
        
        print(f"\n[트랙 A: 평균회귀 신호 - 단기 반등 후보]")
        print("-" * 100)
        for _, r in track_a.iterrows():
            print(f"{r['name']:<15} | {r['ticker']:<8} | {int(r['price']):>10,} | RSI:{r['rsi']:>4.1f} | 이격:{r['disparity']:>5.1f}% | Score:{r['score_MR']:.1f}")

        print(f"\n[트랙 B: 추세지속 신호 - 강세 모멘텀 후보]")
        print("-" * 100)
        for _, r in track_b.iterrows():
            print(f"{r['name']:<15} | {r['ticker']:<8} | {int(r['price']):>10,} | RSI:{r['rsi']:>4.1f} | 이격:{r['disparity']:>5.1f}% | Score:{r['score_TF']:.1f}")
    else:
        print("\n[알림] 현재 조건에 부합하는 종목이 없습니다.")

    print(f"\n[과열 및 리스크 제외 종목: {len(overheated_list)}개]")
    for r in overheated_list[:5]:
        print(f" - {r['name']} ({r['ticker']}): {r['reason']}")
    print("="*100)

if __name__ == "__main__":
    main()
