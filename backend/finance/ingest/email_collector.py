"""
==============================================
PERSONAL FINANCE - 카드 승인 메일 자동 수집 (IMAP)
==============================================
카드사 승인 알림 메일함을 주기적으로 읽어 거래를 자동 적재한다.
가장 현실적인 '자동으로 긁어오기' 경로다 — 은행 로그인 스크래핑이 아니라
'내 메일함을 내가 읽는' 방식이라 약관 문제가 없다.

준비 (Gmail 기준)
  1) 카드사 이용내역 알림 메일 수신 신청
  2) Google 계정 → 2단계 인증 → '앱 비밀번호' 발급
  3) .env 에 아래 값 설정
       FINANCE_IMAP_HOST=imap.gmail.com
       FINANCE_IMAP_USER=you@gmail.com
       FINANCE_IMAP_PASSWORD=앱비밀번호16자리
       FINANCE_IMAP_FOLDER=INBOX
       FINANCE_IMAP_SENDERS=@shinhancard.com,@kbcard.com,@samsungcard.com
  4) python -m backend.finance.cli sync-email --days 30

네이버/다음도 IMAP 설정 후 호스트만 바꾸면 동일하게 동작한다.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from typing import Any, Optional

from ..models import Transaction
from .notifications import parse_notification

DEFAULT_SENDERS = [
    "shinhancard.com", "kbcard.com", "samsungcard.com", "hyundaicard.com",
    "lottecard.co.kr", "hanacard.co.kr", "wooricard.com", "bccard.com",
    "nonghyup.com", "kakaobank.com", "tossbank.com",
]

_TAG_RE = re.compile(r"<[^>]+>")


class EmailConfig:
    def __init__(self, **kw: Any):
        self.host = kw.get("host") or os.getenv("FINANCE_IMAP_HOST", "imap.gmail.com")
        self.port = int(kw.get("port") or os.getenv("FINANCE_IMAP_PORT", "993"))
        self.user = kw.get("user") or os.getenv("FINANCE_IMAP_USER", "")
        self.password = kw.get("password") or os.getenv("FINANCE_IMAP_PASSWORD", "")
        self.folder = kw.get("folder") or os.getenv("FINANCE_IMAP_FOLDER", "INBOX")
        senders = kw.get("senders") or os.getenv("FINANCE_IMAP_SENDERS", "")
        self.senders = [s.strip() for s in senders.split(",") if s.strip()] or DEFAULT_SENDERS

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_text(msg: email.message.Message) -> str:
    """메일 본문을 평문으로 (HTML이면 태그 제거)"""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            parts.append(_payload(part))
    else:
        parts.append(_payload(msg))
    text = "\n".join(p for p in parts if p)
    return _TAG_RE.sub(" ", text)


def _payload(part: email.message.Message) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:
        return ""


def fetch_transactions(config: Optional[EmailConfig] = None, days: int = 30) -> list[Transaction]:
    """최근 N일 카드사 알림 메일 → Transaction 리스트"""
    cfg = config or EmailConfig()
    if not cfg.configured:
        raise RuntimeError(
            "IMAP 설정이 없습니다. .env 에 FINANCE_IMAP_USER / FINANCE_IMAP_PASSWORD 를 넣으세요.\n"
            "(Gmail은 계정 비밀번호가 아니라 '앱 비밀번호'가 필요합니다.)"
        )

    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    txns: list[Transaction] = []

    conn = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    try:
        conn.login(cfg.user, cfg.password)
        conn.select(cfg.folder, readonly=True)   # readonly: 읽음 표시를 바꾸지 않는다
        seen_uids: set[bytes] = set()

        for sender in cfg.senders:
            typ, data = conn.search(None, f'(SINCE {since} FROM "{sender}")')
            if typ != "OK" or not data or not data[0]:
                continue
            for uid in data[0].split():
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                typ, msg_data = conn.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                txn = _message_to_txn(msg)
                if txn:
                    txns.append(txn)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return txns


def _message_to_txn(msg: email.message.Message) -> Optional[Transaction]:
    subject = _decode(msg.get("Subject"))
    body = _body_text(msg)
    txn = parse_notification(f"{subject}\n{body}")
    if txn is None:
        return None
    txn.source = "email"
    # 메일 헤더의 날짜를 우선 사용 (본문에 연도가 없는 경우가 많다)
    try:
        dt = email.utils.parsedate_to_datetime(msg.get("Date"))
        if dt and txn.txn_date[5:] == dt.strftime("%m-%d"):
            txn.txn_date = dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    txn.raw["subject"] = subject[:200]
    return txn


def sync(db, days: int = 30, config: Optional[EmailConfig] = None) -> dict[str, Any]:
    """메일 수집 → 분류 → DB 저장"""
    from ..categorizer import Categorizer

    txns = fetch_transactions(config, days=days)
    Categorizer(db.user_rules()).classify_all(txns)
    new, dup = db.add_transactions(txns)
    db.log_import("email", f"최근 {days}일", new, dup)
    return {"fetched": len(txns), "inserted": new, "duplicated": dup}
