"""
==============================================
QUANT AI - 자동 학습 모듈
==============================================
5개 퀀트 사이트에서 최신 전략/이론 수집
→ Gemini AI로 분석
→ 전략 파라미터 자동 업데이트
→ 학습 결과 DB 저장

실행 주기: 매일 새벽 6시 자동 실행
==============================================
"""

import requests
import json
import os
import time
import logging
import sqlite3
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings("ignore")

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_PATH = os.path.join(os.path.dirname(__file__), "../data/learning.db")

LEARNING_SOURCES = [
    {
        "name": "Quantocracy",
        "url": "https://quantocracy.com/",
        "type": "mashup",
        "selectors": {
            "articles": "div.post",
            "title": "h2.post-title a, a",
            "summary": "div.post-content p",
            "link": "h2.post-title a, a",
        }
    },
    {
        "name": "Ernest Chan Blog",
        "url": "https://epchan.blogspot.com/",
        "type": "blog",
        "selectors": {
            "articles": "div.post",
            "title": "h3.post-title a",
            "summary": "div.post-body",
            "link": "h3.post-title a",
        }
    },
    {
        "name": "QuantInsti",
        "url": "https://blog.quantinsti.com/",
        "type": "blog",
        "selectors": {
            "articles": "article",
            "title": "h2 a, h3 a",
            "summary": "p",
            "link": "h2 a, h3 a",
        }
    },
    {
        "name": "QuantStart",
        "url": "https://www.quantstart.com/articles/",
        "type": "articles",
        "selectors": {
            "articles": "article, div.article",
            "title": "h2 a, h3 a",
            "summary": "p",
            "link": "h2 a, h3 a",
        }
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ─────────────────────────────────────────
# 1. DB 초기화
# ─────────────────────────────────────────
def init_db():
    """학습 결과 저장 DB 초기화"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 수집된 아티클
    c.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            summary TEXT,
            url TEXT,
            collected_at TEXT,
            analyzed INTEGER DEFAULT 0
        )
    """)

    # Gemini 분석 결과
    c.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT,
            strategy_type TEXT,
            key_insight TEXT,
            applicable_to TEXT,
            implementation_priority INTEGER,
            code_suggestion TEXT,
            analyzed_at TEXT
        )
    """)

    # 학습으로 업데이트된 파라미터
    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            param_name TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            source TEXT,
            updated_at TEXT,
            applied INTEGER DEFAULT 0
        )
    """)

    # 학습 요약 리포트
    c.execute("""
        CREATE TABLE IF NOT EXISTS learning_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT,
            articles_collected INTEGER,
            insights_extracted INTEGER,
            params_updated INTEGER,
            summary TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅ 학습 DB 초기화 완료")


# ─────────────────────────────────────────
# 2. 사이트 크롤링
# ─────────────────────────────────────────
class SiteCrawler:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def crawl_site(self, source: dict) -> list:
        """단일 사이트 크롤링"""
        try:
            logger.info(f" 크롤링: {source['name']}")
            r = self.session.get(source["url"], timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            articles = []
            sel = source["selectors"]

            # 아티클 컨테이너 찾기
            containers = soup.select(sel["articles"])
            if not containers:
                containers = [soup]

            for container in containers[:10]:
                try:
                    # 제목
                    title_el = container.select_one(sel["title"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 10:
                        continue

                    # 요약
                    summary_el = container.select_one(sel["summary"])
                    summary = summary_el.get_text(strip=True)[:300] if summary_el else ""

                    # 링크
                    link_el = container.select_one(sel["link"])
                    link = link_el.get("href", "") if link_el else ""
                    if link and not link.startswith("http"):
                        from urllib.parse import urljoin
                        link = urljoin(source["url"], link)

                    # 중복 방지용 ID
                    article_id = hashlib.md5(f"{source['name']}{title}".encode()).hexdigest()[:12]

                    articles.append({
                        "id": article_id,
                        "source": source["name"],
                        "title": title,
                        "summary": summary,
                        "url": link,
                        "collected_at": datetime.now().isoformat(),
                    })
                except Exception as e:
                    continue

            logger.info(f"  ✅ {source['name']}: {len(articles)}개 수집")
            return articles

        except Exception as e:
            logger.error(f"  ❌ {source['name']} 크롤링 실패: {e}")
            return []

    def crawl_all(self) -> list:
        """전체 사이트 크롤링"""
        all_articles = []
        for source in LEARNING_SOURCES:
            articles = self.crawl_site(source)
            all_articles.extend(articles)
            time.sleep(2)  # 요청 간격

        logger.info(f" 총 수집: {len(all_articles)}개 아티클")
        return all_articles


# ─────────────────────────────────────────
# 3. DB 저장
# ─────────────────────────────────────────
def save_articles(articles: list) -> int:
    """새 아티클만 DB에 저장"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_count = 0

    for article in articles:
        try:
            c.execute("""
                INSERT OR IGNORE INTO articles
                (id, source, title, summary, url, collected_at, analyzed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                article["id"], article["source"],
                article["title"], article["summary"],
                article["url"], article["collected_at"]
            ))
            if c.rowcount > 0:
                new_count += 1
        except Exception as e:
            continue

    conn.commit()
    conn.close()
    logger.info(f" 새 아티클 저장: {new_count}개")
    return new_count


# ─────────────────────────────────────────
# 4. Gemini AI 분석
# ─────────────────────────────────────────
class GeminiAnalyzer:

    def __init__(self):
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def analyze_articles(self, articles: list) -> list:
        """아티클 묶음을 Gemini로 분석"""
        if not articles:
            return []

        # 아티클 텍스트 준비
        articles_text = "\n\n".join([
            f"[{i+1}] {a['source']}\n제목: {a['title']}\n내용: {a['summary']}"
            for i, a in enumerate(articles[:15])
        ])

        prompt = f"""
당신은 한국 주식 단기 매매 시스템을 위한 퀀트 전략 분석가입니다.

아래 퀀트 파이낸스 사이트들에서 수집한 최신 아티클들을 분석하여,
우리 시스템에 적용 가능한 전략과 인사이트를 추출해주세요.

우리 시스템 스펙:
- 코스피/코스닥 전종목 스캔
- RSI, 볼린저밴드, MACD 기술적 지표
- XGBoost + RF + GB 앙상블 머신러닝
- 켈리 공식 + 몬테카를로 + VaR 리스크 관리
- 200만원 단타 투자 (1~3일 보유)
- Gemini AI 뉴스 감성 분석

=== 수집된 아티클 ===
{articles_text}

=== 분석 요청 ===
다음 형식의 JSON으로만 응답하세요 (다른 텍스트 없이):

{{
    "insights": [
        {{
            "article_index": 1,
            "strategy_type": "모멘텀/평균회귀/이벤트드리븐/리스크관리/머신러닝 중 하나",
            "key_insight": "핵심 인사이트 1~2문장",
            "applicable_to": "우리 시스템의 어느 부분에 적용 가능한지",
            "priority": 1~5 숫자 (5가 가장 중요),
            "code_hint": "Python 코드 힌트 1~3줄"
        }}
    ],
    "param_updates": [
        {{
            "param_name": "파라미터 이름 (예: rsi_oversold, kelly_fraction 등)",
            "current_value": "현재 값",
            "suggested_value": "제안 값",
            "reason": "변경 이유"
        }}
    ],
    "new_strategies": [
        {{
            "name": "전략 이름",
            "description": "전략 설명",
            "implementation": "구현 방법 간단 설명"
        }}
    ],
    "weekly_summary": "이번 주 퀀트 트렌드 요약 2~3문장"
}}
"""

        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()

            # JSON 파싱
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            logger.info(f" Gemini 분석 완료: {len(result.get('insights', []))}개 인사이트")
            return result

        except Exception as e:
            logger.error(f"❌ Gemini 분석 실패: {e}")
            return {}

    def analyze_single(self, article: dict) -> dict:
        """단일 아티클 상세 분석"""
        prompt = f"""
다음 퀀트 파이낸스 아티클을 분석하여 한국 주식 단기 매매에 적용 가능한
구체적인 Python 코드와 전략을 제시해주세요.

제목: {article['title']}
출처: {article['source']}
내용: {article['summary']}

JSON 형식으로만 응답:
{{
    "strategy_type": "전략 유형",
    "key_insight": "핵심 인사이트",
    "applicable_to": "적용 가능 부분",
    "priority": 1~5,
    "python_code": "실제 구현 가능한 Python 코드 (10~20줄)",
    "backtest_idea": "백테스트 방법",
    "expected_improvement": "예상 개선 효과"
}}
"""
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            return json.loads(text)
        except:
            return {}


# ─────────────────────────────────────────
# 5. 분석 결과 저장 및 전략 업데이트
# ─────────────────────────────────────────
def save_analysis(analysis: dict, articles: list):
    """분석 결과 DB 저장"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()

    # 인사이트 저장
    insights = analysis.get("insights", [])
    for insight in insights:
        idx = insight.get("article_index", 1) - 1
        article_id = articles[idx]["id"] if idx < len(articles) else "unknown"

        c.execute("""
            INSERT INTO analysis_results
            (article_id, strategy_type, key_insight, applicable_to,
             implementation_priority, code_suggestion, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            article_id,
            insight.get("strategy_type", ""),
            insight.get("key_insight", ""),
            insight.get("applicable_to", ""),
            insight.get("priority", 3),
            insight.get("code_hint", ""),
            now
        ))

        # 분석 완료 표시
        c.execute("UPDATE articles SET analyzed=1 WHERE id=?", (article_id,))

    # 파라미터 업데이트 제안 저장
    param_updates = analysis.get("param_updates", [])
    for update in param_updates:
        c.execute("""
            INSERT INTO strategy_updates
            (param_name, old_value, new_value, reason, source, updated_at, applied)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (
            update.get("param_name", ""),
            str(update.get("current_value", "")),
            str(update.get("suggested_value", "")),
            update.get("reason", ""),
            "AI 학습",
            now
        ))

    # 학습 리포트 저장
    c.execute("""
        INSERT INTO learning_reports
        (report_date, articles_collected, insights_extracted,
         params_updated, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d"),
        len(articles),
        len(insights),
        len(param_updates),
        analysis.get("weekly_summary", ""),
        now
    ))

    conn.commit()
    conn.close()
    logger.info(f" 분석 결과 저장: {len(insights)}개 인사이트, {len(param_updates)}개 파라미터 업데이트")


# ─────────────────────────────────────────
# 6. 학습 결과 조회
# ─────────────────────────────────────────
def get_latest_insights(limit: int = 10) -> list:
    """최신 인사이트 조회"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT ar.strategy_type, ar.key_insight, ar.applicable_to,
                   ar.implementation_priority, ar.code_suggestion, ar.analyzed_at,
                   a.source, a.title
            FROM analysis_results ar
            JOIN articles a ON ar.article_id = a.id
            ORDER BY ar.analyzed_at DESC, ar.implementation_priority DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()

        return [{
            "strategy_type": r[0],
            "key_insight": r[1],
            "applicable_to": r[2],
            "priority": r[3],
            "code_hint": r[4],
            "analyzed_at": r[5],
            "source": r[6],
            "article_title": r[7],
        } for r in rows]
    except:
        return []


def get_pending_updates() -> list:
    """적용 대기 중인 파라미터 업데이트 조회"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT param_name, old_value, new_value, reason, source, updated_at
            FROM strategy_updates
            WHERE applied = 0
            ORDER BY updated_at DESC
        """)
        rows = c.fetchall()
        conn.close()

        return [{
            "param": r[0], "old": r[1], "new": r[2],
            "reason": r[3], "source": r[4], "date": r[5]
        } for r in rows]
    except:
        return []


def get_learning_report() -> dict:
    """최신 학습 리포트 조회"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT report_date, articles_collected, insights_extracted,
                   params_updated, summary
            FROM learning_reports
            ORDER BY created_at DESC LIMIT 1
        """)
        row = c.fetchone()
        conn.close()

        if row:
            return {
                "date": row[0], "articles": row[1],
                "insights": row[2], "updates": row[3], "summary": row[4]
            }
        return {}
    except:
        return {}


def apply_param_update(param_name: str, new_value: str) -> bool:
    """승인된 파라미터 업데이트 적용"""
    try:
        # config.py의 파라미터 업데이트
        config_path = os.path.join(os.path.dirname(__file__), "config.py")

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 파라미터 찾아서 업데이트
        import re
        pattern = rf'("{param_name}"\s*:\s*)([^,\n]+)'
        new_content = re.sub(pattern, rf'\g<1>{new_value}', content)

        if new_content != content:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # DB에 적용 완료 표시
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                UPDATE strategy_updates SET applied=1
                WHERE param_name=? AND applied=0
            """, (param_name,))
            conn.commit()
            conn.close()

            logger.info(f"✅ 파라미터 적용: {param_name} = {new_value}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ 파라미터 적용 실패: {e}")
        return False


# ─────────────────────────────────────────
# 7. 메인 학습 루프
# ─────────────────────────────────────────
class QuantLearner:

    def __init__(self):
        init_db()
        self.crawler = SiteCrawler()
        self.analyzer = GeminiAnalyzer()

    def run_daily_learning(self):
        """매일 실행되는 학습 사이클"""
        print("\n" + "="*50)
        print(f"[LEARNING] QUANT AI 자동 학습 시작")
        print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*50)

        try:
            # 1. 크롤링
            print("\n[1/4] 사이트 크롤링 중...")
            articles = self.crawler.crawl_all()
            new_count = save_articles(articles)
            print(f"   → 신규 아티클: {new_count}개")

            if new_count == 0:
                print("   → 새로운 아티클 없음, 학습 스킵")
                return self._get_summary()

            # 2. 미분석 아티클 가져오기
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT id, source, title, summary, url
                FROM articles WHERE analyzed=0
                ORDER BY collected_at DESC LIMIT 15
            """)
            rows = c.fetchall()
            conn.close()

            unanalyzed = [{
                "id": r[0], "source": r[1], "title": r[2],
                "summary": r[3], "url": r[4]
            } for r in rows]

            # 3. Gemini 분석
            print(f"\n [2/4] AI 분석 중 ({len(unanalyzed)}개 아티클)...")
            analysis = self.analyzer.analyze_articles(unanalyzed)

            # 4. 결과 저장
            print("\n [3/4] 분석 결과 저장 중...")
            if analysis:
                save_analysis(analysis, unanalyzed)

            # 5. 요약 출력
            print("\n [4/4] 학습 완료!")
            summary = self._get_summary()
            self._print_summary(summary)

            return summary

        except Exception as e:
            logger.error(f"학습 실패: {e}")
            return {"error": str(e)}

    def _get_summary(self) -> dict:
        """학습 요약 반환"""
        report = get_learning_report()
        insights = get_latest_insights(5)
        updates = get_pending_updates()

        return {
            "report": report,
            "top_insights": insights,
            "pending_updates": updates,
            "updated_at": datetime.now().isoformat()
        }

    def _print_summary(self, summary: dict):
        """요약 출력"""
        report = summary.get("report", {})
        if report:
            print(f"\n 오늘 학습 결과:")
            print(f"   수집 아티클: {report.get('articles', 0)}개")
            print(f"   추출 인사이트: {report.get('insights', 0)}개")
            print(f"   파라미터 업데이트 제안: {report.get('updates', 0)}개")
            if report.get("summary"):
                print(f"\n 주간 트렌드 요약:")
                print(f"   {report['summary']}")

        insights = summary.get("top_insights", [])
        if insights:
            print(f"\n TOP 인사이트:")
            for i, insight in enumerate(insights[:3], 1):
                print(f"\n   [{i}] {insight['source']} - 우선순위 {insight['priority']}/5")
                print(f"   전략: {insight['strategy_type']}")
                print(f"   핵심: {insight['key_insight'][:80]}...")
                print(f"   적용: {insight['applicable_to']}")

        updates = summary.get("pending_updates", [])
        if updates:
            print(f"\n⚙️  파라미터 업데이트 제안 ({len(updates)}개):")
            for u in updates[:3]:
                print(f"   {u['param']}: {u['old']} → {u['new']}")
                print(f"   이유: {u['reason'][:60]}...")


