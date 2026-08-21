"""
==============================================
PERSONAL FINANCE - 데모 데이터 생성기
==============================================
실제 내역을 넣기 전에 리포트가 어떤 모습인지 확인하기 위한 샘플 6개월치 생성.
  python -m backend.finance.cli demo
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .analyzer import month_bounds, month_range
from .categorizer import Categorizer
from .models import Profile, Transaction

SALARY = 3_600_000

FIXED = [   # (가맹점, 금액, 결제일)
    ("행복아파트 관리비", 180_000, 25),
    ("SKT 통신요금", 62_000, 17),
    ("현대해상 실손보험", 48_000, 5),
    ("NETFLIX.COM", 17_000, 12),
    ("유튜브 프리미엄", 14_900, 8),
    ("MELON 멜론", 10_900, 14),
    ("클라이밍짐 정기권", 99_000, 3),
    ("OPENAI CHATGPT", 29_000, 20),
]

VARIABLE = [   # (가맹점, 최소, 최대, 월 평균 횟수)
    ("스타벅스 강남점", 4_500, 7_500, 12),
    ("메가커피", 2_000, 4_500, 8),
    ("배달의민족", 14_000, 32_000, 9),
    ("쿠팡이츠", 12_000, 28_000, 4),
    ("GS25 역삼점", 2_500, 12_000, 14),
    ("이마트 성수점", 25_000, 90_000, 3),
    ("쿠팡", 15_000, 120_000, 6),
    ("올리브영", 12_000, 45_000, 2),
    ("카카오T 택시", 6_000, 18_000, 6),
    ("티머니 교통카드 충전", 30_000, 50_000, 2),
    ("CGV 강남", 14_000, 30_000, 1),
    ("김밥천국", 6_000, 11_000, 5),
    ("이자카야 하루", 30_000, 70_000, 2),
    ("무신사", 30_000, 150_000, 1),
]


def generate(db, months: int = 6, seed: int = 42) -> int:
    rnd = random.Random(seed)
    txns: list[Transaction] = []

    for m in month_range(months):
        start, end = month_bounds(m)
        last_day = int(end[8:10])

        # 급여
        txns.append(Transaction(
            txn_date=f"{m}-{min(25, last_day):02d}",
            amount=SALARY + rnd.randint(-50_000, 250_000),
            description="(주)카카오 급여",
            institution="신한은행", account="신***8901", source="csv",
        ))
        # 카드대금 이체 (지출 이중계상 방지를 위해 '이체'로 분류됨)
        txns.append(Transaction(
            txn_date=f"{m}-{min(14, last_day):02d}", amount=-rnd.randint(700_000, 1_100_000),
            description="신한카드 카드대금", institution="신한은행", source="csv",
        ))
        # 적금·투자 자동이체
        txns.append(Transaction(
            txn_date=f"{m}-26", amount=-300_000, description="주택청약종합저축",
            institution="신한은행", source="csv",
        ))
        txns.append(Transaction(
            txn_date=f"{m}-26", amount=-200_000, description="미래에셋증권 연금저축펀드",
            institution="신한은행", source="csv",
        ))

        # 고정비
        for name, amount, day in FIXED:
            txns.append(Transaction(
                txn_date=f"{m}-{min(day, last_day):02d}",
                amount=-amount, description=name,
                institution="신한카드", source="notification",
            ))

        # 변동비
        for name, lo, hi, cnt in VARIABLE:
            n = max(0, int(rnd.gauss(cnt, cnt * 0.3)))
            for _ in range(n):
                txns.append(Transaction(
                    txn_date=f"{m}-{rnd.randint(1, last_day):02d}",
                    amount=-rnd.randrange(lo, hi, 100),
                    description=name, institution="신한카드", source="notification",
                ))

        # 가끔 큰 지출
        if rnd.random() < 0.4:
            txns.append(Transaction(
                txn_date=f"{m}-{rnd.randint(1, last_day):02d}",
                amount=-rnd.randrange(300_000, 900_000, 1000),
                description=rnd.choice(["제주항공 항공권", "삼성전자 노트북", "치과의원 임플란트", "결혼 축의금"]),
                institution="신한카드", source="notification",
            ))

    Categorizer(db.user_rules()).classify_all(txns)
    new, _ = db.add_transactions(txns)

    db.save_profile(Profile(
        name="홍길동", birth_year=1992, monthly_income=SALARY, dependents=0,
        risk_level="중립형", emergency_fund=4_200_000,
        debts=[{"name": "신용대출", "balance": 12_000_000, "rate": 6.8, "monthly": 350_000}],
        goals=[
            {"name": "전세보증금", "target": 80_000_000, "deadline": "2032-03"},
            {"name": "비상금 6개월", "target": 12_000_000, "deadline": "2027-12"},
        ],
        pension_contrib_ytd=1_600_000, irp_contrib_ytd=0, isa_contrib_ytd=2_400_000,
        holdings=[
            {"ticker": "379800", "name": "KODEX 미국S&P500TR", "value": 5_200_000, "asset": "선진국주식"},
            {"ticker": "069500", "name": "KODEX 200", "value": 1_100_000, "asset": "국내주식"},
            {"ticker": "-", "name": "파킹통장", "value": 4_200_000, "asset": "현금성"},
        ],
    ))
    return new
