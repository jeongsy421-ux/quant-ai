"""
backtest_strategy_winrate.py — 현재 단타 전략의 "실측 승률" 백테스트

목적
    config.py STRATEGY 파라미터(익절 +5% / 손절 -3% / 최대보유 3일 / 동시 3종목)를
    그대로 적용했을 때의 실제 승률·손익비·기대값·MDD를 측정하고,
    그 실측 분포로 "초기자본 → 목표자본" 도달 확률을 추정한다.

엔트리 룰 3종 (코드베이스 로직 재현)
    momentum : screener.py 모멘텀 스캔  — 등락률 +1.0%↑, 거래량비율 1.5배↑, RSI 30~65
    surge    : scalper.py 점수제        — 거래량 쇼크 / BB 상단 돌파 / 이평 정배열 / RSI, score >= 60
    dip      : config.SCAN_FILTER 역추세 — RSI 45↓, 거래량비율 1.3배↑

체결 가정 (낙관 편향 제거)
    - 신호는 D일 종가 기준으로 확정 → D+1 시가에 진입 (look-ahead 차단)
    - 갭 체결 반영: 시가가 이미 손절선 이하면 시가 체결(손실 확대), 익절선 이상이면 시가 체결
    - 같은 봉에서 손절선·익절선을 모두 터치하면 손절 우선 (보수적)
    - max_hold_days 내 미청산 시 마지막 날 종가 청산
    - 거래비용 편도 0.15% (왕복 0.3%) — run_full_validation.py COST 기준

포트폴리오
    - 초기자본을 max_positions 등분, 신호 과다 시 점수 상위 선택
    - 월 누적손실이 RISK.monthly_loss_limit 도달 시 당월 신규 진입 중단

사용법
    python backtest_strategy_winrate.py
    python backtest_strategy_winrate.py --source fdr --years 3
    python backtest_strategy_winrate.py --capital 4000000 --target 10000000
"""
import os
import sys
import glob
import argparse
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ==========================================
# 0. 설정 (backend/config.py 우선, 실패 시 동일 기본값)
# ==========================================
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

DEFAULT_STRATEGY = {
    "total_capital":   2_000_000,
    "stop_loss_pct":   -3.0,
    "take_profit_pct": 5.0,
    "max_positions":   3,
    "max_hold_days":   3,
}
DEFAULT_RISK = {"monthly_loss_limit": -0.10}
DEFAULT_TECHNICAL = {"rsi_period": 14, "volume_surge": 1.5, "momentum_volume": 2.5, "momentum_price": 5.0}
DEFAULT_SCAN_FILTER = {"max_rsi": 45, "min_volume_ratio": 1.3}

try:
    from config import STRATEGY, RISK, TECHNICAL, SCAN_FILTER  # type: ignore
    CONFIG_SOURCE = "backend/config.py"
except Exception:
    STRATEGY, RISK = DEFAULT_STRATEGY, DEFAULT_RISK
    TECHNICAL, SCAN_FILTER = DEFAULT_TECHNICAL, DEFAULT_SCAN_FILTER
    CONFIG_SOURCE = "내장 기본값 (config.py 임포트 실패)"

TP_PCT    = abs(STRATEGY.get("take_profit_pct", 5.0)) / 100.0
SL_PCT    = abs(STRATEGY.get("stop_loss_pct", -3.0)) / 100.0
MAX_POS   = int(STRATEGY.get("max_positions", 3))
MAX_HOLD  = int(STRATEGY.get("max_hold_days", 3))
MONTHLY_LIMIT = float(RISK.get("monthly_loss_limit", -0.10))
COST_SIDE = 0.0015                      # 편도 거래비용 (수수료+세금+슬리피지)

