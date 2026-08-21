"""
==============================================
PERSONAL FINANCE - 은행/카드 내역 파일 임포터
==============================================
은행 앱·홈페이지에서 내려받은 거래내역 CSV/XLS(엑셀)를 자동으로 읽어들인다.
- 기관마다 컬럼명이 다르므로 '별칭 사전'으로 헤더를 자동 감지한다.
- 헤더 앞에 안내문/조회조건 같은 머리글이 여러 줄 있어도 찾아낸다.
- 인코딩(cp949/utf-8-sig/utf-16)과 구분자(,/tab)도 자동 판별한다.
- 은행식(출금액/입금액 분리)과 카드식(이용금액 단일)을 모두 지원한다.

지원 확인 양식: KB국민, 신한, 우리, 하나, NH농협, IBK기업, 카카오뱅크, 토스뱅크,
케이뱅크 / 신한·삼성·현대·KB국민·롯데·하나·BC·NH카드, 토스·카카오페이 내역.
(별칭 사전에 없는 컬럼명이 나오면 COLUMN_ALIASES에 추가하면 즉시 지원된다.)
"""
from __future__ import annotations

import csv
import io
import os
import re
from typing import Any, Iterable, Optional

from ..models import Transaction
from .base import clean_text, mask_account, parse_amount, parse_date

# ─────────────────────────────────────────
# 컬럼 별칭 사전
# ─────────────────────────────────────────
COLUMN_ALIASES: dict[str, list[str]] = {
    "date": [
        "거래일자", "거래일시", "거래일", "거래날짜", "승인일자", "승인일시", "이용일자",
        "이용일", "매출일자", "사용일자", "결제일자", "날짜", "일자", "transaction date",
        "date", "거래 일자", "이용하신날짜",
    ],
    "desc": [
        "적요", "내용", "거래내용", "가맹점명", "이용가맹점", "가맹점", "이용내역",
        "상호", "거래처", "받는분", "보내는분", "메모", "비고", "내역", "description",
        "merchant", "content", "거래기록사항", "이용하신곳",
    ],
    "amount": [
        "거래금액", "금액", "승인금액", "이용금액", "결제금액", "사용금액", "매출금액",
        "amount", "청구금액", "합계금액",
    ],
    "withdraw": [
        "출금액", "출금", "출금금액", "찾으신금액", "지급금액", "지급액", "차변",
        "withdrawal", "출금(원)",
    ],
    "deposit": [
        "입금액", "입금", "입금금액", "맡기신금액", "예입금액", "대변", "deposit",
        "입금(원)",
    ],
    "balance": ["잔액", "거래후잔액", "잔고", "남은잔액", "balance", "거래후 잔액"],
    "installment": ["할부", "할부개월", "할부기간", "할부개월수"],
    "account": ["계좌번호", "카드번호", "출금계좌", "계좌", "card no", "account"],
    "type": ["거래구분", "구분", "이용구분", "승인구분", "입출금구분", "취소여부", "거래유형"],
}

# 취소/승인취소 거래 판별
_CANCEL_RE = re.compile(r"(취소|반품|환불|CANCEL)", re.I)

ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-16", "utf-8")

# 파일명에서 기관 추정
_INSTITUTION_HINTS = [
    ("국민은행", ["kb국민은행", "국민은행", "kbbank"]),
    ("신한은행", ["신한은행", "shinhanbank"]),
    ("우리은행", ["우리은행", "wooribank"]),
    ("하나은행", ["하나은행", "hanabank"]),
    ("농협은행", ["농협", "nh은행", "nonghyup"]),
    ("기업은행", ["기업은행", "ibk"]),
    ("카카오뱅크", ["카카오뱅크", "kakaobank"]),
    ("토스뱅크", ["토스뱅크", "tossbank"]),
    ("케이뱅크", ["케이뱅크", "kbank"]),
    ("신한카드", ["신한카드", "shinhancard"]),
    ("삼성카드", ["삼성카드", "samsungcard"]),
    ("현대카드", ["현대카드", "hyundaicard"]),
    ("국민카드", ["kb국민카드", "국민카드", "kbcard"]),
    ("롯데카드", ["롯데카드", "lottecard"]),
    ("하나카드", ["하나카드", "hanacard"]),
    ("BC카드", ["bc카드", "bccard"]),
    ("NH카드", ["nh카드", "농협카드"]),
    ("우리카드", ["우리카드", "wooricard"]),
    ("토스", ["toss", "토스"]),
    ("카카오페이", ["카카오페이", "kakaopay"]),
]


