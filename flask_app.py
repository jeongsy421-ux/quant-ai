"""
KOSPI 100 Backtest - Flask Web App
핸드폰 브라우저에서 백테스트를 실행하고 결과를 확인할 수 있는 웹 앱.

사용법:
  [로컬]  python flask_app.py
  [PythonAnywhere] WSGI에서 from flask_app import app as application
"""
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── 상태 관리 ──
backtest_status = {
    "running": False,
    "last_run": None,
    "last_summary": None,
    "last_csv_path": None,
    "error": None,
    "progress": ""
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results")


def run_backtest_task():
    """백그라운드 스레드에서 백테스트 실행"""
    global backtest_status
    backtest_status["running"] = True
    backtest_status["error"] = None
    backtest_status["progress"] = "백테스트 시작 중..."

    try:
        from backtest_april2020 import main
        summary, csv_path = main(output_dir=OUTPUT_DIR)
        backtest_status["last_summary"] = summary
        backtest_status["last_csv_path"] = csv_path
        backtest_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        backtest_status["progress"] = "완료"
    except Exception as e:
        backtest_status["error"] = str(e)
        backtest_status["progress"] = f"에러: {e}"
    finally:
        backtest_status["running"] = False


# ── HTML 모바일 UI ──
MOBILE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KOSPI 100 Backtest</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', sans-serif;
    background: #0a0a0f;
    color: #e0e0e0;
    min-height: 100vh;
    padding: 20px;
  }
  .header {
    text-align: center;
    padding: 30px 0 20px;
  }
  .header h1 {
    font-size: 1.5rem;
    background: linear-gradient(135deg, #00d4ff, #7c3aed);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 6px;
  }
  .header p { font-size: 0.85rem; color: #888; }
  .card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 20px;
    margin: 16px 0;
    backdrop-filter: blur(10px);
  }
  .status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
  }
  .badge-idle { background: rgba(100,100,100,0.3); color: #aaa; }
  .badge-running { background: rgba(0,212,255,0.2); color: #00d4ff; animation: pulse 1.5s infinite; }
  .badge-done { background: rgba(0,200,80,0.2); color: #00c850; }
  .badge-error { background: rgba(255,60,60,0.2); color: #ff3c3c; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
  .btn {
    display: block;
    width: 100%;
    padding: 16px;
    border: none;
    border-radius: 12px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    margin: 10px 0;
    transition: all 0.2s;
    font-family: inherit;
  }
  .btn:active { transform: scale(0.97); }
  .btn-primary {
    background: linear-gradient(135deg, #7c3aed, #00d4ff);
    color: #fff;
  }
  .btn-primary:disabled {
    background: #333;
    color: #666;
    cursor: not-allowed;
  }
  .btn-secondary {
    background: rgba(255,255,255,0.06);
    color: #ccc;
    border: 1px solid rgba(255,255,255,0.1);
  }
  .result-box {
    background: rgba(0,0,0,0.3);
    border-radius: 10px;
    padding: 14px;
    margin-top: 12px;
    font-size: 0.8rem;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 50vh;
    overflow-y: auto;
    color: #c0ffc0;
    font-family: 'Courier New', monospace;
  }
  .info-row {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 0.85rem;
  }
  .info-row:last-child { border: none; }
  .info-label { color: #888; }
  .info-value { color: #e0e0e0; font-weight: 600; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #00d4ff;
    border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 6px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="header">
    <h1>📈 KOSPI 100 Backtest</h1>
    <p>April 2020 · KIS API · Ensemble ML</p>
  </div>

  <div class="card">
    <div class="info-row">
      <span class="info-label">상태</span>
      <span id="statusBadge" class="status-badge badge-idle">대기 중</span>
    </div>
    <div class="info-row">
      <span class="info-label">마지막 실행</span>
      <span id="lastRun" class="info-value">-</span>
    </div>
    <div class="info-row">
      <span class="info-label">진행 상황</span>
      <span id="progress" class="info-value">-</span>
    </div>
  </div>

  <button id="runBtn" class="btn btn-primary" onclick="runBacktest()">
    🚀 백테스트 실행
  </button>
  <button class="btn btn-secondary" onclick="refreshStatus()">
    🔄 상태 새로고침
  </button>
  <button class="btn btn-secondary" onclick="downloadCSV()">
    📥 결과 CSV 다운로드
  </button>

  <div id="resultCard" class="card" style="display:none;">
    <h3 style="font-size:0.95rem; margin-bottom:10px;">📊 분석 결과</h3>
    <div id="resultBox" class="result-box"></div>
  </div>

<script>
  let pollTimer = null;

  async function runBacktest() {
    const btn = document.getElementById('runBtn');
    btn.disabled = true;
    btn.textContent = '⏳ 실행 중...';
    try {
      const res = await fetch('/api/run', { method: 'POST' });
      const data = await res.json();
      if (data.error) { alert(data.error); btn.disabled = false; btn.textContent = '🚀 백테스트 실행'; return; }
      startPolling();
    } catch(e) { alert('요청 실패: ' + e); btn.disabled = false; btn.textContent = '🚀 백테스트 실행'; }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refreshStatus, 3000);
  }

  async function refreshStatus() {
    try {
      const res = await fetch('/api/status');
      const d = await res.json();
      const badge = document.getElementById('statusBadge');
      const btn = document.getElementById('runBtn');

      if (d.running) {
        badge.className = 'status-badge badge-running';
        badge.innerHTML = '<span class="spinner"></span>실행 중';
        btn.disabled = true; btn.textContent = '⏳ 실행 중...';
      } else if (d.error) {
        badge.className = 'status-badge badge-error';
        badge.textContent = '에러';
        btn.disabled = false; btn.textContent = '🚀 백테스트 실행';
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      } else if (d.last_run) {
        badge.className = 'status-badge badge-done';
        badge.textContent = '완료';
        btn.disabled = false; btn.textContent = '🚀 백테스트 실행';
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      } else {
        badge.className = 'status-badge badge-idle';
        badge.textContent = '대기 중';
        btn.disabled = false; btn.textContent = '🚀 백테스트 실행';
      }

      document.getElementById('lastRun').textContent = d.last_run || '-';
      document.getElementById('progress').textContent = d.progress || '-';

      if (d.last_summary) {
        document.getElementById('resultCard').style.display = 'block';
        document.getElementById('resultBox').textContent = d.last_summary;
      }
    } catch(e) { console.error(e); }
  }

  async function downloadCSV() {
    try {
      const res = await fetch('/api/status');
      const d = await res.json();
      if (!d.has_csv) { alert('아직 결과 파일이 없습니다.'); return; }
      window.location.href = '/api/download';
    } catch(e) { alert('다운로드 실패'); }
  }

  refreshStatus();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return Response(MOBILE_HTML, content_type="text/html; charset=utf-8")


@app.route("/api/run", methods=["POST"])
def api_run():
    if backtest_status["running"]:
        return jsonify({"error": "이미 실행 중입니다.", "running": True})
    t = threading.Thread(target=run_backtest_task, daemon=True)
    t.start()
    return jsonify({"message": "백테스트가 시작되었습니다.", "running": True})


@app.route("/api/status")
def api_status():
    has_csv = backtest_status["last_csv_path"] and os.path.exists(backtest_status["last_csv_path"])
    return jsonify({
        "running": backtest_status["running"],
        "last_run": backtest_status["last_run"],
        "last_summary": backtest_status["last_summary"],
        "progress": backtest_status["progress"],
        "error": backtest_status["error"],
        "has_csv": has_csv
    })


@app.route("/api/download")
def api_download():
    csv_path = backtest_status["last_csv_path"]
    if csv_path and os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name="kospi100_backtest_april2020.csv")
    return jsonify({"error": "결과 파일이 없습니다."}), 404


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    print(f"\n📱 핸드폰에서 접속: http://<서버IP>:{port}")
    print(f"   로컬 테스트: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
