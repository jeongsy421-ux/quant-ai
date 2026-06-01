import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 백엔드 경로 추가
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
from backend.config import RANKING_UNIVERSE

# ==========================================
# 0. Logging Configuration
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

# ==========================================
# 1. KIS API Auth
# ==========================================
load_dotenv()
KIS_APP_KEY = os.getenv("KIS_APP_KEY")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET")

BASE_URL = "https://openapi.koreainvestment.com:9443"

def get_kis_token():
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET}
    res = requests.post(url, json=body, timeout=10)
    return res.json()["access_token"]

# ==========================================
# 2. Network Stability Helpers
# ==========================================
def safe_request_get(url, headers, params, max_retries=5, initial_delay=1.0):
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=15)
            if res.status_code == 429:
                delay = initial_delay * (2 ** attempt)
                logging.warning(f"API Rate limit hit (429). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            if res.status_code != 200:
                logging.warning(f"API Error ({res.status_code}): {res.text}. Retrying...")
                time.sleep(initial_delay)
                continue
            return res
        except requests.exceptions.RequestException as e:
            delay = initial_delay * (2 ** attempt)
            logging.warning(f"Request exception: {e}. Retrying in {delay}s...")
            time.sleep(delay)
    return None

def get_kis_daily_price_full(ticker, start_date, end_date, token):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET, "tr_id": "FHKST03010100", "custtype": "P"
    }
    all_dfs = []
    current_end = end_date
    while True:
        if current_end < start_date: break
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": current_end,
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0" 
        }
        res = safe_request_get(url, headers=headers, params=params)
        if not res: break
        data = res.json()
        rows = data.get("output2", [])
        if not rows: break
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "stck_bsop_date": "date", "stck_oprc": "open", "stck_hgpr": "high", 
            "stck_lwpr": "low", "stck_clpr": "close", "acml_vol": "volume"
        })
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        all_dfs.append(df)
        earliest_date = df["date"].min()
        if earliest_date <= pd.to_datetime(start_date, format="%Y%m%d"): break
        current_end = (earliest_date - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.05)
    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs).drop_duplicates("date").sort_values("date").reset_index(drop=True)

def get_investor_trading_full(ticker, start_date, end_date, token):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET, "tr_id": "FHKST01010900"
    }
    all_dfs = []
    current_end = end_date
    while True:
        if current_end < start_date: break
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": current_end,
            "FID_PERIOD_DIV_CODE": "D"
        }
        res = safe_request_get(url, headers=headers, params=params)
        if not res: break
        data = res.json()
        rows = data.get("output2", [])
        if not rows: break
        df = pd.DataFrame(rows)
        df = df.rename(columns={"stck_bsop_date": "date", "frgn_ntby_qty": "foreign_net", "orgn_ntby_qty": "institution_net"})
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce").fillna(0)
        df["institution_net"] = pd.to_numeric(df["institution_net"], errors="coerce").fillna(0)
        all_dfs.append(df[["date", "foreign_net", "institution_net"]])
        earliest_date = df["date"].min()
        if earliest_date <= pd.to_datetime(start_date, format="%Y%m%d"): break
        current_end = (earliest_date - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.05)
    if not all_dfs: return pd.DataFrame()
    return pd.concat(all_dfs).drop_duplicates("date").sort_values("date").reset_index(drop=True)

# ==========================================
# 4. Main Data Downloader Execution
# ==========================================
def main():
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    print("=== OOS 검증용 데이터 수집 (2021-2022) 시작 ===")
    try:
        token = get_kis_token()
        print("KIS API 토큰 발급 완료.")
    except Exception as e:
        print(f"Error: KIS API 토큰 발급 실패 ({e})")
        return

    start_date, end_date = "20210101", "20221231"

    # 1. 매크로 데이터
    macro_path = os.path.join(cache_dir, "macro.parquet")
    proxies = {
        "kospi_close": "069500", "sp500": "360750", "nasdaq": "133690",
        "sox": "381170", "usdkrw": "261220"
    }
    
    macro_dfs = []
    for col_name, ticker in proxies.items():
        print(f"  Fetching Macro {col_name} ({ticker})...")
        df = get_kis_daily_price_full(ticker, start_date, end_date, token)
        if not df.empty:
            macro_dfs.append(df[["date", "close"]].rename(columns={"close": col_name}))
    
    if macro_dfs:
        new_macro_df = macro_dfs[0]
        for next_df in macro_dfs[1:]:
            new_macro_df = pd.merge(new_macro_df, next_df, on="date", how="outer")
        
        if os.path.exists(macro_path):
            old_macro_df = pd.read_parquet(macro_path)
            combined_macro = pd.concat([old_macro_df, new_macro_df]).drop_duplicates("date").sort_values("date")
        else:
            combined_macro = new_macro_df.sort_values("date")
        combined_macro.to_parquet(macro_path, index=False)
        print(f"  -> macro.parquet 업데이트 완료 ({len(combined_macro)} 행)")

    # 2. 종목 데이터
    tickers = [t.split(".")[0] for t in RANKING_UNIVERSE]
    success_count = 0
    
    for idx, ticker in enumerate(tickers):
        ticker_path = os.path.join(cache_dir, f"{ticker}.parquet")
        try:
            print(f"[{idx+1}/{len(tickers)}] {ticker} 수집 중...")
            price_df = get_kis_daily_price_full(ticker, start_date, end_date, token)
            if price_df.empty: continue
            investor_df = get_investor_trading_full(ticker, start_date, end_date, token)
            if not investor_df.empty:
                new_df = pd.merge(price_df, investor_df, on='date', how='left').fillna(0)
            else:
                new_df = price_df.assign(foreign_net=0, institution_net=0)
            
            if os.path.exists(ticker_path):
                old_df = pd.read_parquet(ticker_path)
                final_df = pd.concat([old_df, new_df]).drop_duplicates("date").sort_values("date")
            else:
                final_df = new_df.sort_values("date")
            
            final_df.to_parquet(ticker_path, index=False)
            success_count += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  -> 실패 {ticker}: {e}")

    print(f"\n=== 수집 완료 (성공: {success_count}개) ===")

if __name__ == "__main__":
    main()
