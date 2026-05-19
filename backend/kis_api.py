import os
import requests
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

KIS_APP_KEY    = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT    = os.getenv("KIS_ACCOUNT", "")
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"

_access_token   = None
_token_expired  = None

def get_access_token() -> str:
    global _access_token, _token_expired
    if _access_token and _token_expired and datetime.now() < _token_expired:
        return _access_token
    try:
        res = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "grant_type": "client_credentials",
                "appkey":     KIS_APP_KEY,
                "appsecret":  KIS_APP_SECRET,
            }),
            timeout=10
        )
        data = res.json()
        _access_token  = data.get("access_token", "")
        _token_expired = datetime.now() + timedelta(hours=23)
        logger.info("[KIS] 토큰 발급 성공")
        return _access_token
    except Exception as e:
        logger.error(f"[KIS] 토큰 발급 실패: {e}")
        return ""

def get_realtime_price(code: str) -> dict:
    """실시간 현재가 조회"""
    token = get_access_token()
    if not token:
        return {}
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST01010100",
        "custtype":      "P",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            },
            timeout=10
        )
        data = res.json()
        if data.get("rt_cd") != "0":
            return {}
        output = data.get("output", {})
        return {
            "code":       code,
            "price":      int(output.get("stck_prpr", 0)),
            "change":     int(output.get("prdy_vrss", 0)),
            "change_pct": float(output.get("prdy_ctrt", 0)),
            "volume":     int(output.get("acml_vol", 0)),
            "high":       int(output.get("stck_hgpr", 0)),
            "low":        int(output.get("stck_lwpr", 0)),
            "open":       int(output.get("stck_oprc", 0)),
            "time":       datetime.now().strftime("%H:%M:%S"),
        }
    except Exception as e:
        logger.error(f"[KIS] 현재가 실패: {e}")
        return {}

def get_orderbook(code: str) -> dict:
    """실시간 호가창 조회"""
    token = get_access_token()
    if not token:
        return {}
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST01010200",
        "custtype":      "P",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            headers=headers,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            },
            timeout=10
        )
        data = res.json()
        if data.get("rt_cd") != "0":
            return {}
        output = data.get("output1", {})
        asks, bids = [], []
        for i in range(1, 11):
            asks.append({
                "price": int(output.get(f"askp{i}", 0)),
                "qty":   int(output.get(f"askp_rsqn{i}", 0)),
            })
            bids.append({
                "price": int(output.get(f"bidp{i}", 0)),
                "qty":   int(output.get(f"bidp_rsqn{i}", 0)),
            })
        return {"asks": asks, "bids": bids}
    except Exception as e:
        logger.error(f"[KIS] 호가 실패: {e}")
        return {}

def get_minute_chart(code: str) -> list:
    """당일 분봉 데이터 조회"""
    token = get_access_token()
    if not token:
        return []
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST03010200",
        "custtype":      "P",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            headers=headers,
            params={
                "FID_ETC_CLS_CODE":       "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":         code,
                "FID_INPUT_HOUR_1":       datetime.now().strftime("%H%M%S"),
                "FID_PW_DATA_INCU_YN":    "Y",
            },
            timeout=10
        )
        data = res.json()
        if data.get("rt_cd") != "0":
            return []
        result = []
        for row in data.get("output2", []):
            try:
                result.append({
                    "time":   row.get("stck_bsop_date", "") + row.get("stck_cntg_hour", ""),
                    "open":   int(row.get("stck_oprc", 0)),
                    "high":   int(row.get("stck_hgpr", 0)),
                    "low":    int(row.get("stck_lwpr", 0)),
                    "close":  int(row.get("stck_prpr", 0)),
                    "volume": int(row.get("cntg_vol", 0)),
                })
            except:
                continue
        return result
    except Exception as e:
        logger.error(f"[KIS] 분봉 실패: {e}")
        return []

def get_daily_ohlcv(code: str, start: str = "", end: str = "") -> list:
    """
    KIS 일봉 데이터 조회 (국내주식 기간별 시세)
    code: 종목코드 (6자리, 예: 005930)
    start/end: YYYYMMDD 형식
    반환: [{"Date":"2024-01-02","Open":..,"High":..,"Low":..,"Close":..,"Volume":..}, ...]
    """
    token = get_access_token()
    if not token:
        return []
    if not end:
        end = datetime.now().strftime("%Y%m%d")
    if not start:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST03010100",
        "custtype":      "P",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers=headers,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":         code,
                "FID_INPUT_DATE_1":       start,
                "FID_INPUT_DATE_2":       end,
                "FID_PERIOD_DIV_CODE":    "D",
                "FID_ORG_ADJ_PRC":        "0",
            },
            timeout=10
        )
        data = res.json()
        if data.get("rt_cd") != "0":
            logger.warning(f"[KIS] 일봉 조회 실패: {data.get('msg1', '')}")
            return []

        result = []
        for row in data.get("output2", []):
            try:
                date_str = row.get("stck_bsop_date", "")
                if not date_str:
                    continue
                date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                result.append({
                    "Date":   date_fmt,
                    "Open":   int(row.get("stck_oprc", 0)),
                    "High":   int(row.get("stck_hgpr", 0)),
                    "Low":    int(row.get("stck_lwpr", 0)),
                    "Close":  int(row.get("stck_prpr", 0)),
                    "Volume": int(row.get("acml_vol", 0)),
                })
            except:
                continue
        # 날짜 오름차순 정렬
        result.sort(key=lambda x: x["Date"])
        return result
    except Exception as e:
        logger.error(f"[KIS] 일봉 조회 실패: {e}")
        return []

def get_fundamentals(code: str) -> dict:
    """
    KIS 종목 기본정보 조회 (PER, PBR 등)
    code: 종목코드 6자리
    """
    token = get_access_token()
    if not token:
        return {}
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST01010300",
        "custtype":      "P",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor",
            headers=headers,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            },
            timeout=10
        )
        data = res.json()
        if data.get("rt_cd") != "0":
            return {}
        output = data.get("output", {})
        return {
            "per":   float(output.get("per", 0) or 0),
            "pbr":   float(output.get("pbr", 0) or 0),
            "eps":   float(output.get("eps", 0) or 0),
            "bps":   float(output.get("bps", 0) or 0),
        }
    except Exception as e:
        logger.error(f"[KIS] 기본정보 조회 실패: {e}")
        return {}
