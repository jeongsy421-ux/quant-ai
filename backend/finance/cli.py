"""
==============================================
PERSONAL FINANCE - 명령줄 인터페이스
==============================================
사용 예
  python -m backend.finance.cli demo                       # 샘플 데이터로 체험
  python -m backend.finance.cli import ~/Downloads/*.csv   # 은행/카드 내역 파일 임포트
  python -m backend.finance.cli watch --dir ~/Downloads/finance
  python -m backend.finance.cli sync-email --days 30       # 카드 알림 메일 자동 수집
  python -m backend.finance.cli sync-openbanking --days 30
  python -m backend.finance.cli report                     # 컨설팅 리포트 (터미널)
  python -m backend.finance.cli report --html report.html  # HTML 리포트
  python -m backend.finance.cli budget --rate 30
  python -m backend.finance.cli advise
  python -m backend.finance.cli review                     # 미분류 거래 정리
  python -m backend.finance.cli profile --set monthly_income=3600000 risk_level=적극투자형
  python -m backend.finance.cli serve --port 5100          # 웹 API + 대시보드
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# 패키지 밖(python backend/finance/cli.py)에서 실행해도 동작하도록
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from backend.finance import cli  # type: ignore  # noqa
    __package__ = "backend.finance"

from .analyzer import Analyzer
from .categorizer import recategorize_db
from .db import DEFAULT_DB, FinanceDB
from .models import ALL_CATEGORIES, Profile
from .report import build_consultation, render_html, render_text, won


def _db(args) -> FinanceDB:
    return FinanceDB(args.db)


def cmd_demo(args) -> None:
    from .demo import generate
    db = _db(args)
    n = generate(db, months=args.months)
    print(f"샘플 거래 {n}건 생성 완료 → {db.path}")
    print("이어서 실행:  python -m backend.finance.cli report")


def cmd_import(args) -> None:
    from .ingest.csv_importer import import_paths
    db = _db(args)
    paths: list[str] = []
    for pattern in args.paths:
        expanded = glob.glob(os.path.expanduser(pattern))
        paths.extend(expanded or [os.path.expanduser(pattern)])
    if not paths:
        print("임포트할 파일이 없습니다.")
        return
    res = import_paths(db, paths, institution=args.institution)
    for f in res["files"]:
        if "error" in f:
            print(f"  ✗ {f['file']}: {f['error']}")
        else:
            print(f"  ✓ {f['file']}: 파싱 {f['parsed']}건 → 신규 {f['new']} / 중복 {f['duplicated']}")
    print(f"\n합계: 신규 {res['inserted']}건 / 중복 {res['duplicated']}건")


def cmd_watch(args) -> None:
    from .ingest.watcher import scan_once, watch
    db = _db(args)
    if args.once:
        res = scan_once(db, args.dir)
        print(f"신규 {res['inserted']}건 / 중복 {res['duplicated']}건")
    else:
        watch(db, args.dir, interval=args.interval)


def cmd_sync_email(args) -> None:
    from .ingest.email_collector import sync
    db = _db(args)
    res = sync(db, days=args.days)
    print(f"메일 {res['fetched']}건 파싱 → 신규 {res['inserted']} / 중복 {res['duplicated']}")


def cmd_sync_openbanking(args) -> None:
    from .ingest.openbanking import sync
    db = _db(args)
    res = sync(db, days=args.days)
    print(f"조회 {res['fetched']}건 → 신규 {res['inserted']} / 중복 {res['duplicated']}")


def cmd_report(args) -> None:
    db = _db(args)
    c = build_consultation(db, months_back=args.months, target_rate=args.rate)
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(c))
        print(f"HTML 리포트 저장: {args.html}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2, default=lambda o: getattr(o, "__dict__", str(o)))
        print(f"JSON 저장: {args.json}")
    if not args.html and not args.json:
        print(render_text(c))


def cmd_budget(args) -> None:
    from .budget import BudgetPlanner
    db = _db(args)
    az = Analyzer(db.query(include_transfer=True, limit=200000))
    planner = BudgetPlanner(az, db.load_profile())
    plan = planner.build(args.rate)
    if "error" in plan:
        print(plan["error"])
        return
    print(f"수입 {won(plan['income'])} / 목표 저축률 {plan['target_savings_rate']}%")
    print(f"지출예산 {won(plan['planned_spend'])} · 저축 {won(plan['planned_save'])}"
          f" (실현 저축률 {plan['planned_savings_rate']}%)\n")
    print(f"{'카테고리':<12}{'현재':>12}{'예산':>12}{'조정':>12}")
    for r in plan["categories"]:
        if r["current"] == 0:
            continue
        mark = f"-{r['cut']:,}" if r["cut"] else "유지"
        print(f"{r['category']:<12}{r['current']:>12,}{r['budget']:>12,}{mark:>12}")
    if args.save:
        month = args.month or sorted(az.monthly())[-1]
        db.save_budget(month, plan["budget"])
        print(f"\n{month} 예산으로 저장했습니다.")


def cmd_advise(args) -> None:
    from .advisor import Advisor
    from .budget import BudgetPlanner
    db = _db(args)
    az = Analyzer(db.query(include_transfer=True, limit=200000))
    profile = db.load_profile()
    plan = BudgetPlanner(az, profile).build()
    adv = Advisor(az, profile, plan)

    cap = adv.capacity()
    print(f"월 투자여력 {won(cap['planned_monthly_save'])} (현재 {won(cap['current_monthly_save'])})\n")
    for st in adv.waterfall():
        print(f"[{st['priority']}] {st['name']} — 월 {won(st['monthly'])}")
        print(f"    {st.get('vehicle','-')}")
        print(f"    {st.get('why','')}\n")
    ap = adv.action_plan()
    print(f"매월 실행안 (총 {won(ap['monthly_invest_total'])})")
    for o in ap["orders"]:
        print(f"  {o['account']:<12}{o['ticker']:<9}{o['name']:<26}{o['monthly']:>10,}원")
    print(f"\n{ap['disclaimer']}")


def cmd_review(args) -> None:
    """미분류 거래를 대화형으로 정리 — 고친 내용은 규칙으로 학습된다"""
    db = _db(args)
    stats = recategorize_db(db)
    if stats:
        print("규칙 재적용:", ", ".join(f"{k} {v}건" for k, v in stats.items()))
    pending = db.uncategorized(limit=args.limit)
    if not pending:
        print("미분류 거래가 없습니다.")
        return
    print(f"미분류 {len(pending)}건. 번호로 카테고리를 고르세요 (엔터=건너뜀, q=종료)\n")
    for i, cat in enumerate(ALL_CATEGORIES):
        print(f"  {i:>2} {cat}", end="\n" if i % 4 == 3 else "")
    print("\n")
    for t in pending:
        ans = input(f"{t.txn_date} {t.amount:>10,} {t.description[:30]:32s} > ").strip()
        if ans.lower() == "q":
            break
        if not ans.isdigit() or int(ans) >= len(ALL_CATEGORIES):
            continue
        cat = ALL_CATEGORIES[int(ans)]
        db.set_category(t.id, cat)
        print(f"  → {cat} (같은 가맹점은 앞으로 자동 분류)")


def cmd_profile(args) -> None:
    db = _db(args)
    p = db.load_profile()
    if args.set:
        d = json.loads(p.to_json())
        for item in args.set:
            if "=" not in item:
                print(f"무시: {item} (key=value 형식)")
                continue
            k, v = item.split("=", 1)
            if k not in d:
                print(f"무시: 알 수 없는 필드 {k}")
                continue
            if isinstance(d[k], bool):
                d[k] = v.lower() in ("1", "true", "y")
            elif isinstance(d[k], int):
                d[k] = int(v.replace(",", ""))
            elif isinstance(d[k], list):
                d[k] = json.loads(v)
            else:
                d[k] = v
        p = Profile.from_dict(d)
        db.save_profile(p)
        print("프로필 저장 완료\n")
    print(p.to_json())


def cmd_serve(args) -> None:
    from .api import create_app
    app = create_app(db_path=args.db)
    print(f"http://127.0.0.1:{args.port}/finance  (Ctrl+C 종료)")
    app.run(host=args.host, port=args.port, debug=args.debug)


def cmd_stats(args) -> None:
    db = _db(args)
    print(f"DB: {db.path}")
    print(f"거래 {db.count():,}건 · 기간 {db.months()[:1]} ~ {db.months()[-1:]}")
    for row in db.recent_imports(10):
        print(f"  {row['ran_at']}  {row['source']:<12}{row['detail'][:30]:32s}"
              f"신규{row['inserted']:>5} 중복{row['duplicated']:>5}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="finance", description="개인 금융 컨설팅 — 가계부 수집·분석·소비계획·투자배분"
    )
    ap.add_argument("--db", default=os.getenv("FINANCE_DB", DEFAULT_DB), help="SQLite 경로")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="샘플 데이터 생성")
    p.add_argument("--months", type=int, default=6)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("import", help="은행/카드 내역 파일 임포트")
    p.add_argument("paths", nargs="+")
    p.add_argument("--institution", help="기관명 강제 지정 (미지정 시 파일명에서 추정)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("watch", help="폴더 감시 자동 임포트")
    p.add_argument("--dir", default="~/Downloads/finance")
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("sync-email", help="카드 승인 알림 메일 수집(IMAP)")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_sync_email)

    p = sub.add_parser("sync-openbanking", help="오픈뱅킹 계좌 거래내역 수집")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_sync_openbanking)

    p = sub.add_parser("report", help="컨설팅 리포트")
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--rate", type=int, help="목표 저축률(%%)")
    p.add_argument("--html", help="HTML 파일로 저장")
    p.add_argument("--json", help="JSON 파일로 저장")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("budget", help="다음 달 소비 계획")
    p.add_argument("--rate", type=int, help="목표 저축률(%%)")
    p.add_argument("--save", action="store_true", help="예산을 DB에 저장")
    p.add_argument("--month")
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("advise", help="저축·투자 배분 제안")
    p.set_defaults(func=cmd_advise)

    p = sub.add_parser("review", help="미분류 거래 정리(학습)")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("profile", help="프로필 조회/수정")
    p.add_argument("--set", nargs="*", help="key=value 형식")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("stats", help="DB 현황")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("serve", help="웹 API + 대시보드 실행")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5100)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
