# Quant AI Dashboard Issue Report

## 1. Issue Description
- **Symptoms**: The React dashboard shows no data (empty lists and charts) even after clicking the refresh button.
- **Goal**: Real-time market data monitoring and AI-driven trade signal visualization.
- **Platform**: Flask (Backend) + React/Vite (Frontend)

## 2. Error Logs (app.log)
```text
[ERROR] __main__ - [업데이트 오류] unsupported operand type(s) for /: 'NoneType' and 'int'
[ERROR] stock_data - [주가 수집 오류] ^GDAXI: Cannot set a DataFrame with multiple columns to the single column MA5
[ERROR] kakao_alert - [카카오 발송 실패: 401 - {"msg":"this access token does not exist","code":-401}
```

## 3. Key Source Code

### backend/app.py (Main Entry)
- Handles data update loop and API endpoints. 
- `_update_all()` function performs data collection.

### backend/stock_data.py (Data Collector)
- Uses `yfinance` to fetch OHLCV. 
- Encountered issues with `MultiIndex` columns and `MA5` calculation.

### backend/external_data.py (Macro & Events)
- Scrapes CNN Fear & Greed, FedWatch, etc.
- Encountered `NoneType` division errors during calculation.

### backend/config.py (Settings)
- Contains `GLOBAL_TICKERS` and `STRATEGY` mappings.

### frontend/src/App.jsx (React UI)
- Fetches data from `http://localhost:5000/api/dashboard`.

## 4. Current Attempts by Antigravity (AI Assistant)
- Added None-checks in `app.py` and `external_data.py` (e.g., `(value or 0) / (count or 1)`).
- Reverted Google GenAI SDK to `google-generativeai` due to versioning issues.
- Fixed `App.jsx` navigation which was not rendering sections based on `activeNav`.
- Expanded monitored tickers to include both indices and individual stocks.

## 5. Question for Claude
"I am building a Quant AI system using Flask and React. My assistant updated the code to handle MultiIndex columns in yfinance and NoneType division errors, but the dashboard still shows no data. Could you review the backend update logic and suggest why the `_cache` might still be empty or why the API might not be delivering the expected results?"

---
*Note: Refer to the full files in the repository for detailed logic.*
