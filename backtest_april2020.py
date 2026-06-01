import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_absolute_percentage_error
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from dotenv import load_dotenv

# ==========================================
# 1. KIS API Auth
# ==========================================
load_dotenv()
KIS_APP_KEY = os.getenv("KIS_APP_KEY")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")

BASE_URL = "https://openapi.koreainvestment.com:9443"

def get_kis_token():
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET
    }
    res = requests.post(url, json=body)
    return res.json()["access_token"]

KIS_TOKEN = None

def init_token():
    """토큰 발급 (최초 1회)"""
    global KIS_TOKEN
    if KIS_TOKEN is None:
        try:
            KIS_TOKEN = get_kis_token()
            print("KIS 토큰 발급 성공")
        except Exception as e:
            print(f"Failed to get KIS token: {e}")
            KIS_TOKEN = None
    return KIS_TOKEN

# ==========================================
# 2. KIS API Functions
# ==========================================
def get_kis_daily_price(ticker, start_date, end_date, token):
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": "FHKST03010100",
        "custtype": "P"
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0"
    }
    
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 429:
        time.sleep(5)
        res = requests.get(url, headers=headers, params=params)
        
    data = res.json()
    if data.get("rt_cd") != "0":
        raise Exception(f"KIS API 오류: {data.get('msg1')}")
    
    rows = data.get("output2", [])
    if not rows: return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "stck_bsop_date": "date",
        "stck_oprc": "open", "stck_hgpr": "high", "stck_lwpr": "low", "stck_clpr": "close",
        "acml_vol": "volume"
    })[["date", "open", "high", "low", "close", "volume"]]
    
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    return df.sort_values("date").reset_index(drop=True)

def to_kis_ticker(ticker_with_suffix):
    import re
    match = re.search(r'(\d{6})', ticker_with_suffix)
    return match.group(1) if match else ticker_with_suffix[:6]

def get_paginated_daily_price(ticker, token):
    periods = [("20190101", "20190831"), ("20190901", "20200131"), ("20200201", "20200430")]
    dfs = []
    for s, e in periods:
        time.sleep(0.1)
        try:
            df = get_kis_daily_price(ticker, s, e, token)
            if not df.empty: dfs.append(df)
        except: pass
    return pd.concat(dfs).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True) if dfs else pd.DataFrame()

def get_paginated_kospi(token):
    ticker_kodex200 = "069500"
    df = get_paginated_daily_price(ticker_kodex200, token)
    return df.rename(columns={"close": "kospi_close"})[["date", "kospi_close"]] if not df.empty else pd.DataFrame()

# ==========================================
# 3. Target Tickers (KOSPI 100)
# ==========================================
TICKERS_RAW = [
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
    "SK머티리얼즈(036490.KS)", "원익IPS(240810.KS)", "피에스케이(319660.KS)",
    "두산퓨얼셀(336260.KS)", "씨에스윈드(112610.KS)", "한국전력기술(052690.KS)",
    "맥쿼리인프라(088980.KS)", "리츠나라(395400.KS)", "신한알파리츠(293940.KS)",
    "에스원(012750.KS)", "삼성에버랜드모기업삼성물산(028260.KS)", "KT(030200.KS)",
    "LG유플러스(032640.KS)", "SK(034730.KS)"
]