def guess_institution(filename: str, preamble: str = "") -> str:
    """파일명/머리글에서 금융기관명을 추정"""
    hay = f"{os.path.basename(filename)} {preamble}".lower().replace(" ", "")
    for name, keys in _INSTITUTION_HINTS:
        if any(k in hay for k in keys):
            return name
    return "기타"


def _norm_header(h: str) -> str:
    return re.sub(r"[\s_\-()]", "", clean_text(h)).lower()


def _match_column(header: str) -> Optional[str]:
    """헤더 문자열 → 표준 필드명"""
    h = _norm_header(header)
    if not h:
        return None
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            a = _norm_header(alias)
            if h == a:
                return field
    # 완전일치 실패 시 부분일치 (긴 별칭 우선)
    for field, aliases in COLUMN_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            a = _norm_header(alias)
            if len(a) >= 2 and a in h:
                return field
    return None


def _read_text(path: str) -> str:
    """인코딩 자동 판별하여 텍스트로 읽기"""
    with open(path, "rb") as f:
        blob = f.read()
    for enc in ENCODINGS:
        try:
            text = blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # 한글이 깨졌는지 간이 검증
        if "�" not in text:
            return text
    return blob.decode("utf-8", errors="replace")


def _sniff_rows(text: str) -> list[list[str]]:
    sample = "\n".join(text.splitlines()[:50])
    delim = ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        if sample.count("\t") > sample.count(","):
            delim = "\t"
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _find_header(rows: list[list[str]]) -> tuple[int, dict[int, str]]:
    """헤더 행 위치와 {열 인덱스: 표준필드} 매핑을 찾는다."""
    best_idx, best_map, best_score = -1, {}, 0
    for i, row in enumerate(rows[:30]):
        mapping: dict[int, str] = {}
        for j, cell in enumerate(row):
            field = _match_column(cell)
            if field and field not in mapping.values():
                mapping[j] = field
        has_date = "date" in mapping.values()
        has_money = bool({"amount", "withdraw", "deposit"} & set(mapping.values()))
        score = len(mapping) + (3 if has_date else 0) + (3 if has_money else 0)
        if has_date and has_money and score > best_score:
            best_idx, best_map, best_score = i, mapping, score
    return best_idx, best_map


