import os
import logging
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DART_API_KEY = os.getenv("DART_API_KEY", "")

def get_technical(code: str) -> dict:
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")
        df = fdr.DataReader(code, start)
        if df is None or df.empty or len(df) < 5:
            return {}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close_col = next((c for c in ["Close","Adj Close"] if c in df.columns), None)
        vol_col = next((c for c in ["Volume"] if c in df.columns), None)
        if not close_col:
            return {}
        closes = df[close_col].dropna().astype(float)
        price = float(closes.iloc[-1])

        def safe(s, i=-1):
            try:
                v = s.iloc[i]
                return float(v) if not pd.isna(v) else 0.0
            except: return 0.0

        ma5   = safe(closes.rolling(5).mean())
        ma20  = safe(closes.rolling(20).mean())
        ma60  = safe(closes.rolling(60).mean()) if len(closes)>=60 else ma20
        ma120 = safe(closes.rolling(120).mean()) if len(closes)>=120 else ma60

        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = safe(100 - 100/(1+gain/(loss+1e-10)))

        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9, adjust=False).mean()
        macd_val = safe(macd)
        sig_val  = safe(sig)

        bb_mid = safe(closes.rolling(20).mean())
        bb_std = safe(closes.rolling(20).std())
        bb_up  = bb_mid + 2*bb_std
        bb_dn  = bb_mid - 2*bb_std
        bb_pct = (price-bb_dn)/(bb_up-bb_dn)*100 if (bb_up-bb_dn)>0 else 50

        def ret(n):
            if len(closes)<=n: return 0.0
            p = float(closes.iloc[-1-n])
            return round((price/p-1)*100,2) if p>0 else 0.0

        vol_ratio = 0.0
        if vol_col and vol_col in df.columns:
            vols = df[vol_col].dropna().astype(float)
            if len(vols)>=20:
                avg = float(vols.rolling(20).mean().iloc[-1])
                vol_ratio = round(float(vols.iloc[-1])/avg,2) if avg>0 else 0.0

        tail252 = closes.tail(252)
        w52h = float(tail252.max())
        w52l = float(tail252.min())
        w52pct = (price-w52l)/(w52h-w52l)*100 if (w52h-w52l)>0 else 50
        mdd = float((closes/closes.cummax()-1).min()*100)

        return {
            "price":round(price,0),
            "ma5":round(ma5,0),"ma20":round(ma20,0),
            "ma60":round(ma60,0),"ma120":round(ma120,0),
            "ma5_above":price>ma5,"ma20_above":price>ma20,
            "ma60_above":price>ma60,"ma120_above":price>ma120,
            "ma_score":int(price>ma5)+int(price>ma20)+int(price>ma60)+int(price>ma120),
            "rsi":round(rsi,1),
            "macd":round(macd_val,2),"macd_signal":round(sig_val,2),
            "macd_hist":round(macd_val-sig_val,2),
            "macd_cross":"golden" if macd_val>sig_val else "dead",
            "bb_upper":round(bb_up,0),"bb_mid":round(bb_mid,0),
            "bb_lower":round(bb_dn,0),"bb_pct":round(bb_pct,1),
            "vol_ratio":vol_ratio,
            "ret_1d":ret(1),"ret_1w":ret(5),
            "ret_1m":ret(22),"ret_3m":ret(66),"ret_1y":ret(252),
            "mdd":round(mdd,2),
            "w52_high":round(w52h,0),"w52_low":round(w52l,0),
            "w52_pct":round(w52pct,1),
        }
    except Exception as e:
        logger.error(f"[기술지표] {code}: {e}")
        return {}

