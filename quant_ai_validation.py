"""
=====================================================================
 QUANT AI 모델 검증 프레임워크 (Out-of-Sample)
=====================================================================
핵심 질문:
  "기대수익률" 예측이 실제 미래 수익률을 맞추는가?
  아니면 그냥 '오른 종목 정렬'에 UI만 입힌 건가?

검증 방법: walk-forward (과거 여러 시점에서 예측 → 이후 실제 결과 추적)
판정 지표:
  - IC (Information Coefficient): 예측 순위 vs 실제 순위 Spearman 상관
      |IC| < 0.03  → 예측력 없음 (노이즈)
       IC > 0.05 & p<0.05 → 약한 예측력 있음
       IC < -0.03 & p<0.05 → 역방향 (시그널 반대로 가야 = 평균회귀)
  - 분위 스프레드: 상위20% 평균수익 - 하위20% 평균수익 (양수여야 의미)
  - 초과수익: 상위 종목이 시장(전종목) 평균을 이긴 폭

실행: 본인 PC (KRX 데이터 접근 필요)
  pip install pykrx pandas numpy scipy
=====================================================================
"""

from pykrx import stock
import pandas as pd
import numpy as np
from scipy.stats import spearmanr


# ---------------------------------------------------------------
# 공통: 평가 함수
# ---------------------------------------------------------------
def evaluate(signal, forward, label="", top_pct=0.2):
    """signal(예측)과 forward(실제 미래수익률)의 예측력 평가"""
    s = np.asarray(signal, dtype=float)
    f = np.asarray(forward, dtype=float)
    mask = ~(np.isnan(s) | np.isnan(f))
    s, f = s[mask], f[mask]
    if len(s) < 30:
        print(f"[{label}] 표본 부족 ({len(s)}) - 스킵")
        return None

    ic, p = spearmanr(s, f)
    df = pd.DataFrame({"s": s, "f": f})
    k = max(1, int(len(df) * top_pct))
    top = df.nlargest(k, "s")["f"].mean()
    bot = df.nsmallest(k, "s")["f"].mean()
    mkt = df["f"].mean()
    hit = (df.nlargest(k, "s")["f"] > mkt).mean()

    # 판정: 통계적 유의성(p<0.05)까지 반영
    if ic > 0.05 and p < 0.05 and (top - bot) > 0:
        verdict = "예측력 있음 ✓"
    elif ic < -0.03 and p < 0.05:
        verdict = "역방향(평균회귀) ✗ - 시그널 반대로 가야"
    else:
        verdict = "예측력 없음 (노이즈) ✗"

    return {
        "label": label, "n": len(s), "IC": ic, "p": p,
        "top": top, "bot": bot, "spread": top - bot,
        "mkt": mkt, "excess": top - mkt, "hit": hit, "verdict": verdict,
    }


def print_result(r):
    if r is None:
        return
    print(f"\n[{r['label']}]  (표본 {r['n']}개)")
    print(f"  IC: {r['IC']:+.3f} (p={r['p']:.3f})")
    print(f"  상위20% {r['top']:+.2f}% | 하위20% {r['bot']:+.2f}% | 스프레드 {r['spread']:+.2f}%p")
    print(f"  시장평균 {r['mkt']:+.2f}% | 초과수익 {r['excess']:+.2f}%p | Hit {r['hit']:.0%}")
    print(f"  >>> 판정: {r['verdict']}")


# ---------------------------------------------------------------
# 영업일 캘린더 (코스피 지수 기준)
# ---------------------------------------------------------------
def business_days(start, end):
    idx = stock.get_index_ohlcv(start, end, "1001")  # 코스피 지수
    return [d.strftime("%Y%m%d") for d in idx.index]


def period_return(date_from, date_to, market="ALL"):
    """date_from~date_to 구간 전종목 등락률 (index=ticker, col 'ret')"""
    df = stock.get_market_price_change(date_from, date_to, market=market)
    # pykrx 컬럼: 종목명, 시가, 종가, 변동폭, 등락률, 거래량, 거래대금
    return df[["등락률"]].rename(columns={"등락률": "ret"})


