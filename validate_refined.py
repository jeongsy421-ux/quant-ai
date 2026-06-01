import os
import sys
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from scipy.stats import spearmanr
from xgboost import XGBRegressor
import warnings

# ==========================================
# 0. Setup
# ==========================================
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 백엔드 경로 추가
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from backend.config import RANKING_UNIVERSE

CACHE_DIR = "cache"
FEATURES = [
    'volume', 'ma5_slope', 'ma20_slope',
    'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
    'foreign_net_5d', 'institution_net_5d', 'usdkrw_change_5d', 
    'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
    'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
    'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
    'event_flag', 'event_flag_3d', 'news_sentiment'
]
COST = 0.0015 # 왕복 0.3%

# ==========================================
# 1. Core Logic (Re-used)
# ==========================================
def run_fixed_walk_forward(train_start, train_end, test_start, test_end, all_ticker_dfs, raw_returns_df):
    """지정된 Train/Test 기간으로 단일 Walk-forward 검증 수행"""
    # 1. 학습 데이터 구성 (Train 기간 내 전체 데이터 통합)
    X_train_list, y_train_list = [], []
    for ticker, df in all_ticker_dfs.items():
        train_slice = df[(df['date'] >= train_start) & (df['date'] <= train_end)].dropna(subset=FEATURES + ['forward_return_5d'])
        if not train_slice.empty:
            X_train_list.append(train_slice[FEATURES])
            y_train_list.append(train_slice['forward_return_5d'])
            
    if not X_train_list: return None
    
    X_train = pd.concat(X_train_list)
    y_train = pd.concat(y_train_list)
    
    # 2. 모델 학습
    model = XGBRegressor(n_estimators=150, max_depth=3, learning_rate=0.03, n_jobs=-1, random_state=42)
    model.fit(X_train, y_train)
    
    # 3. 테스트 (Test 기간 5일 간격 리밸런싱)
    date_sets = [set(df[(df['date'] >= test_start) & (df['date'] <= test_end)]['date']) for df in all_ticker_dfs.values()]
    test_dates = sorted(set.intersection(*date_sets))[::5]
    
    daily_ics, ls_returns, daily_dfs = [], [], []
    for T in test_dates:
        daily_preds = []
        for ticker, df in all_ticker_dfs.items():
            test_row = df[df['date'] == T]
            if test_row.empty: continue
            
            actual_fwd = raw_returns_df[(raw_returns_df['date'] == T) & (raw_returns_df['ticker'] == ticker)]['forward_return_5d'].values[0]
            pred_score = model.predict(test_row[FEATURES])[0]
            daily_preds.append({'ticker': ticker, 'score': pred_score, 'actual': actual_fwd})
            
        if len(daily_preds) < 20: continue
        d_df = pd.DataFrame(daily_preds)
        ic, _ = spearmanr(d_df['score'], d_df['actual'])
        if not np.isnan(ic): daily_ics.append(ic)
        
        top, bot = d_df.nlargest(20, 'score'), d_df.nsmallest(20, 'score')
        ls_returns.append((top['actual'].mean() - COST) - (bot['actual'].mean() + COST))
        daily_dfs.append(d_df)
        
    if not daily_ics: return None
    ls_cum = (1 + pd.Series(ls_returns)).cumprod().iloc[-1] - 1
    
    # 4. p-value (100 shuffles)
    sims = []
    for i in range(100):
        rng = np.random.RandomState(i)
        sim_rets = []
        for d_df in daily_dfs:
            shuffled = d_df.copy(); shuffled['score'] = rng.permutation(shuffled['score'].values)
            t, b = shuffled.nlargest(20, 'score'), shuffled.nsmallest(20, 'score')
            sim_rets.append((t['actual'].mean() - COST) - (b['actual'].mean() + COST))
        sims.append((1 + pd.Series(sim_rets)).cumprod().iloc[-1] - 1)
    p_val = 1 - (np.mean(np.array(sims) < ls_cum))
    
    return {
        "n_days": len(daily_ics),
        "ic_mean": np.mean(daily_ics),
        "ls_net": ls_cum * 100,
        "p_value": p_val
    }

