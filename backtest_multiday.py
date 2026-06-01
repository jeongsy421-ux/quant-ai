"""
backtest_multiday.py — 다중일 Horizon(1일/5일/20일) 방향 예측 백테스트
33개월 KIS 캐시 데이터를 사용하여 편향 제거(Purged & Non-overlapping) 후 초고속 실행
"""
import os
import sys
import pandas as pd
import numpy as np
import logging
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# ==========================================
# 0. 설정
# ==========================================
out_dir = "backtest_results"
os.makedirs(out_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(out_dir, 'multiday_debug.log'),
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

SECTOR_MAP = {
    "005930":"IT", "000660":"IT", "035420":"IT", "035720":"IT", "000990":"IT", 
    "058470":"IT", "357780":"IT", "240810":"IT", "319660":"IT", "018260":"IT",
    "005380":"자동차", "000270":"자동차", "012330":"자동차", "018880":"자동차", "161390":"자동차",
    "051910":"화학", "011170":"화학", "010130":"화학", "096770":"화학", "010950":"화학", 
    "011780":"화학", "010060":"화학", "009830":"화학", "004000":"화학", "298020":"화학", 
    "298050":"화학", "120110":"화학", "003240":"화학",
    "068270":"제약", "207940":"제약", "128940":"제약", "000100":"제약", "185750":"제약", 
    "170900":"제약", "069620":"제약", "326030":"제약",
    "105560":"금융", "055550":"금융", "086790":"금융", "000810":"금융", "032830":"금융",
    "005490":"철강", "004020":"철강", "000670":"철강",
    "028260":"지주사", "001040":"지주사", "004800":"지주사", "078930":"지주사", "034730":"지주사", "267250":"지주사",
    "009540":"조선", "010140":"조선", "042660":"조선", "329180":"조선", "241560":"기계",
    "097950":"식품", "049770":"식품", "033780":"식품", "271560":"식품", 
    "023530":"유통", "004170":"유통", "069960":"유통", "282330":"유통", "139480":"유통",
    "051900":"화장품", "090430":"화장품",
    "000720":"건설", "006360":"건설", "047040":"건설", "088980":"인프라",
    "017670":"통신", "030200":"통신", "032640":"통신", "251270":"게임", "036570":"게임",
    "015760":"전력", "034020":"에너지", "336260":"에너지", "112610":"에너지", "052690":"에너지",
    "180640":"운송", "003490":"운송", "020560":"운송", "000120":"운송", "028670":"운송", "011200":"운송"
}

THRESHOLD = 0.50

FEATURES = [
    'open', 'high', 'low', 'close', 'volume', 'ma5', 'ma5_slope', 'ma20_slope',
    'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
    'foreign_net_5d', 'institution_net_5d', 'usdkrw', 'usdkrw_change_5d', 
    'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
    'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
    'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
    'event_flag', 'event_flag_3d', 'news_sentiment'
]

def calc_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().copy()
    minus_dm = (-low.diff()).copy()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-9))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di

def compute_features(df, macro_df, sector_data, ticker):
    df = df.merge(macro_df, on="date", how="left")
    df[["sp500", "nasdaq", "sox", "usdkrw", "kospi_close"]] = df[["sp500", "nasdaq", "sox", "usdkrw", "kospi_close"]].ffill().fillna(0)
    sec_name = SECTOR_MAP.get(ticker, "기타")
    if sec_name in sector_data:
        df = df.merge(sector_data[sec_name].reset_index(), on='date', how='left')
    else:
        df['sector_return'] = 0.0
    df["adx"], plus_di, minus_di = calc_adx(df)
    df["di_diff"] = plus_di - minus_di
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma5_slope"], df["ma20_slope"] = df["ma5"].pct_change(5), df["ma20"].pct_change(5)
    df["return_1d"], df["return_5d"] = df["close"].pct_change(1), df["close"].pct_change(5)
    df["vol_change_1d"] = df["volume"].pct_change(1)
    df["vol_ratio_5d"] = df["volume"] / (df["volume"].rolling(5).mean() + 1e-9)
    df["foreign_net_5d"] = df["foreign_net"].rolling(5).sum().fillna(0)
    df["institution_net_5d"] = df["institution_net"].rolling(5).sum().fillna(0)
    df["usdkrw_change_5d"] = df["usdkrw"].pct_change(5)
    df["sector_return_5d"] = df["sector_return"].rolling(5).sum()
    df["stock_vs_sector"] = df["return_5d"] - df["sector_return_5d"]
    df["vix_proxy"] = df["return_1d"].rolling(20).std() * np.sqrt(252)
    df["rsi14"] = 100 - (100 / (1 + (df["return_1d"].rolling(14).mean() / (df["return_1d"].rolling(14).std() + 1e-9))))
    df["days_above_ma20"] = (df["close"] > df["ma20"]).astype(int).rolling(20).sum()
    df["ma_alignment"] = 0
    df.loc[(df["ma5"] > df["ma20"]) & (df["ma20"] > df["ma60"]), "ma_alignment"] = 1
    df.loc[(df["ma5"] < df["ma20"]) & (df["ma20"] < df["ma60"]), "ma_alignment"] = -1
    df["price_vs_ma20_pct"] = (df["close"] - df["ma20"]) / (df["ma20"] + 1e-9)
    df["sp500_return_1d"] = df["sp500"].pct_change().shift(1)
    df["nasdaq_return_1d"] = df["nasdaq"].pct_change().shift(1)
    df["sox_return_1d"] = df["sox"].pct_change().shift(1)
    df["event_flag"] = ((df["volume"] > df["volume"].rolling(20).mean() * 2) & ((df["open"] - df["close"].shift(1)).abs() / df["close"].shift(1) > 0.03)).astype(int)
    df["event_flag_3d"] = df["event_flag"].rolling(3).max().fillna(0)
    df["news_sentiment"] = 0.0
    return df.replace([np.inf, -np.inf], np.nan).fillna(0)

