"""
validate_alpha.py — Ranking 전략 강화 검증 (100종목 버전)
[1] 유니버스 확대: 20종목 -> 100종목 (캐시 데이터 전체)
[2] L-S 확대: Top 10/Bot 10 -> Top 20/Bot 20
[3] 피처 최적화: 절대가격(OHLC) 영구 제거
[4] 통계 검정: 벤치마크 비교, L-S Net 수익률, 100회 랜덤 셔플 (p-value)
"""
import os
import pandas as pd
import numpy as np
from scipy.stats import spearmanr
from xgboost import XGBRegressor
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ==========================================
# 0. 공통 설정
# ==========================================
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

# 가격 피처 영구 제거 (수익률, 수급, 추세 중심)
FEATURES = [
    'volume', 'ma5_slope', 'ma20_slope',
    'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
    'foreign_net_5d', 'institution_net_5d', 'usdkrw_change_5d', 
    'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
    'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
    'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
    'event_flag', 'event_flag_3d', 'news_sentiment'
]

COST = 0.001  # 왕복 거래비용 (0.1%)

# ==========================================
# 1. 기술 지표 및 피처 계산
# ==========================================
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
    
    # Target: 미래 5일 수익률
    df["forward_return_5d"] = (df["close"].shift(-5) / df["close"]) - 1
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0)
    return df

# ==========================================
# 2. 데이터 준비
# ==========================================
def load_data():
    print(">>> 100종목 데이터 로딩 및 피처 생성 중...")
    cache_dir = "cache"
    all_files = [f for f in os.listdir(cache_dir) if f.endswith(".parquet") and f != "macro.parquet"]
    tickers = [f.split(".")[0] for f in all_files]
    
    macro_df = pd.read_parquet(os.path.join(cache_dir, "macro.parquet"))
    
    # 섹터 수익률 미리 계산
    sector_data = {}
    for s_name in set(SECTOR_MAP.values()):
        s_tickers = [t for t, v in SECTOR_MAP.items() if v == s_name]
        s_returns = []
        for st in s_tickers:
            st_path = os.path.join(cache_dir, f"{st}.parquet")
            if os.path.exists(st_path):
                sdf = pd.read_parquet(st_path)
                if not sdf.empty:
                    s_returns.append(sdf.set_index('date')['close'].pct_change())
        if s_returns:
            sector_data[s_name] = pd.concat(s_returns, axis=1).mean(axis=1).rename("sector_return")
    
    all_data_list = []
    for ticker in tickers:
        ticker_path = os.path.join(cache_dir, f"{ticker}.parquet")
        df = pd.read_parquet(ticker_path)
        if df.empty or len(df) < 100: continue
        df = compute_features(df, macro_df, sector_data, ticker)
        df["ticker"] = ticker
        all_data_list.append(df)
    
    full_df = pd.concat(all_data_list)
    raw_returns_df = full_df[['date', 'ticker', 'forward_return_5d']].copy()
    
    # 횡단면 중립화 (Z-score)
    for col in FEATURES + ['forward_return_5d']:
        full_df[col] = full_df.groupby('date')[col].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-9) if len(x) > 1 else x - x.mean()
        )
    
    all_ticker_dfs = {t: full_df[full_df['ticker'] == t].copy() for t in full_df['ticker'].unique()}
    
    # 공통 날짜 (5일 간격 리밸런싱)
    date_sets = [set(df[(df['date'] >= '2024-01-01') & (df['date'] <= '2025-09-30')]['date']) 
                 for df in all_ticker_dfs.values()]
    common_dates = sorted(set.intersection(*date_sets))[::5]
    
    return all_ticker_dfs, raw_returns_df, common_dates, macro_df, tickers

# ==========================================
# 3. 백테스트 엔진 (Top 20 / Bot 20)
# ==========================================
def run_ranking_backtest(all_ticker_dfs, raw_returns_df, common_dates, features, shuffle=False, seed=None):
    rng = np.random.RandomState(seed) if shuffle else None
    daily_ics = []
    ls_returns = []
    daily_dfs = []
    
    for T in common_dates:
        X_train_list, y_train_list, test_info = [], [], []
        
        for ticker, df in all_ticker_dfs.items():
            idx_list = df.index[df['date'] == T].tolist()
            if not idx_list: continue
            idx_T = idx_list[0]
            last_train_idx = idx_T - 5 - 1
            if last_train_idx < 100: continue
            
            # 학습 데이터 (윈도우 600일)
            train_df = df.iloc[:last_train_idx+1].dropna(subset=features + ['forward_return_5d']).tail(600)
            if len(train_df) < 50: continue
            
            X_train_list.append(train_df[features])
            y_train_list.append(train_df['forward_return_5d'])
            
            actual_fwd = raw_returns_df[
                (raw_returns_df['date'] == T) & (raw_returns_df['ticker'] == ticker)
            ]['forward_return_5d'].values[0]
            X_test_row = df.iloc[[idx_T]][features]
            test_info.append({'ticker': ticker, 'X_test': X_test_row, 'actual': actual_fwd})
        
        if not X_train_list or len(test_info) < 20: continue
        
        X_train_all = pd.concat(X_train_list)
        y_train_all = pd.concat(y_train_list)
        
        # 모델 학습 (XGBoost)
        model = XGBRegressor(n_estimators=150, max_depth=3, learning_rate=0.03, n_jobs=-1, random_state=42)
        model.fit(X_train_all, y_train_all)
        
        daily_preds = []
        for item in test_info:
            pred_score = model.predict(item['X_test'])[0]
            daily_preds.append({'ticker': item['ticker'], 'score': pred_score, 'actual': item['actual']})
        
        d_df = pd.DataFrame(daily_preds)
        
        if shuffle and rng is not None:
            d_df['score'] = rng.permutation(d_df['score'].values)
        
        ic, _ = spearmanr(d_df['score'], d_df['actual'])
        if not np.isnan(ic):
            daily_ics.append(ic)
        
        # Long-Short: Top 20 / Bottom 20
        top_n = 20
        top_picks = d_df.nlargest(top_n, 'score')
        bot_picks = d_df.nsmallest(top_n, 'score')
        
        # 비용 차감 (Long + Short 두 번 거래)
        ret = (top_picks['actual'].mean() - COST) - (bot_picks['actual'].mean() + COST)
        ls_returns.append(ret)
        daily_dfs.append(d_df.copy())
    
    if not daily_ics:
        return {'ic_mean': 0, 'icir': 0, 'hit_rate': 0, 'ls_cumulative': 0, 'n_days': 0, 'daily_dfs': []}
    
    ic_mean = np.mean(daily_ics)
    icir = ic_mean / (np.std(daily_ics) + 1e-9)
    hit_rate = np.mean([1 if ic > 0 else 0 for ic in daily_ics]) * 100
    ls_cum = (1 + pd.Series(ls_returns)).cumprod().iloc[-1] - 1
    
    return {
        'ic_mean': ic_mean,
        'icir': icir,
        'hit_rate': hit_rate,
        'ls_cumulative': ls_cum,
        'n_days': len(daily_ics),
        'ls_returns': ls_returns,
        'daily_dfs': daily_dfs,
    }