# ==========================================
# 4. Feature Engineering
# ==========================================
def calculate_features(df, kospi_df):
    df = df.copy()
    df = pd.merge(df, kospi_df, on="date", how="left")
    df["kospi_close"] = df["kospi_close"].ffill()
    
    # 기본 지표
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["return_1d"] = df["close"].pct_change(1)
    df["return_5d"] = df["close"].pct_change(5)
    
    # 모멘텀 피처
    df["return_20d"] = df["close"].pct_change(20)
    df["high_252"] = df["close"].rolling(252, min_periods=1).max()
    df["low_252"] = df["close"].rolling(252, min_periods=1).min()
    df["high_52w_ratio"] = df["close"] / df["high_252"]
    df["low_52w_ratio"] = df["close"] / df["low_252"]
    
    # 거래량 피처
    price_diff = df["close"].diff()
    direction = np.where(price_diff > 0, 1, np.where(price_diff < 0, -1, 0))
    df["obv"] = (direction * df["volume"]).cumsum()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["vol_ma20"]
    df["volume_spike"] = np.where(df["volume_ratio"] >= 2.0, 1, 0)
    
    # 시장 피처
    df["kospi_return_1d"] = df["kospi_close"].pct_change(1)
    df["kospi_return_5d"] = df["kospi_close"].pct_change(5)
    df["stock_vs_kospi"] = df["return_5d"] - df["kospi_return_5d"]
    
    # 기술적 지표
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df["rsi14"] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    df["macd"] = df["close"].ewm(span=12).mean() - df["close"].ewm(span=26).mean()
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    bb_m = df["close"].rolling(20).mean()
    bb_s = df["close"].rolling(20).std()
    df["bb_upper"] = bb_m + 2*bb_s
    df["bb_lower"] = bb_m - 2*bb_s
    
    # 레이블 (상승=1, 하락=0)
    df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
    return df

