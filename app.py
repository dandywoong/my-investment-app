import streamlit as st
import yfinance as yf
import pandas as pd
import streamlit.components.v1 as components

# 1. 페이지 모바일 최적화 설정
st.set_page_config(
    page_title="개인 투자 시스템 v1.0",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (카드 디자인 및 간격 최적화)
st.markdown("""
    <style>
    .main-title { font-size: 1.6rem; font-weight: bold; color: #0F172A; margin-bottom: 0.2rem; }
    .card { background-color: #F8FAFC; border-radius: 12px; padding: 16px; border: 1px solid #E2E8F0; margin-bottom: 12px; }
    .egg-header { background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2px solid #F59E0B; border-radius: 14px; padding: 16px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# 2. 메인 타이틀 헤더
st.markdown("<div class='main-title'>🛡️ 개인 투자 시스템 v1.0</div>", unsafe_allow_html=True)
st.caption("시스템 관점: 기업의 3~5년 미래 가설 + 현재 가격의 냉정함 + 코스톨라니 달걀 이론")

# 3. 종목 정보 매핑
stocks = {
    "SK하이닉스": {"ticker": "000660.KS", "tv_symbol": "KRX:000660", "default_price": 1277000},
    "삼성전자": {"ticker": "005930.KS", "tv_symbol": "KRX:005930", "default_price": 215500},
    "NVIDIA (NVDA)": {"ticker": "NVDA", "tv_symbol": "NASDAQ:NVDA", "default_price": 138.5},
    "Alphabet (GOOGL)": {"ticker": "GOOGL", "tv_symbol": "NASDAQ:GOOGL", "default_price": 165.2},
    "Palantir (PLTR)": {"ticker": "PLTR", "tv_symbol": "NYSE:PLTR", "default_price": 42.1},
    "Tesla (TSLA)": {"ticker": "TSLA", "tv_symbol": "NASDAQ:TSLA", "default_price": 220.0},
    "IonQ (IONQ)": {"ticker": "IONQ", "tv_symbol": "NYSE:IONQ", "default_price": 11.5}
}

selected_stock_name = st.selectbox("🔍 분석할 종목 선택", list(stocks.keys()))
selected_info = stocks[selected_stock_name]

# 4. 야후 파이낸스 실시간 시세 (안전 폴백 장치 포함)
@st.cache_data(ttl=60)
def get_live_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="2d")
        if df is not None and not df.empty and 'Close' in df.columns:
            if len(df) >= 2:
                latest_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2])
                change = latest_price - prev_price
                pct_change = (change / prev_price) * 100
                return latest_price, change, pct_change
            elif len(df) == 1:
                return float(df['Close'].iloc[-1]), 0.0, 0.0
    except Exception:
        pass
    return None, None, None

live_price, change, pct_change = get_live_data(selected_info["ticker"])

if live_price is None or pd.isna(live_price):
    live_price = selected_info["default_price"]
    change = 0.0
    pct_change = 0.0

st.divider()

# 5. 실시간 시세 표기
col_price1, col_price2 = st.columns([1, 1])

with col_price1:
    st.subheader(f"📊 {selected_stock_name}")

with col_price2:
    currency = "KRW" if ".KS" in selected_info["ticker"] else "USD"
    symbol_str = "₩" if currency == "KRW" else "$"
    display_val = f"{symbol_str}{live_price:,.2f}" if currency == "USD" else f"{symbol_str}{int(live_price):,}"
    st.metric(
        label="실시간 시세 (Yahoo Finance)",
        value=display_val,
        delta=f"{change:+,.2f} ({pct_change:+.2f}%)" if change else "0.00 (0.00%)"
    )

# 6. 시스템 판단 및 달걀 국면 매핑 데이터
stock_system_data = {
    "SK하이닉스": {
        "phase_idx": 0,  # A 국면
        "egg_title": "A 국면: 과매도 / 투매 바닥 구간",
        "egg_desc": "공포심 극대화 및 심리적 바닥 다지기 진행 중 (A1 구간)",
        "corp": "3~5년 HBM 및 고성능 메모리 독점적 경쟁우위 가설 유지",
        "invest": "10/28 실적 발표 대기 및 외국인 수급 추이 점검",
        "action": "기존 9주 보유 유지 / 실적 발표 후 HBM 공급 계약 확인 시 추가 매수 검토"
    },
    "삼성전자": {
        "phase_idx": 0,  # A 국면
        "egg_title": "A 국면: 과매도 / 투매 바닥 구간",
        "egg_desc": "메모리 가격 회복 기대 및 외국인 매도세 진정 관찰 (A1 구간)",
        "corp": "메모리+파운드리+디바이스 종합 생태계 복원 가설",
        "invest": "10/29 확정 실적 및 파운드리 적자 폭 확인 필요",
        "action": "기존 20주 보유 유지 / 저가 매수 서두르지 않고 확실한 수급 전환 확인 후 대응"
    },
    "NVIDIA (NVDA)": {
        "phase_idx": 0,  # A 국면
        "egg_title": "A 국면: 기술주 조정 구간",
        "egg_desc": "AI 펀더멘털 견고하나 시장 전체 매도세 반영 중 (A2 구간)",
        "corp": "AI 풀스택 컴퓨팅 플랫폼 독점 및 대체 불가능한 소프트웨어 생태계",
        "invest": "빅테크 CapEx 지출 성과 지표 지속 확인",
        "action": "핵심 성장주 분할 적립 유지 / 전체 포트폴리오 비중 관리"
    }
}

info = stock_system_data.get(selected_stock_name, {
    "phase_idx": 1,
    "egg_title": "B 국면: 회복기 (보유 구간)",
    "egg_desc": "거래량 증가 및 추세 전환 모색 구간",
    "corp": "장기 성장 가설 점검 중",
    "invest": "현재 가격 밸류에이션 재평가 진행 중",
    "action": "보유 관점 유지 / 추가 매수 보류 및 신호 확인"
})

current_idx = info["phase_idx"]

# 7. 코스톨라니 달걀 사이클 시각화 (스트림릿 네이티브 그리드 카드 활용)
st.markdown(f"""
<div class='egg-header'>
    <div style='font-size:0.9rem; color:#92400E; font-weight:bold;'>🍳 코스톨라니 달걀 이론 사이클 (Market Cycle)</div>
    <div style='font-size:1.2rem; font-weight:bold; color:#78350F; margin-top:2px;'>{info['egg_title']}</div>
    <div style='font-size:0.9rem; color:#B45309;'>{info['egg_desc']}</div>
</div>
""", unsafe_allow_html=True)

phases_info = [
    ("A. 침체기", "최저점 / 투매 구간"),
    ("B. 회복기", "거래량 증가 구간"),
    ("C. 상승기", "낙관론 확산 구간"),
    ("D. 버블기", "최고점 / 과열 구간"),
    ("E. 후퇴기", "거래량 감소 구간"),
    ("F. 하락기", "비관론 시작 구간")
]

cols = st.columns(3)
for idx, (p_name, p_desc) in enumerate(phases_info):
    col = cols[idx % 3]
    with col:
        if idx == current_idx:
            st.error(f"**📌 [현재위치] {p_name}**\n\n{p_desc}")
        else:
            st.info(f"**{p_name}**\n\n{p_desc}")

st.write("")

# 8. 2트랙 기업/투자 판단 & 실행 가이드
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"<div class='card'><div style='font-weight:bold; color:#475569;'>💡 기업 판단 (미래 상상력)</div><div style='font-size:0.9rem; margin-top:6px;'>{info['corp']}</div></div>", unsafe_allow_html=True)
with col2:
    st.markdown(f"<div class='card'><div style='font-weight:bold; color:#475569;'>❄️ 투자 판단 (현재 냉정함)</div><div style='font-size:0.9rem; margin-top:6px;'>{info['invest']}</div></div>", unsafe_allow_html=True)

st.markdown(f"<div class='card' style='background-color:#EFF6FF; border-color:#BFDBFE;'><div style='font-size:0.85rem; color:#1E40AF; font-weight:bold;'>🎯 시스템 최종 실행 가이드</div><div style='font-size:1rem; font-weight:bold; color:#1E3A8A; margin-top:4px;'>{info['action']}</div></div>", unsafe_allow_html=True)

# 9. 트레이딩뷰 실시간 차트
st.subheader("📈 실시간 기술적 차트 (TradingView)")
tv_symbol = selected_info['tv_symbol']

tv_widget_html = f"""
<div class="tradingview-widget-container" style="height:500px;width:100%">
  <div id="tradingview_chart" style="height:calc(100% - 32px);width:100%"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
  new TradingView.widget(
  {{
  "autosize": true,
  "symbol": "{tv_symbol}",
  "interval": "D",
  "timezone": "Asia/Seoul",
  "theme": "light",
  "style": "1",
  "locale": "kr",
  "toolbar_bg": "#f1f3f6",
  "enable_publishing": false,
  "allow_symbol_change": true,
  "container_id": "tradingview_chart"
  }}
  );
  </script>
</div>
"""
components.html(tv_widget_html, height=520)
