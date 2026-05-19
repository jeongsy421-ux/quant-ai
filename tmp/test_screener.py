import sys
sys.path.append('c:/Users/jihun/Desktop/quant_ai/backend')
from app import market_screener
import logging
logging.basicConfig(level=logging.INFO)
res = market_screener.run_screen()
print(f"\n[Status] {res['status']}, Risk On: {res['is_risk_on']}")
for r in res.get('all_results', []):
    if r['signal'] == 'BUY':
        print(f"[{r['name']}] Score: {r['score']} Reasons: {r['reasons']}")

