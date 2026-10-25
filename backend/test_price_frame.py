"""
test_price_frame.py - 티커/데이터 불일치 회귀 테스트

과거 사고: data/stock_005930_KS_20260415.csv 에 닛케이225 시계열이 저장돼 있었다.
원인은 MultiIndex 컬럼에서 티커 레벨을 버리고 중복 컬럼을 위치로 추려낸 것.
이 테스트는 그 상황을 재현하고, 이제는 요청한 종목이 선택되는지 확인한다.

    python test_price_frame.py        (또는 pytest test_price_frame.py)
"""
import numpy as np
import pandas as pd
import pytest

from price_frame import (PriceFrameMismatch, flatten_price_columns,
                         safe_flatten, ticker_aliases)

DATES = pd.date_range("2025-01-01", periods=60, freq="B")
SAMSUNG_LAST = 60000.0
NIKKEI_LAST = 42000.0


def multi_frame(order):
    """yfinance 가 여러 심볼을 받을 때 만드는 (필드, 티커) MultiIndex 재현"""
    series = {
        "005930.KS": pd.Series(np.linspace(55000, SAMSUNG_LAST, 60), index=DATES),
        "^N225":     pd.Series(np.linspace(37000, NIKKEI_LAST, 60), index=DATES),
    }
    cols, data = [], {}
    for field in ["Open", "High", "Low", "Close", "Volume"]:
        for tkr in order:
            cols.append((field, tkr))
            data[(field, tkr)] = (pd.Series(1e6, index=DATES) if field == "Volume"
                                  else series[tkr])
    df = pd.DataFrame(data, index=DATES)
    df.columns = pd.MultiIndex.from_tuples(cols)
    return df


@pytest.mark.parametrize("order", [["005930.KS", "^N225"], ["^N225", "005930.KS"]])
def test_요청한_종목이_선택된다(order):
    """컬럼 순서가 바뀌어도 요청한 종목의 데이터가 나와야 한다 (과거 버그 지점)"""
    out = flatten_price_columns(multi_frame(order), "005930.KS")
    assert float(out["Close"].iloc[-1]) == pytest.approx(SAMSUNG_LAST)


@pytest.mark.parametrize("requested", ["005930", "005930.KS", "005930.KQ"])
def test_접미사가_달라도_매칭된다(requested):
    out = flatten_price_columns(multi_frame(["^N225", "005930.KS"]), requested)
    assert float(out["Close"].iloc[-1]) == pytest.approx(SAMSUNG_LAST)


def test_없는_종목이면_예외():
    """프레임에 요청 종목이 없으면 조용히 다른 자산을 주는 대신 예외"""
    with pytest.raises(PriceFrameMismatch):
        flatten_price_columns(multi_frame(["^N225", "005930.KS"]), "000660")


def test_safe_flatten_은_빈_프레임():
    """예외 비발생 버전은 빈 프레임을 준다 (잘못된 데이터를 쓰지 않도록)"""
    assert safe_flatten(multi_frame(["^N225", "005930.KS"]), "000660").empty


def test_단일_심볼_프레임은_평탄화된다():
    df = multi_frame(["005930.KS"])
    out = flatten_price_columns(df, "005930.KS")
    assert not isinstance(out.columns, pd.MultiIndex)
    assert float(out["Close"].iloc[-1]) == pytest.approx(SAMSUNG_LAST)


def test_단일_레벨_프레임은_그대로():
    df = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5,
                       "Volume": 100.0}, index=DATES)
    out = flatten_price_columns(df, "005930")
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_값이_다른_중복컬럼은_예외():
    """이름이 같은데 값이 다르면 여러 자산이 섞인 것 → 임의로 하나 고르지 않는다"""
    df = pd.DataFrame(np.column_stack([np.arange(60.0), np.arange(60.0) * 2]),
                      index=DATES, columns=["Close", "Close"])
    with pytest.raises(PriceFrameMismatch):
        flatten_price_columns(df, "005930")


def test_지표계산_전체경로():
    """StockDataCollector._add_technical_indicators 까지 통과해도 종목이 유지된다"""
    from stock_data import StockDataCollector
    c = StockDataCollector.__new__(StockDataCollector)      # 네트워크 없이 메서드만
    out = c._add_technical_indicators(multi_frame(["^N225", "005930.KS"]), "005930.KS")
    assert float(out["Close"].iloc[-1]) == pytest.approx(SAMSUNG_LAST)
    assert "RSI" in out.columns


def test_ticker_aliases():
    al = ticker_aliases("005930.KS")
    assert {"005930", "005930.KS", "005930.KQ"} <= al


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--no-header", "-q"]))
