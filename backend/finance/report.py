"""
==============================================
PERSONAL FINANCE - 컨설팅 리포트 생성
==============================================
분석/예산/투자 결과를 하나의 리포트로 엮는다. (텍스트 · HTML)
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Optional

from .advisor import Advisor, DISCLAIMER
from .analyzer import Analyzer
from .budget import BudgetPlanner, recommended_savings_rate
from .models import Profile


def won(n: Optional[float]) -> str:
    if n is None:
        return "-"
    return f"{int(round(n)):,}원"


def build_consultation(db, months_back: int = 6, target_rate: Optional[int] = None) -> dict[str, Any]:
    """리포트에 필요한 모든 데이터를 한 번에 계산"""
    from .analyzer import month_range

    months = month_range(months_back)
    txns = db.query(start=f"{months[0]}-01", include_transfer=True, limit=200000)
    az = Analyzer(txns)
    profile = db.load_profile()

    planner = BudgetPlanner(az, profile)
    plan = planner.build(target_rate)
    advisor = Advisor(az, profile, plan)

    all_months = sorted(az.monthly())
    current_month = all_months[-1] if all_months else datetime.now().strftime("%Y-%m")

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profile": profile,
        "txn_count": len(txns),
        "summary": az.summary(),
        "monthly": az.monthly(),
        "categories": az.by_category(month=current_month),
        "categories_all": az.by_category(),
        "recurring": az.recurring(),
        "subscriptions": az.subscriptions(),
        "anomalies": az.anomalies(current_month),
        "top_merchants": az.top_merchants(current_month),
        "small_leaks": az.small_leaks(),
        "no_spend_days": az.no_spend_days(current_month),
        "current_month": current_month,
        "plan": plan,
        "tracking": planner.track(current_month, plan.get("budget")),
        "capacity": advisor.capacity(),
        "waterfall": advisor.waterfall(),
        "allocation": advisor.allocation(),
        "action_plan": advisor.action_plan(),
        "goals": advisor.goal_projection(),
        "recommended_rate": recommended_savings_rate(profile),
        "disclaimer": DISCLAIMER,
    }


# ─────────────────────────────────────────
# 텍스트 리포트
# ─────────────────────────────────────────
def render_text(c: dict[str, Any]) -> str:
    L: list[str] = []
    p: Profile = c["profile"]
    s = c["summary"]
    add = L.append

    add("=" * 62)
    add(f"  개인 금융 컨설팅 리포트   ({c['generated_at']})")
    add(f"  {p.name} · {p.age}세 · 부양가족 {p.dependents}명 · 위험성향 {p.risk_level}")
    add("=" * 62)

    if s.get("months", 0) == 0:
        add("\n분석할 거래내역이 없습니다. 먼저 내역을 임포트하세요.")
        return "\n".join(L)

    # 1. 현금흐름
    add(f"\n[1] 현금흐름 진단   기간 {s['period']} ({s['months']}개월)")
    add("-" * 62)
    add(f"  월평균 수입      {won(s['avg_income']):>16}")
    add(f"  월평균 지출      {won(s['avg_expense']):>16}   (필수 {won(s['avg_need'])} / 재량 {won(s['avg_want'])})")
    add(f"  월평균 저축·투자 {won(s['avg_save']):>16}")
    add(f"  저축률           {s['savings_rate']:>13.1f}%   (권장 {c['recommended_rate']}%)")
    add(f"  소득 대비 필수비 {s['need_ratio']:>13.1f}%   재량비 {s['want_ratio']:.1f}%")
    verdict = _verdict(s["savings_rate"], c["recommended_rate"])
    add(f"  → 진단: {verdict}")

    add("\n  월별 추이")
    add(f"  {'월':<9}{'수입':>13}{'지출':>13}{'저축':>13}{'저축률':>9}")
    for m, v in sorted(c["monthly"].items()):
        add(f"  {m:<9}{v['income']:>13,}{v['expense']:>13,}{v['save']:>13,}{v['savings_rate']:>8.1f}%")

    # 2. 지출 구조
    add(f"\n[2] 지출 구조   ({c['current_month']} 기준)")
    add("-" * 62)
    for row in c["categories"][:12]:
        bar = "█" * max(1, int(row["share"] / 2))
        tag = {"need": "필수", "want": "재량", "save": "저축"}.get(row["kind"], "")
        add(f"  {row['category']:<10}{row['amount']:>12,}  {row['share']:>5.1f}% [{tag}] {bar}")
    cur = c["monthly"].get(c["current_month"], {})
    if cur.get("save"):
        add(f"  {'저축·투자':<10}{cur['save']:>12,}   (지출과 별도 집계)")
    add(f"  무지출일수: {c['no_spend_days']}일")

    # 3. 고정비
    if c["recurring"]:
        total_fixed = sum(r["monthly"] for r in c["recurring"])
        add(f"\n[3] 고정비 · 반복결제   월 {won(total_fixed)} (연 {won(total_fixed*12)})")
        add("-" * 62)
        for r in c["recurring"][:12]:
            add(f"  {r['merchant']:<22}{r['monthly']:>11,}/월  연{r['annual']:>10,}  [{r['category']}] {r['months']}개월 연속")
        if c["subscriptions"]:
            sub_total = sum(r["monthly"] for r in c["subscriptions"])
            add(f"\n  구독·정기결제 {len(c['subscriptions'])}건 = 월 {won(sub_total)} / 연 {won(sub_total*12)}")
            add("  → 최근 30일간 실제로 쓴 것만 남기고 해지하면 즉시 저축률이 오릅니다.")

    # 4. 이상 지출 / 새는 돈
    if c["anomalies"] or c["small_leaks"]:
        add("\n[4] 주의 신호")
        add("-" * 62)
        for a in c["anomalies"][:5]:
            add(f"  ⚠ {a['category']} — {a['month']} {a['amount']:,}원 (평소 {a['usual']:,}원, +{a['excess']:,}원)")
        for l in c["small_leaks"][:5]:
            add(f"  · {l['merchant']:<20} {l['count']:>3}회 누적 {l['amount']:>9,}원 (월 {l['monthly']:,}원) [{l['category']}]")

    # 5. 소비 계획
    plan = c["plan"]
    if "error" not in plan:
        add(f"\n[5] 다음 달 소비 계획   목표 저축률 {plan['target_savings_rate']}%")
        add("-" * 62)
        add(f"  수입 {won(plan['income'])} = 지출예산 {won(plan['planned_spend'])} + 저축 {won(plan['planned_save'])}")
        if plan["required_cut"] > 0:
            add(f"  목표 저축액 {won(plan['target_save'])} → 지출 {won(plan['required_cut'])} 절감 필요"
                f" (계획 반영 {won(plan['achieved_cut'])})")
        else:
            add(f"  목표 저축액 {won(plan['target_save'])}은 현재 지출 수준으로 이미 달성 가능합니다."
                f" 추가 절감 없이 초과분 {won(plan['planned_save'] - plan['target_save'])}을 투자에 배분하세요.")
        add(f"  {'카테고리':<10}{'현재':>11}{'예산':>11}{'조정':>11}  기준선")
        for row in plan["categories"][:14]:
            if row["current"] == 0:
                continue
            mark = f"-{row['cut']:,}" if row["cut"] else "유지"
            add(f"  {row['category']:<10}{row['current']:>11,}{row['budget']:>11,}{mark:>11}  {row['benchmark']:>10,}")
        if plan["planned_savings_rate"] < plan["target_savings_rate"]:
            add(f"  → 지출 조정만으로는 목표({plan['target_savings_rate']}%)에 미달합니다"
                f" (달성 {plan['planned_savings_rate']}%). 수입 증대나 고정비 구조조정이 필요합니다.")

    # 6. 이번 달 진행
    tr = c["tracking"]
    add(f"\n[6] 이번 달 진행   {tr['month']} ({tr['days_passed']}/{tr['days_total']}일 경과)")
    add("-" * 62)
    add(f"  사용 {won(tr['total_spent'])} / 예산 {won(tr['total_budget'])}"
        f"  → 월말 예상 {won(tr['total_projected'])} [{'정상' if tr['on_track'] else '초과 위험'}]")
    for row in tr["rows"][:8]:
        if row["budget"] == 0 and row["spent"] == 0:
            continue
        add(f"  {row['category']:<10}{row['spent']:>10,} / {row['budget']:>10,}  {row['status']}")

    # 7. 저축·투자 우선순위
    add("\n[7] 저축·투자 우선순위")
    add("-" * 62)
    cap = c["capacity"]
    add(f"  월 투자여력: 현재 {won(cap['current_monthly_save'])} → 계획 {won(cap['planned_monthly_save'])}"
        f" (+{won(cap['improvement'])})")
    for st in c["waterfall"]:
        add(f"\n  [{st['priority']}] {st['name']} — 월 {won(st['monthly'])}")
        add(f"      수단: {st.get('vehicle','-')}")
        for line in _wrap(st.get("why", ""), 54):
            add(f"      {line}")
        if st.get("caution"):
            add(f"      ⚠ {st['caution']}")
        if st.get("eta_months"):
            add(f"      예상 소요: 약 {st['eta_months']}개월")

    # 8. 자산배분
    al = c["allocation"]
    add(f"\n[8] 자산배분 ({al['risk_level']} · {al['age']}세)")
    add("-" * 62)
    for row in al["rows"]:
        gap = f"{row['gap_pct']:+.1f}%p" if al["total_holdings"] else "-"
        add(f"  {row['asset']:<10} 목표 {row['target_pct']:>3}%   현재 {row['current_pct']:>5.1f}%   {gap:>8}  {row['action']}")
    add(f"  리밸런싱: {al['rebalance_band']}")

    # 9. 구체적 실행안
    ap = c["action_plan"]
    add(f"\n[9] 매월 실행안   총 {won(ap['monthly_invest_total'])}")
    add("-" * 62)
    cur_acc = ""
    for o in ap["orders"]:
        if o["account"] != cur_acc:
            cur_acc = o["account"]
            add(f"\n  ▸ {cur_acc}")
        add(f"      {o['ticker']:<8}{o['name']:<24}{o['monthly']:>10,}원/월  [{o['asset']}]")
        if o["note"]:
            add(f"      {'':8}{o['note']}")
        if o["alternatives"]:
            add(f"      {'':8}대안: {', '.join(o['alternatives'])}")
    add(f"\n  방법: {ap['method']}")

    # 10. 목표
    if c["goals"]:
        add("\n[10] 목표 달성 시뮬레이션 (연 5% 가정)")
        add("-" * 62)
        for g in c["goals"]:
            fe = {True: "달성 가능", False: "기한 내 어려움", None: ""}[g["feasible"]]
            add(f"  {g['name']:<14}{won(g['target']):>16}  {g['years_needed']}년 소요"
                f"{('  · 기한 '+g['deadline']+' → '+fe) if g['deadline'] else ''}")

    add("\n" + "=" * 62)
    for line in _wrap(c["disclaimer"], 58):
        add(f"  {line}")
    add("=" * 62)
    return "\n".join(L)


def _verdict(rate: float, target: int) -> str:
    if rate >= target:
        return f"양호 — 권장 저축률({target}%)을 충족합니다. 다음 단계는 '어디에 넣느냐'입니다."
    if rate >= target * 0.6:
        return f"보통 — 권장({target}%)까지 {target-rate:.1f}%p 부족. 재량 지출 조정으로 메울 수 있는 수준입니다."
    if rate > 0:
        return f"주의 — 저축률이 낮습니다. 고정비 구조부터 손봐야 합니다."
    return "위험 — 수입보다 지출이 큽니다. 지출 축소가 최우선입니다."


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


# ─────────────────────────────────────────
# HTML 리포트
# ─────────────────────────────────────────
def render_html(c: dict[str, Any]) -> str:
    p: Profile = c["profile"]
    s = c["summary"]
    e = html.escape

    def cat_rows() -> str:
        out = []
        for r in c["categories"][:12]:
            out.append(
                f"<tr><td>{e(r['category'])}</td><td class='num'>{r['amount']:,}</td>"
                f"<td class='num'>{r['share']}%</td>"
                f"<td><div class='bar' style='width:{min(100, r['share']*3)}%'></div></td></tr>"
            )
        return "".join(out)

    def month_rows() -> str:
        return "".join(
            f"<tr><td>{m}</td><td class='num'>{v['income']:,}</td><td class='num'>{v['expense']:,}</td>"
            f"<td class='num'>{v['save']:,}</td><td class='num'>{v['savings_rate']}%</td></tr>"
            for m, v in sorted(c["monthly"].items())
        )

    def plan_rows() -> str:
        plan = c["plan"]
        if "error" in plan:
            return f"<tr><td colspan='4'>{e(plan['error'])}</td></tr>"
        return "".join(
            f"<tr><td>{e(r['category'])}</td><td class='num'>{r['current']:,}</td>"
            f"<td class='num'>{r['budget']:,}</td>"
            f"<td class='num {'cut' if r['cut'] else ''}'>{('-'+format(r['cut'],',')) if r['cut'] else '유지'}</td></tr>"
            for r in plan["categories"][:14] if r["current"] > 0
        )

    def waterfall_html() -> str:
        out = []
        for st in c["waterfall"]:
            out.append(
                f"<div class='step'><div class='step-h'><span class='pri'>{st['priority']}</span>"
                f"<b>{e(st['name'])}</b><span class='amt'>월 {st['monthly']:,}원</span></div>"
                f"<div class='muted'>{e(st.get('vehicle','-'))}</div>"
                f"<p>{e(st.get('why',''))}</p>"
                + (f"<p class='warn'>⚠ {e(st['caution'])}</p>" if st.get("caution") else "")
                + "</div>"
            )
        return "".join(out)

    def alloc_rows() -> str:
        return "".join(
            f"<tr><td>{e(r['asset'])}</td><td class='num'>{r['target_pct']}%</td>"
            f"<td class='num'>{r['current_pct']}%</td><td>{e(r['action'])}</td>"
            f"<td class='muted'>{e(', '.join(i['ticker']+' '+i['name'] for i in r['instruments'][:2]))}</td></tr>"
            for r in c["allocation"]["rows"]
        )

    def order_rows() -> str:
        return "".join(
            f"<tr><td>{e(o['account'])}</td><td><code>{e(o['ticker'])}</code></td>"
            f"<td>{e(o['name'])}</td><td class='num'>{o['monthly']:,}</td>"
            f"<td class='muted'>{e(o['note'])}</td></tr>"
            for o in c["action_plan"]["orders"]
        )

    def fixed_rows() -> str:
        return "".join(
            f"<tr><td>{e(r['merchant'])}</td><td class='num'>{r['monthly']:,}</td>"
            f"<td class='num'>{r['annual']:,}</td><td>{e(r['category'])}</td></tr>"
            for r in c["recurring"][:12]
        )

    alerts = "".join(
        f"<li>⚠ <b>{e(a['category'])}</b> {a['month']} {a['amount']:,}원 "
        f"— 평소 {a['usual']:,}원 대비 <b>+{a['excess']:,}원</b></li>"
        for a in c["anomalies"][:5]
    ) or "<li>특이 지출 없음</li>"

    return f"""<title>금융 컨설팅 리포트</title>
