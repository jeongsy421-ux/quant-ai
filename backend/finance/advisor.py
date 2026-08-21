"""
==============================================
PERSONAL FINANCE - 저축/투자 컨설팅 엔진
==============================================
'남는 돈을 어디에, 얼마나, 어떤 상품으로' 를 규칙 기반으로 계산한다.

우선순위 워터폴 (위에서부터 채운다)
  1) 비상금        — 필수생계비 3~6개월치 (파킹통장/CMA)
  2) 고금리 부채    — 금리가 기대수익률(연 6%)보다 높은 빚부터 상환
  3) 연금저축/IRP  — 연 900만원 세액공제 한도 (13.2~16.5% 즉시 환급 = 확정수익)
  4) ISA          — 순이익 200만(서민형 400만) 비과세 + 초과분 9.9% 분리과세
  5) 일반 위탁계좌  — 나머지

⚠ 고지
  이 모듈은 공개된 자산배분 원칙과 세제 정보를 바탕으로 한 '정보 제공'이며,
  자본시장법상 투자자문이 아니다. 제시되는 종목/ETF는 자산군을 채우는 예시이고,
  실제 매수 전 최신 보수·괴리율·거래대금·종목코드를 반드시 직접 확인해야 한다.
  세법 한도는 매년 바뀌므로 TAX 상수를 최신 기준으로 갱신할 것.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from .analyzer import Analyzer
from .models import NEED, Profile, kind_of

# ─────────────────────────────────────────
# 세제 한도 (2026년 기준 · 매년 확인 필요)
# ─────────────────────────────────────────
TAX = {
    "pension_limit": 6_000_000,        # 연금저축 세액공제 한도(연)
    "pension_irp_total": 9_000_000,    # 연금저축+IRP 합산 한도(연)
    "isa_annual": 20_000_000,          # ISA 연 납입한도
    "isa_total": 100_000_000,          # ISA 총 납입한도
    "credit_rate_low": 0.165,          # 총급여 5,500만 이하 세액공제율
    "credit_rate_high": 0.132,
    "low_income_threshold": 55_000_000,
}

# 부채 상환이 투자보다 유리해지는 기준 금리(연 %)
DEBT_HURDLE_RATE = 6.0

# ─────────────────────────────────────────
# 자산배분 모델 (위험성향 → 자산군 비중 %)
# ─────────────────────────────────────────
ALLOCATION_MODELS: dict[str, dict[str, int]] = {
    "안정형":     {"국내주식": 5,  "선진국주식": 10, "채권": 55, "현금성": 25, "대체": 5},
    "안정추구형": {"국내주식": 10, "선진국주식": 20, "채권": 45, "현금성": 18, "대체": 7},
    "중립형":     {"국내주식": 12, "선진국주식": 33, "채권": 35, "현금성": 12, "대체": 8},
    "적극투자형": {"국내주식": 15, "선진국주식": 45, "채권": 22, "현금성": 8,  "대체": 10},
    "공격투자형": {"국내주식": 15, "선진국주식": 60, "채권": 10, "현금성": 5,  "대체": 10},
}

# ─────────────────────────────────────────
# 자산군별 상품 후보 (예시 — 매수 전 종목코드/보수 확인 필수)
# ─────────────────────────────────────────
INSTRUMENTS: dict[str, list[dict[str, Any]]] = {
    "선진국주식": [
        {"ticker": "379800", "name": "KODEX 미국S&P500TR", "market": "KRX",
         "note": "배당 자동재투자(TR)형. 연금계좌 핵심 자리"},
        {"ticker": "360750", "name": "TIGER 미국S&P500", "market": "KRX",
         "note": "분배금 지급형. 거래대금 가장 큼"},
        {"ticker": "133690", "name": "TIGER 미국나스닥100", "market": "KRX",
         "note": "기술주 비중 높음 — 변동성 큼, 위성 자리"},
        {"ticker": "458730", "name": "TIGER 미국배당다우존스", "market": "KRX",
         "note": "SCHD 추종. 월배당, 현금흐름 원할 때"},
        {"ticker": "VOO", "name": "Vanguard S&P500 ETF", "market": "NYSE",
         "note": "직투용. 연 250만원 양도차익 기본공제"},
        {"ticker": "SCHD", "name": "Schwab US Dividend Equity", "market": "NYSE",
         "note": "직투용 배당성장"},
    ],
    "국내주식": [
        {"ticker": "069500", "name": "KODEX 200", "market": "KRX", "note": "코스피200 대표"},
        {"ticker": "102110", "name": "TIGER 200", "market": "KRX", "note": "동일 지수, 보수 비교 후 선택"},
        {"ticker": "232080", "name": "TIGER 코스닥150", "market": "KRX", "note": "중소형 성장 — 비중 소량"},
    ],
    "채권": [
        {"ticker": "273130", "name": "KODEX 종합채권(AA-이상)액티브", "market": "KRX",
         "note": "국내 우량채 전반. 채권 코어"},
        {"ticker": "305080", "name": "TIGER 미국채10년선물", "market": "KRX",
         "note": "금리 하락기 방어. 환노출 확인"},
        {"ticker": "BND", "name": "Vanguard Total Bond Market", "market": "NASDAQ",
         "note": "직투용 미국 종합채권"},
    ],
    "현금성": [
        {"ticker": "357870", "name": "TIGER CD금리투자KIS", "market": "KRX",
         "note": "하루만 맡겨도 CD금리. 비상금 파킹"},
        {"ticker": "-", "name": "파킹통장 / CMA(RP형)", "market": "은행·증권",
         "note": "예금자보호 여부와 우대금리 조건 확인"},
    ],
    "대체": [
        {"ticker": "132030", "name": "KODEX 골드선물(H)", "market": "KRX",
         "note": "환헤지형 금. 인플레·위기 헤지"},
        {"ticker": "GLD", "name": "SPDR Gold Shares", "market": "NYSE", "note": "직투용 금"},
    ],
}

# 계좌별로 담기 좋은 자산군 (세제 효율 기준)
ACCOUNT_FIT = {
    "연금저축/IRP": ["선진국주식", "채권", "대체"],   # 과세이연 효과가 큰 자산
    "ISA": ["국내주식", "채권", "선진국주식"],        # 국내상장 해외ETF 배당소득세 절감
    "일반계좌": ["선진국주식", "국내주식"],           # 해외 직투는 양도세 250만 공제 활용
}


class Advisor:
    """저축·투자 컨설턴트"""

    def __init__(self, analyzer: Analyzer, profile: Profile, budget_plan: Optional[dict] = None):
        self.az = analyzer
        self.profile = profile
        self.plan = budget_plan or {}

    # ─────────────────────────────────────
    # 투자 여력
    # ─────────────────────────────────────
    def capacity(self) -> dict[str, Any]:
        income = self.profile.monthly_income or self.az.estimated_income()
        summary = self.az.summary()
        current_save = summary.get("avg_save", 0) + max(
            income - summary.get("avg_expense", 0) - summary.get("avg_save", 0), 0
        )
        planned_save = self.plan.get("planned_save", current_save)
        essential = self._essential_monthly()
        return {
            "income": income,
            "essential_monthly": essential,
            "current_monthly_save": int(current_save),
            "planned_monthly_save": int(planned_save),
            "improvement": int(planned_save - current_save),
        }

    def _essential_monthly(self) -> int:
        """비상금 산정용 필수 생계비 (필수 카테고리 월평균)"""
        s = self.az.summary()
        n = max(1, s.get("months", 1))
        need = s.get("need", 0) / n
        # 대출상환은 실직해도 계속 나가므로 포함
        return int(need)

    # ─────────────────────────────────────
    # 우선순위 워터폴
    # ─────────────────────────────────────
    def waterfall(self, monthly: Optional[int] = None) -> list[dict[str, Any]]:
        cap = self.capacity()
        remaining = monthly if monthly is not None else cap["planned_monthly_save"]
        steps: list[dict[str, Any]] = []
        p = self.profile

        # 1) 비상금
        target_months = 6 if (p.dependents or self._income_unstable()) else 3
        target = cap["essential_monthly"] * target_months
        short = max(0, target - p.emergency_fund)
        if short > 0 and remaining > 0:
            # 비상금은 12개월 안에 채우는 것을 목표로, 여력의 최대 60%까지 배정
            alloc = int(min(remaining * 0.6, max(short / 12, 100_000)))
            alloc = min(alloc, remaining, short)
            remaining -= alloc
            steps.append({
                "priority": 1, "name": "비상금 적립", "monthly": alloc,
                "target": target, "current": p.emergency_fund, "shortfall": short,
                "vehicle": "파킹통장 / CMA(RP) / TIGER CD금리투자KIS(357870)",
                "why": f"실직·질병 대비 필수생계비 {target_months}개월치({target:,}원). "
                       f"현재 {p.emergency_fund:,}원 → {short:,}원 부족. "
                       "이게 없으면 투자자산을 하필 최악의 시점에 팔게 된다.",
                "eta_months": (short // alloc + 1) if alloc else None,
            })
        else:
            steps.append({
                "priority": 1, "name": "비상금 적립", "monthly": 0,
                "target": target, "current": p.emergency_fund, "shortfall": 0,
                "vehicle": "-", "why": f"비상금 {target:,}원 목표 달성. 투자 단계로 진행.",
            })

        # 2) 고금리 부채
        high_rate = sorted(
            [d for d in p.debts if float(d.get("rate", 0)) >= DEBT_HURDLE_RATE],
            key=lambda d: -float(d.get("rate", 0)),
        )
        for d in high_rate:
            if remaining <= 0:
                break
            alloc = int(min(remaining * 0.5, d.get("balance", 0)))
            remaining -= alloc
            steps.append({
                "priority": 2, "name": f"고금리 부채 상환 — {d.get('name','대출')}",
                "monthly": alloc, "target": d.get("balance", 0), "rate": d.get("rate"),
                "vehicle": "원금 추가상환 (중도상환수수료 확인)",
                "why": f"연 {d.get('rate')}% 이자는 세후 확정 {d.get('rate')}% 수익과 같다. "
                       f"기대수익 연 {DEBT_HURDLE_RATE}% 투자보다 우선.",
            })

        # 3) 연금저축 + IRP (세액공제)
        credit_rate = (
            TAX["credit_rate_low"]
            if p.monthly_income * 12 <= TAX["low_income_threshold"]
            else TAX["credit_rate_high"]
        )
        pension_room = max(0, TAX["pension_limit"] - p.pension_contrib_ytd)
        irp_room = max(
            0,
            TAX["pension_irp_total"] - p.pension_contrib_ytd - p.irp_contrib_ytd - min(pension_room, 0),
        )
        total_room = max(0, TAX["pension_irp_total"] - p.pension_contrib_ytd - p.irp_contrib_ytd)
        if total_room > 0 and remaining > 0:
            alloc = int(min(remaining, total_room / 12))
            remaining -= alloc
            steps.append({
                "priority": 3, "name": "연금저축 + IRP 세액공제 채우기", "monthly": alloc,
                "target": TAX["pension_irp_total"], "room": total_room,
                "vehicle": "연금저축펀드(증권사) → 한도 소진 후 IRP",
                "why": f"연 {TAX['pension_irp_total']:,}원까지 납입액의 {credit_rate*100:.1f}% "
                       f"(최대 {int(TAX['pension_irp_total']*credit_rate):,}원)를 연말정산에서 돌려받는다. "
                       "시장 수익률과 무관한 확정 수익이라 사실상 1순위 투자.",
                "caution": "만 55세 이전 중도해지 시 기타소득세 16.5%. 여유자금만 넣을 것.",
            })

        # 4) ISA
        isa_room = max(0, TAX["isa_annual"] - p.isa_contrib_ytd)
        if isa_room > 0 and remaining > 0:
            alloc = int(min(remaining, isa_room / 12))
            remaining -= alloc
            steps.append({
                "priority": 4, "name": "ISA 계좌 적립", "monthly": alloc,
                "target": TAX["isa_annual"], "room": isa_room,
                "vehicle": "중개형 ISA (국내상장 ETF 매매 가능)",
                "why": "순이익 200만원(서민형 400만원)까지 비과세, 초과분은 9.9% 분리과세. "
                       "3년 만기 후 연금계좌로 옮기면 전환금액의 10%(최대 300만원) 추가 세액공제.",
            })

        # 5) 일반계좌
        if remaining > 0:
            steps.append({
                "priority": 5, "name": "일반 위탁계좌 투자", "monthly": int(remaining),
                "vehicle": "국내 증권사 일반계좌 (해외 직투 시 양도차익 250만원 기본공제)",
                "why": "세제혜택 계좌를 모두 채운 뒤의 잔여 여력. 유동성이 필요한 자금은 여기에.",
            })

        return steps

    def _income_unstable(self) -> bool:
        """수입 변동성이 크면 비상금을 6개월치로"""
        m = self.az.monthly()
        incomes = [v["income"] for v in m.values() if v["income"] > 0]
        if len(incomes) < 3:
            return False
        avg = sum(incomes) / len(incomes)
        return any(abs(i - avg) / avg > 0.3 for i in incomes)

    # ─────────────────────────────────────
    # 자산배분
    # ─────────────────────────────────────
    def allocation(self) -> dict[str, Any]:
        p = self.profile
        model = dict(ALLOCATION_MODELS.get(p.risk_level, ALLOCATION_MODELS["중립형"]))

        # 나이 조정: 50세 이후 10년마다 위험자산 5%p를 채권/현금으로 이동
        if p.age >= 50:
            shift = min(15, 5 * ((p.age - 40) // 10))
            take = min(shift, model["선진국주식"] - 5)
            model["선진국주식"] -= take
            model["채권"] += take

        # 비상금이 부족하면 현금성 비중을 임시로 높인다
        cap = self.capacity()
        if p.emergency_fund < cap["essential_monthly"] * 3:
            move = min(10, model["선진국주식"] - 5)
            model["선진국주식"] -= move
            model["현금성"] += move

        current = self._current_allocation()
        rows = []
        for asset, pct in model.items():
            cur_pct = current.get(asset, 0.0)
            rows.append({
                "asset": asset,
                "target_pct": pct,
                "current_pct": round(cur_pct, 1),
                "gap_pct": round(pct - cur_pct, 1),
                "action": "매수" if pct - cur_pct > 5 else ("매도/비중축소" if pct - cur_pct < -5 else "유지"),
                "instruments": INSTRUMENTS.get(asset, []),
            })
        rows.sort(key=lambda r: -r["target_pct"])
        return {
            "risk_level": p.risk_level,
            "age": p.age,
            "model": model,
            "rows": rows,
            "rebalance_band": "각 자산군 목표 ±5%p 이탈 시, 또는 연 1~2회 정기 리밸런싱",
            "total_holdings": sum(h.get("value", 0) for h in p.holdings),
        }

    def _current_allocation(self) -> dict[str, float]:
        total = sum(h.get("value", 0) for h in self.profile.holdings)
        if not total:
            return {}
        agg: dict[str, float] = {}
        for h in self.profile.holdings:
            asset = h.get("asset", "선진국주식")
            agg[asset] = agg.get(asset, 0) + h.get("value", 0)
        return {k: v / total * 100 for k, v in agg.items()}

    # ─────────────────────────────────────
    # 구체적 실행안 (계좌 → 종목 → 금액)
    # ─────────────────────────────────────
    def action_plan(self, monthly: Optional[int] = None) -> dict[str, Any]:
        steps = self.waterfall(monthly)
        alloc = self.allocation()
        invest_steps = [s for s in steps if s["priority"] >= 3 and s["monthly"] > 0]
        total_invest = sum(s["monthly"] for s in invest_steps)

        orders: list[dict[str, Any]] = []
        for step in invest_steps:
            account = "연금저축/IRP" if step["priority"] == 3 else (
                "ISA" if step["priority"] == 4 else "일반계좌")
            fit = ACCOUNT_FIT.get(account, ["선진국주식"])
            # 이 계좌에 담을 자산군만 뽑아 목표비중으로 재정규화
            weights = {a: alloc["model"].get(a, 0) for a in fit}
            wsum = sum(weights.values()) or 1
            for asset, w in weights.items():
                amount = int(step["monthly"] * w / wsum / 1000) * 1000
                if amount < 10_000:
                    continue
                pick = INSTRUMENTS.get(asset, [{}])[0]
                orders.append({
                    "account": account,
                    "asset": asset,
                    "monthly": amount,
                    "ticker": pick.get("ticker", "-"),
                    "name": pick.get("name", asset),
                    "note": pick.get("note", ""),
                    "alternatives": [
                        f"{i['ticker']} {i['name']}" for i in INSTRUMENTS.get(asset, [])[1:3]
                    ],
                })
        return {
            "monthly_invest_total": total_invest,
            "orders": orders,
            "method": "매월 급여일 다음 영업일 자동이체 → 같은 날 시장가 분할매수(적립식). "
                      "타이밍을 재지 말고 날짜를 고정하는 편이 장기 성과가 낫다.",
            "rebalance": alloc["rebalance_band"],
            "disclaimer": DISCLAIMER,
        }

    # ─────────────────────────────────────
    # 목표 달성 시뮬레이션
    # ─────────────────────────────────────
    def goal_projection(self, annual_return: float = 5.0) -> list[dict[str, Any]]:
        """프로필의 목표들이 현재 저축 페이스로 언제 달성되는지"""
        cap = self.capacity()
        monthly = max(cap["planned_monthly_save"], 1)
        r = annual_return / 100 / 12
        out = []
        for g in self.profile.goals:
            target = int(g.get("target", 0))
            if target <= 0:
                continue
            # 월복리 적립: FV = P * ((1+r)^n - 1) / r  → n 역산
            n, fv = 0, 0.0
            while fv < target and n < 1200:
                fv = fv * (1 + r) + monthly
                n += 1
            out.append({
                "name": g.get("name", "목표"),
                "target": target,
                "monthly": monthly,
                "months_needed": n,
                "years_needed": round(n / 12, 1),
                "deadline": g.get("deadline"),
                "feasible": _feasible(n, g.get("deadline")),
                "assumed_return": annual_return,
            })
        return out


DISCLAIMER = (
    "본 결과는 공개된 자산배분 원칙과 세제 정보를 바탕으로 계산된 참고 자료이며, "
    "자본시장법상 투자자문·투자권유가 아닙니다. 제시된 ETF는 자산군 예시이고 "
    "종목코드·보수·괴리율은 변경될 수 있으니 매수 전 직접 확인하세요. "
    "투자 원금 손실 가능성이 있으며 최종 판단과 책임은 본인에게 있습니다."
)


def _feasible(months_needed: int, deadline: Optional[str]) -> Optional[bool]:
    if not deadline:
        return None
    from datetime import date
    try:
        y, m = int(deadline[:4]), int(deadline[5:7])
    except (ValueError, IndexError):
        return None
    today = date.today()
    available = (y - today.year) * 12 + (m - today.month)
    return months_needed <= available


def quant_signal_overlay(path: str = "") -> list[dict[str, Any]]:
    """
    (선택) 같은 저장소의 quant-ai 시그널을 '위성 포트폴리오' 후보로 얹는다.
    코어(지수 ETF 적립)는 그대로 두고, 여유자금의 일부만 개별종목에 쓰는 용도.
    """
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    signals = data.get("signals") or data.get("recommendations") or []
    out = []
    for s in signals[:5]:
        if not isinstance(s, dict):
            continue
        out.append({
            "ticker": s.get("ticker") or s.get("code", ""),
            "name": s.get("name", ""),
            "signal": s.get("signal") or s.get("action", ""),
            "score": s.get("score"),
            "note": "위성 포지션 — 총 투자금의 10~20% 이내로 제한할 것",
        })
    return out
