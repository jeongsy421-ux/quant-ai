"""
==============================================
[1단계] 뉴스 수집 모듈
==============================================
- 네이버 뉴스 API (한국어)
- NewsAPI (글로벌)
- DART 공시 수집 및 분석
- 가짜뉴스 1차 필터링 및 돌발 악재 감지
"""

import requests
import hashlib
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)


class NewsItem:
    def __init__(self, title, content, source, url, published_at):
        self.id           = hashlib.md5(url.encode()).hexdigest()[:8]
        self.title        = title
        self.content      = content
        self.source       = source
        self.url          = url
        self.published_at = published_at
        self.trust_score  = 0.0
        self.is_trusted   = False
        self.sentiment    = "중립"
        self.impact       = []   # 영향받는 섹터

    def to_dict(self):
        return {
            "id":           self.id,
            "title":        self.title,
            "content":      self.content[:200],
            "source":       self.source,
            "url":          self.url,
            "published_at": self.published_at,
            "trust_score":  self.trust_score,
            "is_trusted":   self.is_trusted,
            "sentiment":    self.sentiment,
            "impact":       self.impact,
        }


class FakeNewsFilter:
    """가짜뉴스 1차 필터링 및 악재 감지"""

    TRUSTED = [
        "yonhap", "연합뉴스", "hankyung", "한국경제",
        "mk.co.kr", "매일경제", "chosun", "조선일보",
        "donga", "동아일보", "mt.co.kr", "머니투데이",
        "edaily", "이데일리", "sedaily", "서울경제",
        "hani", "한겨레", "newsis", "뉴시스",
        "news1", "뉴스1", "yna.co.kr",
        "reuters", "bloomberg", "apnews", "wsj", "cnbc", "ft.com"
    ]

    SUSPICIOUS = [
        "[단독속보]", "100% 확실", "대박 종목",
        "비밀 정보", "내부자 제보", "긴급!!", "충격!!",
        "지금 당장", "놓치면 후회", "★★★", "폭등 임박",
    ]

    RISK_KEYWORDS = {
        "critical": ["서킷브레이커", "거래정지", "상장폐지", "파산", "부도", "전쟁", "핵공격"],
        "warning": ["폭락", "급락", "위기", "관세", "제재", "봉쇄", "디폴트"],
        "caution": ["우려", "하락압력", "리스크", "불확실", "조정", "경고"]
    }

    def score(self, news: NewsItem) -> float:
        score = 0.5
        src = news.source.lower()
        for t in self.TRUSTED:
            if t.lower() in src or t.lower() in news.url.lower():
                score += 0.4
                news.is_trusted = True
                break
        for p in self.SUSPICIOUS:
            if p in news.title:
                score -= 0.5
                break
        news.trust_score = max(0.0, min(1.0, score))
        return news.trust_score

    def detect_risk(self, news: NewsItem) -> Dict:
        text = news.title + " " + news.content
        for level, keywords in self.RISK_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return {"detected": True, "level": level, "keyword": kw, "title": news.title}
        return {"detected": False}

    def filter(self, news_list: List[NewsItem], min_score: float = 0.4):
        trusted, suspicious, risks = [], [], []
        for news in news_list:
            self.score(news)
            risk = self.detect_risk(news)
            if risk["detected"]: risks.append(risk)
            if news.trust_score >= min_score: trusted.append(news)
            else: suspicious.append(news)
        return trusted, suspicious, risks


class NaverNewsCollector:
    """네이버 뉴스 API (한국)"""
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self, client_id: str, client_secret: str):
        self.headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

    def fetch(self, keyword: str, display: int = 10) -> List[NewsItem]:
        try:
            r = requests.get(self.BASE_URL, headers=self.headers, params={"query": keyword, "display": display, "sort": "date"}, timeout=5)
            r.raise_for_status()
            items = r.json().get("items", [])
            return [NewsItem(item["title"].replace("<b>","").replace("</b>",""), 
                             item.get("description","").replace("<b>","").replace("</b>",""), 
                             "네이버뉴스", item.get("originallink") or item.get("link",""), 
                             item.get("pubDate","")) for item in items]
        except Exception as e:
            logger.error(f"Naver News Error: {e}")
            return []


class NewsAPICollector:
    """NewsAPI (글로벌 뉴스)"""
    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, keyword: str, display: int = 10) -> List[NewsItem]:
        if not self.api_key: return []
        try:
            params = {"q": keyword, "pageSize": display, "sortBy": "publishedAt", "apiKey": self.api_key}
            r = requests.get(self.BASE_URL, params=params, timeout=5)
            r.raise_for_status()
            articles = r.json().get("articles", [])
            return [NewsItem(a["title"], a.get("description") or "", a["source"]["name"], a["url"], a["publishedAt"]) for a in articles]
        except Exception as e:
            logger.error(f"NewsAPI Error: {e}")
            return []


class DartCollector:
    """DART 전자공시 고도화"""
    BASE_URL = "https://opendart.fss.or.kr/api/list.json"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_disclosures(self, bgn_date: str = None) -> List[Dict]:
        if not self.api_key: return []
        params = {"crtfc_key": self.api_key, "bgn_date": bgn_date or datetime.now().strftime("%Y%m%d"), "pblntf_ty": "A"}
        try:
            r = requests.get(self.BASE_URL, params=params, timeout=5)
            return r.json().get("list", [])
        except: return []

    def analyze_disclosures(self, disclosures: List[Dict]) -> Dict:
        """주요 공시(내부자거래, 실적발표 등) 분류"""
        analysis = {"insider": [], "earnings": [], "contracts": []}
        for d in disclosures:
            title = d.get("report_nm", "")
            if "최대주주" in title or "임원" in title: analysis["insider"].append(d)
            elif "영업실적" in title or "잠정실적" in title: analysis["earnings"].append(d)
            elif "단일판매" in title or "공급계약" in title: analysis["contracts"].append(d)
        return analysis


class NewsCollector:
    """뉴스 및 공시 통합 관리자"""

    def __init__(self, config):
        self.naver = NaverNewsCollector(config.NAVER_CLIENT_ID, config.NAVER_CLIENT_SECRET)
        news_api_key = os.getenv("NEWS_API_KEY", "")
        self.global_news = NewsAPICollector(news_api_key) if news_api_key else None
        self.dart = DartCollector(config.DART_API_KEY)
        self.filter = FakeNewsFilter()
        self.config = config

    def collect(self) -> Dict:
        print("\n 뉴스/공시 통합 수집 중...")

        # 1. 뉴스 수집 (한/영)
        kr_news = []
        for kw in self.config.NEWS_KEYWORDS[:3]: kr_news.extend(self.naver.fetch(kw))
        
        en_news = []
        if self.global_news:
            en_news = self.global_news.fetch("KOSPI OR Samsung Electronics")

        all_news = kr_news + en_news
        trusted, suspicious, risks = self.filter.filter(all_news)

        # 2. 공시 수집
        disclosures = self.dart.fetch_disclosures()
        dart_analysis = self.dart.analyze_disclosures(disclosures)

        return {
            "news": {"trusted": [n.to_dict() for n in trusted], "risks": risks},
            "dart": dart_analysis,
            "updated_at": datetime.now().isoformat()
        }