"""
==============================================
PERSONAL FINANCE - Flask API + 대시보드
==============================================
기존 quant-ai Flask 앱에 붙이거나(register_blueprint) 단독 실행할 수 있다.

  from backend.finance.api import finance_bp
  app.register_blueprint(finance_bp)

엔드포인트
  GET  /finance                       리포트 HTML
  GET  /api/finance/summary           현금흐름 요약
  GET  /api/finance/transactions      거래 목록
  GET  /api/finance/categories        카테고리별 지출
  GET  /api/finance/recurring         고정비·구독
  GET  /api/finance/budget            소비 계획
  GET  /api/finance/advice            저축·투자 배분 + 종목
  GET  /api/finance/report            리포트 전체(JSON)
  POST /api/finance/transactions      수기 거래 입력
  POST /api/finance/category          분류 수정(+학습)
  POST /api/finance/profile           프로필 저장
  POST /api/finance/import            파일 경로 임포트
  POST /api/finance/sync/email        메일 수집 실행
  POST /api/finance/webhook/sms       문자 알림 수신 (토큰 필요)
"""
from __future__ import annotations

import hmac
import os
from dataclasses import asdict
from functools import wraps
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from .advisor import Advisor
from .analyzer import Analyzer
from .budget import BudgetPlanner
from .categorizer import Categorizer, recategorize_db
from .db import DEFAULT_DB, FinanceDB
from .models import Profile, Transaction
from .report import build_consultation, render_html

finance_bp = Blueprint("finance", __name__)

_db_cache: dict[str, FinanceDB] = {}


def get_db() -> FinanceDB:
    path = current_app.config.get("FINANCE_DB", os.getenv("FINANCE_DB", DEFAULT_DB))
    if path not in _db_cache:
        _db_cache[path] = FinanceDB(path)
    return _db_cache[path]


def _analyzer(db: FinanceDB, months: int = 6) -> Analyzer:
    from .analyzer import month_range
    start = f"{month_range(months)[0]}-01"
    return Analyzer(db.query(start=start, include_transfer=True, limit=200000))


