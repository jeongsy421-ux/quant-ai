"""
==============================================
PERSONAL FINANCE - 수집 공통 유틸
==============================================
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_NUM_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%y-%m-%d", "%y.%m.%d",
    "%m/%d/%Y", "%m-%d", "%m.%d", "%m/%d",
)


def parse_amount(value) -> Optional[int]:
    """'1,234원', '-1,234', '(1,234)', '1234.00' → 정수(원). 값이 없으면 None"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip()
    if not s or s in ("-", "0원", ""):
        return 0 if s in ("0원",) else None
    negative = s.startswith("(") and s.endswith(")")   # 회계식 음수 표기
    m = _NUM_RE.search(s.replace(" ", ""))
    if not m:
        return None
    num = float(m.group().replace(",", ""))
    if negative:
        num = -abs(num)
    return int(round(num))


def parse_date(value, default_year: Optional[int] = None) -> Optional[str]:
    """다양한 형식의 날짜 → 'YYYY-MM-DD'. 실패 시 None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"\([월화수목금토일]\)", "", s).strip()   # '2026-08-01(토)'
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            dt = dt.replace(year=default_year or datetime.now().year)
        return dt.strftime("%Y-%m-%d")
    # 'YYYY년 M월 D일'
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def mask_account(value: str) -> str:
    """계좌/카드번호 마스킹 — 저장 전에 반드시 통과시킨다."""
    s = clean_text(value)
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return f"{s[:2]}***{digits[-4:]}"
    return s