<style>
:root {{ --bg:#fff; --fg:#16181d; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb;
        --accent:#2563eb; --warn:#dc2626; --ok:#059669; }}
:root:not([data-theme="light"]) {{}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#0f1115; --fg:#e5e7eb; --muted:#9ca3af; --line:#272b33; --card:#161a21;
  --accent:#60a5fa; --warn:#f87171; --ok:#34d399; }} }}
:root[data-theme="dark"] {{ --bg:#0f1115; --fg:#e5e7eb; --muted:#9ca3af; --line:#272b33;
  --card:#161a21; --accent:#60a5fa; --warn:#f87171; --ok:#34d399; }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system,'Apple SD Gothic Neo',
  'Malgun Gothic',system-ui,sans-serif; max-width:940px; margin:0 auto; padding:32px 20px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:36px 0 12px;
  padding-bottom:8px; border-bottom:2px solid var(--line); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }}
.kpi .l {{ color:var(--muted); font-size:12px; }} .kpi .v {{ font-size:20px; font-weight:600; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th,td {{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:left; }}
th {{ color:var(--muted); font-weight:500; font-size:12px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.cut {{ color:var(--warn); }} .muted {{ color:var(--muted); font-size:13px; }}
.bar {{ height:8px; background:var(--accent); border-radius:4px; }}
.step {{ background:var(--card); border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:8px; padding:12px 14px; margin-bottom:10px; }}
.step-h {{ display:flex; align-items:center; gap:8px; }}
.pri {{ background:var(--accent); color:#fff; border-radius:50%; width:22px; height:22px;
  display:inline-flex; align-items:center; justify-content:center; font-size:12px; }}
.amt {{ margin-left:auto; font-weight:600; }}
.step p {{ margin:6px 0 0; font-size:13px; color:var(--muted); }}
.warn {{ color:var(--warn) !important; }}
.verdict {{ background:var(--card); border-left:3px solid var(--ok); padding:12px 14px;
  border-radius:8px; margin:12px 0; }}
.scroll {{ overflow-x:auto; }} code {{ background:var(--card); padding:1px 5px; border-radius:4px; }}
footer {{ margin-top:40px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--muted); font-size:12px; }}
</style>
<h1>개인 금융 컨설팅 리포트</h1>
<div class="sub">{e(p.name)} · {p.age}세 · 부양가족 {p.dependents}명 · {e(p.risk_level)}
 &nbsp;|&nbsp; {e(c['generated_at'])} 기준 · 거래 {c['txn_count']:,}건 · {e(str(s.get('period','-')))}</div>

<div class="grid">
  <div class="kpi"><div class="l">월평균 수입</div><div class="v">{s.get('avg_income',0):,}원</div></div>
  <div class="kpi"><div class="l">월평균 지출</div><div class="v">{s.get('avg_expense',0):,}원</div></div>
  <div class="kpi"><div class="l">저축률</div><div class="v">{s.get('savings_rate',0)}%</div></div>
  <div class="kpi"><div class="l">월 투자여력</div><div class="v">{c['capacity']['planned_monthly_save']:,}원</div></div>
</div>
<div class="verdict">{e(_verdict(s.get('savings_rate',0), c['recommended_rate']))}</div>

<h2>월별 현금흐름</h2>
<div class="scroll"><table>
<tr><th>월</th><th class="num">수입</th><th class="num">지출</th><th class="num">저축</th><th class="num">저축률</th></tr>
{month_rows()}
</table></div>

<h2>지출 구조 ({e(c['current_month'])})</h2>
<div class="scroll"><table>
<tr><th>카테고리</th><th class="num">금액</th><th class="num">비중</th><th></th></tr>
{cat_rows()}
</table></div>

<h2>고정비 · 반복결제</h2>
<div class="scroll"><table>
<tr><th>항목</th><th class="num">월</th><th class="num">연</th><th>분류</th></tr>
{fixed_rows()}
</table></div>

<h2>주의 신호</h2>
<ul>{alerts}</ul>

<h2>다음 달 소비 계획</h2>
<div class="scroll"><table>
<tr><th>카테고리</th><th class="num">현재</th><th class="num">예산</th><th class="num">조정</th></tr>
{plan_rows()}
</table></div>

<h2>저축·투자 우선순위</h2>
{waterfall_html()}

<h2>자산배분 ({e(c['allocation']['risk_level'])})</h2>
<div class="scroll"><table>
<tr><th>자산군</th><th class="num">목표</th><th class="num">현재</th><th>액션</th><th>상품 예시</th></tr>
{alloc_rows()}
</table></div>

<h2>매월 실행안 (총 {c['action_plan']['monthly_invest_total']:,}원)</h2>
<div class="scroll"><table>
<tr><th>계좌</th><th>종목코드</th><th>종목명</th><th class="num">월 납입</th><th>메모</th></tr>
{order_rows()}
</table></div>
<p class="muted">{e(c['action_plan']['method'])}</p>

<footer>{e(c['disclaimer'])}</footer>
"""