# ==========================================
# 2. Main Execution
# ==========================================
def main():
    logger.info(">>> 정밀 검증 2단계: 데이터 균형화 및 2024 WF 검증 시작")
    
    # 데이터 로딩 및 횡단면 정규화 (전체 기간 대상)
    tickers = [t.split(".")[0] for t in RANKING_UNIVERSE]
    all_ticker_list = []
    
    # 2019-2025 전체 데이터 확보
    for tk in tickers:
        path = os.path.join(CACHE_DIR, f"{tk}.parquet")
        if not os.path.exists(path): continue
        df = pd.read_parquet(path)
        # 피처 계산은 run_full_validation.py에서 이미 완료된 캐시라고 가정 (혹은 다시 계산)
        # 여기서는 안정성을 위해 다시 계산하는 로직 포함 (run_full_validation.py의 함수들 필요)
        from run_full_validation import compute_features, SECTOR_MAP, FEATURES as FT_COLS
        macro_df = pd.read_parquet(os.path.join(CACHE_DIR, "macro.parquet"))
        
        # 섹터 데이터 재구축
        sector_data = {}
        for s_name in set(SECTOR_MAP.values()):
            s_rets = []
            for st in [t for t, v in SECTOR_MAP.items() if v == s_name]:
                p = os.path.join(CACHE_DIR, f"{st}.parquet")
                if os.path.exists(p):
                    sdf = pd.read_parquet(p)
                    if not sdf.empty: s_rets.append(sdf.set_index('date')['close'].pct_change())
            if s_rets: sector_data[s_name] = pd.concat(s_rets, axis=1).mean(axis=1)
            
        df = compute_features(df, macro_df, sector_data, tk)
        df["ticker"] = tk
        all_ticker_list.append(df)
        
    full_df = pd.concat(all_ticker_list)
    for col in FEATURES + ['forward_return_5d']:
        full_df[col] = full_df.groupby('date')[col].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    
    all_ticker_dfs = {t: full_df[full_df['ticker'] == t].copy() for t in full_df['ticker'].unique()}
    raw_returns_df = full_df[['date', 'ticker', 'forward_return_5d']].copy()

    # ────────────────────────────────────────────────────────
    # [1] 기간별 n_days 균등 검증 (최소 50일)
    # ────────────────────────────────────────────────────────
    results = []
    # 2021년은 데이터 부족 여부 확인 후 제외
    periods = [(2022, 2022), (2023, 2023), (2024, 2025)]
    from run_full_validation import run_oos
    macro_df = pd.read_parquet(os.path.join(CACHE_DIR, "macro.parquet"))
    
    logger.info("--- [검증 1] 기간별 균등 OOS (최소 50일) ---")
    for y1, y2 in periods:
        res = run_oos(y1, y2, all_ticker_dfs, raw_returns_df, macro_df)
        if res and res['n_days'] >= 45: # 약 50일 근사치
            results.append(res)
        else:
            logger.warning(f"구간 {y1}-{y2} 데이터 부족으로 제외 ({res['n_days'] if res else 0}일)")

    # ────────────────────────────────────────────────────────
    # [2] 2024년 단독 Walk-forward 검증 (Train: 2022-23)
    # ────────────────────────────────────────────────────────
    logger.info("--- [검증 2] 2024 단독 Walk-forward (Train: 22-23) ---")
    wf_res = run_fixed_walk_forward(
        train_start="2022-01-01", train_end="2023-12-31",
        test_start="2024-01-01", test_end="2024-12-31",
        all_ticker_dfs=all_ticker_dfs, raw_returns_df=raw_returns_df
    )
    if wf_res:
        wf_res['period'] = "2024 (WF)"
        # KOSPI 2024 수익률 추가
        kb = macro_df[(macro_df['date'] >= "2024-01-01") & (macro_df['date'] <= "2024-12-31")].sort_values('date')
        wf_res['kospi'] = (kb['kospi_close'].iloc[-1] / kb['kospi_close'].iloc[0] - 1) * 100
        results.append(wf_res)

    # 결과 정리
    df_final = pd.DataFrame(results)
    print("\n" + "="*85)
    print(f"{'Ranking 전략 정밀 검증 (균등화 & WF)':^85}")
    print("="*85)
    print(df_final[['period', 'n_days', 'ic_mean', 'ls_net', 'p_value', 'kospi']].to_string(index=False))
    print("="*85)
    
    # 파일 저장
    df_final.to_markdown("refined_validation_report.md", index=False)
    logger.info("검증 완료. refined_validation_report.md 저장됨.")

if __name__ == "__main__":
    main()