# ==========================================
# MAIN
# ==========================================
def main():
    start_time = datetime.now()
    all_ticker_dfs, raw_returns_df, common_dates, macro_df, tickers = load_data()
    
    print("\n>>> [검증 시작] 유니버스 100종목 / 가격 피처 제거 / Top-Bot 20")
    
    # 1. 랭킹 백테스트 실행
    result = run_ranking_backtest(all_ticker_dfs, raw_returns_df, common_dates, FEATURES)
    
    # 2. 벤치마크 계산
    # (a) KOSPI
    kospi = macro_df[['date', 'kospi_close']].copy()
    kospi = kospi[(kospi['date'] >= '2024-01-01') & (kospi['date'] <= '2025-09-30')].dropna()
    kospi = kospi.sort_values('date')
    kospi_ret = (kospi['kospi_close'].iloc[-1] / kospi['kospi_close'].iloc[0] - 1) * 100 if len(kospi) > 0 else 0
    
    # (b) 100종목 동일가중
    ew_rets = []
    for t in tickers:
        df = all_ticker_dfs[t]
        df = df[(df['date'] >= '2024-01-01') & (df['date'] <= '2025-09-30')].sort_values('date')
        if len(df) > 2:
            ew_rets.append((df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100)
    ew_ret = np.mean(ew_rets) if ew_rets else 0
    
    # 3. 랜덤 셔플 시뮬레이션 (100회)
    print(">>> 랜덤 셔플 검정 진행 중 (100회)...")
    random_ls_results = []
    for i in range(100):
        rng = np.random.RandomState(i)
        sim_ls_returns = []
        for d_df in result['daily_dfs']:
            shuffled_scores = rng.permutation(d_df['score'].values)
            temp_df = d_df.copy()
            temp_df['score'] = shuffled_scores
            
            top_picks = temp_df.nlargest(20, 'score')
            bot_picks = temp_df.nsmallest(20, 'score')
            ret = (top_picks['actual'].mean() - COST) - (bot_picks['actual'].mean() + COST)
            sim_ls_returns.append(ret)
            
        sim_ls_cum = (1 + pd.Series(sim_ls_returns)).cumprod().iloc[-1] - 1
        random_ls_results.append(sim_ls_cum)
    
    random_ls = np.array(random_ls_results)
    percentile_rank = np.mean(random_ls < result['ls_cumulative']) * 100
    p_value = 1 - percentile_rank / 100
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    # 결과 출력
    print("\n" + "="*70)
    print(f"{'Ranking 전략 재검증 결과 (100종목)':^70}")
    print("="*70)
    print(f" {'검증 항목':<25} | {'결과 값':<30}")
    print("-" * 70)
    print(f" {'평가 기간':<25} | 2024-01-01 ~ 2025-09-30")
    print(f" {'총 평가일수 (5일 간격)':<25} | {result['n_days']}일")
    print(f" {'사용 종목 수':<25} | {len(tickers)}종목")
    print(f" {'피처 구성':<25} | {len(FEATURES)}개 (OHLC 제거)")
    print("-" * 70)
    print(f" {'KOSPI 수익률':<25} | {kospi_ret:+.2f}%")
    print(f" {'100종목 동일가중 수익률':<25} | {ew_ret:+.2f}%")
    print(f" {'L-S Net 수익률 (비용차감)':<25} | {result['ls_cumulative']*100:+.2f}%")
    print("-" * 70)
    print(f" {'IC Mean':<25} | {result['ic_mean']:.4f}")
    print(f" {'ICIR':<25} | {result['icir']:.4f}")
    print(f" {'랜덤 셔플 p-value':<25} | {p_value:.4f} (상위 {100-percentile_rank:.1f}%)")
    print("-" * 70)
    
    # 판정
    if p_value < 0.05 and result['ls_cumulative'] > 0:
        conclusion = "★ 통계적 유의미성 확보 (진짜 알파 가능성 매우 높음)"
    elif result['ls_cumulative'] > 0:
        conclusion = "☆ 양의 수익률이나 유의미성 부족 (관찰 필요)"
    else:
        conclusion = "ⓧ 전략적 유효성 상실 (재설계 필요)"
    
    print(f" [최종 판정] {conclusion}")
    print(f" [소요 시간] {duration.total_seconds():.1f}초")
    print("="*70)

if __name__ == "__main__":
    main()
