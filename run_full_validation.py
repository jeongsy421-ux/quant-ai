import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from scipy.stats import spearmanr
from xgboost import XGBRegressor
import warnings

# ==========================================
# 0. Configuration & Setup
# ==========================================
warnings.filterwarnings('ignore')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("multi_period_validation.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
KIS_APP_KEY = os.getenv("KIS_APP_KEY")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET")
BASE_URL = "https://openapi.koreainvestment.com:9443"

# 백엔드 경로 추가
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from backend.config import RANKING_UNIVERSE

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

FEATURES = [
    'volume', 'ma5_slope', 'ma20_slope',
    'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
    'foreign_net_5d', 'institution_net_5d', 'usdkrw_change_5d', 
    'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
    'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
    'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
    'event_flag', 'event_flag_3d', 'news_sentiment'
]

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

COST = 0.0015 # 0.15% per side = 0.3% round-trip

# ==========================================
# 1. Data Fetching Helpers
# ==========================================
def get_kis_token():
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET}
    res = requests.post(url, json=body, timeout=10)
    return res.json()["access_token"]

def safe_request_get(url, headers, params):
    for attempt in range(5):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            return res
        except:
            time.sleep(1)
    return None

def get_kis_data(ticker, start, end, token, mode="price"):
    tr_id = "FHKST03010100" if mode == "price" else "FHKST01010900"
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/" + ("inquire-daily-itemchartprice" if mode == "price" else "inquire-investor")
    headers = {"content-type": "application/json", "authorization": f"Bearer {token}", "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET, "tr_id": tr_id, "custtype": "P"}
    
    all_rows = []
    curr_end = end
    while curr_end >= start:
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker, "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": curr_end, "FID_PERIOD_DIV_CODE": "D"}
        if mode == "price": params["FID_ORG_ADJ_PRC"] = "0"
        
        res = safe_request_get(url, headers, params)
        if not res: break
        rows = res.json().get("output2", [])
        if not rows: break
        all_rows.extend(rows)
        earliest = rows[-1]["stck_bsop_date"]
        if earliest <= start: break
        curr_end = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.05)
    
    if not all_rows: return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    if mode == "price":
        df = df.rename(columns={"stck_bsop_date":"date","stck_oprc":"open","stck_hgpr":"high","stck_lwpr":"low","stck_clpr":"close","acml_vol":"volume"})
        cols = ["open","high","low","close","volume"]
    else:
        df = df.rename(columns={"stck_bsop_date":"date","frgn_ntby_qty":"foreign_net","orgn_ntby_qty":"institution_net"})
        cols = ["foreign_net","institution_net"]
    
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in cols: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df.drop_duplicates("date")

# ==========================================
# 2. Backtest Engine (Logic from validate_alpha_oos_2022.py)
# ==========================================
def calc_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-9))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    return dx.rolling(period).mean(), plus_di, minus_di

def compute_features(df, macro_df, sector_data, ticker):
    df = df.merge(macro_df, on="date", how="left")
    for c in ["sp500", "nasdaq", "sox", "usdkrw"]: df[c] = df[c].ffill().fillna(0)
    
    sec_name = SECTOR_MAP.get(ticker, "기타")
    df['sector_return'] = sector_data.get(sec_name, pd.Series(0, index=df.index)).reindex(df['date']).values if sec_name in sector_data else 0
    
    df["adx"], plus_di, minus_di = calc_adx(df)
    df["di_diff"] = plus_di - minus_di
    for w in [5, 20, 60]: df[f"ma{w}"] = df["close"].rolling(w).mean()
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
    df["days_above_ma20"] = above.groupby((above != above.shift()).cumsum()).cumsum() * above
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
    df["forward_return_5d"] = (df["close"].shift(-5) / df["close"]) - 1
    return df.replace([np.inf, -np.inf], np.nan).fillna(0)

