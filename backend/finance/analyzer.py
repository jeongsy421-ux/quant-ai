"""
==============================================
PERSONAL FINANCE - 가계부 분석 엔진
==============================================
표준 라이브러리만 사용 (pandas 불필요).
- 월별 수입/지출/저축률
- 카테고리별 지출 구조 (필수/재량/저축)
- 고정비·구독 자동 탐지 (매월 반복되는 결제)
- 이상 지출 탐지 (평소 대비 급증한 카테고리)
- 가맹점 랭킹, 소액 반복지출(새는 돈) 탐지
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from .models import (
    INCOME, NEED, SAVE, WANT, Transaction, kind_of, normalize_desc,
)


def month_range(months_back: int = 6, end: Optional[str] = None) -> list[str]:
    """최근 N개월 'YYYY-MM' 리스트 (오래된 것부터)"""
    if end:
        y, m = int(end[:4]), int(end[5:7])
    else:
        today = date.today()
        y, m = today.year, today.month
    out = []
    for _ in range(months_back):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def month_bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


class Analyzer:
    """거래 목록 위에서 동작하는 분석기"""

    def __init__(self, txns: Iterable[Transaction]):
        # 내부 계좌 간 이동(이체)은 수입/지출 어느 쪽도 아니므로 제외
        self.txns = [t for t in txns if t.category != "이체"]
        self.all_txns = list(txns)

    # ─────────────────────────────────────
    # 월별 요약
    # ─────────────────────────────────────
    def monthly(self) -> dict[str, dict[str, Any]]:
        """월 → {income, expense, save, need, want, net, savings_rate}"""
        buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"income": 0, "expense": 0, "save": 0, "need": 0, "want": 0}
        )
        for t in self.txns:
            b = buckets[t.month]
            k = kind_of(t.category)
            if k == INCOME:
                b["income"] += t.amount
            elif k == SAVE:
                b["save"] += t.abs_amount
            else:
                b["expense"] += t.abs_amount
                b[NEED if k == NEED else WANT] += t.abs_amount

        out: dict[str, dict[str, Any]] = {}
        for m in sorted(buckets):
            b = buckets[m]
            income = b["income"]
            net = income - b["expense"] - b["save"]
            out[m] = {
                **b,
                "net": net,
                "savings_rate": round((b["save"] + max(net, 0)) / income * 100, 1) if income else 0.0,
                "burn_rate": round(b["expense"] / income * 100, 1) if income else 0.0,
            }
        return out

    def summary(self, months: Optional[list[str]] = None) -> dict[str, Any]:
        """기간 전체 요약 + 월평균"""
        m = self.monthly()
        target = [k for k in m if not months or k in months]
        if not target:
            return {"months": 0}
        n = len(target)
        agg = {
            key: sum(m[k][key] for k in target)
            for key in ("income", "expense", "save", "need", "want")
        }
        avg = {f"avg_{k}": round(v / n) for k, v in agg.items()}
        income = agg["income"]
        return {
            "months": n,
            "period": f"{target[0]} ~ {target[-1]}",
            **agg,
            **avg,
            "net": income - agg["expense"] - agg["save"],
            "savings_rate": round(
                (agg["save"] + max(income - agg["expense"] - agg["save"], 0)) / income * 100, 1
            ) if income else 0.0,
            "need_ratio": round(agg["need"] / income * 100, 1) if income else 0.0,
            "want_ratio": round(agg["want"] / income * 100, 1) if income else 0.0,
        }

    # ─────────────────────────────────────
    # 카테고리 분석
    # ─────────────────────────────────────
    def by_category(
        self, month: Optional[str] = None, top: int = 0, include_save: bool = False
    ) -> list[dict[str, Any]]:
        """
        카테고리별 '지출' 집계. 수입은 항상 제외한다.
        저축/투자는 지출이 아니므로 기본 제외 — 포함하면 예산 대비 실적이
        이중 계상되어 항상 초과로 보인다. (구조 파악용으로만 include_save=True)
        """
        skip = {INCOME} if include_save else {INCOME, SAVE}
        agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"amount": 0, "count": 0})
        total = 0
        for t in self.txns:
            if month and t.month != month:
                continue
            if kind_of(t.category) in skip:
                continue
            agg[t.category]["amount"] += t.abs_amount
            agg[t.category]["count"] += 1
            total += t.abs_amount

        rows = [
            {
                "category": c,
                "kind": kind_of(c),
                "amount": v["amount"],
                "count": v["count"],
                "share": round(v["amount"] / total * 100, 1) if total else 0.0,
            }
            for c, v in agg.items()
        ]
        rows.sort(key=lambda r: -r["amount"])
        return rows[:top] if top else rows

    def category_trend(self, category: str) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for t in self.txns:
            if t.category == category and kind_of(category) != INCOME:
                out[t.month] += t.abs_amount
        return dict(sorted(out.items()))

    # ─────────────────────────────────────
    # 고정비 / 구독 탐지
    # ─────────────────────────────────────
    def recurring(self, min_months: int = 3, tolerance: float = 0.25) -> list[dict[str, Any]]:
        """
        매월 반복되는 결제를 찾아낸다.
        같은 가맹점에서 min_months 이상, 금액 변동이 tolerance 이내면 고정비로 본다.
        """
        groups: dict[str, list[Transaction]] = defaultdict(list)
        for t in self.txns:
            if not t.is_expense or kind_of(t.category) == SAVE:
                continue
            key = normalize_desc(t.description)[:20]
            if key:
                groups[key].append(t)

        out: list[dict[str, Any]] = []
        for key, items in groups.items():
            months = sorted({t.month for t in items})
            if len(months) < min_months:
                continue
            amounts = [t.abs_amount for t in items]
            med = statistics.median(amounts)
            if med <= 0:
                continue
            spread = (max(amounts) - min(amounts)) / med
            if spread > tolerance:
                continue
            # 연속성 확인 — 최근 달에도 결제되고 있는가
            out.append({
                "merchant": key,
                "category": statistics.mode([t.category for t in items]),
                "monthly": int(med),
                "months": len(months),
                "last_month": months[-1],
                "annual": int(med) * 12,
                "count": len(items),
            })
        out.sort(key=lambda r: -r["monthly"])
        return out

    def subscriptions(self) -> list[dict[str, Any]]:
        """구독서비스로 분류된 반복 결제만 추림 — 해지 검토 1순위"""
        return [
            r for r in self.recurring(min_months=2, tolerance=0.15)
            if r["category"] in ("구독서비스", "문화/여가")
        ]

    # ─────────────────────────────────────
    # 이상 지출 / 새는 돈
    # ─────────────────────────────────────
    def anomalies(self, month: Optional[str] = None, z_threshold: float = 1.5) -> list[dict[str, Any]]:
        """직전 개월 대비 비정상적으로 늘어난 카테고리"""
        monthly_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for t in self.txns:
            if t.is_expense and kind_of(t.category) != SAVE:
                monthly_cat[t.category][t.month] += t.abs_amount

        months = sorted({t.month for t in self.txns})
        if not months:
            return []
        target = month or months[-1]
        out: list[dict[str, Any]] = []

        for cat, series in monthly_cat.items():
            history = [v for m, v in sorted(series.items()) if m < target]
            current = series.get(target, 0)
            if len(history) < 2 or current == 0:
                continue
            mean = statistics.mean(history)
            sd = statistics.pstdev(history) or (mean * 0.15) or 1
            z = (current - mean) / sd
            if z >= z_threshold and current > mean * 1.2:
                out.append({
                    "category": cat,
                    "month": target,
                    "amount": current,
                    "usual": int(mean),
                    "excess": int(current - mean),
                    "z": round(z, 1),
                })
        out.sort(key=lambda r: -r["excess"])
        return out

    def top_merchants(self, month: Optional[str] = None, top: int = 10) -> list[dict[str, Any]]:
        agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"amount": 0, "count": 0, "category": ""})
        for t in self.txns:
            if not t.is_expense or (month and t.month != month):
                continue
            if kind_of(t.category) == SAVE:
                continue
            key = normalize_desc(t.description)[:24] or t.description[:24]
            agg[key]["amount"] += t.abs_amount
            agg[key]["count"] += 1
            agg[key]["category"] = t.category
        rows = [{"merchant": k, **v} for k, v in agg.items()]
        rows.sort(key=lambda r: -r["amount"])
        return rows[:top]

    def small_leaks(self, unit_max: int = 15_000, min_count: int = 8) -> list[dict[str, Any]]:
        """건당 소액이지만 횟수가 많아 총액이 큰 지출 — 가장 줄이기 쉬운 항목"""
        agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"amount": 0, "count": 0, "category": ""})
        for t in self.txns:
            if not t.is_expense or t.abs_amount > unit_max:
                continue
            if kind_of(t.category) == SAVE:
                continue
            key = normalize_desc(t.description)[:24] or t.description[:24]
            agg[key]["amount"] += t.abs_amount
            agg[key]["count"] += 1
            agg[key]["category"] = t.category
        months = max(1, len({t.month for t in self.txns}))
        rows = [
            {"merchant": k, "monthly": round(v["amount"] / months), **v}
            for k, v in agg.items() if v["count"] >= min_count
        ]
        rows.sort(key=lambda r: -r["amount"])
        return rows[:10]

    def no_spend_days(self, month: str) -> int:
        start, end = month_bounds(month)
        days_in_month = int(end[8:10])
        spent = {t.txn_date for t in self.txns if t.month == month and t.is_expense}
        return days_in_month - len(spent)

    # ─────────────────────────────────────
    # 소득 추정
    # ─────────────────────────────────────
    def estimated_income(self, months_back: int = 3) -> int:
        """최근 N개월 수입의 중앙값 — 프로필에 소득이 없을 때 사용"""
        m = self.monthly()
        vals = [v["income"] for k, v in sorted(m.items())[-months_back:] if v["income"] > 0]
        return int(statistics.median(vals)) if vals else 0

    def fixed_cost_total(self) -> int:
        return sum(r["monthly"] for r in self.recurring())
