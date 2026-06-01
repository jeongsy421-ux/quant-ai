import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import logging
import traceback
from datetime import datetime, timedelta
from urllib.parse import quote
from bs4 import BeautifulSoup
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import mean_absolute_error, accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from dotenv import load_dotenv

# ==========================================
# 글로벌 설정 및 뉴스 감성 분석 플래그
# ==========================================
USE_NEWS = False  # 뉴스 감성 분석 사용 여부 (True로 변경 시 Gemini API 키가 필요하며 백테스트 속도가 느려집니다)

# ==========================================
# 0. Logging Configuration
# ==========================================
out_dir = "backtest_results"
os.makedirs(out_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(out_dir, 'backtest_debug.log'),
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

# ==========================================
# 1. Gemini API Auth
# ==========================================
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 초기화
gemini_model = None
if USE_NEWS:
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            gemini_model = genai.GenerativeModel('gemini-pro')
            print("Gemini API 초기화 완료.")
        except Exception as e:
            print(f"Gemini API 초기화 실패: {e}")
            USE_NEWS = False
    else:
        print("경고: USE_NEWS = True 이지만 GEMINI_API_KEY가 .env에 존재하지 않습니다. 뉴스 분석 기능을 비활성화합니다.")
        USE_NEWS = False

# ==========================================
# 2. Sector Mapping Definitions (Expanded for KOSPI 100)
# ==========================================
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

# ==========================================
# 3. News Scraper & Sentiment Helpers
# ==========================================
def fetch_naver_news(company_name, before_date, days=3):
    """
    네이버 뉴스 검색에서 target_date(before_date) 이전 특정 기간의 헤드라인 수집
    """
    end_date = before_date - timedelta(days=1)
    start_date = before_date - timedelta(days=days)
    
    start_str = start_date.strftime("%Y.%m.%d")
    end_str = end_date.strftime("%Y.%m.%d")
    
    query = quote(company_name)
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sm=tab_opt&sort=1&photo=0&field=0&pd=3&ds={start_str}&de={end_str}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return []
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.select("a.news_tit")
        headlines = [link.get_text().strip() for link in links if link.get_text()]
        return headlines
    except Exception as e:
        logging.warning(f"Error scraping news for {company_name} [{start_str} ~ {end_str}]: {e}")
        return []

def get_news_sentiment(ticker, company_name, target_date, cache):
    """
    target_date 기준 직전 3일간 뉴스 헤드라인 감성 점수 (-1 ~ +1)
    cache: {(ticker, date): score} 딕셔너리로 중복 호출 방지
    """
    key = (ticker, target_date.strftime("%Y%m%d"))
    if key in cache:
        return cache[key]
    
    headlines = fetch_naver_news(company_name, before_date=target_date, days=3)
    if not headlines:
        cache[key] = 0.0
        return 0.0
    
    prompt = f'''다음은 {company_name} 관련 뉴스 헤드라인입니다.
주가에 미칠 영향을 -1(매우 부정) ~ +1(매우 긍정)로 평가하세요.
숫자만 출력하세요 (예: 0.3).

헤드라인:
{chr(10).join(headlines[:10])}'''
    
    try:
        response = gemini_model.generate_content(prompt)
        score_text = response.text.strip()
        import re
        match = re.search(r"[-+]?\d*\.\d+|\d+", score_text)
        if match:
            score = float(match.group())
        else:
            score = 0.0
        score = max(-1.0, min(1.0, score))
    except Exception as e:
        logging.warning(f"Gemini API Error for {company_name} on {target_date.strftime('%Y-%m-%d')}: {e}")
        score = 0.0
        
    cache[key] = score
    return score

# ==========================================
# 4. Technical Indicator Helper
# ==========================================
def calc_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff()
    minus_dm = -low.diff()
    
    plus_dm = plus_dm.copy()
    minus_dm = minus_dm.copy()
    
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

# ==========================================
# 5. Local Processing Functions (Cache-driven)
# ==========================================

def process_ticker(ticker, name, macro_df, sector_data, THRESHOLD, news_cache):
    logging.info(f"START {ticker} {name}")
    
    ticker_path = os.path.join("cache", f"{ticker}.parquet")
    if not os.path.exists(ticker_path):
        print(f"  [{name}] cache/{ticker}.parquet 파일이 존재하지 않습니다. 먼저 fetch_data.py를 실행하세요.")
        return [], []

    # 로컬 캐시에서 로드
    df = pd.read_parquet(ticker_path)
    if df.empty:
        logging.warning(f"EMPTY DATA {ticker}")
        return [], []
    
    # 글로벌 매크로 및 KOSPI, 환율 일괄 병합 (로컬 데이터 레이어에서 전달된 macro_df 사용)
    df = df.merge(macro_df, on="date", how="left")
    macro_cols = ["sp500", "nasdaq", "sox", "usdkrw", "kospi_close"]
    df[macro_cols] = df[macro_cols].ffill().fillna(0)
    
    sec_name = SECTOR_MAP.get(ticker, "기타")
    if sec_name in sector_data:
        df = df.merge(sector_data[sec_name].reset_index(), on='date', how='left')
    else:
        df['sector_return'] = 0.0

    # 1-A. ADX & DI 지표 계산
    df["adx"], plus_di, minus_di = calc_adx(df)
    df["di_diff"] = plus_di - minus_di

    # 기술적 피처 계산
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    
    # 이평선 기울기 (5일 전 대비 변화율)
    df["ma5_slope"] = df["ma5"].pct_change(5)
    df["ma20_slope"] = df["ma20"].pct_change(5)
    
    df["return_1d"] = df["close"].pct_change(1)
    df["return_5d"] = df["close"].pct_change(5)
    
    # 거래량 변화율 및 MA 대비 거래량
    df["vol_change_1d"] = df["volume"].pct_change(1)
    df["vol_ratio_5d"] = df["volume"] / (df["volume"].rolling(5).mean() + 1e-9)
    
    df["foreign_net_5d"] = df["foreign_net"].rolling(5).sum().fillna(0)
    df["institution_net_5d"] = df["institution_net"].rolling(5).sum().fillna(0)
    df["usdkrw_change_5d"] = df["usdkrw"].pct_change(5)
    df["sector_return_5d"] = df["sector_return"].rolling(5).sum()
    df["stock_vs_sector"] = df["return_5d"] - df["sector_return_5d"]
    df["vix_proxy"] = df["return_1d"].rolling(20).std() * np.sqrt(252)
    df["rsi14"] = 100 - (100 / (1 + (df["return_1d"].rolling(14).mean() / (df["return_1d"].rolling(14).std() + 1e-9))))
    
    # 1-B. 추세 지속성 피처 추가
    above = (df["close"] > df["ma20"]).astype(int)
    blocks = (above != above.shift()).cumsum()
    df["days_above_ma20"] = above.groupby(blocks).cumsum() * above

    # 정배열/역배열 점수 (MA5 > MA20 > MA60 이면 +1, 역배열 -1, 그 외 0)
    align_up = (df["ma5"] > df["ma20"]) & (df["ma20"] > df["ma60"])
    align_down = (df["ma5"] < df["ma20"]) & (df["ma20"] < df["ma60"])
    df["ma_alignment"] = 0
    df.loc[align_up, "ma_alignment"] = 1
    df.loc[align_down, "ma_alignment"] = -1

    # MA20 괴리율
    df["price_vs_ma20_pct"] = (df["close"] - df["ma20"]) / (df["ma20"] + 1e-9)

    # 2-A. 글로벌 매크로 피처 추가 (전일값 = shift(1))
    df["sp500_return_1d"] = df["sp500"].pct_change().shift(1)
    df["nasdaq_return_1d"] = df["nasdaq"].pct_change().shift(1)
    df["sox_return_1d"] = df["sox"].pct_change().shift(1)

    # 2-C. 실적 발표 근사 D-day 이벤트 플래그 계산
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    close_prev = df["close"].shift(1)
    gap = (df["open"] - close_prev).abs() / (close_prev + 1e-9)
    df["event_flag"] = ((df["volume"] > df["vol_ma20"] * 2) & (gap > 0.03)).astype(int)
    df["event_flag_3d"] = df["event_flag"].rolling(3).max().fillna(0).astype(int)

    # 2-B. 뉴스 감성 분석 사전 계산 (Gemini API 호출 및 캐싱)
    df["news_sentiment"] = 0.0
    if USE_NEWS and gemini_model is not None:
        print(f"  [{name}] 뉴스 감성 점수 수집 중...")
        sentiment_dates = df[(df['date'] >= '2025-05-15') & (df['date'] <= '2025-09-30')]['date'].tolist()
        for d in sentiment_dates:
            df.loc[df['date'] == d, 'news_sentiment'] = get_news_sentiment(ticker, name, d, news_cache)
            time.sleep(0.5)

    # 결측치 최종 제거/처리
    df = df.fillna(0)
    df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
    
    features = [
        'open', 'high', 'low', 'close', 'volume', 'ma5', 'ma5_slope', 'ma20_slope',
        'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
        'foreign_net_5d', 'institution_net_5d', 'usdkrw', 'usdkrw_change_5d', 
        'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
        'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
        'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
        'event_flag', 'event_flag_3d', 'news_sentiment'
    ]

    target_dates = df[(df['date'] >= '2025-06-01') & (df['date'] <= '2025-09-30')]['date'].tolist()
    
    ticker_rows_count = 0
    results = []
    importances_list = []
    
    for T in target_dates:
        idx_T_list = df.index[df['date'] == T].tolist()
        if not idx_T_list: continue
        idx_T = idx_T_list[0]
        if idx_T < 2: continue
        
        train_df = df.iloc[:idx_T-1].dropna(subset=features + ['target'])
        if len(train_df) < 60: continue
        
        X_train, y_train = train_df[features], train_df['target']
        X_test = df.iloc[[idx_T-1]][features]
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # 모델 설정 강화 (복잡도 증가)
        model_a = LogisticRegression(max_iter=3000, class_weight='balanced', solver='saga').fit(X_train_scaled, y_train)
        model_b = RandomForestClassifier(
            n_estimators=500, 
            max_depth=8, 
            min_samples_leaf=10, 
            max_features='sqrt',
            class_weight='balanced', 
            random_state=42
        ).fit(X_train_scaled, y_train)
        
        model_c = GradientBoostingClassifier(
            n_estimators=200, 
            learning_rate=0.05, 
            max_depth=5, 
            subsample=0.8,
            min_samples_leaf=10, 
            random_state=42
        )
        sw = compute_sample_weight('balanced', y_train)
        model_c.fit(X_train_scaled, y_train, sample_weight=sw)
        
        # 기본 앙상블 예측 확률 계산
        prob = 0.20 * model_a.predict_proba(X_test_scaled)[0,1] + 0.40 * model_b.predict_proba(X_test_scaled)[0,1] + 0.40 * model_c.predict_proba(X_test_scaled)[0,1]
        
        # 1-C. 추세장 가중 로직 적용
        val_adx = df.loc[idx_T-1, 'adx']
        val_di_diff = df.loc[idx_T-1, 'di_diff']
        
        if val_adx >= 25:
            if val_di_diff > 0:
                prob += 0.10  # 강한 상승 추세: UP 확률 추가 보정
            elif val_di_diff < 0:
                prob -= 0.10  # 강한 하락 추세: UP 확률 감소 보정
                
        # 0 ~ 1 범위로 최종 클리핑
        prob = np.clip(prob, 0.0, 1.0)
        
        # 피처 중요도 기록
        importances_list.append(model_b.feature_importances_)
        
        return_5d_mean = train_df['return_5d'].abs().mean()
        close_prev_val = df.loc[idx_T-1, 'close']
        pred_close = close_prev_val * (1 + return_5d_mean) if prob >= THRESHOLD else close_prev_val * (1 - return_5d_mean)
        actual_close = df.loc[idx_T, 'close']

        results.append({
            'ticker': ticker, 'company_name': name, 'date': T.strftime('%Y-%m-%d'),
            'predicted_direction': "UP" if prob >= THRESHOLD else "DOWN", 
            'up_probability': prob, 'predicted_close': pred_close, 'actual_close': actual_close, 
            'direction_correct': (prob >= THRESHOLD) == (actual_close > close_prev_val),
            'prediction_error': pred_close - actual_close,
            'adx': val_adx,
            'news_sentiment': df.loc[idx_T-1, 'news_sentiment'],
            'sox_return_1d': df.loc[idx_T-1, 'sox_return_1d']
        })
        ticker_rows_count += 1
    
    logging.info(f"OK    {ticker} rows={ticker_rows_count}")
    
    # 해당 종목의 평균 피처 중요도 출력
    if importances_list:
        avg_imp = np.mean(importances_list, axis=0)
        imp_series = pd.Series(avg_imp, index=features).sort_values(ascending=False)
        print(f"  -> {name} ({ticker}) 피처 중요도 (Top 5):")
        print(imp_series.head(5).to_string())
        
    return results, importances_list

# ==========================================
# 6. Main Execution
# ==========================================
def main():
    print("Starting Advanced KOSPI 100 Backtest (v5.0 - Cache Powered) for 2025 Q3...")
    
    macro_path = os.path.join("cache", "macro.parquet")
    if not os.path.exists(macro_path):
        print("에러: cache/macro.parquet 파일이 존재하지 않습니다.")
        print("먼저 'python fetch_data.py'를 실행하여 데이터를 다운로드 및 캐싱해 주세요.")
        sys.exit(1)

    csv_path = os.path.join(out_dir, "kospi100_backtest_2025_q3_v5.csv")
    THRESHOLD = 0.50

    print("로컬 캐시에서 글로벌 매크로 및 KOSPI/환율 데이터 로드 중...")
    macro_df = pd.read_parquet(macro_path)

    # 로컬 캐시 데이터를 이용하여 섹터 수익률 계산
    print("로컬 캐시 데이터를 이용하여 섹터 수익률 계산 중...")
    sector_data = {}
    for s_name in set(SECTOR_MAP.values()):
        s_tickers = [t for t, v in SECTOR_MAP.items() if v == s_name]
        s_returns = []
        for st in s_tickers:
            st_path = os.path.join("cache", f"{st}.parquet")
            if os.path.exists(st_path):
                sdf = pd.read_parquet(st_path)
                if not sdf.empty:
                    s_returns.append(sdf.set_index('date')['close'].pct_change())
        if s_returns:
            sector_data[s_name] = pd.concat(s_returns, axis=1).mean(axis=1).rename("sector_return")

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
        "SK머티리얼즈(036490.KS)", "원익IPS(240810.KS)", "피에스케이(319660.KS)",
        "두산퓨얼셀(336260.KS)", "씨에스윈드(112610.KS)", "한국전력기술(052690.KS)",
        "맥쿼리인프라(088980.KS)", "리츠나라(395400.KS)", "신한알파리츠(293940.KS)",
        "에스원(012750.KS)", "KT(030200.KS)",
        "LG유플러스(032640.KS)", "SK(034730.KS)"
    ]

    TICKERS = []
    for item in RAW_TICKERS:
        name = item.split("(")[0]
        ticker = item.split("(")[1][:6]
        TICKERS.append((ticker, name))

    results = []
    all_importances = []
    news_cache = {}

    for ticker, company_name in TICKERS:
        try:
            ticker_results, ticker_imps = process_ticker(
                ticker, company_name, macro_df, sector_data, THRESHOLD, news_cache
            )
            if ticker_results is not None and len(ticker_results) > 0:
                results.extend(ticker_results)
                # 매 종목마다 중간 저장 (끊겨도 데이터 보존)
                pd.DataFrame(results).to_csv(csv_path, index=False, encoding='utf-8-sig')
            if ticker_imps:
                all_importances.extend(ticker_imps)
        except Exception as e:
            print(f"  -> FAILED {company_name}: {e}")
            logging.error(f"FAIL {ticker}: {traceback.format_exc()}")
            continue

    print(f"\n완료: {len(set(r['ticker'] for r in results))}개 종목 처리됨")

    if not results:
        print("결과가 생성되지 않았습니다.")
        return

    # 요약 출력
    results_df = pd.read_csv(csv_path)
    print("\n=== Advanced Backtest Summary (2025 Q3 v5.0 - Cache Powered) ===")
    print(f"Overall Direction Accuracy: {results_df['direction_correct'].mean()*100:.2f}%")

    up_mask = results_df['predicted_direction'] == 'UP'
    down_mask = results_df['predicted_direction'] == 'DOWN'
    print(f"UP   Prediction Accuracy: {results_df.loc[up_mask,'direction_correct'].mean()*100:.2f}% ({up_mask.sum()} cases)")
    print(f"DOWN Prediction Accuracy: {results_df.loc[down_mask,'direction_correct'].mean()*100:.2f}% ({down_mask.sum()} cases)")
    print(f"Overall MAE: {results_df['prediction_error'].abs().mean():.2f}")

    # 추세장 vs 횡보장 정확도 비교
    trend_mask = results_df['adx'] >= 25
    range_mask = results_df['adx'] < 20
    
    if trend_mask.sum() > 0:
        trend_acc = results_df.loc[trend_mask, 'direction_correct'].mean() * 100
        print(f"Trend Market (adx >= 25) Accuracy: {trend_acc:.2f}% ({trend_mask.sum()} cases)")
    else:
        print("Trend Market (adx >= 25) Accuracy: N/A (0 cases)")
        
    if range_mask.sum() > 0:
        range_acc = results_df.loc[range_mask, 'direction_correct'].mean() * 100
        print(f"Range Market (adx < 20) Accuracy: {range_acc:.2f}% ({range_mask.sum()} cases)")
    else:
        print("Range Market (adx < 20) Accuracy: N/A (0 cases)")

    # 10개 최고/최저 정확도 종목
    ticker_acc = results_df.groupby('company_name')['direction_correct'].mean()*100
    ticker_acc = pd.to_numeric(ticker_acc, errors='coerce').dropna()
    print("\n--- Top 10 Accuracy ---")
    print(ticker_acc.nlargest(10))
    print("\n--- Bottom 10 Accuracy ---")
    print(ticker_acc.nsmallest(10))

    # 확신 구간 별 분석
    print("\n--- Confidence Filter Analysis ---")
    for threshold in [0.55, 0.60, 0.65]:
        mask = results_df['up_probability'] >= threshold
        if mask.sum() > 0:
            acc = results_df.loc[mask,'direction_correct'].mean()*100
            print(f"up_probability >= {threshold}: {acc:.2f}% ({mask.sum()} cases)")
        mask_down = results_df['up_probability'] <= (1 - threshold)
        if mask_down.sum() > 0:
            acc_down = results_df.loc[mask_down,'direction_correct'].mean()*100
            print(f"up_probability <= {1-threshold}: {acc_down:.2f}% ({mask_down.sum()} cases)")

    # 글로벌 피처 중요도 출력 (Top 15)
    features = [
        'open', 'high', 'low', 'close', 'volume', 'ma5', 'ma5_slope', 'ma20_slope',
        'return_1d', 'return_5d', 'vol_change_1d', 'vol_ratio_5d',
        'foreign_net_5d', 'institution_net_5d', 'usdkrw', 'usdkrw_change_5d', 
        'sector_return_5d', 'stock_vs_sector', 'vix_proxy', 'rsi14',
        'sp500_return_1d', 'nasdaq_return_1d', 'sox_return_1d',
        'adx', 'di_diff', 'days_above_ma20', 'ma_alignment', 'price_vs_ma20_pct',
        'event_flag', 'event_flag_3d', 'news_sentiment'
    ]
    if all_importances:
        global_avg_imp = np.mean(all_importances, axis=0)
        global_imp_series = pd.Series(global_avg_imp, index=features).sort_values(ascending=False)
        print("\n--- Global Feature Importances (Top 15) ---")
        print(global_imp_series.head(15))


if __name__ == "__main__":
    main()
