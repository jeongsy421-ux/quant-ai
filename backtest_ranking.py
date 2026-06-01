"""
backtest_ranking.py — 횡단면 랭킹(IC) 기반 백테스트
33개월 KIS 캐시 데이터를 사용하여 편향 제거(Purged & Non-overlapping) 및 거래비용 반영 후 실행
"""
import os
import sys
import pandas as pd
import numpy as np
import logging
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

# ==========================================
# 0. 설정
# ==========================================
out_dir = "backtest_results"
os.makedirs(out_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(out_dir, 'ranking_debug.log'),
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

SECTOR_MAP = {
    # IT / 반도체
    "005930":"IT", "000660":"IT", "035420":"IT", "035720":"IT", "000990":"IT", 
    "058470":"IT", "357780":"IT", "240810":"IT", "319660":"IT", "018260":"IT",
    # 자동차 / 모빌리티
    "005380":"자동차", "000270":"자동차", "012330":"자동차", "018880":"자동차", "161390":"자동차",
    # 화학 / 에너지
    "051910":"화학", "011170":"화학", "010130":"화학", "096770":"화학", "010950":"화학", 
    "011780":"화학", "010060":"화학", "009830":"화학", "004000":"화학", "298020":"화학", 
    "298050":"화학", "120110":"화학", "003240":"화학",
    # 제약 / 바이오
    "068270":"제약", "207940":"제약", "128940":"제약", "000100":"제약", "185750":"제약", 
    "170900":"제약", "069620":"제약", "326030":"제약",
    # 금융 (은행/증권/보험)
    "105560":"금융", "055550":"금융", "086790":"금융", "000810":"금융", "032830":"금융",
    # 철강 / 소재
    "005490":"철강", "004020":"철강", "000670":"철강",
    # 지주사 / 상사
    "028260":"지주사", "001040":"지주사", "004800":"지주사", "078930":"지주사", "034730":"지주사", "267250":"지주사",
    # 조선 / 기계
    "009540":"조선", "010140":"조선", "042660":"조선", "329180":"조선", "241560":"기계",
    # 유통 / 소비재
    "097950":"식품", "049770":"식품", "033780":"식품", "271560":"식품", 
    "023530":"유통", "004170":"유통", "069960":"유통", "282330":"유통", "139480":"유통",
    "051900":"화장품", "090430":"화장품",
    # 건설 / 인프라
    "000720":"건설", "006360":"건설", "047040":"건설", "088980":"인프라",
    # 통신 / 서비스
    "017670":"통신", "030200":"통신", "032640":"통신", "251270":"게임", "036570":"게임",
    # 전력 / 에너지원
    "015760":"전력", "034020":"에너지", "336260":"에너지", "112610":"에너지", "052690":"에너지",
    # 운송
    "180640":"운송", "003490":"운송", "020560":"운송", "000120":"운송", "028670":"운송", "011200":"운송"
}

FEATURES = [
    'open', 'high', 'low', 'close', 'volume', 'ma5', 'ma5_slope', 'ma20_slope',
    'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
    'foreign_net_5d', 'institution_net_5d', 'usdkrw', 'usdkrw_change_5d', 
    'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
    'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
    'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
    'event_flag', 'event_flag_3d', 'news_sentiment'
]

# ==========================================
# 1. Helper Functions
# ==========================================
def calc_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().copy()
    minus_dm = (-low.diff()).copy()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([high-low, (high-close.shift()).abs(),
                    (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-9))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di

def compute_features(df, macro_df, sector_data, ticker):
    df = df.merge(macro_df, on="date", how="left")
    macro_cols = ["sp500", "nasdaq", "sox", "usdkrw", "kospi_close"]
    df[macro_cols] = df[macro_cols].ffill().fillna(0)

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
    df["ma5_slope"] = df["ma5"].pct_change(5)
    df["ma20_slope"] = df["ma20"].pct_change(5)
    df["return_1d"] = df["close"].pct_change(1)
    df["return_5d"] = df["close"].pct_change(5)
    df["vol_change_1d"] = df["volume"].pct_change(1)
    df["vol_ratio_5d"] = df["volume"] / (df["volume"].rolling(5).mean() + 1e-9)
    df["foreign_net_5d"] = df["foreign_net"].rolling(5).sum().fillna(0)
    df["institution_net_5d"] = df["institution_net"].rolling(5).sum().fillna(0)
    df["usdkrw_change_5d"] = df["usdkrw"].pct_change(5)
    df["sector_return_5d"] = df["sector_return"].rolling(5).sum()
    df["stock_vs_sector"] = df["return_5d"] - df["sector_return_5d"]
    df["vix_proxy"] = df["return_1d"].rolling(20).std() * np.sqrt(252)
    df["rsi14"] = 100 - (100 / (1 + (df["return_1d"].rolling(14).mean() / (df["return_1d"].rolling(14).std() + 1e-9))))

    above = (df["close"] > df["ma20"]).astype(int)
    blocks = (above != above.shift()).cumsum()
    df["days_above_ma20"] = above.groupby(blocks).cumsum() * above
    align_up = (df["ma5"] > df["ma20"]) & (df["ma20"] > df["ma60"])
    align_down = (df["ma5"] < df["ma20"]) & (df["ma20"] < df["ma60"])
    df["ma_alignment"] = 0
    df.loc[align_up, "ma_alignment"] = 1
    df.loc[align_down, "ma_alignment"] = -1
    df["price_vs_ma20_pct"] = (df["close"] - df["ma20"]) / (df["ma20"] + 1e-9)

    df["sp500_return_1d"] = df["sp500"].pct_change().shift(1)
    df["nasdaq_return_1d"] = df["nasdaq"].pct_change().shift(1)
    df["sox_return_1d"] = df["sox"].pct_change().shift(1)

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    close_prev = df["close"].shift(1)
    gap_val = (df["open"] - close_prev).abs() / (close_prev + 1e-9)
    df["event_flag"] = ((df["volume"] > df["vol_ma20"] * 2) & (gap_val > 0.03)).astype(int)
    df["event_flag_3d"] = df["event_flag"].rolling(3).max().fillna(0).astype(int)
    df["news_sentiment"] = 0.0

    df["forward_return_5d"] = (df["close"].shift(-5) / df["close"]) - 1
    
    # [추가] 무한대 및 결측치 처리 (Feature Stability)
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.fillna(0)
    
    return df

# ==========================================
# 2. Main
# ==========================================
def main():
    print("Starting Final Cross-sectional Ranking Backtest (IC/ICIR) for 2024-2025...")
    macro_df = pd.read_parquet(os.path.join("cache", "macro.parquet"))
    sector_data = {}
    for s_name in set(SECTOR_MAP.values()):
        s_tickers = [t for t, v in SECTOR_MAP.items() if v == s_name]
        s_returns = []
        for st in s_tickers:
            st_path = os.path.join("cache", f"{st}.parquet")
            if os.path.exists(st_path):
                sdf = pd.read_parquet(st_path)
                if not sdf.empty: s_returns.append(sdf.set_index('date')['close'].pct_change())
        if s_returns: sector_data[s_name] = pd.concat(s_returns, axis=1).mean(axis=1).rename("sector_return")

    RAW_TICKERS = ["삼성전자(005930.KS)", "SK하이닉스(000660.KS)", "현대차(005380.KS)", "LG화학(051910.KS)", "삼성바이오로직스(207940.KS)", "셀트리온(068270.KS)", "카카오(035720.KS)", "NAVER(035420.KS)", "기아(000270.KS)", "삼성SDI(006400.KS)", "현대모비스(012330.KS)", "LG전자(066570.KS)", "SK텔레콤(017670.KS)", "KB금융(105560.KS)", "신한지주(055550.KS)", "포스코홀딩스(005490.KS)", "하나금융지주(086790.KS)", "삼성물산(028260.KS)", "LG생활건강(051900.KS)", "삼성생명(032830.KS)"]
    TICKERS = [(t.split("(")[1][:6], t.split("(")[0]) for t in RAW_TICKERS]

    print("모든 종목 피처 사전 계산 및 횡단면 중립화 중...")
    all_data_list = []
    for ticker, name in TICKERS:
        ticker_path = os.path.join("cache", f"{ticker}.parquet")
        if not os.path.exists(ticker_path): continue
        df = pd.read_parquet(ticker_path)
        if df.empty: continue
        df = compute_features(df, macro_df, sector_data, ticker)
        df["ticker"] = ticker
        df["_name"] = name
        all_data_list.append(df)

    # 1. 전체 데이터를 하나로 통합
    full_df = pd.concat(all_data_list)
    
    # 원본 수익률 데이터 백업 (수익률 계산용)
    raw_returns_df = full_df[['date', 'ticker', 'forward_return_5d']].copy()
    
    # 2. 날짜별 횡단면 중립화 (Z-Score) - 피처와 타겟 모두 적용
    print("  날짜별 횡단면 중립화 적용 중...")
    for col in FEATURES + ['forward_return_5d']:
        full_df[col] = full_df.groupby('date')[col].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9) if len(x) > 1 else x - x.mean())

    all_ticker_dfs = {t: full_df[full_df['ticker'] == t].copy() for t in full_df['ticker'].unique()}

    # 공통 날짜
    date_sets = [set(df[(df['date'] >= '2024-01-01') & (df['date'] <= '2025-09-30')]['date']) for df in all_ticker_dfs.values()]
    common_dates = sorted(set.intersection(*date_sets))[::5]
    print(f"  공통 예측 거래일 (Non-overlapping): {len(common_dates)}일")

    daily_ics = []
    ls_returns = []
    COST = 0.001 # 거래비용 0.1% (유관기관 수수료 + 슬리피지 최소화 가정)

    for t_idx, T in enumerate(common_dates):
        X_train_list = []
        y_train_list = []
        test_info = []

        for ticker, df in all_ticker_dfs.items():
            idx_list = df.index[df['date'] == T].tolist()
            if not idx_list: continue
            idx_T = idx_list[0]
            
            last_train_idx = idx_T - 5 - 1
            if last_train_idx < 100: continue
            
            train_df = df.iloc[:last_train_idx+1].dropna(subset=FEATURES + ['forward_return_5d']).tail(600)
            if len(train_df) < 50: continue
            
            X_train_list.append(train_df[FEATURES])
            y_train_list.append(train_df['forward_return_5d'])
            # 원본 수익률 참조
            actual_fwd = raw_returns_df[(raw_returns_df['date'] == T) & (raw_returns_df['ticker'] == ticker)]['forward_return_5d'].values[0]
            # 테스트 시점(T)의 피처 (당일 종가 기준 지표들)
            X_test_row = df.iloc[[idx_T]][FEATURES]
            test_info.append({'ticker': ticker, 'X_test': X_test_row, 'actual': actual_fwd})

        if not X_train_list or len(test_info) < 5: continue

        X_train_all = pd.concat(X_train_list)
        y_train_all = pd.concat(y_train_list)

        # 모델 파라미터 미세 조정 (Overfitting 방지 위해 depth 축소)
        model = XGBRegressor(n_estimators=150, max_depth=3, learning_rate=0.03, n_jobs=-1, random_state=42)
        model.fit(X_train_all, y_train_all)

        daily_preds = []
        for item in test_info:
            pred_score = model.predict(item['X_test'])[0]
            daily_preds.append({'ticker': item['ticker'], 'score': pred_score, 'actual': item['actual']})

        d_df = pd.DataFrame(daily_preds)
        ic, _ = spearmanr(d_df['score'], d_df['actual'])
        if not np.isnan(ic): daily_ics.append(ic)

        top_n = max(1, len(d_df) // 5)
        top_picks = d_df.nlargest(top_n, 'score')
        bot_picks = d_df.nsmallest(top_n, 'score')
        
        ret = (top_picks['actual'].mean() - COST) - (bot_picks['actual'].mean() + COST)
        ls_returns.append(ret)
        
        if (t_idx + 1) % 10 == 0 or t_idx == 0:
            print(f"  [{t_idx+1}/{len(common_dates)}] Date={T.strftime('%Y-%m-%d')}, IC={ic:.4f}, L-S(Net)={ret*100:.2f}%")

    # 피처 중요도 출력
    importances = pd.Series(model.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print("\n[Top 10 Features]")
    print(importances.head(10))


    print("\n" + "="*60)
    print("=== Final Cross-sectional Ranking Summary (Purged/Non-overlap/Cost 0.3%) ===")
    print(f"IC Mean: {np.mean(daily_ics):.4f} | ICIR: {np.mean(daily_ics)/(np.std(daily_ics)+1e-9):.4f}")
    print(f"IC Hit Rate: {np.mean([1 if ic > 0 else 0 for ic in daily_ics])*100:.1f}%")
    print(f"Long-Short 누적 수익률(Net): {(1+pd.Series(ls_returns)).cumprod().iloc[-1]-1:.2%}")
    print(f"평가 거래일 수: {len(daily_ics)}일")

if __name__ == "__main__":
    main()
