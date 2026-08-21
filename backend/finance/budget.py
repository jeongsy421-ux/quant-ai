"""
==============================================
PERSONAL FINANCE - 소비 계획 / 예산 수립
==============================================
과거 실제 지출에서 출발해 목표 저축률을 달성하는 다음 달 예산을 만든다.
'50/30/20 같은 교과서 비율'을 그대로 강요하지 않고,
실제 소비 패턴 위에서 재량 지출부터 깎는 방식이라 지킬 수 있는 예산이 나온다.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Optional

from .analyzer import Analyzer, month_bounds
from .models import INCOME, NEED, SAVE, WANT, Profile, kind_of

# 소득 대비 권장 상한 (참고선, 절대 기준 아님)
BENCHMARK_RATIO: dict[str, float] = {
    "주거/관리비": 0.25, "식비": 0.12, "외식/배달": 0.06, "카페/간식": 0.02,
    "교통": 0.06, "통신": 0.04, "생필품": 0.05, "쇼핑": 0.06,
    "문화/여가": 0.04, "여행": 0.04, "구독서비스": 0.015, "미용": 0.02,
    "술/유흥": 0.03, "의료/건강": 0.03, "보험": 0.08, "교육": 0.05,
    "육아": 0.08, "경조사": 0.02, "세금/공과금": 0.03, "대출상환": 0.20,
    "기타지출": 0.03,
}

# 재량 지출 축소 난이도 (낮을수록 먼저 깎는다)
CUT_PRIORITY: dict[str, int] = {
    "술/유흥": 1, "구독서비스": 1, "카페/간식": 2, "외식/배달": 2,
    "쇼핑": 3, "문화/여가": 3, "미용": 4, "여행": 4, "기타지출": 4,
    "경조사": 8, "생필품": 6, "식비": 6, "교통": 7, "의료/건강": 9,
    "통신": 5, "주거/관리비": 9, "보험": 5, "교육": 8, "육아": 9,
    "세금/공과금": 10, "대출상환": 10,
}

DEFAULT_TARGET_RATE = {          # 연령대별 권장 저축률 (%)
    20: 30, 30: 30, 40: 25, 50: 25, 60: 15,
}


def recommended_savings_rate(profile: Profile) -> int:
    decade = min(60, max(20, (profile.age // 10) * 10))
    base = DEFAULT_TARGET_RATE.get(decade, 25)
    if profile.dependents >= 2:
        base -= 5
    return max(10, base)


class BudgetPlanner:
    """다음 달 예산 설계 + 진행 추적"""

    def __init__(self, analyzer: Analyzer, profile: Profile):
        self.az = analyzer
        self.profile = profile
        self.monthly = analyzer.monthly()

    # ── 기준선: 최근 3개월 카테고리별 중앙값 ──
    def baseline(self, months_back: int = 3) -> dict[str, int]:
        months = sorted(self.monthly)[-months_back:]
        per_cat: dict[str, list[int]] = {}
        for m in months:
            for row in self.az.by_category(month=m):
                if kind_of(row["category"]) in (INCOME, SAVE):
                    continue
                per_cat.setdefault(row["category"], []).append(row["amount"])
        return {
            c: int(statistics.median(v + [0] * (len(months) - len(v))))
            for c, v in per_cat.items()
        }

    def income(self) -> int:
        return self.profile.monthly_income or self.az.estimated_income()

    # ── 예산 생성 ──
    def build(self, target_savings_rate: Optional[int] = None) -> dict[str, Any]:
        income = self.income()
        base = self.baseline()
        fixed = {r["merchant"]: r for r in self.az.recurring()}
        target_rate = target_savings_rate or recommended_savings_rate(self.profile)

        if income <= 0:
            return {"error": "소득을 알 수 없습니다. 프로필의 monthly_income을 설정하거나 급여 내역을 임포트하세요."}

        target_save = int(income * target_rate / 100)
        current_spend = sum(base.values())
        available = income - target_save
        gap = current_spend - available        # 0보다 크면 그만큼 줄여야 함

        plan: dict[str, dict[str, Any]] = {}
        for cat, amount in sorted(base.items(), key=lambda x: -x[1]):
            bench = int(income * BENCHMARK_RATIO.get(cat, 0.03))
            plan[cat] = {
                "current": amount,
                "benchmark": bench,
                "budget": amount,
                "cut": 0,
                "kind": kind_of(cat),
                "over_benchmark": amount - bench,
            }

        if gap > 0:
            self._apply_cuts(plan, gap)

        budget = {c: v["budget"] for c, v in plan.items()}
        total_budget = sum(budget.values())

        return {
            "income": income,
            "target_savings_rate": target_rate,
            "target_save": target_save,
            "current_spend": current_spend,
            "planned_spend": total_budget,
            "planned_save": income - total_budget,
            "planned_savings_rate": round((income - total_budget) / income * 100, 1),
            "required_cut": max(gap, 0),
            "achieved_cut": current_spend - total_budget,
            "categories": [
                {"category": c, **v} for c, v in
                sorted(plan.items(), key=lambda x: -x[1]["current"])
            ],
            "fixed_costs": list(fixed.values()),
            "budget": budget,
        }

    def _apply_cuts(self, plan: dict[str, dict[str, Any]], gap: int) -> None:
        """
        삭감 라운드:
          1라운드 — 벤치마크 초과분을 우선순위 순으로 깎는다 (재량 지출부터)
          2라운드 — 그래도 부족하면 재량 지출 전체를 비례 축소 (최대 40%까지)
        필수 지출(need)은 최대 10%까지만 건드린다.
        """
        remaining = gap
        order = sorted(plan, key=lambda c: (CUT_PRIORITY.get(c, 5), -plan[c]["over_benchmark"]))

        for cat in order:
            if remaining <= 0:
                break
            p = plan[cat]
            excess = max(0, p["over_benchmark"])
            if excess <= 0:
                continue
            limit = p["current"] * (0.10 if p["kind"] == NEED else 0.50)
            cut = int(min(excess, remaining, limit))
            if cut > 0:
                p["budget"] -= cut
                p["cut"] += cut
                remaining -= cut

        if remaining <= 0:
            return

        discretionary = [c for c in order if plan[c]["kind"] == WANT and plan[c]["budget"] > 0]
        pool = sum(plan[c]["budget"] for c in discretionary)
        if pool <= 0:
            return
        for cat in discretionary:
            if remaining <= 0:
                break
            p = plan[cat]
            share = p["budget"] / pool
            max_more = int(p["current"] * 0.40) - p["cut"]
            cut = int(min(max(0, max_more), remaining * share + 1, p["budget"]))
            if cut > 0:
                p["budget"] -= cut
                p["cut"] += cut
                remaining -= cut

    # ── 진행 추적 ──
    def track(self, month: str, budget: Optional[dict[str, int]] = None) -> dict[str, Any]:
        """이번 달 예산 대비 소진 현황 + 이 페이스로 갈 때의 월말 예상"""
        if not budget:
            # 소득 정보가 없어 예산을 세울 수 없는 경우에도 실적 집계는 보여준다
            budget = self.build().get("budget", {})
        start, end = month_bounds(month)
        today = date.today().isoformat()
        days_total = int(end[8:10])
        days_passed = max(1, min(days_total, int(today[8:10]) if today[:7] == month else days_total))
        pace = days_total / days_passed

        actual = {r["category"]: r["amount"] for r in self.az.by_category(month=month)}
        rows = []
        for cat in sorted(set(budget) | set(actual), key=lambda c: -budget.get(c, 0)):
            b, a = budget.get(cat, 0), actual.get(cat, 0)
            projected = int(a * pace)
            rows.append({
                "category": cat,
                "budget": b,
                "spent": a,
                "remaining": b - a,
                "used_pct": round(a / b * 100, 1) if b else None,
                "projected": projected,
                "status": _status(b, a, projected),
            })
        total_b, total_a = sum(budget.values()), sum(actual.values())
        return {
            "month": month,
            "days_passed": days_passed,
            "days_total": days_total,
            "total_budget": total_b,
            "total_spent": total_a,
            "total_projected": int(total_a * pace),
            "on_track": total_a * pace <= total_b,
            "rows": rows,
        }


def _status(budget: int, spent: int, projected: int) -> str:
    if budget == 0:
        return "예산없음"
    if spent > budget:
        return "초과"
    if projected > budget:
        return "초과예상"
    if projected > budget * 0.9:
        return "주의"
    return "양호"