def run_oos(start_yr, end_yr, all_ticker_dfs, raw_returns_df, macro_df):
    start_date = f"{start_yr}-01-01"
    end_date = f"{end_yr}-12-31"
    
    date_sets = [set(df[(df['date'] >= start_date) & (df['date'] <= end_date)]['date']) for df in all_ticker_dfs.values()]
    common_dates = sorted(set.intersection(*date_sets))[::5]
    if not common_dates: return None
    
    daily_ics, ls_returns, daily_dfs = [], [], []
    for T in common_dates:
        X_train_list, y_train_list, test_info = [], [], []
        for ticker, df in all_ticker_dfs.items():
            idx_list = df.index[df['date'] == T].tolist()
            if not idx_list: continue
            idx_T = idx_list[0]
            last_train_idx = idx_T - 5 - 1
            if last_train_idx < 100: continue
            train_df = df.iloc[:last_train_idx+1].dropna(subset=FEATURES + ['forward_return_5d']).tail(600)
            if len(train_df) < 50: continue
            X_train_list.append(train_df[FEATURES]); y_train_list.append(train_df['forward_return_5d'])
            actual_fwd = raw_returns_df[(raw_returns_df['date'] == T) & (raw_returns_df['ticker'] == ticker)]['forward_return_5d'].values[0]
            test_info.append({'ticker': ticker, 'X_test': df.iloc[[idx_T]][FEATURES], 'actual': actual_fwd})
        
        if len(test_info) < 20: continue
        model = XGBRegressor(n_estimators=150, max_depth=3, learning_rate=0.03, n_jobs=-1, random_state=42)
        model.fit(pd.concat(X_train_list), pd.concat(y_train_list))
        
        preds = []
        for item in test_info:
            preds.append({'ticker':item['ticker'], 'score':model.predict(item['X_test'])[0], 'actual':item['actual']})
        d_df = pd.DataFrame(preds)
        ic, _ = spearmanr(d_df['score'], d_df['actual'])
        if not np.isnan(ic): daily_ics.append(ic)
        
        top, bot = d_df.nlargest(20, 'score'), d_df.nsmallest(20, 'score')
        ls_returns.append((top['actual'].mean() - COST) - (bot['actual'].mean() + COST))
        daily_dfs.append(d_df)

    if not daily_ics: return None
    ls_cum = (1 + pd.Series(ls_returns)).cumprod().iloc[-1] - 1
    
    # p-value (100 shuffles)
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
    
    # Benchmark (KOSPI)
    kb = macro_df[(macro_df['date'] >= start_date) & (macro_df['date'] <= end_date)].sort_values('date')
    kret = (kb['kospi_close'].iloc[-1] / kb['kospi_close'].iloc[0] - 1) if not kb.empty else 0

    return {
        "period": f"{start_yr}-{end_yr}",
        "n_days": len(daily_ics),
        "ic_mean": np.mean(daily_ics),
        "icir": np.mean(daily_ics) / (np.std(daily_ics) + 1e-9),
        "ls_net": ls_cum * 100,
        "p_value": p_val,
        "kospi": kret * 100
    }

