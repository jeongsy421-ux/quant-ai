"""
==============================================
QUANT AI - 설정 파일 (최종 전종목 버전)
==============================================
"""
from dotenv import load_dotenv
import os

load_dotenv()

# ─────────────────────────────────────────
# API 키
# ─────────────────────────────────────────
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
DART_API_KEY        = os.getenv("DART_API_KEY", "")
FRED_API_KEY        = os.getenv("FRED_API_KEY", "")
KAKAO_REST_API_KEY  = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_ACCESS_TOKEN  = os.getenv("KAKAO_ACCESS_TOKEN", "")
AI_MODEL            = os.getenv("AI_MODEL", "gemini")
AI_BACKUP           = os.getenv("AI_BACKUP", "groq")
TOTAL_CAPITAL       = int(os.getenv("TOTAL_CAPITAL", "2000000"))

# ─────────────────────────────────────────
# 전종목 스캔 설정
# ─────────────────────────────────────────
UNIVERSE_MODE = "ALL"

SCAN_FILTER = {
    "min_market_cap":    50_000_000_000,  # 시총 최소 500억
    "min_volume":        100_000,          # 일 거래량 최소 10만주
    "min_trade_amount":  3_000_000_000,    # 일 거래대금 최소 30억
    "max_rsi":           45,               # RSI 45 이하
    "min_volume_ratio":  1.3,              # 평균 대비 거래량 1.3배 이상
    "exclude_etf":       True,
    "exclude_spac":      True,
    "exclude_preferred": True,
    "max_results":       100,
}

MARKETS = {
    "KOSPI":  {"suffix": ".KS", "enabled": True},
    "KOSDAQ": {"suffix": ".KQ", "enabled": True},
}

# ─────────────────────────────────────────
# 글로벌 지수 티커 (정상 작동하는 것만)
# ─────────────────────────────────────────
GLOBAL_TICKERS = {
    "S&P500":  "^GSPC",
    "NASDAQ":  "^IXIC",
    "KOSPI":   "^KS11",
    "KOSDAQ":  "^KQ11",
    "NIKKEI":  "^N225",
    "상해":     "000001.SS",
    "대만":     "^TWII",
    "DAX":     "^GDAXI",
    "VIX":     "^VIX",
    "USD/KRW": "USDKRW=X",
    # 제거: ^BDIY, M1, M2 (야후파이낸스 미지원)
}

MACRO_TICKERS = {
    "USD/KRW": "USDKRW=X",
    "WTI":     "CL=F",
    "GOLD":    "GC=F",
    "COPPER":  "HG=F",
}

# ─────────────────────────────────────────
# 테마 키워드 매핑
# ─────────────────────────────────────────
THEME_KEYWORDS = {
    "반도체":  ["반도체", "파운드리", "HBM", "메모리", "시스템반도체"],
    "IT":      ["소프트웨어", "플랫폼", "클라우드", "AI", "인터넷"],
    "자동차":  ["자동차", "부품", "전기차", "모빌리티"],
    "방산":    ["방위", "항공우주", "무기", "방산"],
    "원전":    ["원자력", "원전", "핵연료", "에너지솔루션"],
    "조선":    ["조선", "해양", "선박", "LNG선"],
    "건설":    ["건설", "건축", "분양", "시공"],
    "에너지":  ["정유", "석유", "가스", "에너지"],
    "철강":    ["철강", "금속", "제철", "동"],
    "2차전지": ["배터리", "2차전지", "양극재", "음극재", "전해질"],
    "바이오":  ["바이오", "제약", "헬스케어", "신약"],
    "금융":    ["은행", "증권", "보험", "금융"],
    "화학":    ["화학", "석유화학", "소재"],
    "통신":    ["통신", "인터넷", "네트워크"],
    "유통":    ["유통", "리테일", "쇼핑"],
    "항공":    ["항공", "공항", "여행"],
}

# ─────────────────────────────────────────
# 뉴스 키워드
# ─────────────────────────────────────────
NEWS_KEYWORDS = [
    "코스피", "코스닥", "반도체", "관세", "이란",
    "환율", "외국인", "기관매수", "금리", "유가",
    "실적", "방산", "원전", "조선", "건설",
    "2차전지", "바이오", "AI반도체", "HBM",
]