def parse_file(
    path: str,
    institution: Optional[str] = None,
    account: str = "",
    default_expense: bool = True,
) -> list[Transaction]:
    """
    거래내역 파일 1개 → Transaction 리스트

    default_expense: 금액 컬럼이 하나뿐이고 부호가 없는 카드 내역일 때
                     양수를 '지출'로 해석할지 여부 (카드 내역 = True)
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        rows = _read_excel(path)
        text_preamble = " ".join(" ".join(r) for r in rows[:5])
    else:
        text = _read_text(path)
        rows = _sniff_rows(text)
        text_preamble = "\n".join(text.splitlines()[:5])

    header_idx, colmap = _find_header(rows)
    if header_idx < 0:
        raise ValueError(
            f"거래내역 헤더를 찾지 못했습니다: {os.path.basename(path)}\n"
            f"  → backend/finance/ingest/csv_importer.py 의 COLUMN_ALIASES 에 "
            f"해당 기관 컬럼명을 추가하세요."
        )

    inst = institution or guess_institution(path, text_preamble)
    is_card = "카드" in inst or "페이" in inst
    txns: list[Transaction] = []

    for row in rows[header_idx + 1:]:
        if not any(clean_text(c) for c in row):
            continue
        rec: dict[str, Any] = {}
        for j, field in colmap.items():
            if j < len(row):
                rec[field] = row[j]

        txn_date = parse_date(rec.get("date"))
        if not txn_date:
            continue

        amount = _resolve_amount(rec, is_card=is_card, default_expense=default_expense)
        if amount is None or amount == 0:
            continue

        desc = clean_text(rec.get("desc") or rec.get("type") or "")
        if not desc:
            desc = f"{inst} 거래"

        txns.append(
            Transaction(
                txn_date=txn_date,
                amount=amount,
                description=desc,
                institution=inst,
                account=mask_account(rec.get("account", "") or account),
                source="csv",
                balance=parse_amount(rec.get("balance")),
                installment=_parse_installment(rec.get("installment")),
                raw={k: clean_text(v) for k, v in rec.items()},
            )
        )
    return txns


def _resolve_amount(rec: dict[str, Any], is_card: bool, default_expense: bool) -> Optional[int]:
    """출금/입금 분리형과 단일 금액형을 모두 부호 규칙(+입금/-출금)으로 변환"""
    w = parse_amount(rec.get("withdraw")) or 0
    d = parse_amount(rec.get("deposit")) or 0
    if w or d:
        return d - abs(w)

    amt = parse_amount(rec.get("amount"))
    if amt is None:
        return None

    kind = clean_text(rec.get("type", ""))
    cancelled = bool(_CANCEL_RE.search(kind)) or bool(_CANCEL_RE.search(clean_text(rec.get("desc", ""))))

    if amt < 0:                      # 이미 부호가 있는 양식
        return -amt if cancelled else amt
    if cancelled:                    # 취소/환불 → 입금
        return abs(amt)
    if "입금" in kind or "예입" in kind:
        return abs(amt)
    if "출금" in kind or "지급" in kind or "결제" in kind or "승인" in kind:
        return -abs(amt)
    if is_card or default_expense:   # 카드 내역은 기본이 지출
        return -abs(amt)
    return amt


def _parse_installment(value) -> int:
    s = clean_text(value)
    if not s or "일시불" in s:
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


def _read_excel(path: str) -> list[list[str]]:
    """
    엑셀 파일 읽기.
    openpyxl이 있으면 .xlsx를 직접 읽고, 없으면 CSV로 변환 후 사용하도록 안내한다.
    (구형 .xls는 표준 라이브러리로 읽을 수 없어 CSV 변환이 필요하다.)
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        try:
            from openpyxl import load_workbook  # type: ignore
        except ImportError as e:
            raise ImportError(
                "xlsx를 읽으려면 openpyxl이 필요합니다: pip install openpyxl\n"
                "또는 엑셀에서 'CSV(쉼표로 분리)'로 저장한 뒤 임포트하세요."
            ) from e
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = [
            ["" if c is None else str(c) for c in row]
            for row in ws.iter_rows(values_only=True)
        ]
        wb.close()
        return rows
    raise ValueError(
        f"'{ext}' 형식은 직접 읽을 수 없습니다. 엑셀에서 CSV 또는 xlsx로 저장 후 임포트하세요."
    )


def import_paths(db, paths: Iterable[str], institution: Optional[str] = None) -> dict[str, Any]:
    """여러 파일을 읽어 DB에 저장하고 결과 요약을 반환"""
    from ..categorizer import Categorizer

    cz = Categorizer(db.user_rules())
    total_new = total_dup = 0
    details: list[dict[str, Any]] = []

    for path in paths:
        try:
            txns = parse_file(path, institution=institution)
        except Exception as e:                       # 한 파일 실패가 전체를 막지 않도록
            details.append({"file": os.path.basename(path), "error": str(e)})
            continue
        cz.classify_all(txns)
        new, dup = db.add_transactions(txns)
        db.log_import("csv", os.path.basename(path), new, dup)
        total_new += new
        total_dup += dup
        details.append(
            {"file": os.path.basename(path), "parsed": len(txns), "new": new, "duplicated": dup}
        )

    return {"inserted": total_new, "duplicated": total_dup, "files": details}
