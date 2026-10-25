"""
price_frame.py - 가격 프레임 정규화 유틸

요청한 종목과 실제 데이터가 어긋나는 사고를 막는다.

배경:
    yfinance / FDR 은 여러 심볼을 담은 프레임을 MultiIndex 컬럼
    (필드, 티커) 형태로 돌려준다. 코드베이스 전반에서 이걸 이렇게 평탄화했다.

        df.columns = df.columns.get_level_values(0)   # 티커 레벨을 버림
        df = df.loc[:, ~df.columns.duplicated()]      # 같은 이름 중 첫 번째만

    티커 레벨을 버리면 컬럼명이 Close/Close/... 로 중복되고, 이어지는 중복
    제거가 '위치상 첫 번째'를 남긴다. 즉 요청한 종목이 아니라 **프레임에서 먼저
    오는 자산**이 선택된다. 파일명은 요청한 티커로 저장되므로 아무 에러 없이
    내용만 뒤바뀐다.

    실제로 data/ 스냅샷에서 stock_005930_KS_20260415.csv 가 닛케이225,
    stock_000270_KS_20260508.csv 가 S&P500, stock_012450_KS_20260415.csv 가
    DAX 시계열이었다(종가 배수 1.0000, 최대편차 0.0000).

따라서 티커 레벨을 버리지 않고 **요청한 티커의 컬럼만 골라낸다.**
고를 수 없으면 PriceFrameMismatch 를 올려서, 호출부가 조용히 잘못된 데이터를
쓰는 대신 로그를 남기고 건너뛰게 한다.
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class PriceFrameMismatch(ValueError):
    """요청한 티커의 데이터임을 확인할 수 없을 때"""


def ticker_aliases(ticker: str) -> set:
    """'005930.KS' → {'005930.KS', '005930', '005930.KQ', ...} 비교용 표기 집합"""
    t = str(ticker).strip()
    base = t
    for suffix in (".KS", ".KQ", ".KN", ".KP", "_KS", "_KQ", "_KN", "_KP"):
        if base.upper().endswith(suffix):
            base = base[: -len(suffix)]
            break
    out = {t, t.upper(), base, base.upper()}
    if base.isdigit() and len(base) == 6:
        out |= {f"{base}{s}" for s in (".KS", ".KQ", ".KN", "_KS", "_KQ")}
    return {x for x in out if x}


def _dedupe_identical(df: pd.DataFrame) -> pd.DataFrame:
    """이름이 같고 값까지 같은 컬럼만 정리한다 (값이 다르면 손대지 않는다)."""
    if not df.columns.duplicated().any():
        return df
    keep, seen = [], {}
    for i, name in enumerate(df.columns):
        if name not in seen:
            seen[name] = i
            keep.append(i)
            continue
        if df.iloc[:, seen[name]].equals(df.iloc[:, i]):
            continue                       # 완전히 동일한 중복 → 버려도 안전
        raise PriceFrameMismatch(
            f"'{name}' 컬럼이 서로 다른 값으로 중복됨 — 여러 자산이 섞인 프레임"
        )
    return df.iloc[:, keep]


def flatten_price_columns(df, ticker: str):
    """
    MultiIndex 컬럼을 요청한 티커 기준으로 안전하게 평탄화한다.

    - 단일 레벨 컬럼이면 그대로 반환
    - 프레임에 심볼이 하나뿐이면 그 레벨을 떼고 반환
    - 여러 심볼이 있으면 요청한 티커의 컬럼만 선택
    - 선택할 수 없으면 PriceFrameMismatch

    반환: 평탄화된 DataFrame (빈 프레임/None 은 그대로 돌려준다)
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    if not isinstance(df.columns, pd.MultiIndex):
        return _dedupe_identical(df)

    aliases = ticker_aliases(ticker)

    # 어느 레벨이 '심볼' 레벨인지 찾는다 (요청 티커를 담고 있는 레벨)
    for level in range(df.columns.nlevels):
        values = list(dict.fromkeys(df.columns.get_level_values(level)))
        if len(values) == 1:
            # 심볼이 하나뿐인 프레임 → 그 레벨만 떼면 된다
            other = [l for l in range(df.columns.nlevels) if l != level]
            if other:
                picked = df.copy()
                picked.columns = picked.columns.droplevel(level)
                return _dedupe_identical(picked)
        hit = [v for v in values if str(v) in aliases or str(v).upper() in aliases]
        if hit:
            picked = df.xs(hit[0], axis=1, level=level, drop_level=True)
            if isinstance(picked, pd.Series):
                picked = picked.to_frame()
            logger.debug(f"[프레임] {ticker}: 레벨 {level} 에서 '{hit[0]}' 컬럼 선택")
            return _dedupe_identical(picked)

    symbols = {l: list(dict.fromkeys(df.columns.get_level_values(l)))
               for l in range(df.columns.nlevels)}
    raise PriceFrameMismatch(
        f"요청 티커 '{ticker}' 를 프레임에서 찾을 수 없음 — 다른 자산의 데이터일 수 있음. "
        f"프레임 심볼: {symbols}"
    )


def safe_flatten(df, ticker: str, *, context: str = ""):
    """
    flatten_price_columns 의 예외 비발생 버전.
    맞출 수 없으면 경고를 남기고 빈 DataFrame 을 돌려준다(잘못된 데이터를 쓰지 않도록).
    """
    try:
        return flatten_price_columns(df, ticker)
    except PriceFrameMismatch as e:
        logger.error(f"[프레임 불일치] {context or ticker}: {e}")
        return pd.DataFrame()