OUT_DIR = "backtest_results"
os.makedirs(OUT_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(OUT_DIR, "strategy_winrate.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)

# KOSPI/KOSDAQ 기본 유니버스 (FDR 모드에서 사용)
DEFAULT_UNIVERSE = [
    "005930", "000660", "005380", "000270", "012330", "005490", "051910", "006400",
    "035420", "035720", "068270", "207940", "105560", "055550", "086790", "032830",
    "028260", "066570", "017670", "034020", "009540", "010140", "042660", "329180",
    "011200", "003490", "000720", "047040", "051900", "090430", "097950", "033780",
    "251270", "036570", "015760", "018260", "000810", "004020", "001040", "034730",
    "247540", "086520", "091990", "196170", "214150", "278280", "066970", "035900",
    "022100", "005290", "028050", "012450", "012630", "003670", "294870", "373220",
]


# ==========================================
# 1. 데이터 로딩
# ==========================================
def load_from_cache(cache_dir="cache"):
    """fetch_data.py가 만든 cache/*.parquet (33개월 KIS 데이터)"""
    paths = sorted(glob.glob(os.path.join(cache_dir, "*.parquet")))
    paths = [p for p in paths if "macro" not in os.path.basename(p)]
    out = {}
    for p in paths:
        code = os.path.splitext(os.path.basename(p))[0]
        if not (code.isdigit() and len(code) == 6):
            continue
        try:
            df = pd.read_parquet(p)
        except Exception as e:
            logging.warning(f"parquet 로드 실패 {p}: {e}")
            continue
        df = df.rename(columns=str.lower)
        need = {"date", "open", "high", "low", "close", "volume"}
        if not need.issubset(df.columns) or df.empty:
            continue
        df = df[list(need)].copy()
        df["date"] = pd.to_datetime(df["date"])
        out[code] = df.sort_values("date").reset_index(drop=True)
    return out


def load_from_fdr(universe, years):
    """FinanceDataReader 실시간 수집 (사용자 PC에서 권장)"""
    import FinanceDataReader as fdr
    start = (datetime.now() - timedelta(days=int(365.25 * years))).strftime("%Y-%m-%d")
    out = {}
    for i, code in enumerate(universe, 1):
        try:
            df = fdr.DataReader(code, start)
        except Exception as e:
            logging.warning(f"FDR 실패 {code}: {e}")
            continue
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower).reset_index().rename(columns={"index": "date"})
        df.columns = [str(c).lower() for c in df.columns]
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            continue
        df["date"] = pd.to_datetime(df["date"])
        out[code] = df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)
        if i % 10 == 0:
            print(f"  FDR 수집 {i}/{len(universe)}...")
    return out


def load_from_csv_cache(dirs=("data", "backend/data")):
    """
    레포의 stock_*.csv 스냅샷에서 종목별로 **파일 1개만** 선택해 로드 (오프라인 폴백).

    주의: 같은 종목·같은 날짜라도 스냅샷마다 수정주가 배수가 달라 값이 다르다
    (예: 005930 2025-06-02 종가가 파일에 따라 55,931 / 56,800 / 37,470).
    여러 스냅샷을 합치면 ±50% 짜리 가짜 봉이 생겨 승률이 완전히 왜곡되므로
    가장 긴(= 가장 최신) 단일 파일만 쓴다.
    """
    best = {}   # code -> (row_count, snapshot, path)
    for d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "stock_*.csv"))):
            base = os.path.basename(p)[len("stock_"):]
            stem, snap = base.rsplit("_", 1)
            snap = os.path.splitext(snap)[0]
            code = stem.replace("_KS", "").replace("_KQ", "")
            if not (code.isdigit() and len(code) == 6 and snap.isdigit()):
                continue              # 지수(^KS11)·환율(USDKRW=X)·종목명 파일 제외
            try:
                n = sum(1 for _ in open(p, encoding="utf-8-sig")) - 1
            except Exception:
                continue
            key = (n, snap)
            if code not in best or key > best[code][0]:
                best[code] = (key, p)

    out = {}
    for code, (_, path) in best.items():
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception as e:
            logging.warning(f"csv 로드 실패 {path}: {e}")
            continue
        if "Date" not in df.columns or df.empty:
            continue
        df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close", "Volume": "volume"})
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])[["date", "open", "high", "low", "close", "volume"]]
        df = df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
        if len(df) >= 120:
            out[code] = df
    return out


PRICE_LIMIT = 0.31      # 국내 주식 가격제한폭 ±30% → 이보다 큰 변동은 데이터 오류


def sanitize(code, df):
    """
    가격 데이터 정합성 검증 후 가장 긴 '깨끗한' 구간만 반환.
    - 가격/거래량 이상치 제거
    - 고가·저가 정합성 위반 보정
    - 가격제한폭 초과 변동(= 수정주가 접합 오류, 액면분할 미반영 등)에서 시계열 절단
    """
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1) & (df["volume"] >= 0)].copy()
    if df.empty:
        return df, ["전 구간 가격 이상"]

    notes = []
    bad_hl = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
    if bad_hl.any():
        notes.append(f"고저가 정합성 위반 {int(bad_hl.sum())}봉 보정")
        df.loc[bad_hl, "high"] = df.loc[bad_hl, ["open", "high", "close"]].max(axis=1)
        df.loc[bad_hl, "low"] = df.loc[bad_hl, ["open", "low", "close"]].min(axis=1)

    df = df.sort_values("date").reset_index(drop=True)
    ret = df["close"].pct_change()
    breaks = df.index[ret.abs() > PRICE_LIMIT].tolist()
    if breaks:
        bounds = [0] + breaks + [len(df)]
        segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
        a, b = max(segs, key=lambda t: t[1] - t[0])
        notes.append(f"가격제한폭 초과 변동 {len(breaks)}건 → {df['date'].iloc[a]:%Y-%m-%d}~{df['date'].iloc[b-1]:%Y-%m-%d} 구간만 사용")
        df = df.iloc[a:b].reset_index(drop=True)

    if notes:
        logging.warning(f"[{code}] " + " / ".join(notes))
    return df, notes