# ==========================================
# 5. Main Execution
# ==========================================
def main(output_dir=None):
    """백테스트 실행. output_dir 미지정 시 스크립트 위치 기준 backtest_results 폴더 사용.
    Returns: (summary_text, csv_path) tuple or (None, None) on failure.
    """
    print("Starting Improved KOSPI 100 Backtest (Classification + Imbalance Fix) for April 2020...")
    init_token()
    if not KIS_TOKEN:
        return ("Error: KIS 토큰 발급 실패", None)

    kospi_df = get_paginated_kospi(KIS_TOKEN)
    if kospi_df.empty:
        return ("Error: KOSPI 지수 데이터 조회 실패", None)

    results = []
    features = ['open', 'high', 'low', 'close', 'volume', 'ma5', 'ma20', 'ma60', 
                'return_1d', 'return_5d', 'return_20d', 'high_52w_ratio', 'low_52w_ratio',
                'obv', 'volume_ratio', 'volume_spike', 'kospi_return_1d', 'kospi_return_5d', 
                'stock_vs_kospi', 'rsi14', 'macd', 'macd_signal', 'bb_upper', 'bb_lower']
    
    # 전체 샘플링 분포 기록용
    actual_labels = []

    for item in TICKERS_RAW:
        name = item.split("(")[0]
        kis_ticker = to_kis_ticker(item)
        print(f"Processing {name} ({kis_ticker})...")
        
        df = get_paginated_daily_price(kis_ticker, KIS_TOKEN)
        if df.empty: continue
        df = calculate_features(df, kospi_df)
        
        april_dates = df[(df['date'] >= '2020-04-01') & (df['date'] <= '2020-04-30')]['date'].tolist()
        
        for T in april_dates:
            idx_list = df.index[df['date'] == T].tolist()
            if not idx_list: continue
            idx_T = idx_list[0]
            if idx_T < 2: continue
            
            idx_T_minus_1 = idx_T - 1
            train_df = df.iloc[:idx_T_minus_1].dropna(subset=features + ['target'])
            if len(train_df) < 60: continue
            
            # [개선 2: 피처 스케일링]
            X_train, y_train = train_df[features], train_df['target']
            X_test = df.iloc[[idx_T_minus_1]][features]
            if X_test.isna().any().any(): continue

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            # [개선 1: 클래스 불균형 해결]
            model_a = LogisticRegression(max_iter=3000, solver='saga', class_weight='balanced').fit(X_train_scaled, y_train)
            model_b = RandomForestClassifier(n_estimators=200, max_depth=6, class_weight='balanced', random_state=42).fit(X_train_scaled, y_train)
            
            # GBC는 class_weight 미지원으로 sample_weight 적용
            model_c = GradientBoostingClassifier(n_estimators=100, learning_rate=0.05, random_state=42)
            sw = compute_sample_weight('balanced', y_train)
            model_c.fit(X_train_scaled, y_train, sample_weight=sw)
            
            # 앙상블 상승 확률 (Soft Voting)
            prob = 0.25 * model_a.predict_proba(X_test_scaled)[0,1] + \
                   0.50 * model_b.predict_proba(X_test_scaled)[0,1] + \
                   0.25 * model_c.predict_proba(X_test_scaled)[0,1]
            
            # [개선 3: 예측 임계값 조정]
            pred_dir_str = "UP" if prob >= 0.45 else "DOWN"
            
            # 종가 추정 (5일 평균 변동폭 활용)
            return_5d_mean = train_df['return_5d'].abs().mean()
            close_prev = df.loc[idx_T_minus_1, 'close']
            pred_close = close_prev * (1 + return_5d_mean) if prob >= 0.45 else close_prev * (1 - return_5d_mean)
            
            actual_close = df.loc[idx_T, 'close']
            actual_dir = 1 if actual_close > close_prev else 0
            actual_labels.append(actual_dir)
            
            results.append({
                'ticker': kis_ticker, 'company_name': name, 'date': T.strftime('%Y-%m-%d'),
                'predicted_direction': pred_dir_str, 'up_probability': prob,
                'predicted_close': pred_close, 'actual_close': actual_close,
                'direction_correct': (prob >= 0.45) == (actual_dir == 1),
                'actual_direction': "UP" if actual_dir == 1 else "DOWN",
                'prediction_error': pred_close - actual_close,
                'error_pct': ((pred_close - actual_close) / actual_close) * 100,
                'model_confidence': prob
            })

    res_df = pd.DataFrame(results)
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results")
    out_dir = output_dir
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "kospi100_backtest_april2020.csv")
    res_df.to_csv(csv_path, index=False, encoding='utf-8-sig')

    if not res_df.empty:
        # [지표 계산]
        acc = res_df['direction_correct'].mean() * 100
        up_res = res_df[res_df['predicted_direction'] == "UP"]
        dn_res = res_df[res_df['predicted_direction'] == "DOWN"]
        up_acc = up_res['direction_correct'].mean() * 100 if not up_res.empty else 0
        dn_acc = dn_res['direction_correct'].mean() * 100 if not dn_res.empty else 0
        
        # 실제 및 예측 분포
        real_up_ratio = np.mean(actual_labels) * 100
        pred_up_ratio = (res_df['predicted_direction'] == "UP").mean() * 100
        
        mae = mean_absolute_error(res_df['actual_close'], res_df['predicted_close'])
        ticker_acc = res_df.groupby('company_name')['direction_correct'].mean() * 100
        
        # [개선 4: Summary 추가 출력]
        summary = (
            f"=== Balanced Backtest Summary (April 2020) ===\n"
            f"Overall Direction Accuracy: {acc:.2f}%\n"
            f"UP Prediction Accuracy: {up_acc:.2f}% ({len(up_res)} cases)\n"
            f"DOWN Prediction Accuracy: {dn_acc:.2f}% ({len(dn_res)} cases)\n"
            f"Overall MAE: {mae:.2f}\n\n"
            f"--- Label Distribution ---\n"
            f"Actual UP Ratio: {real_up_ratio:.2f}%\n"
            f"Predicted UP Ratio: {pred_up_ratio:.2f}%\n\n"
            f"--- Top 10 Accuracy (By Ticker) ---\n{ticker_acc.nlargest(10).to_string()}\n\n"
            f"--- Bottom 10 Accuracy (By Ticker) ---\n{ticker_acc.nsmallest(10).to_string()}\n"
        )
        print("\n" + summary)
        with open(os.path.join(out_dir, "kospi100_backtest_summary.txt"), 'w', encoding='utf-8') as f:
            f.write(summary)
        return (summary, csv_path)
    return ("결과 데이터 없음", csv_path)

if __name__ == "__main__":
    summary, path = main()
    if path:
        print(f"\nCSV 저장 완료: {path}")