def get_valuation_naver(code: str) -> dict:
    try:
        import FinanceDataReader as fdr
        # 1. 시가총액 및 기본 지표 수집 (FDR 활용)
        df_list = fdr.StockListing('KRX')
        row = df_list[df_list['Code'] == code]
        
        mkt_cap = 0
        if not row.empty:
            mkt_cap = int(row.iloc[0]['MarCap']) # 시가총액(원 단위)
            
        # 2. 네이버 상세 정보 크롤링 (보완용)
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        res = requests.get(url, headers=headers, timeout=8)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        
        result = {"per": 0, "pbr": 0, "roe": 0, "market_cap_str": "--"}
        
        if mkt_cap > 0:
            if mkt_cap >= 10**12:
                result["market_cap_str"] = f"{mkt_cap // 10**12}조 {(mkt_cap % 10**12) // 10**8}억"
            else:
                result["market_cap_str"] = f"{mkt_cap // 10**8}억"
        
        # 주요 지표 추출 (aside 섹션)
        aside = soup.select_one(".aside_invest_info")
        if aside:
            for em in aside.select("em"):
                txt = em.parent.get_text()
                val = em.get_text(strip=True).replace(",","")
                try:
                    v = float(val)
                    if "PER" in txt and "추정" not in txt: result["per"] = v
                    elif "PBR" in txt: result["pbr"] = v
                    elif "ROE" in txt: result["roe"] = v
                except: pass
        
        # === FDR 폴백 (반드시 실행) ===
        try:
            import FinanceDataReader as fdr
            krx = fdr.StockListing('KRX')
            match = krx[krx['Code'] == code]
            if not match.empty:
                row = match.iloc[0]
                
                # PER
                if (not result.get('per') or result['per'] == 0):
                    val = row.get('PER', 0)
                    if pd.notna(val) and val and float(val) > 0:
                        result['per'] = round(float(val), 2)
                
                # PBR
                if (not result.get('pbr') or result['pbr'] == 0):
                    val = row.get('PBR', 0)
                    if pd.notna(val) and val and float(val) > 0:
                        result['pbr'] = round(float(val), 2)
                
                # ROE
                if (not result.get('roe') or result['roe'] == 0):
                    val = row.get('ROE', 0)
                    if pd.notna(val):
                        result['roe'] = round(float(val), 2)
                
                # 시가총액
                marcap = row.get('Marcap', 0)
                if pd.notna(marcap) and marcap and float(marcap) > 0:
                    mc = float(marcap)
                    result['market_cap'] = mc
                    # 가독성 있는 문자열
                    if mc >= 1_000_000_000_000:
                        result['market_cap_str'] = f"{mc / 1_000_000_000_000:.2f}조원"
                    elif mc >= 100_000_000:
                        result['market_cap_str'] = f"{mc / 100_000_000:.0f}억원"
                    else:
                        result['market_cap_str'] = f"{mc:,.0f}원"
                
                logger.info(f"[밸류에이션 FDR 폴백] {code}: PER={result.get('per')}, PBR={result.get('pbr')}, MC={result.get('market_cap_str')}")
        except Exception as e:
            logger.warning(f"[밸류에이션 FDR 폴백 실패] {code}: {e}")
        
        return result
    except Exception as e:
        logger.error(f"[밸류에이션] {code}: {e}")
        return {"per": 0, "pbr": 0, "roe": 0, "market_cap_str": "--"}

def get_supply_naver(code: str) -> dict:
    try:
        # 네이버 금융의 수급 데이터를 더 확실하게 가져오기 위해 
        # 모바일용 데이터 API URL을 사용합니다.
        url = f"https://m.stock.naver.com/api/stock/{code}/investor"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
            "Referer": f"https://m.stock.naver.com/kr/stock/{code}/investor"
        }
        res = requests.get(url, headers=headers, timeout=8)
        data = res.json()
        
        rows = []
        cum5 = {"individual": 0, "foreign": 0, "institution": 0}
        
        items = data.get("items", [])
        for item in items[:10]:
            r = {
                "date": item.get("dealDate"),
                "individual": int(item.get("individualNetPurchaseAmount") or 0),
                "foreign": int(item.get("foreignNetPurchaseAmount") or 0),
                "institution": int(item.get("institutionNetPurchaseAmount") or 0),
            }
            rows.append(r)
            
        for r in rows[:5]:
            cum5["individual"] += r["individual"]
            cum5["foreign"] += r["foreign"]
            cum5["institution"] += r["institution"]
            
        f_pct = float(items[0].get("foreignOwnRate") or 0) if items else 0.0

        return {"daily": rows, "foreign_pct": f_pct, "cum_5d": cum5}
    except Exception as e:
        logger.error(f"[수급] {code}: {e}")
        return {"daily": [], "foreign_pct": 0.0, "cum_5d": {"individual": 0, "foreign": 0, "institution": 0}}