def load_data(source, universe, years):
    if source in ("auto", "cache") and os.path.isdir("cache"):
        data = load_from_cache()
        if data:
            return data, "cache/*.parquet (KIS)"
    if source == "fdr" or (source == "auto" and not os.path.isdir("cache")):
        try:
            data = load_from_fdr(universe, years)
            if data:
                return data, f"FinanceDataReader (최근 {years}년)"
            print("[경고] FDR에서 받은 종목이 0개입니다(네트워크/차단 가능성) → CSV 스냅샷으로 폴백합니다.")
            logging.warning("FDR 수집 결과 0건 → CSV 폴백")
        except Exception as e:
            print(f"[경고] FDR 수집 실패 → CSV 스냅샷 폴백: {e}")
            logging.warning(f"FDR 수집 실패: {e}")
    if source in ("auto", "csv", "fdr"):
        data = load_from_csv_cache()
        if data:
            return data, "data/stock_*.csv 스냅샷 (오프라인 폴백)"
    raise SystemExit("사용 가능한 가격 데이터가 없습니다. --source fdr 로 재시도하거나 fetch_data.py 로 cache/ 를 만드세요.")


def clean_universe(data, min_rows=120):
    """전 종목 정합성 검증 → 사용 가능한 종목만 남김"""
    cleaned, dropped, flagged = {}, [], []
    for code, df in data.items():
        df, notes = sanitize(code, df)
        if len(df) < min_rows:
            dropped.append(code)
            continue
        if notes:
            flagged.append(code)
        cleaned[code] = df
    return cleaned, dropped, flagged


# ==========================================
# 2. 지표 계산
# ==========================================
def add_indicators(df):
    c, v = df["close"], df["volume"]
    n = int(TECHNICAL.get("rsi_period", 14))

    df["ret_1d"] = c.pct_change()
    df["ma5"]  = c.rolling(5).mean()
    df["ma20"] = c.rolling(20).mean()
    df["ma60"] = c.rolling(60).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    std = c.rolling(20).std()
    df["bb_upper"] = df["ma20"] + 2 * std

    df["vol_ma20"] = v.rolling(20).mean()
    df["vol_ratio"] = v / df["vol_ma20"].replace(0, np.nan)
    df["vol_ma50"] = v.rolling(50).mean()
    df["vol_shock"] = v / df["vol_ma50"].replace(0, np.nan)
    df["trade_amount"] = c * v
    return df


# ==========================================
# 3. 엔트리 시그널 (코드베이스 룰 재현)
# ==========================================
def signal_momentum(r, prev):
    """screener.py 모멘텀 스캔 조건"""
    if r["ret_1d"] >= 0.01 and r["vol_ratio"] >= TECHNICAL.get("volume_surge", 1.5) and 30 <= r["rsi"] <= 65:
        return 50 + min(30, r["vol_ratio"] * 5) + min(20, r["ret_1d"] * 500)
    return 0


def signal_surge(r, prev):
    """scalper.py analyze_ticker 점수제 (score >= 60 진입)"""
    score = 0
    if r["vol_shock"] > 5.0:
        score += 50
    elif r["vol_shock"] > 3.0:
        score += 30
    if r["close"] > r["bb_upper"]:
        score += 30
    if r["ma5"] > r["ma20"] > r["ma60"]:
        score += 20 if prev["ma5"] <= prev["ma20"] else 10
    if 50 < r["rsi"] < 75:
        score += 10
    return score if score >= 60 else 0


def signal_dip(r, prev):
    """config.SCAN_FILTER 역추세(과매도) 조건"""
    if r["rsi"] <= SCAN_FILTER.get("max_rsi", 45) and r["vol_ratio"] >= SCAN_FILTER.get("min_volume_ratio", 1.3):
        return 50 + (SCAN_FILTER.get("max_rsi", 45) - r["rsi"])
    return 0


SIGNAL_RULES = {
    "momentum": signal_momentum,
    "surge":    signal_surge,
    "dip":      signal_dip,
}


def build_signals(data, rule_fn, min_trade_amount):
    """전 종목 × 전 거래일 신호 테이블 생성"""
    rows = []
    for code, df in data.items():
        need = ["rsi", "vol_ratio", "vol_shock", "ma5", "ma20", "ma60", "bb_upper", "ret_1d"]
        ok = df.dropna(subset=need)
        for i in range(1, len(ok)):
            r, prev = ok.iloc[i], ok.iloc[i - 1]
            if r["trade_amount"] < min_trade_amount:
                continue                      # 거래대금 필터 (유동성)
            score = rule_fn(r, prev)
            if score > 0:
                rows.append({"date": r["date"], "code": code, "score": float(score)})
    if not rows:
        return pd.DataFrame(columns=["date", "code", "score"])
    return pd.DataFrame(rows).sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)