# ==========================================
# 3. Main Orchestrator
# ==========================================
def main():
    logger.info("=== 다중 기간 OOS 전수 검증 시작 ===")
    token = get_kis_token()
    
    # 1. 부족 데이터 수집 (2019-2020, 2023)
    periods = [("20190101", "20201231"), ("20230101", "20231231")]
    for s, e in periods:
        logger.info(f"데이터 수집 중: {s} ~ {e}")
        # Macro
        proxies = {"kospi_close": "069500", "sp500": "360750", "nasdaq": "133690", "sox": "381170", "usdkrw": "261220"}
        macro_dfs = []
        for name, tk in proxies.items():
            df = get_kis_data(tk, s, e, token, "price")
            if not df.empty: macro_dfs.append(df[["date", "close"]].rename(columns={"close": name}))
        if macro_dfs:
            new_m = macro_dfs[0]
            for n in macro_dfs[1:]: new_m = pd.merge(new_m, n, on="date", how="outer")
            old_m = pd.read_parquet(os.path.join(CACHE_DIR, "macro.parquet")) if os.path.exists(os.path.join(CACHE_DIR, "macro.parquet")) else pd.DataFrame()
            pd.concat([old_m, new_m]).drop_duplicates("date").sort_values("date").to_parquet(os.path.join(CACHE_DIR, "macro.parquet"), index=False)
        
        # Stocks
        for tk_ks in RANKING_UNIVERSE:
            tk = tk_ks.split(".")[0]
            p = get_kis_data(tk, s, e, token, "price")
            if p.empty: continue
            
            i = get_kis_data(tk, s, e, token, "investor")
            if not i.empty and "date" in i.columns:
                merged = pd.merge(p, i, on="date", how="left").fillna(0)
            else:
                # 수급 데이터가 없는 경우 0으로 채움
                merged = p.assign(foreign_net=0, institution_net=0)
                
            p_path = os.path.join(CACHE_DIR, f"{tk}.parquet")
            old = pd.read_parquet(p_path) if os.path.exists(p_path) else pd.DataFrame()
            pd.concat([old, merged]).drop_duplicates("date").sort_values("date").to_parquet(p_path, index=False)
    
    logger.info("데이터 수집 완료. 백테스트 시작...")
    
    # 2. 피처 계산 (메모리 효율을 위해 로딩 후 처리)
    macro_df = pd.read_parquet(os.path.join(CACHE_DIR, "macro.parquet"))
    tickers = [t.split(".")[0] for t in RANKING_UNIVERSE]
    sector_data = {}
    for s_name in set(SECTOR_MAP.values()):
        s_rets = []
        for st in [t for t, v in SECTOR_MAP.items() if v == s_name]:
            path = os.path.join(CACHE_DIR, f"{st}.parquet")
            if os.path.exists(path):
                sdf = pd.read_parquet(path)
                if not sdf.empty: s_rets.append(sdf.set_index('date')['close'].pct_change())
        if s_rets: sector_data[s_name] = pd.concat(s_rets, axis=1).mean(axis=1)

    all_ticker_list = []
    for tk in tickers:
        path = os.path.join(CACHE_DIR, f"{tk}.parquet")
        if not os.path.exists(path): continue
        df = pd.read_parquet(path)
        if len(df) < 100: continue
        df = compute_features(df, macro_df, sector_data, tk)
        df["ticker"] = tk
        all_ticker_list.append(df)
    
    full_df = pd.concat(all_ticker_list)
    raw_returns_df = full_df[['date', 'ticker', 'forward_return_5d']].copy()
    
    # ─── 정합성 수정: 진짜 횡단면 Z-score (날짜별 그룹화) ───
    # 기존: 종목별 루프 내에서 정규화 (시계열 오류)
    # 수정: 전체 통합 후 날짜별로 그룹화하여 종목 간 상대값 산출
    for col in FEATURES + ['forward_return_5d']:
        full_df[col] = full_df.groupby('date')[col].transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-9) if len(x) > 1 else x - x.mean()
        )
    
    all_ticker_dfs = {t: full_df[full_df['ticker'] == t].copy() for t in full_df['ticker'].unique()}
    
    # 3. 연도별 실행
    results = []
    test_years = [(2020, 2020), (2021, 2021), (2022, 2022), (2023, 2023), (2024, 2025)]
    for y1, y2 in test_years:
        logger.info(f"검증 중: {y1} ~ {y2}")
        res = run_oos(y1, y2, all_ticker_dfs, raw_returns_df, macro_df)
        if res: results.append(res)
        
    # 4. 결과 정리 및 저장
    df_res = pd.DataFrame(results)
    md = "# Ranking 전략 다중 기간 OOS 검증 리포트\n\n"
    md += f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    md += "## 기간별 성과 요약\n\n"
    md += df_res.to_markdown(index=False) + "\n\n"
    
    all_positive = all(df_res['ls_net'] > 0)
    stability = "✅ 우수 (전 기간 양수)" if all_positive else "⚠️ 주의 (일부 기간 손실)"
    md += f"## 안정성 판정\n- 전 기간 L-S Net 양수 여부: {stability}\n"
    md += f"- 평균 p-value: {df_res['p_value'].mean():.4f}\n"
    
    with open("multi_period_validation.md", "w", encoding="utf-8") as f:
        f.write(md)
    
    logger.info("\n" + df_res.to_string(index=False))
    logger.info("=== 모든 검증 완료 (multi_period_validation.md 저장됨) ===")

if __name__ == "__main__":
    main()