# ─────────────────────────────────────────
# 8. Flask API 엔드포인트용 함수
# ─────────────────────────────────────────
def get_learning_status() -> dict:
    """대시보드에 표시할 학습 현황"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 전체 통계
        c.execute("SELECT COUNT(*) FROM articles")
        total_articles = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM analysis_results")
        total_insights = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM strategy_updates WHERE applied=0")
        pending_updates = c.fetchone()[0]

        # 최근 7일 소스별 수집량
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        c.execute("""
            SELECT source, COUNT(*) as cnt
            FROM articles WHERE collected_at > ?
            GROUP BY source ORDER BY cnt DESC
        """, (week_ago,))
        source_stats = {r[0]: r[1] for r in c.fetchall()}

        conn.close()

        report = get_learning_report()
        insights = get_latest_insights(5)

        return {
            "total_articles": total_articles,
            "total_insights": total_insights,
            "pending_updates": pending_updates,
            "source_stats": source_stats,
            "latest_report": report,
            "top_insights": insights,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────
# 9. 스케줄러 (매일 새벽 6시 자동 실행)
# ─────────────────────────────────────────
def start_scheduler():
    """백그라운드 스케줄러 시작"""
    import schedule
    import threading

    learner = QuantLearner()

    def daily_job():
        logger.info("⏰ 스케줄 학습 시작")
        learner.run_daily_learning()

    # 매일 새벽 6시 실행 설정
    schedule.every().day.at("06:00").do(daily_job)
    # 시작 시 즉시 1회 실행
    daily_job()

    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    logger.info("✅ 자동 학습 스케줄러 시작 (매일 06:00)")


# ─────────────────────────────────────────
# 직접 실행 시 즉시 학습
# ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    learner = QuantLearner()
    result = learner.run_daily_learning()

    # 미적용 파라미터 업데이트 확인
    updates = get_pending_updates()
    if updates:
        print(f"\n⚠️  {len(updates)}개 파라미터 업데이트 대기 중")
        print("적용하려면 app.py의 /api/learning/apply 엔드포인트 사용")