# ==========================================
# 4. 단일 트레이드 청산 시뮬레이션
# ==========================================
def simulate_trade(df, signal_idx):
    """
    signal_idx: 신호가 발생한 봉의 위치. 진입은 signal_idx+1 시가.
    반환: dict(net_return, hold_days, exit_reason, ...) 또는 None(데이터 부족)
    """
    entry_idx = signal_idx + 1
    if entry_idx >= len(df):
        return None

    entry = float(df["open"].iloc[entry_idx])
    if entry <= 0:
        return None

    tp_price = entry * (1 + TP_PCT)
    sl_price = entry * (1 - SL_PCT)

    exit_price, exit_reason, hold_days = None, None, 0
    for k in range(entry_idx, min(entry_idx + MAX_HOLD, len(df))):
        o, h, l = float(df["open"].iloc[k]), float(df["high"].iloc[k]), float(df["low"].iloc[k])
        hold_days = k - entry_idx + 1

        if k > entry_idx and o <= sl_price:           # 갭하락 → 시가 체결(손실 확대)
            exit_price, exit_reason = o, "손절(갭)"
            break
        if k > entry_idx and o >= tp_price:           # 갭상승 → 시가 체결
            exit_price, exit_reason = o, "익절(갭)"
            break
        if l <= sl_price and h >= tp_price:           # 같은 봉 양방향 터치 → 손절 우선
            exit_price, exit_reason = sl_price, "손절(동일봉)"
            break
        if l <= sl_price:
            exit_price, exit_reason = sl_price, "손절"
            break
        if h >= tp_price:
            exit_price, exit_reason = tp_price, "익절"
            break

    if exit_price is None:                            # 기간 만료 → 종가 청산
        last = min(entry_idx + MAX_HOLD, len(df)) - 1
        exit_price, exit_reason = float(df["close"].iloc[last]), "기간만료"
        hold_days = last - entry_idx + 1

    gross = exit_price / entry - 1
    # 매수 시 비용만큼 비싸게, 매도 시 비용만큼 싸게 체결된 것으로 처리
    net = (1 + gross) * (1 - COST_SIDE) / (1 + COST_SIDE) - 1
    return {
        "entry_date": df["date"].iloc[entry_idx],
        "exit_date":  df["date"].iloc[min(entry_idx + hold_days - 1, len(df) - 1)],
        "entry": entry, "exit": exit_price,
        "gross_return": gross, "net_return": net,
        "hold_days": hold_days, "exit_reason": exit_reason,
    }


# ==========================================
# 5. 포트폴리오 시뮬레이션
# ==========================================
def run_portfolio(data, signals, capital):
    """
    동시 MAX_POS 종목, 종목당 자본 1/MAX_POS, 월 손실한도 도달 시 당월 신규진입 중단.
    반환: (trades DataFrame, equity DataFrame)
    """
    idx_map = {code: {d: i for i, d in enumerate(df["date"])} for code, df in data.items()}

    equity = float(capital)
    month_key, month_start_equity = None, float(capital)
    open_positions = []               # [(청산예정일, 종목코드)]
    trades, curve = [], []
    blocked_months = set()

    for date, day in signals.groupby("date", sort=True):
        open_positions = [x for x in open_positions if x[0] > date]
        held = {code for _, code in open_positions}
        free = MAX_POS - len(open_positions)

        mk = (date.year, date.month)
        if mk != month_key:
            month_key, month_start_equity = mk, equity

        if equity / month_start_equity - 1 <= MONTHLY_LIMIT:
            blocked_months.add(mk)      # 월 손실한도 초과 → 당월 신규진입 중단
            curve.append({"date": date, "equity": equity})
            continue
        if free <= 0:
            curve.append({"date": date, "equity": equity})
            continue

        taken = 0
        for _, sig in day.iterrows():
            if taken >= free:
                break
            code = sig["code"]
            if code in held:           # 동일 종목 중복 보유 금지
                continue
            df = data[code]
            si = idx_map[code].get(date)
            if si is None:
                continue
            t = simulate_trade(df, si)
            if t is None:
                continue

            size = equity / MAX_POS
            pnl = size * t["net_return"]
            equity += pnl
            open_positions.append((t["exit_date"], code))
            held.add(code)
            taken += 1

            t.update({"code": code, "score": sig["score"], "signal_date": date,
                      "size": size, "pnl": pnl, "equity_after": equity})
            trades.append(t)

        curve.append({"date": date, "equity": equity})

    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(curve).drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    if not tdf.empty:
        tdf = tdf.sort_values("entry_date").reset_index(drop=True)
    return tdf, edf, sorted(blocked_months)