TRUSTED_SOURCES = [
    "yonhap", "연합뉴스", "hankyung", "한국경제",
    "mk.co.kr", "매일경제", "chosun", "조선일보",
    "donga", "동아일보", "mt.co.kr", "머니투데이",
    "edaily", "이데일리", "sedaily", "서울경제",
    "newsis", "뉴시스", "news1", "뉴스1",
    "reuters", "bloomberg", "apnews", "wsj",
]

# ─────────────────────────────────────────
# 매매 전략
# ─────────────────────────────────────────
STRATEGY = {
    "total_capital":     2_000_000,
    "buy_threshold":     65,
    "sell_threshold":    65,
    "stop_loss_pct":     -3.0,
    "take_profit_pct":   5.0,
    "max_positions":     3,
    "kelly_fraction":    0.5,   # 하프 켈리
    "max_hold_days":     3,
}

# ─────────────────────────────────────────
# 기술적 지표
# ─────────────────────────────────────────
TECHNICAL = {
    "rsi_period":        14,
    "rsi_oversold":      35,
    "rsi_overbought":    70,
    "bb_period":         20,
    "bb_std":            2.0,
    "ma_short":          5,
    "ma_mid":            20,
    "ma_long":           60,
    "volume_surge":      1.5,
    "momentum_volume":   2.5,   # 급등주 감지 거래량 배율
    "momentum_price":    5.0,   # 급등주 감지 가격 상승률(%)
}

# ─────────────────────────────────────────
# 리스크 관리
# ─────────────────────────────────────────
RISK = {
    "var_confidence":    [0.95, 0.99],
    "monte_carlo_runs":  1000,
    "max_drawdown":      -0.10,   # 월 최대 손실 -10%
    "monthly_loss_limit": -0.10,  # 이 이상 손실 시 매매 중단
}

# ─────────────────────────────────────────
# 외부 데이터 소스 (14개 사이트)
# ─────────────────────────────────────────
EXTERNAL_SOURCES = {
    "fear_greed_url":    "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
    "trendforce_url":    "https://www.trendforce.com/price/dram",
    "finviz_enabled":    True,
    "whalewisdom_enabled": True,
    "cryptoquant_enabled": True,
}

# ─────────────────────────────────────────
# 자동 학습 소스
# ─────────────────────────────────────────
LEARNING_SOURCES = [
    "https://quantocracy.com/",
    "https://epchan.blogspot.com/",
    "https://blog.quantinsti.com/",
    "https://www.quantstart.com/articles/",
    "https://www.investopedia.com/trading-4427765",
]

# ─────────────────────────────────────────
# 시스템 설정
# ─────────────────────────────────────────
SYSTEM = {
    "news_interval_min":  5,
    "analysis_interval":  15,
    "scan_interval":      30,
    "learning_hour":      6,    # 매일 새벽 6시 자동 학습
    "log_dir":            "logs",
    "data_dir":           "data",
    "port":               5000,
}

# ─────────────────────────────────────────
# ETF (장기 모드)
# ─────────────────────────────────────────
ETF_UNIVERSE = {
    "KODEX200":        {"ticker": "069500.KS", "type": "국내주식"},
    "TIGER미국S&P500": {"ticker": "360750.KS", "type": "해외주식"},
    "KODEX국채":       {"ticker": "114820.KS", "type": "채권"},
    "TIGER금선물":     {"ticker": "132030.KS", "type": "원자재"},
    "KODEX리츠":       {"ticker": "432320.KS", "type": "리츠"},
}

PORTFOLIO_STYLES = {
    "안정형": {"국내주식":15,"해외주식":15,"채권":40,"원자재":20,"리츠":10},
    "균형형": {"국내주식":25,"해외주식":25,"채권":25,"원자재":15,"리츠":10},
    "성장형": {"국내주식":35,"해외주식":45,"채권":10,"원자재":5,"리츠":5},
}

# ─────────────────────────────────────────
# Polymarket 스타일 이벤트 예측
# ─────────────────────────────────────────
EVENTS = [
    {
        "id": "fomc_hold",
        "title": "이번 FOMC 금리 동결",
        "category": "매크로",
        "related_themes": ["금융"],
        "base_prob": 0.78,
    },
    {
        "id": "samsung_surprise",
        "title": "삼성전자 실적 서프라이즈",
        "category": "반도체",
        "related_themes": ["반도체"],
        "base_prob": 0.62,
    },
    {
        "id": "tariff_chip",
        "title": "반도체 관세 실제 시행",
        "category": "지정학",
        "related_themes": ["반도체"],
        "base_prob": 0.45,
    },
]
