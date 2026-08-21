"""
개인 금융 컨설팅 모듈 테스트
  python -m unittest discover tests -v
  python tests/test_finance.py
표준 unittest만 사용한다 (pytest 불필요).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.finance.advisor import Advisor
from backend.finance.analyzer import Analyzer, month_bounds
from backend.finance.budget import BudgetPlanner
from backend.finance.categorizer import Categorizer
from backend.finance.db import FinanceDB
from backend.finance.ingest.base import mask_account, parse_amount, parse_date
from backend.finance.ingest.csv_importer import parse_file
from backend.finance.ingest.notifications import parse_notification
from backend.finance.models import Profile, Transaction
from backend.finance.report import build_consultation, render_html, render_text


BANK_CSV = """조회기간 : 2026-07-01 ~ 2026-07-31
계좌번호 : 1002-345-678901

거래일시,적요,찾으신금액,맡기신금액,거래후잔액,거래점
2026-07-25 09:12:03,(주)카카오 급여,,3200000,5120000,인터넷
2026-07-26 11:40:00,삼성카드 카드대금,870000,,4250000,자동이체
2026-07-27 19:03:11,GS25 역삼점,4800,,4245200,체크카드
"""

CARD_TSV = """신한카드 이용내역
이용일자\t이용가맹점\t이용금액\t할부\t승인구분
2026.07.03\t스타벅스 강남2호점\t5,500\t일시불\t승인
2026.07.05\t배달의민족\t23,000\t일시불\t승인
2026.07.06\t쿠팡\t61,200\t3개월\t승인
2026.07.08\t배달의민족\t23,000\t일시불\t승인취소
"""


class TestParsers(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("1,234원"), 1234)
        self.assertEqual(parse_amount("-12,000"), -12000)
        self.assertEqual(parse_amount("(5,000)"), -5000)   # 회계식 음수
        self.assertEqual(parse_amount(3500.4), 3500)
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount(None))

    def test_parse_date(self):
        for raw in ("2026-08-01", "2026.08.01", "2026/08/01", "20260801",
                    "2026-08-01 13:22:01", "2026년 8월 1일", "2026-08-01(토)"):
            self.assertEqual(parse_date(raw), "2026-08-01", raw)
        self.assertIsNone(parse_date("설명없음"))

    def test_mask_account(self):
        self.assertEqual(mask_account("1002-345-678901"), "10***8901")
        self.assertNotIn("345", mask_account("1002-345-678901"))

    def test_month_bounds(self):
        self.assertEqual(month_bounds("2026-02"), ("2026-02-01", "2026-02-28"))
        self.assertEqual(month_bounds("2024-02"), ("2024-02-01", "2024-02-29"))  # 윤년
        self.assertEqual(month_bounds("2026-12"), ("2026-12-01", "2026-12-31"))


class TestCsvImporter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.bank = os.path.join(self.dir.name, "신한은행_거래내역_202607.csv")
        self.card = os.path.join(self.dir.name, "신한카드_202607.csv")
        # 국내 은행은 cp949로 내려주는 곳이 많다
        with open(self.bank, "w", encoding="cp949") as f:
            f.write(BANK_CSV)
        with open(self.card, "w", encoding="utf-8-sig") as f:
            f.write(CARD_TSV)

    def tearDown(self):
        self.dir.cleanup()

    def test_bank_file(self):
        """머리글 스킵 + cp949 + 출금/입금 분리 컬럼"""
        txns = parse_file(self.bank)
        self.assertEqual(len(txns), 3)
        self.assertEqual(txns[0].amount, 3_200_000)      # 입금 → +
        self.assertEqual(txns[1].amount, -870_000)       # 출금 → -
        self.assertEqual(txns[0].institution, "신한은행")
        self.assertEqual(txns[2].balance, 4_245_200)

    def test_card_file(self):
        """탭 구분 + 단일 금액 컬럼 + 할부/취소 처리"""
        txns = parse_file(self.card)
        self.assertEqual(len(txns), 4)
        self.assertEqual(txns[0].amount, -5_500)         # 카드 승인 → 지출
        self.assertEqual(txns[2].installment, 3)
        self.assertEqual(txns[3].amount, 23_000)         # 승인취소 → 환입

    def test_dedup_on_reimport(self):
        db = FinanceDB(os.path.join(self.dir.name, "t.db"))
        first = db.add_transactions(parse_file(self.bank))
        second = db.add_transactions(parse_file(self.bank))
        self.assertEqual(first, (3, 0))
        self.assertEqual(second, (0, 3))                 # 같은 파일 재임포트 → 전부 중복


class TestNotifications(unittest.TestCase):
    def test_card_approval(self):
        t = parse_notification("[Web발신] 신한카드 승인 홍길동 5,500원 일시불 08/21 13:22 스타벅스강남점 누적1,234,567원")
        self.assertEqual(t.amount, -5_500)               # 누적금액에 속지 않는다
        self.assertIn("스타벅스", t.description)
        self.assertEqual(t.txn_date[5:], "08-21")

    def test_cancel_is_positive(self):
        t = parse_notification("삼성카드 결제 취소 23,000원 08/20 요기요")
        self.assertEqual(t.amount, 23_000)

    def test_bank_deposit(self):
        t = parse_notification("[카카오뱅크] 08/25 급여 입금 3,200,000원 (주)카카오")
        self.assertEqual(t.amount, 3_200_000)

    def test_installment(self):
        t = parse_notification("현대카드 승인 61,200원 3개월 08/06 쿠팡")
        self.assertEqual(t.installment, 3)

    def test_unparseable(self):
        self.assertIsNone(parse_notification("광고입니다 지금 신청하세요"))


class TestCategorizer(unittest.TestCase):
    def setUp(self):
        self.cz = Categorizer()

    def _cat(self, desc, amount=-10000):
        return self.cz.classify(Transaction("2026-08-01", amount, desc))

    def test_known_merchants(self):
        cases = {
            "스타벅스코리아": "카페/간식",
            "배달의민족": "외식/배달",
            "NETFLIX.COM": "구독서비스",
            "GS25 역삼점": "생필품",
            "카카오T": "교통",
            "한국전력공사 전기요금": "주거/관리비",
            "미래에셋증권 이체": "투자",
            "삼성카드 카드대금": "이체",
        }
        for desc, expected in cases.items():
            self.assertEqual(self._cat(desc), expected, desc)

    def test_income_only_on_deposit(self):
        """'급여' 키워드가 있어도 출금이면 수입으로 분류하지 않는다"""
        self.assertEqual(self._cat("(주)카카오 급여", 3_200_000), "급여")
        self.assertNotEqual(self._cat("급여이체 출금", -3_200_000), "급여")

    def test_user_rule_wins(self):
        cz = Categorizer([("스타벅스", "업무경비")])
        self.assertEqual(cz.classify(Transaction("2026-08-01", -5500, "스타벅스 강남")), "업무경비")

    def test_learning_applies_retroactively(self):
        with tempfile.TemporaryDirectory() as d:
            db = FinanceDB(os.path.join(d, "t.db"))
            db.add_transactions([
                Transaction("2026-08-01", -9000, "동네정육점", institution="신한카드"),
                Transaction("2026-08-05", -12000, "동네정육점", institution="신한카드"),
            ])
            target = db.query(limit=10)[-1]
            db.set_category(target.id, "식비")
            # 같은 가맹점의 다른 거래도 소급 적용된다
            self.assertTrue(all(t.category == "식비" for t in db.query(limit=10)))


def _seed(db: FinanceDB, months=("2026-05", "2026-06", "2026-07")) -> None:
    txns = []
    for m in months:
        txns += [
            Transaction(f"{m}-25", 3_000_000, "(주)회사 급여", "은행"),
            Transaction(f"{m}-01", -600_000, "행복아파트 관리비", "은행"),
            Transaction(f"{m}-12", -17_000, "NETFLIX.COM", "카드"),
            Transaction(f"{m}-03", -200_000, "배달의민족", "카드"),
            Transaction(f"{m}-07", -150_000, "쿠팡", "카드"),
            Transaction(f"{m}-26", -300_000, "주택청약종합저축", "은행"),
        ]
    Categorizer().classify_all(txns)
    db.add_transactions(txns)


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = FinanceDB(os.path.join(self.dir.name, "t.db"))
        _seed(self.db)
        self.az = Analyzer(self.db.query(include_transfer=True, limit=1000))

    def tearDown(self):
        self.dir.cleanup()

    def test_monthly_totals(self):
        m = self.az.monthly()["2026-06"]
        self.assertEqual(m["income"], 3_000_000)
        self.assertEqual(m["expense"], 967_000)          # 저축 300,000은 지출에서 제외
        self.assertEqual(m["save"], 300_000)

    def test_savings_not_double_counted(self):
        """저축은 지출 집계(by_category)에 들어가면 안 된다"""
        cats = {r["category"] for r in self.az.by_category()}
        self.assertNotIn("저축", cats)
        self.assertIn("저축", {r["category"] for r in self.az.by_category(include_save=True)})

    def test_recurring_detection(self):
        merchants = {r["merchant"] for r in self.az.recurring()}
        self.assertTrue(any("관리비" in m for m in merchants))
        self.assertTrue(any("NETFLIX" in m.upper() for m in merchants))

    def test_subscriptions(self):
        self.assertTrue(any("NETFLIX" in s["merchant"].upper() for s in self.az.subscriptions()))

    def test_anomaly_detection(self):
        self.db.add_transactions(Categorizer().classify_all(
            [Transaction("2026-08-10", -900_000, "배달의민족", "카드")]
        ))
        az = Analyzer(self.db.query(include_transfer=True, limit=1000))
        flagged = {a["category"] for a in az.anomalies("2026-08")}
        self.assertIn("외식/배달", flagged)

    def test_estimated_income(self):
        self.assertEqual(self.az.estimated_income(), 3_000_000)


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = FinanceDB(os.path.join(self.dir.name, "t.db"))
        _seed(self.db)
        self.az = Analyzer(self.db.query(include_transfer=True, limit=1000))
        self.profile = Profile(birth_year=1992, monthly_income=3_000_000)

    def tearDown(self):
        self.dir.cleanup()

    def test_plan_meets_target(self):
        plan = BudgetPlanner(self.az, self.profile).build(target_savings_rate=40)
        self.assertGreaterEqual(plan["planned_savings_rate"], 40.0)
        self.assertLessEqual(plan["planned_spend"], plan["income"] * 0.6)

    def test_discretionary_cut_first(self):
        """필수(관리비)보다 재량(배달/쇼핑)을 먼저 깎는다"""
        # 이 시드는 저축률 67%까지는 삭감 없이 달성된다 → 삭감이 필요한 수준으로 올린다
        plan = BudgetPlanner(self.az, self.profile).build(target_savings_rate=75)
        cuts = {r["category"]: r["cut"] for r in plan["categories"]}
        self.assertGreater(cuts.get("외식/배달", 0), 0)
        self.assertGreaterEqual(cuts.get("외식/배달", 0), cuts.get("주거/관리비", 0))

    def test_need_cut_capped_at_10pct(self):
        plan = BudgetPlanner(self.az, self.profile).build(target_savings_rate=80)
        for r in plan["categories"]:
            if r["kind"] == "need" and r["current"]:
                self.assertLessEqual(r["cut"], r["current"] * 0.10 + 1, r["category"])

    def test_no_income_returns_error(self):
        empty = Analyzer([])
        plan = BudgetPlanner(empty, Profile(monthly_income=0)).build()
        self.assertIn("error", plan)

    def test_tracking(self):
        planner = BudgetPlanner(self.az, self.profile)
        plan = planner.build(30)
        tr = planner.track("2026-07", plan["budget"])
        self.assertEqual(tr["month"], "2026-07")
        self.assertGreater(tr["total_spent"], 0)


class TestAdvisor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = FinanceDB(os.path.join(self.dir.name, "t.db"))
        _seed(self.db)
        self.az = Analyzer(self.db.query(include_transfer=True, limit=1000))

    def tearDown(self):
        self.dir.cleanup()

    def _advisor(self, **kw) -> Advisor:
        p = Profile(birth_year=1992, monthly_income=3_000_000, **kw)
        plan = BudgetPlanner(self.az, p).build(30)
        return Advisor(self.az, p, plan)

    def test_emergency_fund_comes_first(self):
        adv = self._advisor(emergency_fund=0)
        steps = adv.waterfall()
        self.assertEqual(steps[0]["priority"], 1)
        self.assertGreater(steps[0]["monthly"], 0)

    def test_high_rate_debt_before_investing(self):
        adv = self._advisor(emergency_fund=50_000_000,
                            debts=[{"name": "카드론", "balance": 5_000_000, "rate": 15.0}])
        priorities = [s["priority"] for s in adv.waterfall() if s["monthly"] > 0]
        self.assertIn(2, priorities)
        self.assertEqual(priorities, sorted(priorities))   # 우선순위 순서대로 배분

    def test_low_rate_debt_is_not_prioritized(self):
        adv = self._advisor(emergency_fund=50_000_000,
                            debts=[{"name": "주택담보", "balance": 100_000_000, "rate": 3.2}])
        self.assertNotIn(2, [s["priority"] for s in adv.waterfall() if s["monthly"] > 0])

    def test_allocation_sums_to_100(self):
        for risk in ("안정형", "중립형", "공격투자형"):
            adv = self._advisor(emergency_fund=50_000_000, risk_level=risk)
            self.assertEqual(sum(adv.allocation()["model"].values()), 100, risk)

    def test_allocation_gets_conservative_with_age(self):
        young = Advisor(self.az, Profile(birth_year=2000, monthly_income=3_000_000,
                                         emergency_fund=50_000_000), {}).allocation()["model"]
        old = Advisor(self.az, Profile(birth_year=1965, monthly_income=3_000_000,
                                       emergency_fund=50_000_000), {}).allocation()["model"]
        self.assertGreater(young["선진국주식"], old["선진국주식"])
        self.assertLess(young["채권"], old["채권"])

    def test_action_plan_has_concrete_tickers(self):
        adv = self._advisor(emergency_fund=50_000_000)
        orders = adv.action_plan()["orders"]
        self.assertTrue(orders)
        for o in orders:
            self.assertTrue(o["ticker"])
            self.assertGreater(o["monthly"], 0)
            self.assertIn(o["account"], ("연금저축/IRP", "ISA", "일반계좌"))
        self.assertIn("투자자문", adv.action_plan()["disclaimer"])

    def test_allocation_does_not_exceed_capacity(self):
        adv = self._advisor(emergency_fund=0)
        cap = adv.capacity()["planned_monthly_save"]
        self.assertLessEqual(sum(s["monthly"] for s in adv.waterfall()), cap + 1)

    def test_goal_projection(self):
        adv = self._advisor(emergency_fund=50_000_000,
                            goals=[{"name": "전세금", "target": 50_000_000, "deadline": "2040-01"}])
        g = adv.goal_projection()[0]
        self.assertGreater(g["months_needed"], 0)
        self.assertTrue(g["feasible"])


class TestReport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = FinanceDB(os.path.join(self.dir.name, "t.db"))
        _seed(self.db)
        self.db.save_profile(Profile(name="테스터", birth_year=1992, monthly_income=3_000_000))

    def tearDown(self):
        self.dir.cleanup()

    def test_text_report(self):
        text = render_text(build_consultation(self.db))
        for section in ("현금흐름 진단", "지출 구조", "저축·투자 우선순위", "자산배분", "매월 실행안"):
            self.assertIn(section, text)

    def test_html_report(self):
        html = render_html(build_consultation(self.db))
        self.assertIn("<title>", html)
        self.assertIn("prefers-color-scheme", html)      # 다크모드 대응
        self.assertNotIn("<script", html.lower())        # 정적 리포트

    def test_empty_db_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            empty = FinanceDB(os.path.join(d, "empty.db"))
            self.assertIn("거래내역이 없습니다", render_text(build_consultation(empty)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