# ==========================================
# 6. 통계
# ==========================================
def trade_stats(tdf, edf, capital, data):
    if tdf.empty:
        return None
    r = tdf["net_return"]
    wins, losses = r[r > 0], r[r <= 0]
    avg_w = float(wins.mean()) if len(wins) else 0.0
    avg_l = float(abs(losses.mean())) if len(losses) else 0.0
    win_rate = len(wins) / len(r)
    payoff = avg_w / avg_l if avg_l > 0 else float("inf")
    breakeven = avg_l / (avg_w + avg_l) if (avg_w + avg_l) > 0 else float("nan")

    all_dates = pd.concat([df["date"] for df in data.values()])
    span_days = (all_dates.max() - all_dates.min()).days or 1
    years = span_days / 365.25

    eq = edf["equity"]
    mdd = float(((eq - eq.cummax()) / eq.cummax()).min()) if len(eq) else 0.0
    final = float(eq.iloc[-1]) if len(eq) else float(capital)
    cagr = (final / capital) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")

    # 승률 95% 신뢰구간 (정규근사) — 표본이 작을 때 과신 방지
    se = np.sqrt(win_rate * (1 - win_rate) / len(r))
    wr_lo, wr_hi = max(0.0, win_rate - 1.96 * se), min(1.0, win_rate + 1.96 * se)

    # 기대값이 0보다 큰지 부트스트랩 검정 (단측 p-value)
    rng = np.random.default_rng(0)
    boot_means = rng.choice(r.to_numpy(), size=(10000, len(r)), replace=True).mean(axis=1)
    p_value = float((boot_means <= 0).mean())

    return {
        "n_trades": int(len(r)),
        "trades_per_year": len(r) / years,
        "win_rate": win_rate,
        "win_rate_lo": float(wr_lo), "win_rate_hi": float(wr_hi),
        "p_value": p_value,
        "avg_win": avg_w, "avg_loss": avg_l,
        "payoff": payoff,
        "expectancy": float(r.mean()),
        "breakeven_win_rate": breakeven,
        "edge": win_rate - breakeven,
        "avg_hold_days": float(tdf["hold_days"].mean()),
        "final_equity": final,
        "total_return": final / capital - 1,
        "cagr": cagr,
        "mdd": mdd,
        "years": years,
        "exit_mix": tdf["exit_reason"].value_counts().to_dict(),
    }


# ==========================================
# 7. 목표 도달 확률 (실측 트레이드 부트스트랩)
# ==========================================
def bootstrap_goal(tdf, stats, capital, target, horizon_years, runs=20000, seed=42, ruin_frac=0.5):
    """실측 net_return 분포에서 복원추출하여 목표 도달 / 반토막 확률 추정"""
    if tdf.empty or stats is None:
        return None
    rng = np.random.default_rng(seed)
    pool = tdf["net_return"].to_numpy()

    cycles_per_year = max(stats["trades_per_year"] / MAX_POS, 1e-9)
    n_cycles = int(round(cycles_per_year * horizon_years))
    if n_cycles < 1:
        return {"n_cycles": 0, "reach": 0.0, "ruin": 0.0,
                "median": float(capital), "p10": float(capital), "p90": float(capital),
                "cycles_per_year": cycles_per_year}

    draws = rng.choice(pool, size=(runs, n_cycles, MAX_POS), replace=True)
    cycle_ret = draws.mean(axis=2)                       # 종목당 1/MAX_POS 비중

    eq = np.full(runs, float(capital))
    peak = eq.copy()
    reached = np.zeros(runs, dtype=bool)
    ruined = np.zeros(runs, dtype=bool)
    month_anchor = eq.copy()
    cycles_per_month = max(cycles_per_year / 12.0, 1e-9)

    for j in range(n_cycles):
        if j > 0 and j % max(int(round(cycles_per_month)), 1) == 0:
            month_anchor = eq.copy()
        active = (eq / month_anchor - 1) > MONTHLY_LIMIT   # 월 손실한도 도달분은 당월 휴식
        eq = np.where(active & ~reached, eq * (1 + cycle_ret[:, j]), eq)
        peak = np.maximum(peak, eq)
        reached |= eq >= target
        ruined |= eq <= capital * ruin_frac

    return {
        "n_cycles": n_cycles,
        "cycles_per_year": cycles_per_year,
        "reach": float(reached.mean()),
        "ruin": float(ruined.mean()),
        "median": float(np.median(eq)),
        "p10": float(np.percentile(eq, 10)),
        "p90": float(np.percentile(eq, 90)),
    }


# ==========================================
# 8. 리포트
# ==========================================
def fmt_won(x):
    return f"{x/10000:,.0f}만"


