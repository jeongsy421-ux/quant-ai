import React, { useState, useEffect, useCallback } from "react";
import {
  TrendingUp, Search, Newspaper, Brain, Briefcase,
  Settings, Bell, RefreshCcw, AlertTriangle, Target,
  LayoutDashboard, Flame, Zap
} from "lucide-react";
import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, Legend
} from "recharts";

const API_URL = "";

const TICKER_MAP = {
  "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
  "005380.KS": "현대차", "035420.KS": "NAVER",
  "000270.KS": "기아", "012450.KS": "한화에어로",
  "034020.KS": "두산에너빌리티", "329180.KS": "HD현대중공업",
  "000001.SS": "상해종합",
};
const THEME_MAP = {
  "005930.KS": "반도체", "000660.KS": "반도체",
  "005380.KS": "자동차", "000270.KS": "자동차",
  "012450.KS": "방산", "034020.KS": "원전",
  "329180.KS": "조선", "035420.KS": "IT",
  "000001.SS": "글로벌",
};

const fmt = (v, d = 0) => (v != null && !isNaN(v) ? Number(v).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }) : "--");
const pct = (v) => (v != null && !isNaN(v) ? `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%` : "--");
const getInfo = (t) => ({ name: TICKER_MAP[t] || t, theme: THEME_MAP[t] || "기타" });

