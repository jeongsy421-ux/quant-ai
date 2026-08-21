"""
==============================================
PERSONAL FINANCE - 도메인 모델
==============================================
금액은 모두 '원' 단위 정수로 다룬다. (부동소수 오차 방지)
부호 규칙: 입금/수입 = +, 출금/지출 = -
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Optional

# ─────────────────────────────────────────
# 카테고리 정의
# ─────────────────────────────────────────
# need   : 필수 지출 (줄이기 어려움)
# want   : 재량 지출 (조절 가능)
# save   : 저축/투자 (지출이 아님)
# income : 수입
NEED, WANT, SAVE, INCOME = "need", "want", "save", "income"

CATEGORY_KIND = {
    "주거/관리비": NEED,
    "통신": NEED,
    "보험": NEED,
    "대출상환": NEED,
    "세금/공과금": NEED,
    "의료/건강": NEED,
    "교통": NEED,
    "식비": NEED,
    "생필품": NEED,
    "교육": NEED,
    "육아": NEED,
    "카페/간식": WANT,
    "외식/배달": WANT,
    "쇼핑": WANT,
    "문화/여가": WANT,
    "여행": WANT,
    "구독서비스": WANT,
    "미용": WANT,
    "술/유흥": WANT,
    "경조사": WANT,
    "기타지출": WANT,
    "저축": SAVE,
    "투자": SAVE,
    "연금": SAVE,
    "급여": INCOME,
    "사업/부수입": INCOME,
    "금융수익": INCOME,
    "환급/기타수입": INCOME,
    "이체": "transfer",  # 내 계좌 간 이동 → 집계에서 제외
}

ALL_CATEGORIES = list(CATEGORY_KIND.keys())
UNCATEGORIZED = "미분류"


def kind_of(category: str) -> str:
    """카테고리 → 성격(need/want/save/income/transfer)"""
    return CATEGORY_KIND.get(category, WANT)


_SPACE_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"[*]{2,}|\(주\)|주식회사|\[.*?\]")


def normalize_desc(text: str) -> str:
    """가맹점명 정규화 — 지점번호/공백/노이즈 제거로 동일 가맹점을 묶는다."""
    if not text:
        return ""
    s = _NOISE_RE.sub(" ", str(text))
    s = re.sub(r"\d{2,}", " ", s)          # 지점코드/일련번호 제거
    s = _SPACE_RE.sub(" ", s).strip()
    return s


@dataclass
class Transaction:
    """정규화된 단일 거래"""
    txn_date: str                       # YYYY-MM-DD
    amount: int                         # +입금 / -출금 (원)
    description: str                    # 원본 적요/가맹점명
    institution: str = ""               # 국민은행, 신한카드 ...
    account: str = ""                   # 계좌/카드 식별자 (마스킹 권장)
    source: str = "manual"              # csv | email | sms | openbanking | manual
    category: str = UNCATEGORIZED
    balance: Optional[int] = None       # 거래 후 잔액 (있으면)
    memo: str = ""
    installment: int = 0                # 할부 개월 (0 = 일시불)
    raw: dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    # ── 파생 속성 ──
    @property
    def norm_desc(self) -> str:
        return normalize_desc(self.description)

    @property
    def month(self) -> str:
        return self.txn_date[:7]

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    @property
    def abs_amount(self) -> int:
        return abs(self.amount)

    def fingerprint(self) -> str:
        """중복 임포트 방지용 지문. 같은 거래가 여러 경로로 들어와도 1건으로."""
        key = f"{self.txn_date}|{self.amount}|{self.institution}|{self.norm_desc}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("id", None)
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        d["fingerprint"] = self.fingerprint()
        d["norm_desc"] = self.norm_desc
        return d

    @classmethod
    def from_row(cls, row: Any) -> "Transaction":
        raw = row["raw"]
        return cls(
            id=row["id"],
            txn_date=row["txn_date"],
            amount=row["amount"],
            description=row["description"],
            institution=row["institution"],
            account=row["account"],
            source=row["source"],
            category=row["category"],
            balance=row["balance"],
            memo=row["memo"],
            installment=row["installment"],
            raw=json.loads(raw) if raw else {},
        )


@dataclass
class Profile:
    """컨설팅에 필요한 사용자 정보"""
    name: str = "사용자"
    birth_year: int = 1990
    monthly_income: int = 0             # 세후 월 실수령 (0이면 거래내역에서 추정)
    dependents: int = 0
    risk_level: str = "중립형"           # 안정형/안정추구형/중립형/적극투자형/공격투자형
    emergency_fund: int = 0             # 현재 비상금 잔액
    debts: list[dict[str, Any]] = field(default_factory=list)
    # 예: [{"name":"신용대출","balance":10000000,"rate":6.5,"monthly":300000}]
    goals: list[dict[str, Any]] = field(default_factory=list)
    # 예: [{"name":"전세보증금","target":50000000,"deadline":"2029-03"}]
    pension_contrib_ytd: int = 0        # 올해 연금저축 납입액
    irp_contrib_ytd: int = 0            # 올해 IRP 납입액
    isa_contrib_ytd: int = 0            # 올해 ISA 납입액
    holdings: list[dict[str, Any]] = field(default_factory=list)
    # 예: [{"ticker":"379800","name":"KODEX 미국S&P500TR","value":3000000,"asset":"주식"}]

    @property
    def age(self) -> int:
        return max(0, datetime.now().year - self.birth_year)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)