def main():
    ap = argparse.ArgumentParser(description="단타 전략 실측 승률 백테스트")
    ap.add_argument("--source", default="auto", choices=["auto", "cache", "fdr", "csv"])
    ap.add_argument("--years", type=float, default=3.0, help="FDR 모드 수집 기간(년)")
    ap.add_argument("--capital", type=float, default=float(STRATEGY.get("total_capital", 2_000_000)))
    ap.add_argument("--target", type=float, default=0.0, help="목표 자본 (기본: 초기자본 × 2.5)")
    ap.add_argument("--horizon", type=float, default=1.0, help="목표 달성 기간(년)")
    ap.add_argument("--horizons", default="1,2,3", help="목표 도달확률을 함께 볼 기간들(년, 쉼표구분)")
    ap.add_argument("--min-trade-amount", type=float, default=3_000_000_000, help="최소 거래대금 필터")
    ap.add_argument("--runs", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rules", default="momentum,surge,dip")
    args = ap.parse_args()

    capital = args.capital
    target = args.target if args.target > 0 else capital * 2.5

    print("=" * 78)
    print(" 단타 전략 실측 승률 백테스트")
    print("=" * 78)
    print(f"설정 출처     : {CONFIG_SOURCE}")
    print(f"전략          : 익절 +{TP_PCT*100:.0f}% / 손절 -{SL_PCT*100:.0f}% / 최대 {MAX_HOLD}일 보유 / 동시 {MAX_POS}종목")
    print(f"거래비용      : 편도 {COST_SIDE*100:.2f}% (왕복 {COST_SIDE*200:.1f}%)")
    print(f"월 손실한도   : {MONTHLY_LIMIT*100:.0f}%")
    print(f"자본          : {fmt_won(capital)}원 → 목표 {fmt_won(target)}원 ({args.horizon:.0f}년 내)")
    print()

    raw, src_label = load_data(args.source, DEFAULT_UNIVERSE, args.years)
    data, dropped, flagged = clean_universe(raw)
    if not data:
        raise SystemExit("정합성 검증을 통과한 종목이 없습니다.")
    for code in list(data):
        data[code] = add_indicators(data[code])
    all_dates = pd.concat([df["date"] for df in data.values()])
    print(f"데이터 소스   : {src_label}")
    print(f"유니버스      : {len(data)}종목 | 기간 {all_dates.min():%Y-%m-%d} ~ {all_dates.max():%Y-%m-%d}")
    if dropped:
        print(f"제외          : {len(dropped)}종목 (데이터 부족/이상) {', '.join(dropped[:8])}{'...' if len(dropped) > 8 else ''}")
    if flagged:
        print(f"정합성 보정   : {len(flagged)}종목 (상세는 {OUT_DIR}/strategy_winrate.log)")
    print()

    results = {}
    for rule in [r.strip() for r in args.rules.split(",") if r.strip()]:
        fn = SIGNAL_RULES.get(rule)
        if fn is None:
            print(f"[경고] 알 수 없는 룰: {rule}")
            continue
        print(f"[{rule}] 신호 생성 중...")
        signals = build_signals(data, fn, args.min_trade_amount)
        if signals.empty:
            print(f"  → 신호 0건. 건너뜀\n")
            continue
        tdf, edf, blocked = run_portfolio(data, signals, capital)
        st = trade_stats(tdf, edf, capital, data)
        if st is None:
            print(f"  → 체결 0건. 건너뜀\n")
            continue
        bs = bootstrap_goal(tdf, st, capital, target, args.horizon, args.runs, args.seed)
        horizons = [float(h) for h in args.horizons.split(",") if h.strip()]
        multi = {h: bootstrap_goal(tdf, st, capital, target, h, args.runs, args.seed) for h in horizons}
        results[rule] = {"stats": st, "boot": bs, "multi": multi, "trades": tdf, "equity": edf,
                         "blocked": blocked, "n_signals": len(signals)}
        print(f"  신호 {len(signals):,}건 → 체결 {st['n_trades']:,}건 | 승률 {st['win_rate']*100:.1f}%")
        tdf.to_csv(os.path.join(OUT_DIR, f"trades_{rule}.csv"), index=False, encoding="utf-8-sig")
    print()

    if not results:
        print("측정 가능한 결과가 없습니다.")
        return

    # ── 콘솔 요약 ─────────────────────────────────────────
    print("=" * 78)
    print(" 핵심 결과")
    print("=" * 78)
    hdr = (f"{'룰':<9} {'체결':>6} {'연간':>6} {'승률':>7} {'승률 95%CI':>14} {'평균익':>7} {'평균손':>7} "
           f"{'손익비':>6} {'기대값':>8} {'손익분기':>8} {'엣지':>7} {'p값':>6}")
    print(hdr)
    print("-" * len(hdr))
    for rule, r in results.items():
        s = r["stats"]
        ci = f"{s['win_rate_lo']*100:.1f}~{s['win_rate_hi']*100:.1f}%"
        print(f"{rule:<9} {s['n_trades']:>6,} {s['trades_per_year']:>6.0f} {s['win_rate']*100:>6.1f}% {ci:>14} "
              f"{s['avg_win']*100:>6.2f}% {s['avg_loss']*100:>6.2f}% {s['payoff']:>6.2f} "
              f"{s['expectancy']*100:>7.3f}% {s['breakeven_win_rate']*100:>7.1f}% {s['edge']*100:>+6.1f}%p "
              f"{s['p_value']:>6.3f}")

    print()
    hdr2 = f"{'룰':<9} {'기간수익':>9} {'CAGR':>8} {'MDD':>8} {'최종잔고':>10} | {'목표도달':>8} {'반토막':>7} {'중앙값':>9} {'하위10%':>9}"
    print(hdr2)
    print("-" * len(hdr2))
    for rule, r in results.items():
        s, b = r["stats"], r["boot"]
        print(f"{rule:<9} {s['total_return']*100:>+8.1f}% {s['cagr']*100:>+7.1f}% {s['mdd']*100:>7.1f}% "
              f"{fmt_won(s['final_equity']):>10} | {b['reach']*100:>7.1f}% {b['ruin']*100:>6.1f}% "
              f"{fmt_won(b['median']):>9} {fmt_won(b['p10']):>9}")
    print()
    hs = sorted(next(iter(results.values()))["multi"].keys())
    hdr3 = f"{'룰':<9} " + " ".join(f"{str(int(h))+'년내 도달':>11}" for h in hs) + f" {'사이클/년':>9}"
    print(hdr3)
    print("-" * len(hdr3))
    for rule, r in results.items():
        cells = " ".join(f"{r['multi'][h]['reach']*100:>10.1f}%" for h in hs)
        print(f"{rule:<9} {cells} {r['multi'][hs[0]]['cycles_per_year']:>9.1f}")

    print()
    print("* 엣지 = 실측승률 − 손익분기승률. 음수면 비용 차감 후 기대값이 마이너스.")
    print("* p값 = 기대값이 0 이하일 확률(부트스트랩 단측). 0.05 미만이어야 '우연 아님'으로 본다.")
    print(f"* 목표도달 = 실측 트레이드 분포 부트스트랩({args.runs:,}회) 기준 {args.horizon:.0f}년 내 {fmt_won(target)}원 도달 확률.")
    print()

    # ── 마크다운 리포트 ────────────────────────────────────
    lines = [
        "# 단타 전략 실측 승률 백테스트 리포트", "",
        f"생성일: {datetime.now():%Y-%m-%d %H:%M}", "",
        "## 1. 조건", "",
        f"- 설정 출처: `{CONFIG_SOURCE}`",
        f"- 전략: 익절 **+{TP_PCT*100:.0f}%** / 손절 **-{SL_PCT*100:.0f}%** / 최대 보유 **{MAX_HOLD}일** / 동시 **{MAX_POS}종목**",
        f"- 거래비용: 편도 {COST_SIDE*100:.2f}% (왕복 {COST_SIDE*200:.1f}%)",
        f"- 월 손실한도: {MONTHLY_LIMIT*100:.0f}% (도달 시 당월 신규진입 중단)",
        f"- 자본: {fmt_won(capital)}원 → 목표 {fmt_won(target)}원, 기간 {args.horizon:.0f}년",
        f"- 데이터: {src_label} / {len(data)}종목 / {all_dates.min():%Y-%m-%d} ~ {all_dates.max():%Y-%m-%d}",
        f"- 체결 가정: 신호 익일 **시가 진입**, 갭 체결 반영, 동일봉 양방향 터치는 **손절 우선**", "",
        "## 2. 트레이드 통계", "",
        "| 룰 | 체결 | 연간 | 승률 | 승률 95% CI | 평균익 | 평균손 | 손익비 | 기대값/트레이드 | 손익분기승률 | 엣지 | p값 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule, r in results.items():
        s = r["stats"]
        lines.append(f"| {rule} | {s['n_trades']:,} | {s['trades_per_year']:.0f} | {s['win_rate']*100:.1f}% | "
                     f"{s['win_rate_lo']*100:.1f}~{s['win_rate_hi']*100:.1f}% | "
                     f"{s['avg_win']*100:.2f}% | {s['avg_loss']*100:.2f}% | {s['payoff']:.2f} | "
                     f"{s['expectancy']*100:+.3f}% | {s['breakeven_win_rate']*100:.1f}% | {s['edge']*100:+.1f}%p | "
                     f"{s['p_value']:.3f} |")

    lines += ["", "## 3. 포트폴리오 성과 및 목표 도달 확률", "",
              "| 룰 | 기간수익 | CAGR | MDD | 최종잔고 | 목표도달 | 반토막 | 중앙값 | 하위10% | 상위10% |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rule, r in results.items():
        s, b = r["stats"], r["boot"]
        lines.append(f"| {rule} | {s['total_return']*100:+.1f}% | {s['cagr']*100:+.1f}% | {s['mdd']*100:.1f}% | "
                     f"{fmt_won(s['final_equity'])} | **{b['reach']*100:.1f}%** | {b['ruin']*100:.1f}% | "
                     f"{fmt_won(b['median'])} | {fmt_won(b['p10'])} | {fmt_won(b['p90'])} |")

    hs = sorted(next(iter(results.values()))["multi"].keys())
    lines += ["", f"### 기간별 {fmt_won(target)}원 도달 확률", "",
              "| 룰 | " + " | ".join(f"{int(h)}년 내" for h in hs) + " | 사이클/년 |",
              "|---|" + "---:|" * (len(hs) + 1)]
    for rule, r in results.items():
        lines.append(f"| {rule} | " + " | ".join(f"{r['multi'][h]['reach']*100:.1f}%" for h in hs) +
                     f" | {r['multi'][hs[0]]['cycles_per_year']:.1f} |")

    lines += ["", "## 4. 청산 사유 분포", "", "| 룰 | " + " | ".join(["익절", "익절(갭)", "손절", "손절(갭)", "손절(동일봉)", "기간만료"]) + " |",
              "|---|" + "---:|" * 6]
    for rule, r in results.items():
        mix = r["stats"]["exit_mix"]
        lines.append(f"| {rule} | " + " | ".join(str(mix.get(k, 0)) for k in
                     ["익절", "익절(갭)", "손절", "손절(갭)", "손절(동일봉)", "기간만료"]) + " |")

    lines += ["", "## 5. 판정", ""]
    for rule, r in results.items():
        s, b = r["stats"], r["boot"]
        ci_clears = s["win_rate_lo"] > s["breakeven_win_rate"]
        if s["edge"] > 0.03 and ci_clears and s["p_value"] < 0.05:
            verdict = f"✅ 엣지 확인 ({s['edge']*100:+.1f}%p) — 승률 신뢰구간 하단도 손익분기 상회"
        elif s["edge"] > 0:
            why = "승률 신뢰구간 하단이 손익분기 미달" if not ci_clears else f"기대값 p값 {s['p_value']:.3f}"
            verdict = f"⚠️ 엣지 미확정 ({s['edge']*100:+.1f}%p) — {why}, 실전 슬리피지로 소멸 가능"
        else:
            verdict = f"❌ 엣지 없음 ({s['edge']*100:+.1f}%p) — 비용 차감 후 기대값 마이너스, 실자금 투입 부적합"
        lines.append(f"- **{rule}**: {verdict}")
        lines.append(f"  - 승률 {s['win_rate']*100:.1f}% (95% CI {s['win_rate_lo']*100:.1f}~{s['win_rate_hi']*100:.1f}%), "
                     f"손익분기 {s['breakeven_win_rate']*100:.1f}%, 기대값 p값 {s['p_value']:.3f}")
        lines.append(f"  - {args.horizon:.0f}년 내 {fmt_won(target)}원 도달확률 {b['reach']*100:.1f}%, "
                     f"반토막({fmt_won(capital*0.5)}원) 확률 {b['ruin']*100:.1f}%")

    span_years = next(iter(results.values()))["stats"]["years"]
    if span_years < 2.0:
        lines += ["",
                  f"> ⚠️ **검증기간 {span_years:.1f}년** — 상승장·하락장을 모두 거치지 않았다. "
                  f"위 '엣지 확인' 판정은 한 가지 시장 레짐에서만 성립한 것이므로 그대로 신뢰하면 안 된다. "
                  f"`multi_period_validation.md` 가 보여주듯 이 레포의 다른 전략도 2024-25년만 양수였고 "
                  f"2021~2023년에는 손실이었다. `--source fdr --years 3` 이상으로 재검증하라."]

    lines += ["", "## 6. 한계", "",
              "- 일봉 기반이라 장중 손절·익절 **체결 순서**를 알 수 없다. 동일봉 양방향 터치는 손절 우선으로 가정했으나 실제는 더 나쁠 수도 있다.",
              "- 호가 슬리피지·거래정지·상하한가 미반영. 왕복 0.3%는 대형주 기준이며 소형주 단타는 더 크다.",
              "- 유니버스가 생존 종목 위주라면 생존 편향(survivorship bias)이 성과를 과대평가한다.",
              "- 부트스트랩은 트레이드를 독립 추출하므로 **연속 손실(losing streak)의 군집성**을 과소평가한다. 실제 MDD는 더 깊을 수 있다.",
              "- 표본이 수백 건 수준이면 승률 신뢰구간이 넓다. 신뢰구간 하단이 손익분기승률보다 낮으면 '엣지 있음'이라고 단정할 수 없다.",
              "- 오프라인 폴백(`data/stock_*.csv`)은 스냅샷마다 수정주가 배수가 달라 종목별 단일 파일만 쓴다. 기간이 1년 남짓이라 **레짐 1개만 검증**된 셈이므로, 실제 판단은 `--source fdr --years 3` 이상으로 다시 돌려서 하라.", ""]

    path = os.path.join(OUT_DIR, "strategy_winrate_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"리포트 저장: {path}")
    print(f"트레이드 원본: {OUT_DIR}/trades_<룰>.csv")


if __name__ == "__main__":
    main()
