# 개인 금융 컨설팅 모듈

가계부 자동 수집 → 소비 분석 → 다음 달 소비 계획 → 저축·투자 배분(구체 종목까지)을
한 흐름으로 처리하는 모듈입니다. `backend/finance/` 에 있습니다.

표준 라이브러리만으로 동작합니다 (pandas·numpy 불필요). 웹 API를 쓸 때만 Flask가 필요하고,
엑셀(.xlsx) 임포트를 쓸 때만 openpyxl이 필요합니다.

---

## 1. 60초 체험

```bash
python -m backend.finance.cli demo          # 샘플 6개월치 생성
python -m backend.finance.cli report        # 컨설팅 리포트 출력
python -m backend.finance.cli report --html report.html
```

내 데이터로 시작할 준비가 되면 `backend/finance/data/finance.db` 를 지우고 아래 2번으로 갑니다.

---

## 2. 거래내역 자동 수집 — 4가지 경로

> **먼저 알아둘 것**
> 은행·카드사 홈페이지에 아이디/비밀번호나 공동인증서로 대신 로그인해 화면을 긁어오는
> **스크래핑은 이 모듈에 없습니다.** 대부분 이용약관 위반이고, 계정 잠금·이상거래 차단·
> 법적 분쟁의 위험이 있습니다. 대신 아래 4가지로 사실상 동일한 자동화를 얻습니다.

### (A) 카드 승인 알림 메일 자동 수집 — 가장 실용적

카드사 "이용내역 알림 메일"을 신청해두면, 내 메일함을 내가 읽는 방식이라 문제가 없습니다.

1. 카드사 앱/홈페이지 → 이용내역 알림 → **이메일 수신 신청**
2. Gmail 기준: Google 계정 → 2단계 인증 → **앱 비밀번호** 발급 (16자리)
3. `.env` 에 추가

```env
FINANCE_IMAP_HOST=imap.gmail.com
FINANCE_IMAP_USER=you@gmail.com
FINANCE_IMAP_PASSWORD=앱비밀번호16자리
FINANCE_IMAP_FOLDER=INBOX
FINANCE_IMAP_SENDERS=@shinhancard.com,@kbcard.com,@samsungcard.com
```

4. 실행

```bash
python -m backend.finance.cli sync-email --days 30
```

5. 자동화 (crontab — 매일 새벽 3시)

```cron
0 3 * * * cd /path/to/quant-ai && python -m backend.finance.cli sync-email --days 3 >> logs/finance.log 2>&1
```

메일함은 `readonly` 로 열기 때문에 읽음 표시가 바뀌지 않습니다.

### (B) 문자 알림 웹훅 — 실시간

안드로이드의 문자 자동전달 앱(SMS Forwarder, Tasker, MacroDroid 등)에서
카드 승인 문자를 서버로 POST하면 **결제 즉시** 가계부에 들어옵니다.

```env
FINANCE_WEBHOOK_TOKEN=충분히-긴-무작위-문자열
```

```bash
curl -X POST http://<서버>:5000/api/finance/webhook/sms \
  -H "X-Finance-Token: $FINANCE_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"[Web발신] 신한카드 승인 5,500원 08/21 13:22 스타벅스강남점"}'
```

토큰이 설정되지 않으면 이 엔드포인트는 **503으로 비활성화**됩니다. 외부에 노출한다면
반드시 HTTPS로 감싸세요.

### (C) 내역 파일 폴더 감시 — 은행 거래내역용

카드 알림 메일은 카드만 커버하므로, 계좌 입출금은 은행에서 내려받은 파일로 채웁니다.

```bash
# 1회 임포트
python -m backend.finance.cli import ~/Downloads/신한은행_거래내역_202608.csv

# 폴더에 넣기만 하면 자동 임포트 (처리 후 _imported/ 로 이동)
python -m backend.finance.cli watch --dir ~/Downloads/finance --interval 300
```

지원: CSV/TSV/TXT, xlsx(openpyxl 설치 시). cp949·utf-8·utf-16 자동 판별, 안내문 머리글 자동 스킵,
`출금액/입금액` 분리형과 `이용금액` 단일형 모두 지원.

**컬럼명이 달라 실패하면** `backend/finance/ingest/csv_importer.py` 의 `COLUMN_ALIASES`
에 그 기관의 컬럼명 한 줄만 추가하면 즉시 지원됩니다.

### (D) 오픈뱅킹 / 마이데이터 API — 자격이 있다면