def main():
    print("Starting Optimized Multi-day Pooled Backtest (20-day sampling)...")
    macro_df = pd.read_parquet("cache/macro.parquet")
    sector_data = {}
    for s_name in set(SECTOR_MAP.values()):
        s_tickers = [t for t, v in SECTOR_MAP.items() if v == s_name]
        s_rets = []
        for st in s_tickers:
            st_path = f"cache/{st}.parquet"
            if os.path.exists(st_path):
                sdf = pd.read_parquet(st_path)
                if not sdf.empty: s_rets.append(sdf.set_index('date')['close'].pct_change())
        if s_rets: sector_data[s_name] = pd.concat(s_rets, axis=1).mean(axis=1).rename("sector_return")
    
    RAW_TICKERS = ["삼성전자(005930.KS)", "SK하이닉스(000660.KS)", "현대차(005380.KS)", "LG화학(051910.KS)", "삼성바이오로직스(207940.KS)", "셀트리온(068270.KS)", "카카오(035720.KS)", "NAVER(035420.KS)", "기아(000270.KS)", "삼성SDI(006400.KS)", "현대모비스(012330.KS)", "LG전자(066570.KS)", "SK텔레콤(017670.KS)", "KB금융(105560.KS)", "신한지주(055550.KS)", "포스코홀딩스(005490.KS)", "하나금융지주(086790.KS)", "삼성물산(028260.KS)", "LG생활건강(051900.KS)", "삼성생명(032830.KS)"]
    TICKERS = [(t.split("(")[1][:6], t.split("(")[0]) for t in RAW_TICKERS]
    
    print("모든 종목 피처 계산 중...")
    all_ticker_dfs = {}
    for t, n in TICKERS:
        ticker_path = f"cache/{t}.parquet"
        if not os.path.exists(ticker_path): continue
        df = pd.read_parquet(ticker_path)
        if df.empty: continue
        df = compute_features(df, macro_df, sector_data, t)
        df["ticker"] = t
        
        # 타겟 생성
        for h in [1, 5, 20]:
            df[f"target_{h}d"] = (df["close"].shift(-h) > df["close"]).astype(int)
            df[f"future_close_{h}d"] = df["close"].shift(-h)
            df[f"future_{h}d_valid"] = df["close"].shift(-h).notna()
        
        all_ticker_dfs[t] = df

    # 테스트 날짜 (2024년 이후, 20일 간격 샘플링)
    common_dates = sorted(set.intersection(*[set(df[(df['date'] >= '2024-01-01') & (df['date'] <= '2025-09-30')]['date']) for df in all_ticker_dfs.values()]))
    sampling_dates = common_dates[::20]
    
    print(f"테스트 시작 (Horizon 1, 5, 20일)... 샘플링 거래일: {len(sampling_dates)}일")
    
    final_results = []
    for horizon in [1, 5, 20]:
        target_col = f"target_{horizon}d"
        future_col = f"future_close_{horizon}d"
        valid_col = f"future_{horizon}d_valid"
        
        for T in sampling_dates:
            X_train_list = []
            y_train_list = []
            test_info = []
            
            for t, df in all_ticker_dfs.items():
                idx_list = df.index[df['date'] == T].tolist()
                if not idx_list: continue
                idx_T = idx_list[0]
                if not df.loc[idx_T, valid_col]: continue
                
                last_train_idx = idx_T - horizon - 1
                if last_train_idx < 100: continue
                
                train_df = df.iloc[:last_train_idx+1].dropna(subset=FEATURES + [target_col]).tail(600)
                if len(train_df) < 50: continue
                
                X_train_list.append(train_df[FEATURES])
                y_train_list.append(train_df[target_col])
                
                X_test_row = df.iloc[[idx_T]][FEATURES]
                test_info.append({'ticker': t, 'X_test': X_test_row, 'cur_close': df.loc[idx_T, 'close'], 'fut_val': df.loc[idx_T, future_col]})
            
            if not X_train_list or len(test_info) < 5: continue
            
            # 모델 학습
            X_train_all = pd.concat(X_train_list)
            y_train_all = pd.concat(y_train_list)
            
            # 방향성 예측은 정규화가 중요하므로 StandardScaler 적용
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train_all)
            
            model = XGBClassifier(n_estimators=150, max_depth=5, learning_rate=0.03, n_jobs=-1, random_state=42)
            model.fit(X_train_scaled, y_train_all)
            
            for item in test_info:
                X_test_scaled = scaler.transform(item['X_test'])
                prob = model.predict_proba(X_test_scaled)[0, 1]
                pred_up = prob >= 0.5
                actual_up = item['fut_val'] > item['cur_close']
                final_results.append({'horizon': horizon, 'correct': pred_up == actual_up})
        
        sub = pd.DataFrame([r for r in final_results if r['horizon'] == horizon])
        if not sub.empty:
            print(f"{horizon}일 Horizon: 정확도 {sub['correct'].mean()*100:.2f}% ({len(sub)} cases)")

    print("\n=== Final Multi-day Pooled Summary ===")

if __name__ == "__main__":
    main()
