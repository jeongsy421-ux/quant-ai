import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import argparse
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

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

# ==========================================
# 3. KIS Split-Loop Data Fetching
# ==========================================

def get_kis_daily_price_full(ticker, start_date, end_date, token):
    """
    100일 제한을 우회하기 위해 역산 루프(Backward Loop)를 사용하여 전체 일봉 수집
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET, "tr_id": "FHKST03010100", "custtype": "P"
    }
    
    all_dfs = []
    current_end = end_date
    
    while True:
        if current_end < start_date:
            break
            
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": current_end,
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0" # 수정주가 적용
        }
        
        res = safe_request_get(url, headers=headers, params=params)
        if not res: break
        
        data = res.json()
        rows = data.get("output2", [])
        if not rows: break
        
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "stck_bsop_date": "date", 
            "stck_oprc": "open", 
            "stck_hgpr": "high", 
            "stck_lwpr": "low", 
            "stck_clpr": "close", 
            "acml_vol": "volume"
        })
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        all_dfs.append(df)
        
        # 가장 빠른 날짜 확인
        earliest_date = df["date"].min()
        if earliest_date <= pd.to_datetime(start_date, format="%Y%m%d"):
            break
            
        # 다음 루프를 위해 종료일 갱신 (1일 차감)
        current_end = (earliest_date - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.1) # 루프 간 짧은 휴식
        
    if not all_dfs: return pd.DataFrame()
    
    final_df = pd.concat(all_dfs).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return final_df

def get_investor_trading_full(ticker, start_date, end_date, token):
    """
    수급 데이터(외국인/기관)를 분할 수집
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET, "tr_id": "FHKST01010900"
    }
    
    all_dfs = []
    current_end = end_date
    
    while True:
        if current_end < start_date:
            break
            
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": current_end,
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
        if earliest_date <= pd.to_datetime(start_date, format="%Y%m%d"):
            break
            
        current_end = (earliest_date - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.1)
        
    if not all_dfs: return pd.DataFrame()
    
    final_df = pd.concat(all_dfs).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return final_df

