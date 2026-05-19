import os
import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DART_API_KEY = os.getenv("DART_API_KEY", "")

# 급등 유발 키워드
BULLISH_KEYWORDS = [
    "수주", "계약", "공급", "납품", "MOU", "협약",
    "임상", "승인", "허가", "특허", "선정",
    "영업이익", "흑자전환", "매출", "실적",
    "자사주", "배당", "분할",
]
BEARISH_KEYWORDS = [
    "횡령", "배임", "조사", "검찰", "상장폐지",
    "적자", "손실", "소송", "과징금",
]

def get_today_disclosures() -> list:
    """오늘 DART 공시 전체 수집"""
    if not DART_API_KEY:
        return []
    try:
        today = datetime.now().strftime("%Y%m%d")
        res = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "bgn_de":    today,
                "end_de":    today,
                "page_count": 100,
                "sort":      "date",
                "sort_mth":  "desc",
            },
            timeout=10
        )
        data = res.json()
        if data.get("status") != "000":
            return []
        return data.get("list", [])
    except Exception as e:
        logger.error(f"[DART] 공시 수집 실패: {e}")
        return []

def get_earnings_disclosures() -> list:
    """실적 관련 공시만 필터링"""
    if not DART_API_KEY:
        return []
    try:
        today = datetime.now().strftime("%Y%m%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        res = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": DART_API_KEY,
                "bgn_de":    week_ago,
                "end_de":    today,
                "pblntf_ty": "A",  # 정기공시
                "page_count": 100,
            },
            timeout=10
        )
        data = res.json()
        if data.get("status") != "000":
            return []
        disclosures = data.get("list", [])

        # 실적 관련만 필터
        earnings = []
        for d in disclosures:
            title = d.get("report_nm", "")
            if any(k in title for k in ["사업보고서", "분기보고서", "반기보고서", "실적"]):
                earnings.append({
                    "corp_name":  d.get("corp_name", ""),
                    "stock_code": d.get("stock_code", ""),
                    "title":      title,
                    "date":       d.get("rcept_dt", ""),
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d.get('rcept_no','')}",
                })
        return earnings
    except Exception as e:
        logger.error(f"[DART] 실적공시 수집 실패: {e}")
        return []

def analyze_disclosures(disclosures: list) -> list:
    """
    공시 분석 - 급등 가능성 점수 계산
    """
    results = []
    for d in disclosures:
        title = d.get("report_nm", "")
        corp  = d.get("corp_name", "")
        code  = d.get("stock_code", "")

        if not code:
            continue

        # 감성 분석
        bullish_count = sum(1 for k in BULLISH_KEYWORDS if k in title)
        bearish_count = sum(1 for k in BEARISH_KEYWORDS if k in title)

        if bullish_count == 0 and bearish_count == 0:
            continue

        sentiment = "bullish" if bullish_count > bearish_count else "bearish"
        score     = bullish_count - bearish_count

        # 매칭된 키워드
        matched = [k for k in BULLISH_KEYWORDS if k in title]
        matched += [k for k in BEARISH_KEYWORDS if k in title]

        results.append({
            "corp_name":  corp,
            "stock_code": code,
            "title":      title,
            "sentiment":  sentiment,
            "score":      score,
            "keywords":   matched,
            "date":       d.get("rcept_dt", ""),
            "time":       d.get("rcept_no", "")[:6] if d.get("rcept_no") else "",
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d.get('rcept_no','')}",
        })

    # 점수 높은 순 정렬
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def get_upcoming_earnings() -> list:
    """
    이번 주 실적 발표 예정 종목
    (네이버 증권 크롤링)
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        url = "https://finance.naver.com/research/earning_list.naver"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        results = []
        for row in soup.select("table.type_1 tr"):
            tds = row.select("td")
            if len(tds) < 4:
                continue
            try:
                results.append({
                    "corp_name":     tds[0].get_text(strip=True),
                    "period":        tds[1].get_text(strip=True),
                    "expected_date": tds[2].get_text(strip=True),
                    "revenue_est":   tds[3].get_text(strip=True),
                })
            except:
                continue
        return results[:20]
    except Exception as e:
        logger.error(f"[실적캘린더] {e}")
        return []
