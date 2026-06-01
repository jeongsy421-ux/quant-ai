import os
import sys
import logging
import time
from datetime import datetime

# 백엔드 경로 추가
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

import backend.app as app
from backend.config import RANKING_UNIVERSE

logging.basicConfig(level=logging.INFO)

def verify():
    print(">>> 하이브리드 확장 방식 테스트 시작 (100종목)...")
    
    # 1. 업데이트 실행 (시간 측정은 app.py 내부에 포함됨)
    app._update_all()
    
    # 2. 결과 검증 (reassignment 대응을 위해 모듈 변수 직접 접근)
    ranking = app._cache.get("ranking", [])
    signals = app._cache.get("signals", {})
    
    print("\n" + "="*50)
    print(f" {'검증 항목':<20} | {'결과':<20}")
    print("-" * 50)
    print(f" {'랭킹 종목 수':<20} | {len(ranking)}개")
    print(f" {'상세 분석 종목 수':<20} | {len(signals)}개")
    
    # 환율/지수 포함 여부 확인
    invalid_tickers = [r['ticker'] for r in ranking if "^" in r['ticker'] or "=" in r['ticker']]
    print(f" {'부적절 티커 발견':<20} | {len(invalid_tickers)}개")
    if invalid_tickers:
        print(f" [ERROR] 발견된 부적절 티커: {invalid_tickers}")
    else:
        print(f" [OK] 모든 랭킹 종목이 유효한 한국 주식입니다.")
    
    # 랭킹 샘플 출력
    if ranking:
        print("-" * 50)
        print(" [Top 5 랭킹 샘플]")
        for r in ranking[:5]:
            print(f"  {r['rank']}위: {r['ticker']} (Score: {r['score']:.4f}) - {r['status']}")
            
    print("="*50)

if __name__ == "__main__":
    verify()