def require_token(fn):
    """웹훅용 공유 토큰 검증 — FINANCE_WEBHOOK_TOKEN 미설정 시 엔드포인트를 막는다."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.getenv("FINANCE_WEBHOOK_TOKEN", "")
        if not expected:
            return jsonify({"error": "FINANCE_WEBHOOK_TOKEN이 설정되지 않아 비활성화됨"}), 503
        given = request.headers.get("X-Finance-Token", "") or request.args.get("token", "")
        if not hmac.compare_digest(given, expected):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────
# 조회
# ─────────────────────────────────────────
@finance_bp.get("/finance")
def dashboard() -> Response:
    c = build_consultation(get_db())
    return Response(render_html(c), mimetype="text/html; charset=utf-8")


@finance_bp.get("/api/finance/summary")
def api_summary():
    az = _analyzer(get_db(), int(request.args.get("months", 6)))
    return jsonify({"summary": az.summary(), "monthly": az.monthly()})


@finance_bp.get("/api/finance/transactions")
def api_transactions():
    db = get_db()
    txns = db.query(
        start=request.args.get("start"),
        end=request.args.get("end"),
        category=request.args.get("category"),
        include_transfer=request.args.get("include_transfer") == "1",
        limit=int(request.args.get("limit", 200)),
    )
    return jsonify([{**asdict(t), "month": t.month} for t in txns])


@finance_bp.get("/api/finance/categories")
def api_categories():
    az = _analyzer(get_db())
    return jsonify(az.by_category(month=request.args.get("month")))


@finance_bp.get("/api/finance/recurring")
def api_recurring():
    az = _analyzer(get_db())
    return jsonify({"recurring": az.recurring(), "subscriptions": az.subscriptions(),
                    "monthly_total": az.fixed_cost_total()})


@finance_bp.get("/api/finance/budget")
def api_budget():
    db = get_db()
    az = _analyzer(db)
    planner = BudgetPlanner(az, db.load_profile())
    rate = request.args.get("rate", type=int)
    plan = planner.build(rate)
    month = request.args.get("month") or (sorted(az.monthly()) or [""])[-1]
    return jsonify({"plan": plan, "tracking": planner.track(month, plan.get("budget")) if month else None})


@finance_bp.get("/api/finance/advice")
def api_advice():
    db = get_db()
    az = _analyzer(db)
    profile = db.load_profile()
    plan = BudgetPlanner(az, profile).build()
    adv = Advisor(az, profile, plan)
    return jsonify({
        "capacity": adv.capacity(),
        "waterfall": adv.waterfall(),
        "allocation": adv.allocation(),
        "action_plan": adv.action_plan(),
        "goals": adv.goal_projection(),
    })


@finance_bp.get("/api/finance/report")
def api_report():
    c = build_consultation(get_db(), months_back=int(request.args.get("months", 6)))
    c["profile"] = asdict(c["profile"])
    return jsonify(c)


@finance_bp.get("/api/finance/stats")
def api_stats():
    db = get_db()
    return jsonify({"count": db.count(), "months": db.months(), "imports": db.recent_imports()})


# ─────────────────────────────────────────
# 입력 / 수정
# ─────────────────────────────────────────
@finance_bp.post("/api/finance/transactions")
def api_add_transaction():
    db = get_db()
    body = request.get_json(silent=True) or {}
    try:
        txn = Transaction(
            txn_date=body["txn_date"],
            amount=int(body["amount"]),
            description=body.get("description", ""),
            institution=body.get("institution", ""),
            memo=body.get("memo", ""),
            source="manual",
        )
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"txn_date와 amount는 필수입니다: {e}"}), 400
    if body.get("category"):
        txn.category = body["category"]
    else:
        Categorizer(db.user_rules()).classify_all([txn])
    new, dup = db.add_transactions([txn])
    return jsonify({"inserted": new, "duplicated": dup, "category": txn.category})


@finance_bp.post("/api/finance/category")
def api_set_category():
    body = request.get_json(silent=True) or {}
    txn_id, category = body.get("id"), body.get("category")
    if not txn_id or not category:
        return jsonify({"error": "id와 category가 필요합니다"}), 400
    try:
        get_db().set_category(int(txn_id), category, learn=body.get("learn", True))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True, "learned": bool(body.get("learn", True))})


@finance_bp.post("/api/finance/recategorize")
def api_recategorize():
    stats = recategorize_db(get_db(), only_uncategorized=not request.args.get("all"))
    return jsonify({"updated": stats})


@finance_bp.post("/api/finance/profile")
def api_profile():
    db = get_db()
    body = request.get_json(silent=True) or {}
    profile = Profile.from_dict({**{k: v for k, v in asdict(db.load_profile()).items()}, **body})
    db.save_profile(profile)
    return jsonify(asdict(profile))


# ─────────────────────────────────────────
# 자동 수집
# ─────────────────────────────────────────
@finance_bp.post("/api/finance/import")
def api_import():
    from .ingest.csv_importer import import_paths
    body = request.get_json(silent=True) or {}
    paths = body.get("paths") or []
    if not paths:
        return jsonify({"error": "paths 배열이 필요합니다"}), 400
    return jsonify(import_paths(get_db(), paths, institution=body.get("institution")))


@finance_bp.post("/api/finance/sync/email")
def api_sync_email():
    from .ingest.email_collector import sync
    try:
        return jsonify(sync(get_db(), days=int(request.args.get("days", 30))))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


@finance_bp.post("/api/finance/sync/openbanking")
def api_sync_openbanking():
    from .ingest.openbanking import sync
    try:
        return jsonify(sync(get_db(), days=int(request.args.get("days", 30))))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


@finance_bp.post("/api/finance/webhook/sms")
@require_token
def api_webhook_sms():
    """
    안드로이드 문자 자동전달 앱(예: SMS Forwarder, Tasker, MacroDroid)에서
    카드 승인 문자를 이 주소로 POST하면 즉시 가계부에 반영된다.

      POST /api/finance/webhook/sms
      Header: X-Finance-Token: <FINANCE_WEBHOOK_TOKEN>
      Body:   {"text": "[Web발신] 신한카드 승인 5,500원 08/21 스타벅스"}
    """
    from .ingest.notifications import parse_notification

    body = request.get_json(silent=True) or {}
    text = body.get("text") or body.get("message") or request.form.get("text", "")
    if not text:
        return jsonify({"error": "text 필드가 필요합니다"}), 400

    txn = parse_notification(text)
    if txn is None:
        return jsonify({"parsed": False, "reason": "금액을 찾지 못했습니다"}), 200

    db = get_db()
    txn.source = "sms"
    Categorizer(db.user_rules()).classify_all([txn])
    new, dup = db.add_transactions([txn])
    db.log_import("sms", txn.description[:40], new, dup)
    return jsonify({
        "parsed": True, "inserted": new, "duplicated": dup,
        "transaction": {"date": txn.txn_date, "amount": txn.amount,
                        "merchant": txn.description, "category": txn.category},
    })


def create_app(db_path: str = "") -> Any:
    """단독 실행용 앱"""
    from flask import Flask
    try:
        from flask_cors import CORS
    except ImportError:
        CORS = None

    app = Flask(__name__)
    if db_path:
        app.config["FINANCE_DB"] = db_path
    if CORS:
        CORS(app, resources={r"/api/finance/*": {"origins": os.getenv("FINANCE_CORS", "*")}})
    app.register_blueprint(finance_bp)
    return app