`backend/finance/ingest/openbanking.py` 에 어댑터가 준비되어 있습니다.
오픈뱅킹은 **이용기관으로 등록된 사업자**만 운영 키를 받을 수 있고, 개인은
[오픈뱅킹 테스트베드](https://developers.openbanking.or.kr)에서 샌드박스 키로 실험할 수 있습니다.

```env
OPENBANKING_BASE=https://testapi.openbanking.or.kr
OPENBANKING_ACCESS_TOKEN=...
OPENBANKING_USER_SEQ_NO=...
OPENBANKING_ORG_CODE=...
```

```bash
python -m backend.finance.cli sync-openbanking --days 30
```

### 중복 걱정 없음

같은 거래가 문자·메일·CSV로 세 번 들어와도 `날짜+금액+기관+정규화된 가맹점명` 지문으로
1건만 저장됩니다. 같은 파일을 몇 번 임포트해도 안전합니다.

---

## 3. 자동 분류와 학습

거래는 내장 키워드 사전(국내 가맹점 300여 개)으로 자동 분류됩니다.
틀린 분류를 고치면 **그 순간 규칙으로 학습**되어 과거 거래까지 소급 적용되고,
다음부터 같은 가맹점은 자동으로 맞습니다.

```bash
python -m backend.finance.cli review     # 미분류 건을 번호로 찍어 정리
```

```bash
curl -X POST localhost:5000/api/finance/category \
  -H 'Content-Type: application/json' -d '{"id":123,"category":"식비"}'
```

카테고리는 성격별로 묶여 있습니다.

| 성격 | 카테고리 | 예산에서의 취급 |
|---|---|---|
| `need` 필수 | 주거/관리비, 통신, 보험, 대출상환, 교통, 식비, 의료 … | 최대 10%까지만 삭감 |
| `want` 재량 | 외식/배달, 카페/간식, 쇼핑, 여행, 구독서비스, 술/유흥 … | 우선 삭감 대상 |
| `save` 저축 | 저축, 투자, 연금 | 지출이 아님 — 집계에서 분리 |
| `income` 수입 | 급여, 사업/부수입, 금융수익 | |
| `transfer` | 이체 (카드대금·내 계좌 간 이동) | 이중계상 방지를 위해 제외 |

---

## 4. 프로필 입력

컨설팅 품질은 프로필 정확도에 비례합니다.

```bash
python -m backend.finance.cli profile --set \
  birth_year=1992 monthly_income=3600000 risk_level=중립형 \
  emergency_fund=4200000 dependents=0 \
  pension_contrib_ytd=1600000 isa_contrib_ytd=2400000

# 부채·목표·보유자산은 JSON으로
python -m backend.finance.cli profile --set \
  'debts=[{"name":"신용대출","balance":12000000,"rate":6.8,"monthly":350000}]' \
  'goals=[{"name":"전세보증금","target":80000000,"deadline":"2032-03"}]' \
  'holdings=[{"ticker":"379800","name":"KODEX 미국S&P500TR","value":5200000,"asset":"선진국주식"}]'
```

`risk_level`: 안정형 / 안정추구형 / 중립형 / 적극투자형 / 공격투자형

---

## 5. 분석 · 소비 계획 · 투자 배분

```bash
python -m backend.finance.cli report            # 전체 컨설팅 리포트
python -m backend.finance.cli budget --rate 30  # 저축률 30% 목표 소비 계획
python -m backend.finance.cli budget --rate 30 --save
python -m backend.finance.cli advise            # 저축·투자 우선순위 + 종목
python -m backend.finance.cli stats
```

리포트가 답하는 것:

1. **현금흐름 진단** — 월평균 수입/지출/저축률, 연령대 권장 저축률 대비 위치
2. **지출 구조** — 카테고리별 금액·비중, 필수/재량 구분, 무지출일수
3. **고정비·반복결제** — 매월 반복되는 결제를 자동 탐지, 연간 환산액
4. **주의 신호** — 평소 대비 급증한 카테고리(z-score), 소액 반복지출(새는 돈)
5. **다음 달 소비 계획** — 목표 저축률에서 역산한 카테고리별 예산
6. **이번 달 진행** — 예산 소진율과 현재 페이스 기준 월말 예상
7. **저축·투자 우선순위** — 비상금 → 고금리부채 → 연금/IRP → ISA → 일반계좌
8. **자산배분** — 위험성향·나이 기반 목표 비중과 현재 보유의 괴리
9. **매월 실행안** — 계좌별로 어떤 종목을 얼마씩 자동이체할지
10. **목표 시뮬레이션** — 현재 페이스로 목표 달성까지 걸리는 기간

### 예산이 만들어지는 방식

교과서적인 50/30/20을 그대로 강요하지 않습니다.
최근 3개월 **실제 지출의 중앙값**에서 출발해, 목표 저축액에 미달하는 만큼만
**재량 지출부터, 벤치마크 초과분 순으로** 깎습니다. 필수 지출은 최대 10%까지만
건드리고, 그래도 부족하면 재량 지출을 비례 축소합니다(최대 40%).
지킬 수 있는 숫자가 나오는 게 목적입니다.

### 투자 우선순위가 그 순서인 이유

| 순위 | 항목 | 근거 |
|---|---|---|
| 1 | 비상금 (필수생계비 3~6개월) | 없으면 하필 폭락장에서 투자자산을 판다 |
| 2 | 연 6% 초과 고금리 부채 | 이자 절감 = 세후 확정 수익 |
| 3 | 연금저축 + IRP (연 900만) | 납입액의 13.2~16.5% 즉시 환급 — 시장과 무관한 확정 수익 |
| 4 | ISA (연 2,000만) | 순이익 200만(서민형 400만) 비과세 + 초과분 9.9% 분리과세 |
| 5 | 일반 위탁계좌 | 유동성이 필요한 자금 |

세법 한도는 `backend/finance/advisor.py` 의 `TAX` 상수에 모아두었습니다. **매년 확인해서 갱신하세요.**

### 종목에 대하여

`INSTRUMENTS` 딕셔너리에 자산군별 ETF 후보가 정의되어 있고, 계좌별 세제 효율
(`ACCOUNT_FIT`)에 맞춰 배분됩니다. 예: 연금저축/IRP에는 배당 재투자형(TR) 해외지수,
ISA에는 국내상장 해외ETF, 일반계좌에는 해외 직투(양도차익 250만원 기본공제).

> 제시되는 종목은 **자산군을 채우는 예시**입니다. 종목코드·보수·괴리율·거래대금은
> 바뀔 수 있으니 매수 전 직접 확인하세요. 본인 취향에 맞게 `INSTRUMENTS`를 고쳐 쓰는 것이
> 정상적인 사용법입니다.

---

## 6. 웹 API

```bash
python -m backend.finance.cli serve --port 5100   # 단독 실행
python flask_app.py                                # 기존 앱에 이미 붙어 있음 (/finance)
```

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/finance` | 리포트 대시보드(HTML) |
| GET | `/api/finance/summary` | 현금흐름 요약 |
| GET | `/api/finance/transactions` | 거래 목록 |
| GET | `/api/finance/categories` | 카테고리별 지출 |
| GET | `/api/finance/recurring` | 고정비·구독 |
| GET | `/api/finance/budget?rate=30` | 소비 계획 + 진행률 |
| GET | `/api/finance/advice` | 투자 우선순위·자산배분·종목 |
| GET | `/api/finance/report` | 리포트 전체(JSON) |
| POST | `/api/finance/transactions` | 수기 거래 입력 |
| POST | `/api/finance/category` | 분류 수정(+학습) |
| POST | `/api/finance/profile` | 프로필 저장 |
| POST | `/api/finance/import` | 파일 임포트 |
| POST | `/api/finance/sync/email` | 메일 수집 실행 |
| POST | `/api/finance/webhook/sms` | 문자 알림 수신 (토큰 필요) |

---

## 7. 프라이버시

- 모든 데이터는 **로컬 SQLite** 파일에 저장됩니다. 외부로 전송하지 않습니다.
- `.gitignore` 에 DB·내역 파일·리포트가 등록되어 있습니다. **커밋되지 않는지 반드시 확인하세요.**
- 계좌·카드번호는 저장 시 `mask_account()` 로 마스킹됩니다.
- IMAP 비밀번호는 반드시 **앱 비밀번호**를 쓰고, 계정 비밀번호는 넣지 마세요.
- 서버를 외부에 노출한다면 `/api/finance/*` 전체에 인증을 걸어야 합니다
  (현재는 웹훅만 토큰으로 보호).

---

## 8. 테스트

```bash
python -m unittest discover tests -v
```

38개 테스트가 파서·임포터·분류기·분석기·예산·투자배분·리포트를 검증합니다.

---

## 9. 면책

이 모듈은 공개된 자산배분 원칙과 세제 정보를 바탕으로 계산하는 **정보 제공 도구**이며,
자본시장법상 투자자문·투자권유가 아닙니다. 세법과 상품은 수시로 바뀌고, 투자에는 원금
손실 가능성이 있습니다. 중요한 결정은 세무사·재무설계사와 확인하세요.
최종 판단과 책임은 본인에게 있습니다.