def get_dart_financials(code: str) -> dict:
    if not DART_API_KEY: return {"revenue":0, "operating_income":0, "net_income":0, "op_margin":0, "debt_ratio":0}
    try:
        # 기업 코드 검색
        res = requests.get("https://opendart.fss.or.kr/api/company.json", params={"crtfc_key": DART_API_KEY, "stock_code": code}, timeout=8)
        c_data = res.json()
        if c_data.get("status") != "000": return {"revenue":0, "operating_income":0, "net_income":0, "op_margin":0, "debt_ratio":0}
        c_code = c_data.get("corp_code")
        
        year = str(datetime.now().year - 1)
        # 1. 주요재무상태 (SinglAcnt)
        res = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json", 
                           params={"crtfc_key": DART_API_KEY, "corp_code": c_code, "bsns_year": year, "reprt_code": "11011"}, timeout=10)
        data = res.json()
        
        result = {"year": year, "revenue":0, "operating_income":0, "net_income":0, "total_assets":0, "total_debt":0, "total_equity":0, "op_margin":0, "debt_ratio":0}
        
        if data.get("status") == "000":
            for item in data.get("list", []):
                nm = item.get("account_nm","")
                try: val = int(str(item.get("thstrm_amount","0")).replace(",",""))
                except: continue
                if "매출액" in nm or "수익" in nm: result["revenue"] = val
                elif "영업이익" in nm: result["operating_income"] = val
                elif "당기순이익" in nm: result["net_income"] = val

        # 2. 부채비율 등을 위한 전체 계정 (SinglAcntAll)
        if result["revenue"] == 0 or result["total_debt"] == 0:
            res_all = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", 
                                   params={"crtfc_key": DART_API_KEY, "corp_code": c_code, "bsns_year": year, "reprt_code": "11011", "fs_div": "CFS"}, timeout=10)
            data_all = res_all.json()
            if data_all.get("status") == "000":
                for item in data_all.get("list", []):
                    nm = item.get("account_nm","").replace(" ","")
                    try: val = int(str(item.get("thstrm_amount","0")).replace(",",""))
                    except: continue
                    if ("매출액" in nm or "수익" in nm) and result["revenue"] == 0: result["revenue"] = val
                    elif "영업이익" in nm and result["operating_income"] == 0: result["operating_income"] = val
                    elif "자산총계" in nm: result["total_assets"] = val
                    elif "부채총계" in nm: result["total_debt"] = val
                    elif "자본총계" in nm: result["total_equity"] = val

        if result["revenue"] > 0: result["op_margin"] = round(result["operating_income"] / result["revenue"] * 100, 2)
        if result["total_equity"] > 0: result["debt_ratio"] = round(result["total_debt"] / result["total_equity"] * 100, 2)
        
        return result
    except Exception as e:
        logger.error(f"[DART] {code}: {e}")
        return {"revenue":0, "operating_income":0, "net_income":0, "op_margin":0, "debt_ratio":0}





def get_full_analysis(ticker: str) -> dict:
    code = ticker.replace(".KS","").replace(".KQ","").replace(".KP","")
    tech   = get_technical(code)
    val    = get_valuation_naver(code)
    supply = get_supply_naver(code)
    dart   = get_dart_financials(code)

    risk_flags = []
    risk_score = 0
    debt = dart.get("debt_ratio", 0)
    if debt > 200:
        risk_flags.append({"label":"부채비율 과다","value":f"{debt:.0f}%","level":"danger"})
        risk_score += 30
    elif debt > 100:
        risk_flags.append({"label":"부채비율 주의","value":f"{debt:.0f}%","level":"warning"})
        risk_score += 15
    if dart.get("net_income",0) < 0:
        risk_flags.append({"label":"당기순손실","value":f"{dart.get('net_income',0):,}원","level":"danger"})
        risk_score += 25
    if tech.get("mdd",0) < -50:
        risk_flags.append({"label":"최대낙폭 과다","value":f"{tech['mdd']:.1f}%","level":"danger"})
        risk_score += 20
    per = val.get("per",0)
    if per > 100 and per > 0:
        risk_flags.append({"label":"PER 고평가","value":f"{per:.1f}배","level":"warning"})
        risk_score += 10
    risk_level = "안전" if risk_score<20 else "주의" if risk_score<50 else "위험"

    score_items = []
    if tech:
        score_items.append({"label":"이동평균","score":tech.get("ma_score",0)*25,"max":100})
        rsi_v = tech.get("rsi",50)
        score_items.append({"label":"RSI","score":round(max(0,100-abs(rsi_v-50)*2),0),"max":100})
        score_items.append({"label":"MACD","score":70 if tech.get("macd_cross")=="golden" else 30,"max":100})
        score_items.append({"label":"볼린저밴드","score":round(min(100,max(0,100-abs(tech.get("bb_pct",50)-50))),0),"max":100})
    if val:
        per_v = val.get("per",0)
        score_items.append({"label":"PER","score":80 if 5<per_v<20 else 50 if 0<per_v<30 else 20,"max":100})
        roe_v = val.get("roe",0)
        score_items.append({"label":"ROE","score":min(100,max(0,round(roe_v*5,0))),"max":100})

    total_score = round(sum(s["score"] for s in score_items)/len(score_items),1) if score_items else 50

    return {
        "ticker":  ticker,
        "code":    code,
        "summary": {
            "total_score": total_score,
            "grade": "매우좋음" if total_score>=80 else "좋음" if total_score>=60 else "보통" if total_score>=40 else "주의",
            "score_items": score_items,
            "ret_summary": {
                "1d":tech.get("ret_1d",0),"1w":tech.get("ret_1w",0),
                "1m":tech.get("ret_1m",0),"3m":tech.get("ret_3m",0),"1y":tech.get("ret_1y",0),
            }
        },
        "risk":      {"score":risk_score,"level":risk_level,"flags":risk_flags},
        "supply":    supply,
        "technical": tech,
        "valuation": val,
        "dart":      dart,
    }
