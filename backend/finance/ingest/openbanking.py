"""
==============================================
PERSONAL FINANCE - 오픈뱅킹 / 마이데이터 어댑터
==============================================
금융결제원 오픈뱅킹 API로 계좌 거래내역을 직접 조회하는 어댑터.

⚠ 전제 조건
  오픈뱅킹·마이데이터 API는 '이용기관'으로 등록된 사업자만 발급받을 수 있다.
  (개인 개발자는 오픈뱅킹 테스트베드에서 샌드박스 키를 받아 실험할 수 있다:
   https://developers.nonghyup.com / https://www.open-platform.or.kr)
  자격이 없다면 email_collector(카드 알림 메일) + csv_importer(내역 파일)로 충분하다.

⛔ 하지 않는 것
  은행/카드사 홈페이지에 사용자 ID·비밀번호나 공동인증서로 로그인해 화면을 긁어오는
  방식(스크래핑)은 대부분 약관 위반이며 계정 잠금·법적 분쟁 위험이 있어 구현하지 않는다.

.env 설정
  OPENBANKING_BASE=https://testapi.openbanking.or.kr
  OPENBANKING_CLIENT_ID=...
  OPENBANKING_CLIENT_SECRET=...
  OPENBANKING_ACCESS_TOKEN=...      # 사용자 동의 후 발급된 토큰
  OPENBANKING_USER_SEQ_NO=...
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional

from ..models import Transaction
from .base import clean_text, mask_account, parse_amount, parse_date


class OpenBankingClient:
    """오픈뱅킹 REST 호출 래퍼 (표준 라이브러리 urllib 사용)"""

    def __init__(
        self,
        base: Optional[str] = None,
        access_token: Optional[str] = None,
        user_seq_no: Optional[str] = None,
        timeout: int = 15,
    ):
        self.base = (base or os.getenv("OPENBANKING_BASE", "https://testapi.openbanking.or.kr")).rstrip("/")
        self.access_token = access_token or os.getenv("OPENBANKING_ACCESS_TOKEN", "")
        self.user_seq_no = user_seq_no or os.getenv("OPENBANKING_USER_SEQ_NO", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.user_seq_no)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError(
                "오픈뱅킹 토큰이 없습니다. 이용기관 등록 후 .env 에 "
                "OPENBANKING_ACCESS_TOKEN / OPENBANKING_USER_SEQ_NO 를 설정하세요."
            )
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.access_token}"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _tran_id(self) -> str:
        """오픈뱅킹 거래고유번호(이용기관코드 + U + 9자리 일련번호)"""
        org = os.getenv("OPENBANKING_ORG_CODE", "M202100000")
        seq = datetime.now().strftime("%H%M%S%f")[:9]
        return f"{org}U{seq}"

    # ── 계좌 목록 ──
    def accounts(self) -> list[dict[str, Any]]:
        data = self._get(
            "/v2.0/user/me",
            {"user_seq_no": self.user_seq_no},
        )
        return data.get("res_list", [])

    # ── 거래내역 ──
    def transactions(
        self,
        fintech_use_num: str,
        from_date: str,
        to_date: str,
        account_alias: str = "",
    ) -> list[Transaction]:
        data = self._get(
            "/v2.0/account/transaction_list/fin_num",
            {
                "bank_tran_id": self._tran_id(),
                "fintech_use_num": fintech_use_num,
                "inquiry_type": "A",              # A: 전체(입금+출금)
                "inquiry_base": "D",              # D: 일자 기준
                "from_date": from_date.replace("-", ""),
                "to_date": to_date.replace("-", ""),
                "sort_order": "D",
                "tran_dtime": datetime.now().strftime("%Y%m%d%H%M%S"),
            },
        )
        bank = clean_text(data.get("bank_name", "")) or account_alias or "오픈뱅킹"
        out: list[Transaction] = []
        for row in data.get("res_list", []):
            txn_date = parse_date(row.get("tran_date"))
            amount = parse_amount(row.get("tran_amt"))
            if not txn_date or amount is None:
                continue
            inout = clean_text(row.get("inout_type"))        # 입금 / 출금
            signed = abs(amount) if "입금" in inout else -abs(amount)
            out.append(
                Transaction(
                    txn_date=txn_date,
                    amount=signed,
                    description=clean_text(row.get("print_content") or row.get("branch_name")),
                    institution=bank,
                    account=mask_account(fintech_use_num),
                    source="openbanking",
                    balance=parse_amount(row.get("after_balance_amt")),
                    raw={k: clean_text(v) for k, v in row.items()},
                )
            )
        return out


def sync(db, days: int = 30, client: Optional[OpenBankingClient] = None) -> dict[str, Any]:
    """등록된 모든 계좌의 최근 N일 내역을 수집 → 분류 → 저장"""
    from ..categorizer import Categorizer

    cli = client or OpenBankingClient()
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    all_txns: list[Transaction] = []
    for acc in cli.accounts():
        fin_num = acc.get("fintech_use_num")
        if not fin_num:
            continue
        all_txns.extend(
            cli.transactions(fin_num, from_date, to_date, acc.get("account_alias", ""))
        )

    Categorizer(db.user_rules()).classify_all(all_txns)
    new, dup = db.add_transactions(all_txns)
    db.log_import("openbanking", f"{from_date}~{to_date}", new, dup)
    return {"fetched": len(all_txns), "inserted": new, "duplicated": dup}