# ---------------------------------------------------------------
# PART A: 순수 모멘텀 베이스라인 (모델 없이 바로 실행 가능)
# ---------------------------------------------------------------
# "과거 N일 오른 종목이 이후 M일에도 오르는가?"
# 너희 모델이 모멘텀 외삽이라면, 이 베이스라인 IC가 모델 IC의 상한선.
# 여기서 IC ≈ 0 이면, 1일/7일/1달 '기대수익률'은 전부 예측력 없음.
def momentum_baseline(test_dates, lookback, forward, market="ALL"):
    cal = business_days("20250101", "20260527")  # 충분히 넓게
    rows = []
    for d in test_dates:
        if d not in cal:
            continue
        i = cal.index(d)
        if i - lookback < 0 or i + forward >= len(cal):
            continue
        lb_start, lb_end = cal[i - lookback], cal[i]
        fw_start, fw_end = cal[i], cal[i + forward]

        sig = period_return(lb_start, lb_end, market).rename(columns={"ret": "signal"})
        fwd = period_return(fw_start, fw_end, market).rename(columns={"ret": "forward"})
        m = sig.join(fwd, how="inner").dropna()
        r = evaluate(m["signal"], m["forward"], label=f"{d} (룩백{lookback}/포워드{forward})")
        if r:
            rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------
# PART B: 너희 모델 예측 검증
# ---------------------------------------------------------------
# 모델을 과거 여러 시점에 돌려서 아래 형식 CSV로 저장한 뒤 넣어줘:
#   date,ticker,expected_return
#   20260301,011070,17.77
#   20260301,000990,16.93
#   ...
# 각 (date,ticker)의 실제 forward 수익률을 pykrx로 붙여서 베이스라인과 비교.
def validate_model(pred_csv, forward, market="ALL"):
    pred = pd.read_csv(pred_csv, dtype={"ticker": str})
    cal = business_days("20250101", "20260527")
    rows = []
    for d, g in pred.groupby("date"):
        d = str(d)
        if d not in cal:
            continue
        i = cal.index(d)
        if i + forward >= len(cal):
            continue
        fwd = period_return(cal[i], cal[i + forward], market)
        g = g.set_index("ticker").join(fwd, how="inner").dropna()
        r = evaluate(g["expected_return"], g["ret"], label=f"모델 {d}")
        if r:
            rows.append(r)
    return pd.DataFrame(rows)


def summary(df, title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)
    if df.empty:
        print(" 결과 없음")
        return
    print(f" 검증 시점 {len(df)}개 평균:")
    print(f"   평균 IC          : {df['IC'].mean():+.3f}")
    print(f"   IC>0 비율        : {(df['IC']>0).mean():.0%}")
    print(f"   평균 분위 스프레드 : {df['spread'].mean():+.2f}%p")
    print(f"   평균 초과수익     : {df['excess'].mean():+.2f}%p")
    print(f"   평균 Hit rate    : {df['hit'].mean():.0%}")
    # 종합 판정
    if df["IC"].mean() > 0.05 and (df["IC"] > 0).mean() > 0.6:
        print("   >>> 종합: 예측력 있음 (모멘텀이 실제로 작동)")
    elif df["IC"].mean() < -0.03:
        print("   >>> 종합: 역방향 - 추격매수가 손해. 평균회귀가 지배적")
    else:
        print("   >>> 종합: 예측력 없음 - '오른 거 정렬'에 불과할 가능성 높음")


if __name__ == "__main__":
    # 검증할 과거 시점들 (영업일 기준, 본인 데이터 범위에 맞게 조정)
    TEST_DATES = ["20260102", "20260120", "20260203", "20260217",
                  "20260303", "20260317", "20260401", "20260415",
                  "20260504", "20260518"]

    # --- PART A: 1일/7일/1달 모멘텀 베이스라인 ---
    for lb, fw, name in [(1, 1, "1일→1일"), (5, 5, "7일→7일"), (20, 20, "1달→1달")]:
        res = momentum_baseline(TEST_DATES, lookback=lb, forward=fw)
        summary(res, f"PART A 베이스라인: 과거 {name} 모멘텀")

    # --- PART B: 너희 모델 (예측 CSV 준비되면 주석 해제) ---
    # res_model = validate_model("my_model_predictions.csv", forward=1)
    # summary(res_model, "PART B: QUANT AI 모델 (1일)")
    #
    # 비교: 모델 평균IC > 베이스라인 평균IC 이면 모델이 모멘텀 이상의 정보 가짐.
    #       비슷하면 → UI만 입힌 모멘텀.