# ==========================================
# 4. Main Data Downloader Execution
# ==========================================
def main():
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)

    print("=== KIS API 기반 33개월 전수 데이터 수집 시작 ===")
    
    try:
        token = get_kis_token()
        print("KIS API 토큰 발급 완료.")
    except Exception as e:
        print(f"Error: KIS API 토큰 발급 실패 ({e})")
        sys.exit(1)

    start_date, end_date = "20230101", "20250930"

    # 1. 매크로 데이터 (KIS ETF 프록시 사용)
    macro_path = os.path.join(cache_dir, "macro.parquet")
    print("매크로 데이터(ETF 프록시) 수집 중...")
    
    proxies = {
        "kospi_close": "069500", # KODEX 200
        "sp500": "360750",       # TIGER 미국S&P500
        "nasdaq": "133690",      # TIGER 미국나스닥100
        "sox": "381170",         # TIGER 미국필라델피아반도체나스닥
        "usdkrw": "261220"       # KODEX 미국달러선물
    }
    
    macro_master_df = None
    for col_name, ticker in proxies.items():
        print(f"  Fetching {col_name} ({ticker})...")
        df = get_kis_daily_price_full(ticker, start_date, end_date, token)
        if df.empty: continue
        
        temp_df = df[["date", "close"]].rename(columns={"close": col_name})
        if macro_master_df is None:
            macro_master_df = temp_df
        else:
            macro_master_df = pd.merge(macro_master_df, temp_df, on="date", how="outer")
            
    if macro_master_df is not None:
        macro_master_df = macro_master_df.sort_values("date").reset_index(drop=True)
        macro_master_df.to_parquet(macro_path, index=False)
        print(f"  -> cache/macro.parquet 저장 완료 ({len(macro_master_df)} 행)")

    # 2. 개별 종목 데이터 수집
    RAW_TICKERS = [
        "삼성전자(005930.KS)", "SK하이닉스(000660.KS)", "현대차(005380.KS)",
        "LG화학(051910.KS)", "삼성바이오로직스(207940.KS)", "셀트리온(068270.KS)",
        "카카오(035720.KS)", "NAVER(035420.KS)", "기아(000270.KS)", "삼성SDI(006400.KS)",
        "현대모비스(012330.KS)", "LG전자(066570.KS)", "SK텔레콤(017670.KS)", "KB금융(105560.KS)",
        "신한지주(055550.KS)", "포스코홀딩스(005490.KS)", "하나금융지주(086790.KS)",
        "삼성물산(028260.KS)", "LG생활건강(051900.KS)", "삼성생명(032830.KS)",
        "SK이노베이션(096770.KS)", "한국전력(015760.KS)", "롯데케미칼(011170.KS)",
        "두산에너빌리티(034020.KS)", "삼성에스디에스(018260.KS)", "코웨이(021240.KS)",
        "넷마블(251270.KS)", "엔씨소프트(036570.KS)", "한온시스템(018880.KS)",
        "카카오뱅크(323410.KS)", "삼성화재(000810.KS)", "SK바이오팜(326030.KS)",
        "오리온(271560.KS)", "아모레퍼시픽(090430.KS)", "KT&G(033780.KS)",
        "이마트(139480.KS)", "GS칼텍스모기업GS(078930.KS)", "S-Oil(010950.KS)",
        "금호석유(011780.KS)", "HMM(011200.KS)", "현대제철(004020.KS)",
        "한화솔루션(009830.KS)", "한국타이어앤테크놀로지(161390.KS)", "현대건설(000720.KS)",
        "GS건설(006360.KS)", "대우건설(047040.KS)", "영풍(000670.KS)", "고려아연(010130.KS)",
        "OCI(010060.KS)", "동원F&B(049770.KS)", "CJ제일제당(097950.KS)", "CJ(001040.KS)",
        "롯데쇼핑(023530.KS)", "신세계(004170.KS)", "현대백화점(069960.KS)",
        "BGF리테일(282330.KS)", "한미약품(128940.KS)", "유한양행(000100.KS)",
        "종근당(185750.KS)", "동아ST(170900.KS)", "대웅제약(069620.KS)",
        "한국항공우주(047810.KS)", "한화에어로스페이스(012450.KS)", "LIG넥스원(079550.KS)",
        "현대로템(064350.KS)", "한진칼(180640.KS)", "대한항공(003490.KS)",
        "아시아나항공(020560.KS)", "CJ대한통운(000120.KS)", "팬오션(028670.KS)",
        "대한해운(005880.KS)", "한국가스공사(036460.KS)", "한국석유(004090.KS)",
        "두산밥캣(241560.KS)", "HD현대(267250.KS)", "삼성중공업(010140.KS)",
        "한화오션(042660.KS)", "HD현대중공업(329180.KS)", "한국조선해양(009540.KS)",
        "롯데정밀화학(004000.KS)", "효성(004800.KS)", "효성티앤씨(298020.KS)",
        "효성첨단소재(298050.KS)", "코오롱인더(120110.KS)", "태광산업(003240.KS)",
        "DB하이텍(000990.KS)", "리노공업(058470.KS)", "솔브레인(357780.KS)",
        "원익IPS(240810.KS)", "피에스케이(319660.KS)",
        "두산퓨얼셀(336260.KS)", "씨에스윈드(112610.KS)", "한국전력기술(052690.KS)",
        "맥쿼리인프라(088980.KS)", "리츠나라(395400.KS)", "신한알파리츠(293940.KS)",
        "에스원(012750.KS)", "KT(030200.KS)",
        "LG유플러스(032640.KS)", "SK(034730.KS)"
    ]

    success_count = 0
    fail_count = 0

    for idx, item in enumerate(RAW_TICKERS):
        name = item.split("(")[0]
        ticker = item.split("(")[1][:6]
        ticker_path = os.path.join(cache_dir, f"{ticker}.parquet")

        try:
            print(f"[{idx+1}/{len(RAW_TICKERS)}] {name} ({ticker}) 수집 중...")
            
            # 1. 일봉 가격 (33개월)
            price_df = get_kis_daily_price_full(ticker, start_date, end_date, token)
            if price_df.empty:
                print(f"  -> EMPTY PRICE DATA {ticker}")
                fail_count += 1
                continue
                
            # 2. 수급 데이터 (33개월)
            investor_df = get_investor_trading_full(ticker, start_date, end_date, token)
            if not investor_df.empty:
                final_df = pd.merge(price_df, investor_df, on='date', how='left').fillna(0)
            else:
                final_df = price_df.assign(foreign_net=0, institution_net=0)

            # 저장
            final_df.to_parquet(ticker_path, index=False)
            success_count += 1
            
            # 종목 간 충분한 휴식 (Rate Limit 방지)
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  -> 실패 {name} ({ticker}): {e}")
            fail_count += 1
            continue

    print(f"\n=== 전체 수집 완료 ===")
    print(f"성공: {success_count}개 | 실패: {fail_count}개")

    # 3. 삼성전자(005930) 검증
    samsung_path = os.path.join(cache_dir, "005930.parquet")
    if os.path.exists(samsung_path):
        sdf = pd.read_parquet(samsung_path)
        print(f"\n[검증] 삼성전자(005930) 데이터 스냅샷:")
        print(f"  - 시작일: {sdf['date'].min()}")
        print(f"  - 종료일: {sdf['date'].max()}")
        print(f"  - 총 행수: {len(sdf)} 행")

if __name__ == "__main__":
    main()
