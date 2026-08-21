"""
==============================================
PERSONAL FINANCE - 카드 승인 알림 파서
==============================================
카드사가 보내는 승인 알림(문자/이메일/푸시)의 본문에서 거래를 추출한다.
이메일 수집(IMAP)과 문자 웹훅이 공통으로 이 파서를 쓴다.

지원 문구 예시
  [Web발신] 신한카드 승인 홍길동 5,500원 일시불 08/21 13:22 스타벅스강남점 누적1,234,567원
  KB국민카드 승인 12,000원 08/21 스타벅스 일시불
  삼성카드 결제 취소 23,000원 08/21 배달의민족
  [국민은행] 08/21 13:22 출금 42,000 한국전력 잔액 1,234,567
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from ..models import Transaction
from .base import clean_text, parse_amount

# 카드사/은행명
ISSUER_RE = re.compile(
    r"(신한|삼성|현대|롯데|하나|우리|국민|KB국민|BC|NH농협|농협|씨티|카카오뱅크|토스뱅크|"
    r"케이뱅크|기업|IBK|새마을금고|우체국|토스|카카오페이|네이버페이)\s*(카드|은행|페이|뱅크)?",
    re.I,
)
AMOUNT_RE = re.compile(r"([\d,]{3,})\s*원")
# 날짜: 08/21, 08.21, 2026/08/21, 08월 21일
DATE_RE = re.compile(r"(?:(\d{4})[./-])?(\d{1,2})[./월\-]\s?(\d{1,2})\s?일?")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
INSTALLMENT_RE = re.compile(r"(\d{1,2})\s*개월")

CANCEL_RE = re.compile(r"(취소|반품|환불)")
DEPOSIT_RE = re.compile(r"(입금|급여|이체입금|받음)")
WITHDRAW_RE = re.compile(r"(출금|이체출금|자동이체|납부)")

# 금액 뒤에 붙는 부가정보 — 가맹점명으로 오인하면 안 되는 토큰
_NOISE_TOKENS = re.compile(
    r"(누적|잔액|한도|승인|취소|결제|일시불|\d+개월|Web발신|웹발신|체크|신용|이용)"
)


def parse_notification(text: str, default_year: Optional[int] = None) -> Optional[Transaction]:
    """알림 본문 1건 → Transaction (해석 불가면 None)"""
    body = clean_text(text)
    if not body:
        return None

    amounts = AMOUNT_RE.findall(body)
    if not amounts:
        return None
    # 첫 번째 금액이 거래금액, 그 뒤의 '누적/잔액'은 무시
    amount = parse_amount(amounts[0])
    if not amount:
        return None

    issuer_m = ISSUER_RE.search(body)
    institution = clean_text(issuer_m.group(0)) if issuer_m else "기타"
    if issuer_m and not issuer_m.group(2):
        institution += "카드" if "카드" in body else ""

    # 부호 결정
    is_cancel = bool(CANCEL_RE.search(body))
    is_deposit = bool(DEPOSIT_RE.search(body)) and not WITHDRAW_RE.search(body)
    signed = amount if (is_cancel or is_deposit) else -amount

    # 날짜
    year = default_year or datetime.now().year
    txn_date = datetime.now().strftime("%Y-%m-%d")
    dm = DATE_RE.search(body)
    if dm:
        y, mo, d = dm.group(1), int(dm.group(2)), int(dm.group(3))
        try:
            txn_date = datetime(int(y) if y else year, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            pass

    merchant = _extract_merchant(body)
    inst_m = INSTALLMENT_RE.search(body)

    return Transaction(
        txn_date=txn_date,
        amount=signed,
        description=merchant or f"{institution} 승인",
        institution=institution,
        source="notification",
        installment=int(inst_m.group(1)) if inst_m else 0,
        raw={"body": body[:500]},
    )


def _extract_merchant(body: str) -> str:
    """알림 본문에서 가맹점명 추출 — 금액/시각 뒤의 의미 있는 토큰"""
    tail = body
    m = list(AMOUNT_RE.finditer(body))
    if m:
        tail = body[m[0].end():]
    tail = TIME_RE.sub(" ", tail)
    tail = DATE_RE.sub(" ", tail)
    tail = re.sub(r"[\d,]{3,}\s*원?", " ", tail)          # 누적/잔액 숫자 제거
    parts = [p for p in re.split(r"[\s|/()\[\]]+", tail) if p]
    cands = [p for p in parts if len(p) >= 2 and not _NOISE_TOKENS.fullmatch(p) and not p.isdigit()]
    cands = [p for p in cands if not _NOISE_TOKENS.match(p)]
    return " ".join(cands[:3]).strip()


def parse_many(texts: list[str]) -> list[Transaction]:
    out = []
    for t in texts:
        txn = parse_notification(t)
        if txn:
            out.append(txn)
    return out
