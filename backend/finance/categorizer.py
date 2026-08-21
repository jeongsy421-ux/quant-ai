"""
==============================================
PERSONAL FINANCE - 자동 카테고리 분류기
==============================================
1) 사용자 학습 규칙 (DB) — 최우선
2) 내장 키워드 사전 (국내 가맹점/은행 적요 기준)
3) 금액/부호 휴리스틱 (급여, 이체, 카드대금 등)
분류가 틀리면 set_category()로 고치는 순간 규칙으로 학습되어 다음부터 자동 적용된다.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .models import Transaction, UNCATEGORIZED, normalize_desc

# ─────────────────────────────────────────
# 내장 키워드 사전 (카테고리 → 키워드들)
# ─────────────────────────────────────────
KEYWORDS: dict[str, list[str]] = {
    "식비": [
        "김밥", "백반", "국밥", "food", "푸드", "정식", "분식", "칼국수", "냉면",
        "食", "restaurant", "구내식당", "한솥", "본죽", "김치찌개",
    ],
    "외식/배달": [
        "배달의민족", "배민", "요기요", "쿠팡이츠", "땡겨요", "맥도날드", "버거킹",
        "롯데리아", "KFC", "맘스터치", "도미노", "피자헛", "미스터피자", "BBQ",
        "BHC", "교촌", "굽네", "네네치킨", "노브랜드버거", "써브웨이", "아웃백",
        "빕스", "애슐리", "삼겹", "곱창", "포차", "요기요",
    ],
    "카페/간식": [
        "스타벅스", "STARBUCKS", "투썸", "이디야", "메가커피", "메가엠지씨",
        "컴포즈", "빽다방", "커피", "COFFEE", "폴바셋", "할리스", "탐앤탐스",
        "공차", "배스킨", "설빙", "파리바게뜨", "뚜레쥬르", "던킨",
    ],
    "생필품": [
        "GS25", "CU ", "씨유", "세븐일레븐", "이마트24", "emart24", "미니스톱",
        "이마트", "홈플러스", "롯데마트", "코스트코", "COSTCO", "다이소",
        "마켓컬리", "컬리", "오아시스", "SSG", "노브랜드", "하나로마트",
    ],
    "쇼핑": [
        "쿠팡", "COUPANG", "네이버페이", "11번가", "지마켓", "G마켓", "옥션",
        "무신사", "29CM", "지그재그", "에이블리", "알리익스프레스", "ALIEXPRESS",
        "테무", "TEMU", "올리브영", "유니클로", "ZARA", "H&M", "백화점", "아울렛",
        "인터파크", "위메프", "티몬", "AMAZON", "노트북", "가전", "전자제품",
        "애플스토어", "APPLE STORE", "삼성전자판매", "하이마트", "전자랜드", "LG전자",
        "다나와", "이케아", "IKEA", "한샘",
    ],
    "교통": [
        "티머니", "TMONEY", "이동의즐거움", "카카오택시", "카카오T", "KAKAO T",
        "우티", "UT ", "타다", "코레일", "KORAIL", "SRT", "고속버스", "지하철",
        "버스", "주유", "SK에너지", "GS칼텍스", "S-OIL", "현대오일", "알뜰주유",
        "하이패스", "한국도로공사", "주차", "PARKING", "쏘카", "그린카", "따릉이",
    ],
    "주거/관리비": [
        "관리비", "월세", "임대료", "전기요금", "한국전력", "한전", "도시가스",
        "수도요금", "상수도", "정수기", "청소", "아파트",
    ],
    "통신": [
        "SKT", "SK텔레콤", "KT ", "케이티", "LGU", "LG유플러스", "유플러스",
        "알뜰폰", "통신요금", "인터넷요금", "헬로모바일", "KT엠모바일",
    ],
    "구독서비스": [
        "NETFLIX", "넷플릭스", "유튜브", "YOUTUBE", "SPOTIFY", "스포티파이",
        "멜론", "MELON", "지니뮤직", "왓챠", "WATCHA", "티빙", "TVING", "웨이브",
        "쿠팡플레이", "디즈니", "DISNEY", "APPLE.COM", "GOOGLE", "구글",
        "MICROSOFT", "OPENAI", "CHATGPT", "ANTHROPIC", "CLAUDE", "NOTION",
        "ADOBE", "ICLOUD", "밀리의서재", "리디",
    ],
    "문화/여가": [
        "CGV", "메가박스", "롯데시네마", "예스24", "YES24", "교보문고", "알라딘",
        "인터파크티켓", "공연", "전시", "PC방", "스팀", "STEAM", "닌텐도",
        "PLAYSTATION", "볼링", "당구", "노래방", "헬스", "피트니스", "FITNESS",
        "클라이밍", "필라테스", "요가", "수영장", "GYM", "짐 ", "스크린골프", "골프",
    ],
    "여행": [
        "항공", "AIR", "대한항공", "아시아나", "제주항공", "티웨이", "진에어",
        "야놀자", "여기어때", "호텔", "HOTEL", "에어비앤비", "AIRBNB", "AGODA",
        "아고다", "부킹", "BOOKING", "하나투어", "모두투어", "리조트", "펜션",
    ],
    "의료/건강": [
        "의원", "병원", "치과", "한의원", "약국", "PHARM", "메디", "клиник",
        "건강검진", "안과", "피부과", "정형외과", "내과", "산부인과", "동물병원",
    ],
    "미용": [
        "미용실", "헤어", "HAIR", "네일", "왁싱", "에스테틱", "스파", "마사지",
        "이발", "바버",
    ],
    "술/유흥": ["호프", "이자카야", "와인", "위스키", "BAR ", "펍", "PUB", "주점", "맥주"],
    "교육": [
        "학원", "인강", "클래스101", "패스트캠퍼스", "인프런", "유데미", "UDEMY",
        "등록금", "교습", "과외", "도서구입", "EBS",
    ],
    "육아": ["어린이집", "유치원", "키즈", "육아", "아기", "베베", "맘스"],
    "보험": [
        "생명", "화재", "손해보험", "보험료", "삼성생명", "한화생명", "교보생명",
        "현대해상", "DB손해", "메리츠화재", "KB손해", "실손", "국민건강보험",
    ],
    "세금/공과금": [
        "국세", "지방세", "세금", "재산세", "자동차세", "취득세", "주민세",
        "국민연금", "건강보험", "고용보험", "위택스", "홈택스", "과태료", "범칙금",
    ],
    "대출상환": [
        "대출이자", "대출원금", "원리금", "상환", "이자납입", "주택담보", "전세자금",
        "마이너스통장", "카드론", "현금서비스",
    ],
    "경조사": ["축의금", "부의금", "조의", "결혼", "장례", "화환"],
    "저축": [
        "적금", "예금", "정기적금", "청약", "주택청약", "저축은행예치", "CMA",
    ],
    "투자": [
        "증권", "미래에셋", "삼성증권", "한국투자", "NH투자", "키움", "KB증권",
        "신한투자", "토스증권", "대신증권", "하나증권", "유안타", "이베스트",
        "업비트", "빗썸", "코인원", "코빗",
    ],
    "연금": ["연금저축", "IRP", "퇴직연금", "개인형퇴직"],
    "급여": ["급여", "월급", "상여", "성과급", "임금", "PAYROLL", "SALARY"],
    "사업/부수입": ["정산", "수수료입금", "매출", "사업소득", "용역료", "원고료", "강의료"],
    "금융수익": ["이자", "배당", "INTEREST", "DIVIDEND", "예금이자"],
    "환급/기타수입": ["환급", "환불", "캐시백", "지원금", "보험금", "포인트"],
    "이체": [
        "카드대금", "카드결제", "자동이체출금", "타행이체", "내계좌", "본인이체",
        "체크카드결제", "일시불", "TOSS", "토스", "카카오페이충전",
    ],
}

# 카드사/은행명 (기관 컬럼에만 쓰이고 가맹점 분류에는 방해가 되는 토큰)
_ISSUER_TOKENS = re.compile(
    r"(국민|신한|삼성|현대|롯데|하나|우리|BC|NH|농협|기업|카카오뱅크|케이뱅크|토스뱅크)?"
    r"(카드|은행)?", re.I
)

# 급여로 볼 만한 최소 입금액 (원)
SALARY_MIN = 500_000


class Categorizer:
    """키워드 + 학습 규칙 기반 분류기"""

    def __init__(self, user_rules: Optional[list[tuple[str, str]]] = None):
        # 사용자 규칙: 긴 패턴부터 매칭 (더 구체적인 것 우선)
        self.user_rules = sorted(user_rules or [], key=lambda x: -len(x[0]))
        self._kw = [
            (kw.upper().strip(), cat)
            for cat, kws in KEYWORDS.items()
            for kw in kws
        ]
        # 긴 키워드 우선 (예: "카카오T" 보다 "카카오페이충전")
        self._kw.sort(key=lambda x: -len(x[0]))

    # ── 단건 분류 ──
    def classify(self, txn: Transaction) -> str:
        desc = txn.description or ""
        norm = normalize_desc(desc)
        hay = f"{desc} {norm} {txn.memo}".upper()

        # 1) 사용자 학습 규칙 최우선
        for pattern, cat in self.user_rules:
            if pattern and pattern.upper() in hay:
                return cat

        # 2) 내장 키워드
        for kw, cat in self._kw:
            if kw and kw in hay:
                # 수입 카테고리는 입금 거래에만, 지출 카테고리는 출금 거래에만 적용
                if cat in ("급여", "사업/부수입", "금융수익", "환급/기타수입"):
                    if txn.amount > 0:
                        return cat
                    continue
                if txn.amount > 0 and cat not in ("이체", "저축", "투자", "연금"):
                    continue
                return cat

        # 3) 휴리스틱
        if txn.amount >= SALARY_MIN and re.search(r"(주식회사|㈜|법인|\(주\))", desc):
            return "급여"
        if txn.amount > 0:
            return "환급/기타수입"
        return UNCATEGORIZED

    # ── 일괄 분류 ──
    def classify_all(self, txns: Iterable[Transaction]) -> list[Transaction]:
        for t in txns:
            if t.category in (UNCATEGORIZED, "", None):
                t.category = self.classify(t)
        return list(txns)


def recategorize_db(db, only_uncategorized: bool = True) -> dict[str, int]:
    """DB에 저장된 거래를 최신 규칙으로 다시 분류. 반환: 카테고리별 변경 건수"""
    cz = Categorizer(db.user_rules())
    targets = db.uncategorized(limit=100000) if only_uncategorized else db.query(
        include_transfer=True, limit=100000
    )
    updates: dict[int, str] = {}
    stats: dict[str, int] = {}
    for t in targets:
        new = cz.classify(t)
        if new != t.category and new != UNCATEGORIZED:
            updates[t.id] = new
            stats[new] = stats.get(new, 0) + 1
    if updates:
        db.update_categories(updates)
    return stats