const StockChart = ({ ticker }) => {
  const [chartData, setChartData] = useState(null);
  const [error, setError] = useState(null);
  
  useEffect(() => {
    if (!ticker) return;
    setChartData(null);
    setError(null);
    
    fetch(`${API_URL}/api/stock/${ticker}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        // 응답이 배열인지 확인
        const items = Array.isArray(data) ? data : (data.ohlcv || []);
        if (items.length === 0) throw new Error('데이터 없음');
        
        // 최근 60일 + 대문자 키 사용 + MA가 0인 경우 null로 변환 (차트에서 안 그려지게)
        const formatted = items.slice(-60).map(d => ({
          date: d.Date.slice(5),  // MM-DD
          close: d.Close,
          ma5: d.MA5 > 0 ? d.MA5 : null,
          ma20: d.MA20 > 0 ? d.MA20 : null,
          ma60: d.MA60 > 0 ? d.MA60 : null,
          volume: d.Volume
        }));
        setChartData(formatted);
      })
      .catch(e => {
        console.error('[StockChart]', ticker, e);
        setError(e.message);
      });
  }, [ticker]);
  
  if (error) return (
    <div style={{padding: '2rem', textAlign: 'center', color: '#ef4444'}}>
      차트 로드 실패: {error}
    </div>
  );
  if (!chartData) return (
    <div style={{padding: '2rem', textAlign: 'center'}}>📊 차트 로딩 중...</div>
  );
  
  return (
    <div style={{width: '100%', height: 350, marginTop: '1rem', marginBottom: '1rem'}}>
      <ResponsiveContainer>
        <ComposedChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="date" tick={{fontSize: 11}} />
          <YAxis yAxisId="price" domain={['auto', 'auto']} tick={{fontSize: 11}} />
          <YAxis yAxisId="volume" orientation="right" tick={{fontSize: 11}} />
          <Tooltip 
            formatter={(value, name) => {
              if (value == null) return ['—', name];
              return [value.toLocaleString(), name];
            }}
          />
          <Legend />
          <Bar yAxisId="volume" dataKey="volume" fill="#d1d5db" opacity={0.5} name="거래량" />
          <Line yAxisId="price" type="monotone" dataKey="close" stroke="#000" strokeWidth={2} dot={false} name="종가" />
          <Line yAxisId="price" type="monotone" dataKey="ma5" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="MA5" connectNulls={false} />
          <Line yAxisId="price" type="monotone" dataKey="ma20" stroke="#8b5cf6" strokeWidth={1.5} dot={false} name="MA20" connectNulls={false} />
          <Line yAxisId="price" type="monotone" dataKey="ma60" stroke="#10b981" strokeWidth={1.5} dot={false} name="MA60" connectNulls={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

function StockDetail({ ticker }) {
  const [loading, setLoading] = useState(true);
  const [stockInfo, setStockInfo] = useState(null);
  const [analysis, setAnalysis] = useState(null);

  useEffect(() => {
    let active = true;
    const loadDetail = async () => {
      setLoading(true);
      try {
        const [stockRes, analysisRes] = await Promise.all([
          fetch(`/api/stock/${ticker}?period=3mo`),
          fetch(`/api/analysis/${ticker}`)
        ]);
        if (!active) return;
        
        let stockData = null;
        let analysisData = null;
        
        if (stockRes.ok) stockData = await stockRes.json();
        if (analysisRes.ok) analysisData = await analysisRes.json();
        
        setStockInfo(stockData);
        setAnalysis(analysisData);
      } catch (e) {
        console.error(e);
      } finally {
        if (active) setLoading(false);
      }
    };
    loadDetail();
    return () => { active = false; };
  }, [ticker]);

  if (loading) return <div style={{ padding: '2rem', textAlign: 'center', fontSize: '13px', color: '#888' }}>⏳ 데이터를 불러오는 중...</div>;

  const latestPrice = stockInfo && stockInfo.length > 0 ? stockInfo[stockInfo.length - 1] : null;

  return (
    <div>
      {latestPrice && (
        <div style={{ marginBottom: '1.5rem', background: '#f8f9fb', padding: '1.25rem', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '16px', fontWeight: '800' }}>현재가: {latestPrice.Close?.toLocaleString()}원</div>
            <div style={{ fontSize: '12px', color: '#888', marginTop: '4px' }}>거래량: {latestPrice.Volume?.toLocaleString()}주</div>
          </div>
          {analysis && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '16px', fontWeight: '800', color: '#0081ff' }}>종합 점수: {analysis.summary?.total_score}점</div>
              <div style={{ fontSize: '12px', color: analysis.risk?.level === '안전' ? '#22c55e' : '#f04452', fontWeight: '700', marginTop: '4px' }}>리스크 레벨: {analysis.risk?.level || '보통'}</div>
            </div>
          )}
        </div>
      )}
      
      <StockChart ticker={ticker} />
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '1.5rem' }}>
        <div style={{ border: '1px solid #eee', padding: '1.25rem', borderRadius: '12px', background: '#fff' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '13px', fontWeight: '800', color: '#888' }}>📈 기술지표 요약</h4>
          {analysis?.technical ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>RSI (14)</span><span style={{ fontWeight: '700' }}>{analysis.technical.rsi}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>MA 정배열 스코어</span><span style={{ fontWeight: '700' }}>{analysis.technical.ma_score}/4</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>MACD 크로스</span><span style={{ fontWeight: '700' }}>{analysis.technical.macd_cross === 'golden' ? '골든크로스' : '데드크로스'}</span></div>
            </div>
          ) : <span style={{ fontSize: '12px', color: '#aaa' }}>분석 정보 없음</span>}
        </div>
        
        <div style={{ border: '1px solid #eee', padding: '1.25rem', borderRadius: '12px', background: '#fff' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '13px', fontWeight: '800', color: '#888' }}>💎 밸류에이션 요약</h4>
          {analysis?.valuation ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>PER</span><span style={{ fontWeight: '700' }}>{analysis.valuation.per ? `${analysis.valuation.per}배` : '--'}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>PBR</span><span style={{ fontWeight: '700' }}>{analysis.valuation.pbr ? `${analysis.valuation.pbr}배` : '--'}</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>시가총액</span><span style={{ fontWeight: '700' }}>{analysis.valuation.market_cap_str || '--'}</span></div>
            </div>
          ) : <span style={{ fontSize: '12px', color: '#aaa' }}>밸류에이션 정보 없음</span>}
        </div>
      </div>
    </div>
  );
}

function NavItem({ active, icon, label, onClick, badge }) {
  return (
    <div onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 12, padding: "13px 20px",
      borderRadius: 12, cursor: "pointer", fontSize: 14, marginBottom: 4,
      position: "relative", transition: "0.15s",
      color: active ? "#0081ff" : "#555",
      backgroundColor: active ? "#f0f7ff" : "transparent",
      fontWeight: active ? 800 : 500,
    }}>
      {active && <div style={{ position: "absolute", left: 0, top: "25%", height: "50%", width: 4, backgroundColor: "#0081ff", borderRadius: "0 4px 4px 0" }} />}
      {icon}<span style={{ flex: 1 }}>{label}</span>
      {badge && <span style={{ fontSize: 10, backgroundColor: "#f04452", color: "#fff", borderRadius: 10, padding: "2px 6px", fontWeight: 800 }}>{badge}</span>}
    </div>
  );
}

function SignalBadge({ signal }) {
  const map = {
    BUY: { bg: "#fff1f1", color: "#f04452", label: "매수" },
    SELL: { bg: "#f1f6ff", color: "#2272eb", label: "매도" },
    HOLD: { bg: "#fff7e6", color: "#ffa940", label: "관망" },
  };
  const c = map[signal] || map.HOLD;
  return <span style={{ fontSize: 11, fontWeight: 800, padding: "4px 8px", borderRadius: 6, backgroundColor: c.bg, color: c.color }}>{c.label}</span>;
}

function Top3Card({ ticker, data, rank, budget, onClick }) {
  const info = getInfo(ticker);
  const prob = ((data.signal?.ai_predict?.ensemble_prob || 0.5) * 100).toFixed(1);
  const medals = ["🥇", "🥈", "🥉"];
  return (
    <div onClick={onClick} style={{
      backgroundColor: "#fff", borderRadius: 20, padding: 24, cursor: "pointer",
      border: rank === 1 ? "2px solid #ffd700" : "1px solid #eee",
      position: "relative", transition: "0.2s",
    }}>
      <div style={{ position: "absolute", top: -10, left: 20, fontSize: 24 }}>{medals[rank - 1] || "🏅"}</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginTop: 10 }}>
        <div>
          <div style={{ fontSize: 11, background: "#f0f7ff", color: "#0081ff", padding: "2px 8px", borderRadius: 4, display: "inline-block", fontWeight: 800, marginBottom: 6 }}>{info.theme}</div>
          <div style={{ fontSize: 18, fontWeight: 900 }}>{info.name}</div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 900, color: "#f04452", fontFamily: "monospace" }}>{prob}%</div>
      </div>
      <div style={{ backgroundColor: "#f8f9fb", borderLeft: "4px solid #0081ff", padding: "10px 14px", borderRadius: "0 10px 10px 0", fontSize: 12, color: "#555", margin: "14px 0", lineHeight: 1.5 }}>
        {data.signal?.technical?.reasons?.[0] || "AI 앙상블 모델 기반 상승 추세 전환 예상 구간"}
      </div>
      <div style={{ display: "flex", gap: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#666", backgroundColor: "#f3f4f6", padding: "4px 10px", borderRadius: 6, display: "flex", gap: 6 }}>
          <span>권장금액</span><span style={{ color: "#0081ff" }}>{fmt(Math.round(budget * 10000 * 0.22 / 10000))}만</span>
        </div>
      </div>
    </div>
  );
}

const CandleTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div style={{ backgroundColor: "#fff", padding: "12px 16px", borderRadius: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.12)", border: "1px solid #eee", fontSize: 12 }}>
      <div style={{ fontWeight: 800, marginBottom: 8 }}>{d.Date}</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" }}>
        <span style={{ color: "#888" }}>시가</span><span style={{ fontFamily: "monospace", fontWeight: 700 }}>{fmt(d.Open)}</span>
        <span style={{ color: "#888" }}>고가</span><span style={{ fontFamily: "monospace", fontWeight: 700, color: "#f04452" }}>{fmt(d.High)}</span>
        <span style={{ color: "#888" }}>저가</span><span style={{ fontFamily: "monospace", fontWeight: 700, color: "#2272eb" }}>{fmt(d.Low)}</span>
        <span style={{ color: "#888" }}>종가</span><span style={{ fontFamily: "monospace", fontWeight: 700 }}>{fmt(d.Close)}</span>
        <span style={{ color: "#888" }}>거래량</span><span style={{ fontFamily: "monospace", fontWeight: 700 }}>{fmt(d.Volume)}</span>
      </div>
    </div>
  );
};

// ── 테마 화면 ──
function ThemeScreen({ apiUrl }) {
  const [themeData, setThemeData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState("전체");
  const [selectedTheme, setSelectedTheme] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [viewMode, setViewMode] = useState("theme");

  const loadThemes = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/themes`);
      const json = await res.json();
      setThemeData(json);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const handleSearch = async (q) => {
    setSearchQuery(q);
    if (!q.trim()) { setSearchResults(null); return; }
    try {
      const res = await fetch(`${apiUrl}/api/themes/search?q=${encodeURIComponent(q)}`);
      const json = await res.json();
      setSearchResults(json);
    } catch (e) { }
  };

  const categories = themeData
    ? ["전체", ...new Set(Object.values(themeData.themes || {}).map(t => t.category))]
    : ["전체"];

  const filteredThemes = themeData
    ? Object.entries(themeData.themes || {}).filter(([, t]) =>
      (selectedCategory === "전체" || t.category === selectedCategory) &&
      (!searchResults || searchResults.themes.includes(t.name))
    ).sort((a, b) => b[1].avg_change - a[1].avg_change)
    : [];

  const catColors = {
    "정치/정책": "#0081ff", "기술/산업": "#7c3aed",
    "지정학/글로벌": "#dc2626", "사회이슈": "#059669",
    "자연재해/계절": "#d97706", "에너지": "#ea580c",
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 900, margin: 0 }}>📊 테마 주식 분석</h2>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, backgroundColor: "#fff", padding: "8px 16px", borderRadius: 10, border: "1px solid #eee", minWidth: 200 }}>
            <Search size={15} color="#aaa" />
            <input placeholder="테마·종목 검색" value={searchQuery} onChange={e => handleSearch(e.target.value)}
              style={{ border: "none", background: "none", outline: "none", fontSize: 13, width: "100%", fontFamily: "inherit" }} />
            {searchQuery && <button onClick={() => { setSearchQuery(""); setSearchResults(null); }} style={{ border: "none", background: "none", cursor: "pointer", color: "#aaa", fontSize: 15 }}>✕</button>}
          </div>
          <div style={{ display: "flex", gap: 6, backgroundColor: "#f3f4f6", padding: 4, borderRadius: 10 }}>
            <button type="button" onClick={() => setViewMode("theme")} style={{ padding: "6px 14px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", backgroundColor: viewMode === "theme" ? "#fff" : "transparent", color: viewMode === "theme" ? "#0081ff" : "#888" }}>🎯 테마별</button>
            <button type="button" onClick={() => setViewMode("surge")} style={{ padding: "6px 14px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", backgroundColor: viewMode === "surge" ? "#fff" : "transparent", color: viewMode === "surge" ? "#f04452" : "#888" }}>🚀 거래량 급등</button>
          </div>
          <button type="button" onClick={loadThemes} disabled={loading} style={{ backgroundColor: loading ? "#aaa" : "#0081ff", color: "#fff", border: "none", padding: "8px 18px", borderRadius: 10, fontSize: 13, fontWeight: 700, cursor: loading ? "not-allowed" : "pointer", fontFamily: "inherit" }}>
            {loading ? "⏳ 스캔 중..." : "🔄 테마 스캔"}
          </button>
        </div>
      </div>

      {!themeData && !loading && (
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 60, textAlign: "center", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📊</div>
          <p style={{ fontSize: 16, fontWeight: 700, color: "#555", marginBottom: 8 }}>테마 스캔을 시작해보세요</p>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 24 }}>22개 테마, 100여개 종목의 실시간 데이터를 분석합니다</p>
          <button type="button" onClick={loadThemes} style={{ backgroundColor: "#0081ff", color: "#fff", border: "none", padding: "12px 32px", borderRadius: 12, fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>🚀 지금 스캔 시작</button>
        </div>
      )}

      {loading && (
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 60, textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>⏳</div>
          <p style={{ fontWeight: 700, color: "#555" }}>22개 테마 100여개 종목 분석 중...</p>
        </div>
      )}

      {themeData && !loading && (
        <>
          {viewMode === "surge" && (
            <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
              <h3 style={{ fontSize: 15, fontWeight: 900, margin: "0 0 16px", color: "#f04452", display: "flex", alignItems: "center", gap: 8 }}>
                <Zap size={16} /> 거래량 급등 종목
              </h3>
              {(themeData.surge_stocks || []).length === 0
                ? <p style={{ color: "#aaa", textAlign: "center", padding: 40 }}>현재 거래량 급등 종목 없음</p>
                : <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead style={{ backgroundColor: "#fff5f5" }}>
                    <tr>{["종목", "테마", "현재가", "등락률", "거래량 비율", "RSI"].map(h => (
                      <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 12, fontWeight: 700, color: "#888" }}>{h}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {(themeData.surge_stocks || []).map((s, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #fff5f5" }}>
                        <td style={{ padding: "12px 14px" }}><div style={{ fontWeight: 700 }}>{s.name}</div><div style={{ fontSize: 11, color: "#888" }}>{s.ticker}</div></td>
                        <td style={{ padding: "12px 14px" }}><div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{(s.themes || []).slice(0, 2).map(t => (<span key={t} style={{ fontSize: 10, backgroundColor: "#f0f7ff", color: "#0081ff", padding: "2px 6px", borderRadius: 4, fontWeight: 700 }}>{t}</span>))}</div></td>
                        <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700 }}>{fmt(s.price)}</td>
                        <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700, color: s.change_pct >= 0 ? "#f04452" : "#2272eb" }}>{pct(s.change_pct)}</td>
                        <td style={{ padding: "12px 14px" }}><span style={{ backgroundColor: "#fff1f1", color: "#f04452", padding: "3px 8px", borderRadius: 6, fontSize: 12, fontWeight: 800 }}>{s.volume_ratio}x</span></td>
                        <td style={{ padding: "12px 14px", fontSize: 12, fontWeight: 700 }}>{s.rsi}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            </div>
          )}

          {viewMode === "theme" && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
                {categories.map(cat => (
                  <button key={cat} type="button" onClick={() => setSelectedCategory(cat)} style={{ padding: "7px 16px", borderRadius: 20, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", border: "none", backgroundColor: selectedCategory === cat ? (catColors[cat] || "#0081ff") : "#fff", color: selectedCategory === cat ? "#fff" : "#555", boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>{cat}</button>
                ))}
              </div>

              {selectedTheme ? (
                <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                    <div>
                      <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>{selectedTheme.category}</div>
                      <h3 style={{ fontSize: 20, fontWeight: 900, margin: 0 }}>{selectedTheme.emoji} {selectedTheme.name}</h3>
                      <p style={{ fontSize: 13, color: "#666", marginTop: 6 }}>{selectedTheme.description}</p>
                    </div>
                    <button type="button" onClick={() => setSelectedTheme(null)} style={{ border: "1px solid #eee", backgroundColor: "#fff", borderRadius: 10, padding: "8px 16px", cursor: "pointer", fontSize: 13, fontWeight: 700, fontFamily: "inherit" }}>← 목록으로</button>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
                    {[
                      { label: "오늘 평균", value: pct(selectedTheme.avg_change), color: selectedTheme.avg_change >= 0 ? "#f04452" : "#2272eb" },
                      { label: "대장주 1주", value: pct(selectedTheme.leader_chg_1w), color: (selectedTheme.leader_chg_1w || 0) >= 0 ? "#f04452" : "#2272eb" },
                      { label: "대장주 1달", value: pct(selectedTheme.leader_chg_1m), color: (selectedTheme.leader_chg_1m || 0) >= 0 ? "#f04452" : "#2272eb" },
                      { label: "급등 종목", value: `${selectedTheme.surge_count}개`, color: "#ff9500" },
                    ].map(item => (
                      <div key={item.label} style={{ backgroundColor: "#f8f9fb", borderRadius: 12, padding: "14px 16px", textAlign: "center" }}>
                        <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>{item.label}</div>
                        <div style={{ fontSize: 18, fontWeight: 900, fontFamily: "monospace", color: item.color }}>{item.value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#888", marginBottom: 8 }}>관련 키워드</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {(selectedTheme.keywords || []).map(kw => (<span key={kw} style={{ backgroundColor: "#f0f7ff", color: "#0081ff", padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600 }}>#{kw}</span>))}
                    </div>
                  </div>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead style={{ backgroundColor: "#f8f9fb" }}>
                      <tr>{["종목", "역할", "현재가", "오늘", "1주", "1달", "거래량", "RSI"].map(h => (<th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 12, fontWeight: 700, color: "#888" }}>{h}</th>))}</tr>
                    </thead>
                    <tbody>
                      {(selectedTheme.stocks || []).map((s, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid #f5f5f5" }}>
                          <td style={{ padding: "12px 14px" }}><div style={{ fontWeight: 700 }}>{s.name}</div><div style={{ fontSize: 11, color: "#888" }}>{s.ticker}</div></td>
                          <td style={{ padding: "12px 14px" }}><span style={{ fontSize: 10, fontWeight: 800, padding: "3px 7px", borderRadius: 4, backgroundColor: s.role === "대장주" ? "#fff1f1" : s.role === "핵심주" ? "#fff8e6" : "#f0f7ff", color: s.role === "대장주" ? "#f04452" : s.role === "핵심주" ? "#ff9500" : "#0081ff" }}>{s.role}</span></td>
                          <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700 }}>{fmt(s.price)}</td>
                          <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700, color: s.change_pct >= 0 ? "#f04452" : "#2272eb" }}>{pct(s.change_pct)}</td>
                          <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700, color: (s.chg_1w || 0) >= 0 ? "#f04452" : "#2272eb" }}>{pct(s.chg_1w)}</td>
                          <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700, color: (s.chg_1m || 0) >= 0 ? "#f04452" : "#2272eb" }}>{pct(s.chg_1m)}</td>
                          <td style={{ padding: "12px 14px" }}>{s.is_surge ? <span style={{ backgroundColor: "#fff1f1", color: "#f04452", fontSize: 11, fontWeight: 800, padding: "2px 7px", borderRadius: 4 }}>🔥 급등</span> : <span style={{ color: "#aaa", fontSize: 12 }}>{s.volume_ratio}x</span>}</td>
                          <td style={{ padding: "12px 14px", fontSize: 12, fontWeight: 700, color: s.rsi > 70 ? "#f04452" : s.rsi < 30 ? "#2272eb" : "#555" }}>{s.rsi}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
                  {filteredThemes.map(([name, theme]) => (
                    <div key={name} onClick={() => setSelectedTheme({ ...theme, name, keywords: theme.keywords || [] })}
                      style={{ backgroundColor: "#fff", borderRadius: 16, padding: 20, cursor: "pointer", boxShadow: "0 1px 3px rgba(0,0,0,0.06)", border: "1px solid #f0f0f0", borderTop: `3px solid ${catColors[theme.category] || "#0081ff"}` }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                        <div>
                          <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>{theme.category}</div>
                          <div style={{ fontSize: 15, fontWeight: 800 }}>{theme.emoji} {name}</div>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 18, fontWeight: 900, fontFamily: "monospace", color: theme.avg_change >= 0 ? "#f04452" : "#2272eb" }}>{pct(theme.avg_change)}</div>
                          <div style={{ fontSize: 10, color: "#aaa" }}>테마 평균</div>
                        </div>
                      </div>
                      <p style={{ fontSize: 12, color: "#888", lineHeight: 1.5, margin: "0 0 12px", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{theme.description}</p>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", gap: 6 }}>
                          {theme.is_hot && <span style={{ fontSize: 10, backgroundColor: "#fff1f1", color: "#f04452", padding: "2px 7px", borderRadius: 4, fontWeight: 800 }}>🔥 HOT</span>}
                          {theme.surge_count > 0 && <span style={{ fontSize: 10, backgroundColor: "#fff8e6", color: "#ff9500", padding: "2px 7px", borderRadius: 4, fontWeight: 800 }}>⚡ 급등 {theme.surge_count}개</span>}
                        </div>
                        <span style={{ fontSize: 11, color: "#aaa" }}>{Object.keys(theme.stocks || {}).length}개 →</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeNav, setActiveNav] = useState("대시보드");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedBudget, setSelectedBudget] = useState(200);
  const [selectedReturn, setSelectedReturn] = useState(20);
  const [mode, setMode] = useState("단타");
  const [selectedStock, setSelectedStock] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [compareList, setCompareList] = useState([]);
  const [savedStrategies, setSavedStrategies] = useState(() => {
    const saved = localStorage.getItem("quant_strategies");
    return saved ? JSON.parse(saved) : [];
  });
  const [showCompareModal, setShowCompareModal] = useState(false);
  const [fullScanResults, setFullScanResults] = useState([]);
  const [fullScanLoading, setFullScanLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [analysisData, setAnalysisData] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [intradayData, setIntradayData] = useState(null);
  const [chartModal, setChartModal] = useState(null);
  const [livePrice, setLivePrice] = useState(null);

  useEffect(() => {
    if (!chartModal) {
      setLivePrice(null);
      return;
    }
    
    const fetchLive = () => {
      fetch(`${API_URL}/api/realtime/${chartModal}`)
        .then(r => r.json())
        .then(setLivePrice)
        .catch(() => {});
    };
    
    fetchLive();
    const interval = setInterval(fetchLive, 5000);  // 5초마다 갱신
    return () => clearInterval(interval);
  }, [chartModal]);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/dashboard`);
      const json = await res.json();
      setData(json);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const fetchIntradayRecommendations = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/intraday/recommendations`);
      if (!response.ok) return;
      const data = await response.json();
      setIntradayData(data);
    } catch (error) {
      console.error('Intraday fetch error:', error);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchIntradayRecommendations();
    
    // 무거운 데이터: 30초마다
    const heavyInterval = setInterval(() => {
      fetchData();
      fetchIntradayRecommendations();
    }, 30000);
    
    // 가벼운 데이터 (시장 지수): 5초마다
    const lightInterval = setInterval(() => {
      fetch(`${API_URL}/api/market/indices`)
        .then(r => r.json())
        .then(data => {
          setData(prev => prev ? {...prev, market_indices: data} : prev);
        })
        .catch(() => {});
    }, 5000);
    
    return () => {
      clearInterval(heavyInterval);
      clearInterval(lightInterval);
    };
  }, [fetchData, fetchIntradayRecommendations]);

  const saveStrategy = () => {
    const name = prompt("전략 이름:", `전략 ${savedStrategies.length + 1}`);
    if (!name) return;
    const newS = { name, budget: selectedBudget, targetReturn: selectedReturn, mode, id: Date.now() };
    const updated = [...savedStrategies, newS];
    setSavedStrategies(updated);
    localStorage.setItem("quant_strategies", JSON.stringify(updated));
  };

  const loadStrategy = (s) => { setSelectedBudget(s.budget); setSelectedReturn(s.targetReturn); setMode(s.mode); };
  const deleteStrategy = (id) => {
    const updated = savedStrategies.filter(s => s.id !== id);
    setSavedStrategies(updated);
    localStorage.setItem("quant_strategies", JSON.stringify(updated));
  };

  const toggleCompare = (ticker, d) => {
    if (compareList.find(c => c.ticker === ticker)) {
      setCompareList(compareList.filter(c => c.ticker !== ticker));
    } else {
      if (compareList.length >= 4) { alert("최대 4개까지 비교 가능합니다."); return; }
      setCompareList([...compareList, { ticker, name: d.name || getInfo(ticker).name, price: d.price, change_pct: d.change_pct }]);
    }
  };

  const loadStockDetail = async (ticker, stockData) => {
    try {
      const res = await fetch(`${API_URL}/api/stock/${ticker}?period=3mo`);
      if (!res.ok) { const err = await res.json(); alert(err.error || "데이터 없음"); return; }
      const json = await res.json();
      setChartData(json.map(d => ({ ...d, isUp: d.Close >= d.Open })));
      setSelectedStock({ ...stockData, ticker });
    } catch (e) { console.error(e); }
  };

  const loadAnalysis = async (ticker) => {
    setAnalysisLoading(true);
    setAnalysisData(null);
    try {
      const res = await fetch(`${API_URL}/api/analysis/${ticker}`);
      const json = await res.json();
      setAnalysisData(json);
    } catch (e) { console.error(e); }
    finally { setAnalysisLoading(false); }
  };


  // ── 전체 스캔 상태 ──
  const [scanPeriod, setScanPeriod] = useState("1m");
  const [scanResults, setScanResults] = useState([]);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanTotal, setScanTotal] = useState(0);

  const runScan = async (period) => {
    setScanLoading(true);
    setScanResults([]);
    try {
      const res = await fetch(`${API_URL}/api/scan/all?period=${period}`);
      const json = await res.json();
      setScanResults(json.results || []);
      setScanTotal(json.total || 0);
    } catch (e) { console.error(e); }
    finally { setScanLoading(false); }
  };

  useEffect(() => {
    if (activeNav === "종목 스캔" && scanResults.length === 0 && !scanLoading) {
      runScan(scanPeriod);
    }
  }, [activeNav]);

  const handleSearch = async () => {
    const query = searchQuery.trim();
    if (!query) return;
    setSearchLoading(true);
    setSearchResults([]);
    try {
      const isCode = /^[0-9]/.test(query);
      if (isCode) {
        const code = query.replace(".KQ", "").replace(".KS", "");
        const res = await fetch(`${API_URL}/api/search/${encodeURIComponent(code)}`);
        const json = await res.json();
        if (!json.error) {
          const score = Math.abs(json.signal?.score || 0) * 100;
          json.expectedReturn = Math.max(0, score * 0.7 + (json.change_pct || 0) * 0.3).toFixed(1);
          setSearchResults([json]);
        }
        return;
      }
      const nameRes = await fetch(`${API_URL}/api/search/name/${encodeURIComponent(query)}`);
      const nameJson = await nameRes.json();
      if (!nameJson.results?.length) { alert(`"${query}"에 해당하는 종목이 없습니다`); return; }

      const details = await Promise.all(
        nameJson.results.slice(0, 10).map(async (c) => {
          try {
            const r = await fetch(`${API_URL}/api/search/${encodeURIComponent(c.code)}`);
            const d = await r.json();
            if (d.error) return null;
            d.name = c.name; d.market = c.market; d.sector = c.sector;
            const score = Math.abs(d.signal?.score || 0) * 100;
            const chg = d.change_pct || 0;
            const rsi = d.rsi || 50;
            // 예상수익률: 매수신호 + RSI낮을수록 + 등락률 반영
            const signalBonus = d.signal?.signal === "BUY" ? 15 : d.signal?.signal === "SELL" ? -15 : 0;
            const rsiBonus = rsi < 40 ? 10 : rsi > 70 ? -10 : 0;
            d.expectedReturn = Math.max(0, score * 0.6 + chg * 0.3 + signalBonus * 0.1 + rsiBonus * 0.1).toFixed(1);
            d.rankScore = parseFloat(d.expectedReturn);
            return d;
          } catch { return null; }
        })
      );

      // 예상수익률 높은 순 정렬
      const sorted = details.filter(Boolean).sort((a, b) => b.rankScore - a.rankScore);
      setSearchResults(sorted);
    } catch (e) { alert("검색 중 오류가 발생했습니다"); }
    finally { setSearchLoading(false); }
  };

  if (loading && !data) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100vh" }}>
      <RefreshCcw size={40} color="#0081ff" />
      <p style={{ marginTop: 20, fontWeight: 700, color: "#666" }}>AI 데이터 동기화 중...</p>
    </div>
  );

  // ── 예상수익률 기준 정렬 ──
  const calcExpectedReturn = (d) => {
    const score = Math.abs(d.signal?.score || 0) * 100;
    const chg = d.change_pct || 0;
    const rsi = d.rsi || 50;
    const signalBonus = d.signal?.signal === "BUY" ? 15 : d.signal?.signal === "SELL" ? -15 : 0;
    const rsiBonus = rsi < 40 ? 10 : rsi < 60 ? 5 : rsi > 70 ? -10 : 0;
    return Math.max(0, score * 0.6 + chg * 0.3 + signalBonus * 0.1 + rsiBonus * 0.1);
  };

  const getRecommended = () => {
    const all = Object.entries(data?.top_signals || {});
    let f;
    if (selectedReturn <= 5) f = all.filter(([, d]) => d.signal?.signal === "BUY");
    else if (selectedReturn <= 10) f = all.filter(([, d]) => d.signal?.signal === "BUY" && (d.signal?.score || 0) > 0);
    else if (selectedReturn <= 20) f = all.filter(([, d]) => d.signal?.signal === "BUY" && (d.signal?.score || 0) > 0.1);
    else f = all;
    return f.sort((a, b) => (b[1].signal?.score || 0) - (a[1].signal?.score || 0));
  };

  const recommended = getRecommended();
  const top3 = recommended.slice(0, 3);

  // 예상수익률 높은 순으로 정렬
  const allStocks = Object.entries(data?.top_signals || {})
    .filter(([t, d]) => (d.name || getInfo(t).name).includes(searchQuery) || t.includes(searchQuery))
    .map(([t, d]) => {
      const er = calcExpectedReturn(d);
      return [t, { ...d, expectedReturn: er.toFixed(1) }];
    })
    .sort((a, b) => parseFloat(b[1].expectedReturn) - parseFloat(a[1].expectedReturn));

  const StockTable = ({ stocks }) => (
    <>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 8 }}>
        ※ 접속 시점 기준 AI 예상 수익률 높은 순 정렬
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead style={{ backgroundColor: "#f8f9fb" }}>
          <tr>{["순위", "종목", "현재가", "등락률", "RSI", "신호", "예상수익률", "AI 점수", "비교"].map(h => (
            <th key={h} style={{ padding: "10px 14px", textAlign: h === "순위" ? "center" : "left", fontSize: 12, fontWeight: 700, color: "#888" }}>{h}</th>
          ))}</tr>
        </thead>
        <tbody>
          {stocks.map(([t, d], index) => (
            <tr key={t} onClick={() => loadStockDetail(t, d)} style={{ borderBottom: "1px solid #f5f5f5", cursor: "pointer" }}>
              <td style={{ padding: "12px 14px", textAlign: "center", fontSize: 14 }}>
                {["🥇", "🥈", "🥉"][index] || `${index + 1}위`}
              </td>
              <td style={{ padding: "12px 14px" }}>
                <div style={{ fontWeight: 700 }}>{d.name || getInfo(t).name}</div>
                <div style={{ fontSize: 11, color: "#888" }}>{t}</div>
              </td>
              <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700 }}>{fmt(d.price, 0)}</td>
              <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 700, color: (d.change_pct || 0) >= 0 ? "#f04452" : "#2272eb" }}>{pct(d.change_pct)}</td>
              <td style={{ padding: "12px 14px" }}>
                <span style={{ fontSize: 12, fontWeight: 700, backgroundColor: "#f3f4f6", padding: "2px 8px", borderRadius: 4 }}>{fmt(d.rsi, 1)}</span>
              </td>
              <td style={{ padding: "12px 14px" }}><SignalBadge signal={d.signal?.signal} /></td>
              <td style={{ padding: "12px 14px", fontFamily: "monospace", fontWeight: 900, color: "#0081ff", fontSize: 15 }}>
                +{d.expectedReturn}%
              </td>
              <td style={{ padding: "12px 14px", width: 130 }}>
                <div style={{ width: "100%", height: 10, backgroundColor: "#f3f4f6", borderRadius: 5, overflow: "hidden" }}>
                  <div style={{ height: "100%", backgroundColor: "#0081ff", borderRadius: 5, width: `${Math.min(Math.abs(d.signal?.score || 0) * 100, 100)}%` }} />
                </div>
                <div style={{ fontSize: 10, color: "#888", marginTop: 2 }}>{fmt(Math.abs(d.signal?.score || 0) * 100, 1)}점</div>
              </td>
              <td style={{ padding: "12px 14px" }} onClick={(e) => e.stopPropagation()}>
                <button 
                  onClick={() => toggleCompare(t, d)}
                  style={{
                    padding: '0.25rem 0.75rem',
                    background: compareList.some(c => c.ticker === t) ? '#0081ff' : '#f3f4f6',
                    color: compareList.some(c => c.ticker === t) ? 'white' : '#374151',
                    border: '1px solid ' + (compareList.some(c => c.ticker === t) ? '#0081ff' : '#d1d5db'),
                    borderRadius: '6px',
                    fontSize: '0.875rem',
                    cursor: 'pointer'
                  }}
                >
                  {compareList.some(c => c.ticker === t) ? '✓ 선택됨' : '비교'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );

  const renderContent = () => {
    if (activeNav === "테마 분석") return <ThemeScreen apiUrl={API_URL} />;

    if (activeNav === "뉴스 분석") {
      const news = data?.news_feed?.news?.trusted || [];
      return (
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <h3 style={{ fontSize: 16, fontWeight: 800, marginBottom: 20 }}>📰 실시간 뉴스 ({news.length}건)</h3>
          {news.map((n, i) => (
            <div key={i} onClick={() => window.open(n.url, "_blank")} style={{ padding: "14px 0", borderBottom: "1px solid #f5f5f5", cursor: "pointer" }}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 5, lineHeight: 1.5 }}>{n.title}</div>
              <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#888" }}>
                <span>{n.source}</span><span>{n.published_at?.slice(5, 16)}</span>
                <span style={{ color: n.trust_score >= 0.8 ? "#00c471" : "#888" }}>신뢰도 {Math.round((n.trust_score || 0) * 100)}%</span>
              </div>
            </div>
          ))}
        </div>
      );
    }

    if (activeNav === "종목 스캔") {
      const PERIODS = [
        { key:"1d", label:"1일",  desc:"단타" },
        { key:"7d", label:"7일",  desc:"단기" },
        { key:"1m", label:"1달",  desc:"중기" },
        { key:"3m", label:"3달",  desc:"중장기" },
        { key:"1y", label:"1년",  desc:"장기" },
      ];
      const estKey = {"1d":"est_1d","7d":"est_7d","1m":"est_1m","3m":"est_3m","1y":"est_1y"}[scanPeriod]||"est_1m";
      const retKey = {"1d":"ret_1d","7d":"ret_7d","1m":"ret_1m","3m":"ret_3m","1y":"ret_1y"}[scanPeriod]||"ret_1m";
      const periodLabel = PERIODS.find(p=>p.key===scanPeriod)?.label||"1달";

      return (
        <div style={{ backgroundColor:"#fff", borderRadius:20, padding:24, boxShadow:"0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:20 }}>
            <h3 style={{ fontSize:16, fontWeight:800, margin:0 }}>🔍 KRX 전종목 기대수익률 분석</h3>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <div style={{ display:"flex", alignItems:"center", gap:8, backgroundColor:"#f8f9fb", padding:"8px 14px", borderRadius:10, border:"1px solid #eee" }}>
                <Search size={15} color="#aaa"/>
                <input placeholder="종목명 또는 코드 (예: 알체라, 005930)" value={searchQuery}
                  onChange={e=>setSearchQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handleSearch()}
                  style={{ border:"none", background:"none", outline:"none", fontSize:13, width:200, fontFamily:"inherit" }}/>
                {searchQuery && <button type="button" onClick={()=>{setSearchQuery("");setSearchResults([]);}} style={{ border:"none",background:"none",cursor:"pointer",color:"#aaa",fontSize:15 }}>✕</button>}
              </div>
              <button type="button" onClick={handleSearch} disabled={searchLoading} style={{ backgroundColor:searchLoading?"#aaa":"#0081ff",color:"#fff",border:"none",padding:"9px 16px",borderRadius:10,fontSize:13,fontWeight:700,cursor:searchLoading?"not-allowed":"pointer",fontFamily:"inherit" }}>
                {searchLoading?"⏳":"🔍 검색"}
              </button>
            </div>
          </div>

          {/* 기간 선택 탭 */}
          <div style={{ display:"flex", gap:6, marginBottom:20, backgroundColor:"#f8f9fb", padding:5, borderRadius:14 }}>
            {PERIODS.map(p=>(
              <button key={p.key} type="button" onClick={()=>{ setScanPeriod(p.key); setScanResults([]); runScan(p.key); }} style={{
                flex:1, padding:"10px 0", borderRadius:10, border:"none", cursor:"pointer", fontFamily:"inherit", transition:"all 0.15s",
                backgroundColor: scanPeriod===p.key?"#0081ff":"transparent",
                color: scanPeriod===p.key?"#fff":"#888",
                fontWeight: scanPeriod===p.key?800:600,
                boxShadow: scanPeriod===p.key?"0 2px 8px rgba(0,129,255,0.3)":"none",
              }}>
                <div style={{ fontSize:14 }}>{p.label}</div>
                <div style={{ fontSize:10, opacity:0.8, marginTop:2 }}>{p.desc}</div>
              </button>
            ))}
          </div>

          {/* 로딩 */}
          {scanLoading && (
            <div style={{ textAlign:"center", padding:"60px 0" }}>
              <div style={{ fontSize:40, marginBottom:16 }}>⏳</div>
              <div style={{ fontSize:15, fontWeight:700, color:"#555", marginBottom:8 }}>KRX 전종목 기대수익률 분석 중...</div>
              <div style={{ fontSize:12, color:"#aaa" }}>코스피 + 코스닥 전종목 ({periodLabel} 기준) · 3~5분 소요</div>
            </div>
          )}

          {/* 스캔 결과 */}
          {!scanLoading && scanResults.length > 0 && !searchResults.length && (
            <div>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
                <span style={{ fontSize:13, fontWeight:700, color:"#888" }}>
                  총 {scanTotal}개 종목 분석 · <span style={{ color:"#0081ff" }}>{periodLabel} 기대수익률 높은 순</span>
                </span>
                <button type="button" onClick={()=>{setScanResults([]);runScan(scanPeriod);}} style={{ fontSize:12,color:"#0081ff",backgroundColor:"#f0f7ff",border:"1px solid #0081ff",padding:"5px 12px",borderRadius:8,cursor:"pointer",fontFamily:"inherit",fontWeight:700 }}>
                  🔄 새로 스캔
                </button>
              </div>
              <table style={{ width:"100%", borderCollapse:"collapse" }}>
                <thead style={{ backgroundColor:"#f8f9fb" }}>
                  <tr>
                    {["순위","종목","현재가","전일등락","RSI","MA위치",`${periodLabel} 실적`,`기대수익률(${periodLabel})`,"신호"].map(h=>(
                      <th key={h} style={{ padding:"10px 12px", textAlign:h==="순위"?"center":"left", fontSize:11, fontWeight:700, color:"#888", whiteSpace:"nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {scanResults.map((s,i)=>{
                    const est = s[estKey]||0;
                    const ret = s[retKey]||0;
                    const sigColor = s.signal==="BUY"?"#f04452":s.signal==="SELL"?"#2272eb":"#ffa940";
                    const sigLabel = s.signal==="BUY"?"매수":s.signal==="SELL"?"매도":"관망";
                    return (
                      <tr key={i} onClick={()=>loadStockDetail(s.ticker,s)} style={{ borderBottom:"1px solid #f5f5f5", cursor:"pointer" }}>
                        <td style={{ padding:"11px 12px", textAlign:"center", fontSize:13 }}>{["🥇","🥈","🥉"][i]||`${i+1}위`}</td>
                        <td style={{ padding:"11px 12px" }}>
                          <div style={{ fontWeight:700, fontSize:13 }}>{s.name}</div>
                          <div style={{ fontSize:10, color:"#aaa" }}>{s.ticker}</div>
                          {s.is_momentum && <span style={{ fontSize:9,backgroundColor:"#fff1f1",color:"#f04452",padding:"1px 5px",borderRadius:3,fontWeight:800 }}>🔥 모멘텀</span>}
                        </td>
                        <td style={{ padding:"11px 12px", fontFamily:"monospace", fontWeight:700, fontSize:13 }}>{s.price?.toLocaleString()}</td>
                        <td style={{ padding:"11px 12px", fontFamily:"monospace", fontWeight:700, color:s.ret_1d>=0?"#f04452":"#2272eb", fontSize:13 }}>{s.ret_1d>=0?"+":""}{s.ret_1d}%</td>
                        <td style={{ padding:"11px 12px" }}>
                          <span style={{ fontSize:12,fontWeight:700,padding:"2px 8px",borderRadius:4,backgroundColor:s.rsi>70?"#fff1f1":s.rsi<30?"#f0f7ff":"#f3f4f6",color:s.rsi>70?"#f04452":s.rsi<30?"#2272eb":"#555" }}>{s.rsi}</span>
                        </td>
                        <td style={{ padding:"11px 12px" }}>
                          <div style={{ display:"flex", gap:2 }}>
                            {[0,1,2].map(mi=>(<div key={mi} style={{ width:12,height:12,borderRadius:2,backgroundColor:s.ma_score>mi?"#0081ff":"#e5e7eb" }}/>))}
                          </div>
                          <div style={{ fontSize:9,color:"#aaa",marginTop:2 }}>{s.ma_score}/3 위</div>
                        </td>
                        <td style={{ padding:"11px 12px", fontFamily:"monospace", fontWeight:700, color:ret>=0?"#f04452":"#2272eb", fontSize:13 }}>{ret>=0?"+":""}{ret}%</td>
                        <td style={{ padding:"11px 12px" }}>
                          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                            <div style={{ flex:1,height:8,backgroundColor:"#f3f4f6",borderRadius:4,overflow:"hidden",minWidth:50 }}>
                              <div style={{ height:"100%",borderRadius:4,backgroundColor:est>=0?"#0081ff":"#f04452",width:`${Math.min(Math.abs(est)*3,100)}%` }}/>
                            </div>
                            <span style={{ fontFamily:"monospace",fontWeight:900,color:est>=0?"#0081ff":"#f04452",fontSize:13,minWidth:44 }}>{est>=0?"+":""}{est}%</span>
                          </div>
                        </td>
                        <td style={{ padding:"11px 12px" }}>
                          <span style={{ fontSize:11,fontWeight:800,padding:"4px 8px",borderRadius:6,backgroundColor:s.signal==="BUY"?"#fff1f1":s.signal==="SELL"?"#f1f6ff":"#fff7e6",color:sigColor }}>{sigLabel}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ marginTop:12,fontSize:11,color:"#bbb",textAlign:"center" }}>
                ※ 기대수익률은 과거 수익률 모멘텀 + 기술 지표 기반 추정치이며 실제 수익을 보장하지 않습니다
              </div>
            </div>
          )}

          {!scanLoading && scanResults.length===0 && !searchResults.length && (
            <div style={{ textAlign:"center", padding:"40px 0", color:"#bbb" }}>
              <div style={{ fontSize:32, marginBottom:12 }}>📊</div>
              <div style={{ fontSize:13, fontWeight:700, marginBottom:8 }}>기간을 선택하면 자동으로 스캔합니다</div>
              <button type="button" onClick={()=>runScan(scanPeriod)} style={{ fontSize:13,color:"#0081ff",backgroundColor:"#f0f7ff",border:"1px solid #0081ff",padding:"8px 20px",borderRadius:10,cursor:"pointer",fontFamily:"inherit",fontWeight:700 }}>
                🚀 지금 스캔 시작
              </button>
            </div>
          )}

          {/* 검색 결과 */}
          {searchResults.length > 0 && (
            <div style={{ marginBottom:20 }}>
              <div style={{ fontSize:13,fontWeight:700,color:"#888",marginBottom:12,display:"flex",alignItems:"center",gap:8 }}>
                <span>🔍 "{searchQuery}" 검색 결과</span>
                <span style={{ backgroundColor:"#f0f7ff",color:"#0081ff",padding:"2px 8px",borderRadius:10,fontSize:12 }}>{searchResults.length}개</span>
                <span style={{ fontSize:11,color:"#bbb" }}>· 예상수익률 높은 순</span>
              </div>
              <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
                {searchResults.map((s,i)=>{
                  const isUp=(s.change_pct||0)>=0;
                  const signal=s.signal?.signal;
                  const sigColor=signal==="BUY"?"#f04452":signal==="SELL"?"#2272eb":"#ffa940";
                  const sigLabel=signal==="BUY"?"매수":signal==="SELL"?"매도":"관망";
                  return (
                    <div key={s.ticker} style={{ backgroundColor:"#fff",borderRadius:16,padding:"18px 22px",boxShadow:"0 1px 4px rgba(0,0,0,0.06)",border:"1px solid #f0f0f0",borderLeft:`4px solid ${sigColor}`,cursor:"pointer" }}
                      onClick={()=>loadStockDetail(s.ticker,s)}>
                      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                        <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                          <div style={{ fontSize:20,minWidth:32 }}>{["🥇","🥈","🥉"][i]||`${i+1}위`}</div>
                          <div>
                            <div style={{ display:"flex",alignItems:"center",gap:8,marginBottom:4 }}>
                              <span style={{ fontSize:16,fontWeight:900 }}>{s.name}</span>
                              <span style={{ fontSize:10,backgroundColor:"#f3f4f6",color:"#888",padding:"2px 7px",borderRadius:4,fontWeight:700 }}>{s.market}</span>
                              {s.sector&&<span style={{ fontSize:10,backgroundColor:"#f0f7ff",color:"#0081ff",padding:"2px 7px",borderRadius:4,fontWeight:700 }}>{s.sector}</span>}
                            </div>
                            <div style={{ fontSize:11,color:"#aaa" }}>{s.ticker}</div>
                          </div>
                        </div>
                        <div style={{ display:"flex", alignItems:"center", gap:16 }}>
                          <div style={{ textAlign:"right" }}>
                            <div style={{ fontSize:18,fontWeight:900,fontFamily:"monospace" }}>{s.price?.toLocaleString()}원</div>
                            <div style={{ fontSize:12,fontWeight:700,color:isUp?"#f04452":"#2272eb" }}>{isUp?"+":""}{s.change_pct}%</div>
                          </div>
                          <div style={{ textAlign:"center",backgroundColor:"#f0f7ff",borderRadius:10,padding:"10px 16px",minWidth:80 }}>
                            <div style={{ fontSize:9,color:"#888",marginBottom:3 }}>예상 수익률</div>
                            <div style={{ fontSize:20,fontWeight:900,color:"#0081ff",fontFamily:"monospace" }}>+{s.expectedReturn}%</div>
                          </div>
                          <div style={{ textAlign:"center",backgroundColor:signal==="BUY"?"#fff1f1":signal==="SELL"?"#f1f6ff":"#fff8e6",borderRadius:10,padding:"10px 16px",minWidth:60 }}>
                            <div style={{ fontSize:9,color:"#888",marginBottom:3 }}>AI 신호</div>
                            <div style={{ fontSize:16,fontWeight:900,color:sigColor }}>{sigLabel}</div>
                          </div>
                          <div style={{ textAlign:"center",backgroundColor:"#f8f9fb",borderRadius:10,padding:"10px 14px",minWidth:55 }}>
                            <div style={{ fontSize:9,color:"#888",marginBottom:3 }}>RSI</div>
                            <div style={{ fontSize:16,fontWeight:900,fontFamily:"monospace",color:s.rsi>70?"#f04452":s.rsi<30?"#2272eb":"#555" }}>{s.rsi}</div>
                          </div>
                        </div>
                      </div>
                      {s.signal?.technical?.reasons?.length>0&&(
                        <div style={{ marginTop:10,fontSize:12,color:"#888",backgroundColor:"#f8f9fb",padding:"8px 12px",borderRadius:8,borderLeft:"3px solid #e5e7eb" }}>
                          {s.signal.technical.reasons.join(" · ")}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div style={{ marginTop:10,fontSize:11,color:"#bbb",textAlign:"center" }}>
                ※ 예상 수익률은 AI 모델 기반 추정치이며 실제 수익을 보장하지 않습니다
              </div>
            </div>
          )}
        </div>
      );
    }

    if (activeNav === "AI 자동학습") {
      return (
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <h3 style={{ fontSize: 16, fontWeight: 800, marginBottom: 20 }}>🧠 AI 자동학습 현황</h3>
          {[
            { bg: "#f0f7ff", color: "#0081ff", title: "📚 학습 소스", items: ["Quantocracy", "Ernest Chan Blog", "QuantInsti", "QuantStart"] },
            { bg: "#fff8e6", color: "#ff9500", title: "⏰ 스케줄", items: ["매일 새벽 06:00 자동 실행"] },
            { bg: "#f0fff8", color: "#00c471", title: "📊 DB 상태", items: ["data/learning.db 저장 중"] },
          ].map(b => (
            <div key={b.title} style={{ padding: 20, background: b.bg, borderRadius: 12, marginBottom: 14 }}>
              <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 10, color: b.color }}>{b.title}</div>
              {b.items.map(item => <div key={item} style={{ padding: "8px 0", fontSize: 13, color: "#555" }}>✅ {item}</div>)}
            </div>
          ))}
        </div>
      );
    }

    if (activeNav === "포트폴리오") {
      return (
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 60, textAlign: "center" }}>
          <Briefcase size={48} color="#ddd" />
          <p style={{ marginTop: 16, fontSize: 18, fontWeight: 700, color: "#aaa" }}>준비 중입니다</p>
        </div>
      );
    }

    const displayRecommendations = (intradayData && intradayData.recommendations && intradayData.recommendations.length > 0)
      ? intradayData.recommendations
      : top3.map(([ticker, d]) => {
          const price = d.price || 0;
          const sig_obj = d.signal || {};
          const ai_prob = sig_obj.ai_predict?.ensemble_prob || 0.5;
          const rsi = d.rsi || 50;
          return {
            ticker: ticker,
            name: d.name || getInfo(ticker).name,
            entry_price: price,
            take_profit: price * 1.05,
            stop_loss: price * 0.98,
            ai_probability: ai_prob,
            signal_score: (sig_obj.score || 0) * 100,
            expected_return: calcExpectedReturn(d),
            reasoning: sig_obj.technical?.reasons?.[0] || `RSI ${rsi.toFixed(1)}, 상승 모멘텀 탐색`,
          };
        });

    // 대시보드
    return (
      <>
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
            <h3 style={{ fontSize: 15, fontWeight: 800, margin: 0, display: "flex", alignItems: "center", gap: 8 }}><Settings size={16} /> 투자 시뮬레이션 설정</h3>
            <button type="button" onClick={saveStrategy} style={{ backgroundColor: "#f0f7ff", color: "#0081ff", border: "1px solid #0081ff33", padding: "6px 12px", borderRadius: 8, fontSize: 13, fontWeight: 800, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}>
              <Target size={14} /> 전략 저장
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#888", marginBottom: 8 }}>투자금액</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {[50, 100, 200, 500, 1000].map(v => (
                  <button type="button" key={v} onClick={() => setSelectedBudget(v)} style={{ border: `1.5px solid ${v === selectedBudget ? "#0081ff" : "#e5e7eb"}`, backgroundColor: v === selectedBudget ? "#0081ff" : "#fff", color: v === selectedBudget ? "#fff" : "#555", padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>{v}만</button>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#888", marginBottom: 8 }}>목표 수익률</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {[[5, "안정"], [10, "보통"], [20, "공격"], [30, "최대"]].map(([v, l]) => (
                  <button type="button" key={v} onClick={() => setSelectedReturn(v)} style={{ border: `1.5px solid ${v === selectedReturn ? "#0081ff" : "#e5e7eb"}`, backgroundColor: v === selectedReturn ? "#0081ff" : "#fff", color: v === selectedReturn ? "#fff" : "#555", padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>{v}% ({l})</button>
                ))}
              </div>
            </div>
            {savedStrategies.length > 0 && (
              <div style={{ marginTop: 10, borderTop: "1px solid #f3f4f6", paddingTop: 15 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#888", marginBottom: 8 }}>저장된 전략</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {savedStrategies.map(strat => (
                    <div key={strat.id} style={{ backgroundColor: "#fff", border: "1px solid #eee", padding: "6px 12px", borderRadius: 10, fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
                      <span onClick={() => loadStrategy(strat)} style={{ cursor: "pointer" }}>{strat.name}</span>
                      <button onClick={() => deleteStrategy(strat.id)} style={{ background: "none", border: "none", color: "#aaa", fontSize: 16, cursor: "pointer" }}>×</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <h3 style={{ fontSize: 17, fontWeight: 900, margin: "28px 0 16px" }}>🔥 오늘의 단타 추천 (AI 실시간 TOP 3)</h3>
        {displayRecommendations.length === 0
          ? <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 40, textAlign: "center", color: "#bbb" }}>현재 추천할 수 있는 종목이 없습니다</div>
          : <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18 }}>
              {displayRecommendations.slice(0, 3).map((rec) => (
                <div 
                  key={rec.ticker}
                  onClick={() => setChartModal(rec.ticker)} 
                  style={{
                    cursor: 'pointer', 
                    border: '2px solid #e5e7eb', 
                    borderRadius: '12px', 
                    padding: '1.5rem', 
                    background: 'white',
                    transition: 'transform 0.15s, box-shadow 0.15s',
                  }}
                  onMouseOver={(e) => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.boxShadow = '0 6px 12px rgba(0,0,0,0.05)';
                  }}
                  onMouseOut={(e) => {
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.boxShadow = 'none';
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '8px' }}>
                    <div>
                      <div style={{ fontSize: '15px', fontWeight: '800' }}>{rec.name}</div>
                      <div style={{ fontSize: '11px', color: '#888' }}>({rec.ticker})</div>
                    </div>
                    {rec.expected_return && (
                      <div style={{ fontSize: '14px', fontWeight: '900', color: '#f04452' }}>
                        +{rec.expected_return.toFixed(1)}%
                      </div>
                    )}
                  </div>
                  <div style={{ fontSize: '13px', color: '#333', marginBottom: '8px' }}>현재가: {rec.entry_price?.toLocaleString()}원</div>
                  <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem', marginTop: '1rem', background: '#f8f9fb', padding: '10px', borderRadius: '10px', textAlign: 'center'}}>
                    <div><span style={{color: '#6b7280', fontSize: '0.75rem'}}>📊 진입</span><br/><span style={{ fontSize: '12px', fontWeight: '700' }}>{rec.entry_price?.toLocaleString()}</span></div>
                    <div style={{color: '#ef4444'}}><span style={{color: '#6b7280', fontSize: '0.75rem'}}>🎯 +5%</span><br/><span style={{ fontSize: '12px', fontWeight: '700' }}>{Math.round(rec.take_profit)?.toLocaleString()}</span></div>
                    <div style={{color: '#3b82f6'}}><span style={{color: '#6b7280', fontSize: '0.75rem'}}>🛑 -2%</span><br/><span style={{ fontSize: '12px', fontWeight: '700' }}>{Math.round(rec.stop_loss)?.toLocaleString()}</span></div>
                  </div>
                  <div style={{marginTop: '0.75rem', padding: '0.5rem', background: '#eff6ff', borderRadius: '6px', fontSize: '0.875rem', display: 'flex', justifyContent: 'space-between'}}>
                    <span style={{ fontWeight: '700', color: '#0081ff' }}>AI {(rec.ai_probability * 100).toFixed(0)}%</span>
                    <span style={{ color: '#888' }}>|</span>
                    <span style={{ fontWeight: '700' }}>점수 {rec.signal_score?.toFixed(0)}점</span>
                  </div>
                  <div style={{marginTop: '0.5rem', fontSize: '0.75rem', color: '#6b7280', background: '#fafafa', padding: '6px 10px', borderRadius: '4px', lineHeight: 1.4}}>💡 {rec.reasoning}</div>
                  
                  <button
                    type="button"
                    style={{
                      width: '100%',
                      marginTop: '12px',
                      padding: '10px',
                      background: '#0081ff',
                      color: 'white',
                      border: 'none',
                      borderRadius: '10px',
                      fontWeight: '800',
                      fontSize: '12px',
                      cursor: 'pointer',
                      fontFamily: 'inherit'
                    }}
                  >
                    상세 차트 보기
                  </button>
                </div>
              ))}
            </div>
        }
        <div style={{ backgroundColor: "#fff", borderRadius: 20, padding: 24, marginTop: 28, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
            <h3 style={{ fontSize: 15, fontWeight: 800, margin: 0 }}>전체 종목</h3>
            <div style={{ display: "flex", alignItems: "center", gap: 8, backgroundColor: "#f8f9fb", padding: "7px 14px", borderRadius: 10, border: "1px solid #eee" }}>
              <Search size={14} color="#aaa" />
              <input placeholder="종목명 검색..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} style={{ border: "none", background: "none", outline: "none", fontSize: 13, width: 130, fontFamily: "inherit" }} />
              {searchQuery && <button type="button" onClick={() => setSearchQuery("")} style={{ border: "none", background: "none", cursor: "pointer", color: "#aaa", fontSize: 15 }}>✕</button>}
            </div>
          </div>
          <StockTable stocks={allStocks} />
        </div>
      </>
    );
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", backgroundColor: "#f9fafb", fontFamily: "'Pretendard','Noto Sans KR',sans-serif" }}>
      <aside style={{ width: 200, backgroundColor: "#fff", borderRight: "1px solid #e5e7eb", display: "flex", flexDirection: "column", position: "fixed", height: "100vh", zIndex: 100 }}>
        <div style={{ padding: "26px 22px", display: "flex", alignItems: "center", gap: 10, fontSize: 19, fontWeight: 900 }}>
          <TrendingUp size={22} color="#0081ff" strokeWidth={3} />
          <span>QUANT <span style={{ color: "#0081ff" }}>AI</span></span>
        </div>
        <nav style={{ flex: 1, padding: "0 10px" }}>
          <NavItem active={activeNav === "대시보드"} icon={<LayoutDashboard size={18} />} label="대시보드" onClick={() => setActiveNav("대시보드")} />
          <NavItem active={activeNav === "종목 스캔"} icon={<Search size={18} />} label="종목 스캔" onClick={() => setActiveNav("종목 스캔")} />
          <NavItem active={activeNav === "테마 분석"} icon={<Flame size={18} />} label="테마 분석" onClick={() => setActiveNav("테마 분석")} badge="NEW" />
          <NavItem active={activeNav === "뉴스 분석"} icon={<Newspaper size={18} />} label="뉴스 분석" onClick={() => setActiveNav("뉴스 분석")} />
          <NavItem active={activeNav === "AI 자동학습"} icon={<Brain size={18} />} label="AI 자동학습" onClick={() => setActiveNav("AI 자동학습")} />
          <NavItem active={activeNav === "포트폴리오"} icon={<Briefcase size={18} />} label="포트폴리오" onClick={() => setActiveNav("포트폴리오")} />
        </nav>
        <div style={{ padding: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 700, color: "#22c55e" }}>
            <div style={{ width: 7, height: 7, backgroundColor: "#22c55e", borderRadius: "50%" }} />System Live
          </div>
        </div>
      </aside>

      <main style={{ flex: 1, marginLeft: 200, padding: "28px 36px", paddingBottom: 80 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#888" }}>
            {new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "long" })}
            &nbsp;{new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, backgroundColor: "#fff", padding: "6px 12px", borderRadius: 10, border: "1px solid #eee" }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: mode === "단타" ? "#0081ff" : "#aaa" }}>단타</span>
              <div onClick={() => setMode(mode === "단타" ? "장기" : "단타")} style={{ width: 40, height: 22, backgroundColor: mode === "장기" ? "#0081ff" : "#e5e7eb", borderRadius: 11, padding: 2, cursor: "pointer", transition: "0.2s" }}>
                <div style={{ width: 18, height: 18, backgroundColor: "#fff", borderRadius: 9, transition: "0.2s", transform: mode === "장기" ? "translateX(18px)" : "translateX(0)" }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 700, color: mode === "장기" ? "#0081ff" : "#aaa" }}>장기</span>
            </div>
            <button type="button" onClick={() => { fetchData(); fetchIntradayRecommendations(); }} style={{ background: "#e8f3ff", border: "1px solid #0081ff", color: "#0081ff", padding: "7px 14px", borderRadius: 8, cursor: "pointer", display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700, fontFamily: "inherit" }}>
              <RefreshCcw size={13} /> 새로고침
            </button>
            <button type="button" style={{ background: "none", border: "none", cursor: "pointer", color: "#666", padding: 6 }}><Bell size={18} /></button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 24 }}>
          {["KOSPI", "KOSDAQ", "USD/KRW", "VIX"].map(name => {
            const info = data?.market_indices?.[name];
            const isUp = info?.up;
            return (
              <div key={name} style={{ backgroundColor: "#fff", borderRadius: 14, padding: "18px 20px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)", borderTop: `3px solid ${!info ? "#e5e7eb" : isUp ? "#f04452" : "#2272eb"}` }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#888", marginBottom: 6 }}>{name}</div>
                <div style={{ fontSize: 20, fontWeight: 900, fontFamily: "monospace" }}>{info ? fmt(info.value, 1) : "--"}</div>
                {info && <div style={{ fontSize: 12, fontWeight: 800, color: isUp ? "#f04452" : "#2272eb", marginTop: 4 }}>{pct(info.change_pct)}</div>}
              </div>
            );
          })}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 24 }}>
          <div>{renderContent()}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {(data?.news_feed?.news?.risks || []).length > 0 && (
              <div style={{ backgroundColor: "#fff1f1", color: "#f04452", padding: 18, borderRadius: 18, border: "1px solid rgba(240,68,82,0.15)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8, fontWeight: 800, fontSize: 13 }}>
                  <AlertTriangle size={16} /> 돌발 악재 {(data?.news_feed?.news?.risks || []).length}건
                </div>
                {(data?.news_feed?.news?.risks || []).slice(0, 2).map((r, i) => (<div key={i} style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 3, opacity: 0.9 }}>{r.title?.slice(0, 38)}...</div>))}
              </div>
            )}
            <div style={{ background: "linear-gradient(135deg,#0081ff,#0056b3)", padding: 22, borderRadius: 18, color: "#fff" }}>
              <h4 style={{ margin: "0 0 14px", fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}><Target size={16} /> 켈리 + 몬테카를로</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {[
                  { label: "권장 투자금", value: `${fmt(Math.round(selectedBudget * 10000 * 0.22 / 10000))}만원` },
                  { label: "수익 확률", value: "68.4%" },
                  { label: "평균 수익", value: `+${(selectedReturn - 2.5).toFixed(1)}%` },
                  { label: "최악 손실", value: "-4.2%" },
                ].map(item => (
                  <div key={item.label}>
                    <div style={{ fontSize: 10, opacity: 0.8, marginBottom: 3 }}>{item.label}</div>
                    <div style={{ fontSize: 16, fontWeight: 900, fontFamily: "monospace" }}>{item.value}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4 style={{ fontSize: 13, fontWeight: 900, margin: "0 0 10px" }}>실시간 뉴스</h4>
              {(data?.news_feed?.news?.trusted || []).slice(0, 5).map((n, i) => (
                <div key={i} onClick={() => window.open(n.url, "_blank")} style={{ cursor: "pointer", marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.5, marginBottom: 3, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{n.title}</div>
                  <div style={{ fontSize: 11, color: "#888" }}>{n.source}</div>
                </div>
              ))}
            </div>
            <div>
              <h4 style={{ fontSize: 13, fontWeight: 900, margin: "0 0 10px" }}>거시경제 매크로</h4>
              {Object.entries(data?.macro || {}).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 700, backgroundColor: "#fff", padding: "9px 14px", borderRadius: 10, marginBottom: 6 }}>
                  <span style={{ color: "#888" }}>{k}</span>
                  <span style={{ fontFamily: "monospace" }}>{fmt(v, 2)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>



      {selectedStock && (
        <div onClick={() => setSelectedStock(null)} style={{ position: "fixed", top: 0, left: 0, width: "100%", height: "100%", backgroundColor: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", justifyContent: "center", alignItems: "flex-end" }}>
          <div onClick={e => e.stopPropagation()} style={{ backgroundColor: "#fff", width: "100%", maxWidth: 960, borderRadius: "28px 28px 0 0", padding: "36px 40px", maxHeight: "92vh", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: 24, fontWeight: 900 }}>{selectedStock.name || getInfo(selectedStock.ticker).name}</h2>
                <div style={{ fontSize: 13, color: "#888", marginTop: 4 }}>
                  {selectedStock.ticker} &nbsp;|&nbsp;
                  <strong style={{ fontSize: 18, color: "#191f28" }}>{fmt(selectedStock.price)}원</strong>
                  &nbsp;<span style={{ color: (selectedStock.change_pct || 0) >= 0 ? "#f04452" : "#2272eb", fontWeight: 700 }}>{pct(selectedStock.change_pct)}</span>
                </div>
              </div>
              <button type="button" onClick={() => setSelectedStock(null)} style={{ fontSize: 26, background: "none", border: "none", cursor: "pointer", color: "#bbb" }}>✕</button>
            </div>
            <div style={{ backgroundColor: "#f9fafb", borderRadius: 18, padding: "20px 10px", marginBottom: 24 }}>
              <div style={{ display: "flex", gap: 16, padding: "0 10px 10px", fontSize: 11, fontWeight: 700 }}>
                <span style={{ color: "#facc15" }}>● MA5</span><span style={{ color: "#22c55e" }}>● MA20</span><span style={{ color: "#a855f7" }}>● MA60</span>
                <span style={{ marginLeft: "auto", color: "#f04452" }}>■ 상승</span><span style={{ color: "#2272eb" }}>■ 하락</span>
              </div>
              {chartData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eee" />
                      <XAxis dataKey="Date" tick={{ fontSize: 9 }} minTickGap={30} tickLine={false} />
                      <YAxis domain={["auto", "auto"]} tick={{ fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={v => fmt(v, 0)} />
                      <Tooltip content={<CandleTooltip />} />
                      <Bar dataKey="Close" barSize={6}>{chartData.map((d, i) => <Cell key={i} fill={d.isUp ? "#f04452" : "#2272eb"} opacity={0.85} />)}</Bar>
                      <Line type="monotone" dataKey="MA5" stroke="#facc15" dot={false} strokeWidth={1.5} connectNulls />
                      <Line type="monotone" dataKey="MA20" stroke="#22c55e" dot={false} strokeWidth={1.5} connectNulls />
                      <Line type="monotone" dataKey="MA60" stroke="#a855f7" dot={false} strokeWidth={1.5} connectNulls />
                    </ComposedChart>
                  </ResponsiveContainer>
                  <ResponsiveContainer width="100%" height={50}>
                    <ComposedChart data={chartData} margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
                      <XAxis dataKey="Date" hide /><YAxis hide />
                      <Bar dataKey="Volume" barSize={6}>{chartData.map((d, i) => <Cell key={i} fill={d.isUp ? "#f04452" : "#2272eb"} opacity={0.4} />)}</Bar>
                    </ComposedChart>
                  </ResponsiveContainer>
                </>
              ) : <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 270, color: "#bbb" }}>차트 로딩 중...</div>}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
              <div>
                <h4 style={{ margin: "0 0 14px", fontSize: 14, fontWeight: 900, color: "#888" }}>📊 리스크 지표</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  {[
                    { label: "1일 VaR (95%)", value: pct((selectedStock.risk?.var_95_1d || 0) * 100) },
                    { label: "MDD", value: pct((selectedStock.risk?.mdd || 0) * 100) },
                    { label: "샤프 비율", value: fmt(selectedStock.risk?.sharpe, 2) },
                    { label: "연간 변동성", value: pct((selectedStock.risk?.volatility_annual || 0) * 100) },
                  ].map(item => (
                    <div key={item.label} style={{ backgroundColor: "#f8f9fb", padding: "14px 16px", borderRadius: 12 }}>
                      <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>{item.label}</div>
                      <div style={{ fontSize: 16, fontWeight: 900, fontFamily: "monospace" }}>{item.value}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h4 style={{ margin: "0 0 14px", fontSize: 14, fontWeight: 900, color: "#888" }}>🧠 AI 분석</h4>
                <div style={{ backgroundColor: "#f0f7ff", padding: 18, borderRadius: 14, marginBottom: 14 }}>
                  <div style={{ fontSize: 20, fontWeight: 900, color: "#f04452", marginBottom: 8 }}>
                    {selectedStock.signal?.signal === "BUY" ? "▲ 매수" : selectedStock.signal?.signal === "SELL" ? "▼ 매도" : "● 관망"}
                    &nbsp;<span style={{ fontSize: 13, color: "#888", fontWeight: 600 }}>확률 {((selectedStock.signal?.ai_predict?.ensemble_prob || 0) * 100).toFixed(1)}%</span>
                  </div>
                  <p style={{ fontSize: 13, color: "#555", lineHeight: 1.6, margin: 0 }}>
                    {selectedStock.signal?.technical?.reasons?.join(". ") || "AI 앙상블 모델 기반 분석 결과입니다."}
                  </p>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button type="button" style={{ flex: 1, backgroundColor: "#f04452", color: "#fff", border: "none", padding: "15px", borderRadius: 12, fontSize: 14, fontWeight: 900, cursor: "pointer", fontFamily: "inherit" }}>강력 매수</button>
                  <button type="button" style={{ width: 80, backgroundColor: "#2272eb", color: "#fff", border: "none", padding: "15px", borderRadius: 12, fontSize: 14, fontWeight: 900, cursor: "pointer", fontFamily: "inherit" }}>매도</button>
                </div>
                <button type="button" 
                  onClick={() => loadAnalysis(selectedStock.ticker)}
                  style={{ width: "100%", marginTop: 12, backgroundColor: "#fff", color: "#0081ff", border: "1.5px solid #0081ff", padding: "12px", borderRadius: 12, fontSize: 13, fontWeight: 800, cursor: "pointer", fontFamily: "inherit" }}>
                  {analysisLoading ? "⏳ 분석 중..." : "🔍 AI 심층 리포트 보기"}
                </button>
              </div>
            </div>

            {analysisData && (
              <div style={{ marginTop: 30, borderTop: "2px solid #f0f0f0", paddingTop: 30 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                  <h3 style={{ fontSize: 18, fontWeight: 900 }}>✦ AI 심층 분석 리포트</h3>
                  <div style={{ display: "flex", gap: 10 }}>
                    <span style={{ fontSize: 12, backgroundColor: "#f0f7ff", color: "#0081ff", padding: "4px 10px", borderRadius: 6, fontWeight: 800 }}>종합점수: {analysisData.summary?.total_score}점</span>
                    <span style={{ fontSize: 12, backgroundColor: analysisData.risk?.level === "안전" ? "#f0fff8" : "#fff1f1", color: analysisData.risk?.level === "안전" ? "#00c471" : "#f04452", padding: "4px 10px", borderRadius: 6, fontWeight: 800 }}>리스크: {analysisData.risk?.level}</span>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
                  <div style={{ backgroundColor: "#f8f9fb", borderRadius: 16, padding: 20 }}>
                    <h4 style={{ fontSize: 14, fontWeight: 800, marginBottom: 12, color: "#555" }}>📈 기술적 분석 (Technical)</h4>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 20px" }}>
                      {[
                        { label: "MA 정배열", value: analysisData.technical?.ma_score === 4 ? "완성" : "미완성" },
                        { label: "RSI (14)", value: analysisData.technical?.rsi },
                        { label: "MACD", value: analysisData.technical?.macd_cross === "golden" ? "골든크로스" : "데드크로스" },
                        { label: "볼린저 밴드", value: `${analysisData.technical?.bb_pct}% (위치)` },
                      ].map(item => (
                        <div key={item.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span style={{ color: "#888" }}>{item.label}</span>
                          <span style={{ fontWeight: 700 }}>{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div style={{ backgroundColor: "#f8f9fb", borderRadius: 16, padding: 20 }}>
                    <h4 style={{ fontSize: 14, fontWeight: 800, marginBottom: 12, color: "#555" }}>💎 가치 분석 (Valuation)</h4>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 20px" }}>
                      {[
                        { label: "PER", value: analysisData.valuation?.per ? `${analysisData.valuation.per}배` : "--" },
                        { label: "PBR", value: analysisData.valuation?.pbr ? `${analysisData.valuation.pbr}배` : "--" },
                        { label: "ROE", value: analysisData.valuation?.roe ? `${analysisData.valuation.roe}%` : "--" },
                        { label: "시가총액", value: analysisData.valuation?.market_cap_str || "--" },
                      ].map(item => (
                        <div key={item.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span style={{ color: "#888" }}>{item.label}</span>
                          <span style={{ fontWeight: 700 }}>{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div style={{ backgroundColor: "#fff1f1", borderRadius: 16, padding: 20, marginBottom: 24 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 800, marginBottom: 12, color: "#f04452" }}>⚠️ 리스크 체크 (Risk Flags)</h4>
                  {analysisData.risk?.flags?.length > 0 ? (
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {analysisData.risk.flags.map((f, i) => (
                        <div key={i} style={{ backgroundColor: "#fff", border: "1px solid #f04452", color: "#f04452", padding: "6px 12px", borderRadius: 8, fontSize: 12, fontWeight: 700 }}>
                          {f.label}: {f.value}
                        </div>
                      ))}
                    </div>
                  ) : <div style={{ fontSize: 13, color: "#00c471", fontWeight: 700 }}>감지된 주요 재무/기술적 리스크 없음</div>}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                  <div style={{ border: "1px solid #eee", borderRadius: 16, padding: 20 }}>
                    <h4 style={{ fontSize: 14, fontWeight: 800, marginBottom: 12 }}>🤝 최근 5일 수급 (Supply)</h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {[
                        { label: "외국인", value: analysisData.supply?.cum_5d?.foreign, color: (analysisData.supply?.cum_5d?.foreign || 0) >= 0 ? "#f04452" : "#2272eb" },
                        { label: "기관", value: analysisData.supply?.cum_5d?.institution, color: (analysisData.supply?.cum_5d?.institution || 0) >= 0 ? "#f04452" : "#2272eb" },
                        { label: "개인", value: analysisData.supply?.cum_5d?.individual, color: (analysisData.supply?.cum_5d?.individual || 0) >= 0 ? "#f04452" : "#2272eb" },
                      ].map(item => (
                        <div key={item.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span style={{ color: "#888" }}>{item.label}</span>
                          <span style={{ fontWeight: 800, color: item.color }}>{fmt(item.value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div style={{ border: "1px solid #eee", borderRadius: 16, padding: 20 }}>
                    <h4 style={{ fontSize: 14, fontWeight: 800, marginBottom: 12 }}>🏢 DART 재무 요약 ({analysisData.dart?.year}년)</h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {[
                        { label: "매출액", value: analysisData.dart?.revenue ? `${fmt(Math.round(analysisData.dart.revenue/100000000))}억` : "0억" },
                        { label: "영업이익", value: analysisData.dart?.operating_income ? `${fmt(Math.round(analysisData.dart.operating_income/100000000))}억` : "0억" },
                        { label: "영업이익률", value: analysisData.dart?.op_margin != null ? `${analysisData.dart.op_margin}%` : "0%" },
                        { label: "부채비율", value: analysisData.dart?.debt_ratio != null ? `${analysisData.dart.debt_ratio}%` : "0%" },
                      ].map(item => (
                        <div key={item.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span style={{ color: "#888" }}>{item.label}</span>
                          <span style={{ fontWeight: 700 }}>{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>
      )}

      {chartModal && (
        <div 
          onClick={() => setChartModal(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', 
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
          }}
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'white', borderRadius: '12px', padding: '2rem',
              maxWidth: '900px', width: '90%', maxHeight: '90vh', overflow: 'auto'
            }}
          >
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <h2 style={{fontSize: '1.5rem', fontWeight: '600', margin: 0}}>종목 상세: {chartModal}</h2>
                {livePrice && (
                  <div style={{
                    display: 'inline-block',
                    padding: '0.25rem 0.75rem',
                    background: '#10b981',
                    color: 'white',
                    borderRadius: '20px',
                    fontSize: '0.75rem',
                    marginLeft: '1rem'
                  }}>
                    🔴 LIVE · {livePrice.price.toLocaleString()}원 ({livePrice.change_pct > 0 ? '+' : ''}{livePrice.change_pct.toFixed(2)}%)
                    <span style={{opacity: 0.7, marginLeft: '0.5rem'}}>{livePrice.source}</span>
                  </div>
                )}
              </div>
              <button onClick={() => setChartModal(null)} style={{background: 'none', border: 'none', fontSize: '1.5rem', cursor: 'pointer'}}>✕</button>
            </div>
            <StockDetail ticker={chartModal} />
          </div>
        </div>
      )}

      {compareList.length > 0 && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          background: 'white', borderTop: '2px solid #0081ff',
          padding: '1rem 2rem', boxShadow: '0 -4px 12px rgba(0,0,0,0.1)',
          display: 'flex', alignItems: 'center', gap: '1rem', zIndex: 100
        }}>
          <strong>비교 중 ({compareList.length}/4):</strong>
          {compareList.map(c => (
            <span key={c.ticker} style={{
              padding: '0.25rem 0.75rem', background: '#eff6ff',
              borderRadius: '6px', fontSize: '0.875rem'
            }}>
              {c.name} ({c.ticker})
              <button 
                onClick={() => setCompareList(compareList.filter(x => x.ticker !== c.ticker))}
                style={{marginLeft: '0.5rem', background: 'none', border: 'none', cursor: 'pointer'}}
              >
                ✕
              </button>
            </span>
          ))}
          <button 
            onClick={() => setActiveNav('포트폴리오')}
            style={{
              marginLeft: 'auto', padding: '0.5rem 1.5rem',
              background: '#0081ff', color: 'white', border: 'none',
              borderRadius: '6px', cursor: 'pointer', fontWeight: '600'
            }}
          >
            비교하기 →
          </button>
          <button 
            onClick={() => setCompareList([])}
            style={{
              padding: '0.5rem 1rem', background: '#f3f4f6',
              border: '1px solid #d1d5db', borderRadius: '6px', cursor: 'pointer'
            }}
          >
            초기화
          </button>
        </div>
      )}

      <style>{`
        * { box-sizing:border-box; margin:0; padding:0; }
        body { font-family:'Pretendard','Noto Sans KR',sans-serif; }
        ::-webkit-scrollbar { width:4px; }
        ::-webkit-scrollbar-thumb { background:#e5e7eb; border-radius:4px; }
        tr:hover td { background:#fafafa; }
      `}</style>
    </div>
  );
}
