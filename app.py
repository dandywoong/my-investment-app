import streamlit as st
import yfinance as yf
import pandas as pd
import streamlit.components.v1 as components

# 1. 페이지 설정
st.set_page_config(
    page_title="개인 투자 시스템 v3.0",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (모바일 최적화 및 세련된 UI)
st.markdown("""
    <style>
    .main-title { font-size: 1.5rem; font-weight: bold; color: #0F172A; margin-bottom: 0.2rem; }
    .card { background-color: #F8FAFC; border-radius: 12px; padding: 16px; border: 1px solid #E2E8F0; margin-bottom: 12px; }
    .egg-box { background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2px solid #F59E0B; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
    .ai-box { background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; padding: 16px; margin-bottom: 12px; }
    
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] { height: 46px; border-radius: 8px; font-weight: bold; font-size: 0.92rem; }
    </style>
""", unsafe_allow_html=True)

# 2. 메인 헤더
st.markdown("<div class='main-title'>🛡️ 개인 투자 시스템 v3.0 (AI & 포트폴리오)</div>", unsafe_allow_html=True)

# 3. 사이드바 / 상단 종목 검색 시스템 (한국 및 미국 모든 종목 지원)
st.sidebar.header("🔍 종목 검색 & 포트폴리오 설정")

# 자주 찾는 추천 종목 + 자유 입력 조합
search_preset = {
    "SK하이닉스 (000660.KS)": "000660.KS",
    "삼성전자 (005930.KS)": "005930.KS",
    "NVIDIA (NVDA)": "NVDA",
    "Alphabet (GOOGL)": "GOOGL",
    "Palantir (PLTR)": "PLTR",
    "Tesla (TSLA)": "TSLA",
    "IonQ (IONQ)": "IONQ",
    "직접 입력 (티커/종목코드)": "CUSTOM"
}

selected_preset = st.selectbox("🔍 종목 선택 또는 티커 검색", list(search_preset.keys()))

if search_preset[selected_preset] == "CUSTOM":
    ticker_input = st.text_input("야후 파이낸스 티커 입력 (예: 005930.KS, NVDA, AAPL)", value="000660.KS").strip().upper()
else:
    ticker_input = search_preset[selected_preset]

# 4. 실시간 주가 및 수급 데이터 라이브 추출 함수
@st.cache_data(ttl=30)
def fetch_live_stock_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d")
        info = ticker.fast_info
        
        if df is not None and not df.empty and 'Close' in df.columns:
            latest_price = float(df['Close'].iloc[-1])
            prev_price = float(df['Close'].iloc[-2]) if len(df) >= 2 else latest_price
            change = latest_price - prev_price
            pct_change = (change / prev_price) * 100 if prev_price else 0.0
            volume = int(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0
            avg_volume = int(df['Volume'].mean()) if 'Volume' in df.columns else 1
            
            return {
                "symbol": symbol,
                "price": latest_price,
                "change": change,
                "pct_change": pct_change,
                "volume": volume,
                "avg_volume": avg_volume,
                "currency": "KRW" if ".KS" in symbol or ".KQ" in symbol else "USD"
            }
    except Exception:
        pass
    return None

stock_data = fetch_live_stock_data(ticker_input)

if not stock_data:
    st.error(f"'{ticker_input}' 종목 정보를 불러올 수 없습니다. 올바른 티커(예: 005930.KS, NVDA)인지 확인해 주세요.")
    st.stop()

# 시세 표기 가공
currency_symbol = "₩" if stock_data["currency"] == "KRW" else "$"
price_fmt = f"{currency_symbol}{stock_data['price']:,.2f}" if stock_data["currency"] == "USD" else f"{currency_symbol}{int(stock_data['price']):,}"

col_h1, col_h2 = st.columns([1, 1])
with col_h1:
    st.subheader(f"📊 {ticker_input}")
with col_h2:
    st.metric(
        label="실시간 라이브 시세",
        value=price_fmt,
        delta=f"{stock_data['change']:+,.2f} ({stock_data['pct_change']:+.2f}%)"
    )

st.divider()

# 5. 메인 멀티 탭 구성
tab1, tab2, tab3, tab4 = st.tabs(["📊 차트 & 수급", "🍳 AI 달걀 국면 분석", "🤖 실시간 AI 리포트", "💼 내 포트폴리오"])

# --- TAB 1: 차트 & 수급 지표 ---
with tab1:
    st.subheader("📈 실시간 기술적 차트 & 수급 분석")
    
    v_col1, v_col2, v_col3 = st.columns(3)
    vol_ratio = (stock_data['volume'] / stock_data['avg_volume']) * 100 if stock_data['avg_volume'] else 100
    
    with v_col1:
        st.metric(label="당일 거래량", value=f"{stock_data['volume']:,} 주")
    with v_col2:
        st.metric(label="5일 평균 대비 거래량", value=f"{vol_ratio:.1f}%")
    with v_col3:
        status_text = "거래 폭발 (수급 유입)" if vol_ratio > 130 else ("거래 정체 (관망)" if vol_ratio < 70 else "보통 거래 흐름")
        st.metric(label="수급 상태 판정", value=status_text)
        
    st.write("")
    
    # 트레이딩뷰 심볼 형식 자동 변환
    tv_code = stock_data['symbol']
    if ".KS" in tv_code:
        tv_symbol = f"KRX:{tv_code.replace('.KS', '')}"
    elif ".KQ" in tv_code:
        tv_symbol = f"KOSDAQ:{tv_code.replace('.KQ', '')}"
    else:
        tv_symbol = tv_code
        
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

# --- TAB 2: AI 코스톨라니 달걀 국면 판정 ---
with tab2:
    # 수급/등락률에 기반한 규칙 기반 AI 국면 판정 엔진
    pct = stock_data["pct_change"]
    
    if pct < -2.0:
        current_phase = "A 국면 (침체기 / 투매 구간)"
        phase_idx = 0
        phase_desc = "가격 낙폭이 심화되며 비관론이 팽배한 구간입니다. 코스톨라니 관점에서는 분할 매수 기회 모니터링 구간입니다."
    elif -2.0 <= pct < 0.5:
        current_phase = "B 국면 (회복기 / 바닥 다지기)"
        phase_idx = 1
        phase_desc = "매도세가 진정되고 바닥을 형성하며 거래량 회복을 기다리는 보유/관망 국면입니다."
    elif 0.5 <= pct < 3.0:
        current_phase = "C 국면 (상승기 / 낙관 확산)"
        phase_idx = 2
        phase_desc = "상승 모멘텀이 이어지며 주가가 본 궤도에 진입하는 구간입니다."
    else:
        current_phase = "D 국면 (과열기 / 버블 형성)"
        phase_idx = 3
        phase_desc = "단기 단급 상승으로 대중적 관심이 최고조에 달한 구간입니다. 추격 매수에 신중함이 필요합니다."

    st.markdown(f"""
    <div class='egg-box'>
        <div style='font-size:0.9rem; color:#92400E; font-weight:bold;'>🍳 코스톨라니 달걀 이론 실시간 국면 진단</div>
        <div style='font-size:1.25rem; font-weight:bold; color:#78350F; margin-top:4px;'>{current_phase}</div>
        <div style='font-size:0.92rem; color:#B45309; margin-top:4px;'>{phase_desc}</div>
    </div>
    """, unsafe_allow_html=True)
    
    phases = [
        ("A. 침체기 (매수 준비)", "비관론 극대화 및 가격 저점 구간"),
        ("B. 회복기 (보유 홀딩)", "스마트머니 유입 및 바닥 타진"),
        ("C. 상승기 (비중 관리)", "실적 호조 및 대중 참여 증가"),
        ("D. 버블기 (차익 실현)", "과열 및 분할 매도 고려"),
        ("E. 후퇴기 (관망 대기)", "거래량 감소 및 상승세 꺾임"),
        ("F. 하락기 (현금 확보)", "본격 조정 및 매도 우선")
    ]
    
    cols = st.columns(2)
    for idx, (p_title, p_desc) in enumerate(phases):
        col = cols[idx % 2]
        with col:
            if idx == phase_idx:
                st.error(f"**📌 [실시간 매핑] {p_title}**\n\n{p_desc}")
            else:
                st.info(f"**{p_title}**\n\n{p_desc}")

# --- TAB 3: 실시간 AI 리포트 ---
with tab3:
    st.markdown(f"""
    <div class='ai-box'>
        <div style='font-weight:bold; color:#166534; font-size:1.05rem;'>🤖 [AI 실시간 종목 진단 리포트] {stock_data['symbol']}</div>
        <div style='font-size:0.92rem; color:#14532D; margin-top:8px; line-height:1.6;'>
            • <b>실시간 가격/수급 동향:</b> 현재 주가는 {price_fmt} (전일 대비 {stock_data['pct_change']:+.2f}%) 수준에서 형성되어 있습니다.<br>
            • <b>거래량 수급 평가:</b> 5일 평균 거래량 대비 {vol_ratio:.1f}% 수준으로, {status_text} 상태를 보이고 있습니다.<br>
            • <b>투자 가설 및 냉정함 관점:</b> 단기 시장 변동성에 일희일비하기보다는 기업의 3~5년 장기 경쟁력 가설이 유효한지 점검할 타이밍입니다.
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- TAB 4: 내 포트폴리오 (삼성증권 등 보유 주식 관리) ---
with tab4:
    st.subheader("💼 나의 실시간 포트폴리오 자산 트래커")
    st.caption("실제 보유 중인 종목의 매수가와 수량을 입력하면 실시간 평가 손익이 자동으로 계산됩니다.")
    
    col_in1, col_in2 = st.columns(2)
    with col_in1:
        my_qty = st.number_input("보유 수량 (주)", min_value=0, value=10, step=1)
    with col_in2:
        my_buy_price = st.number_input(f"평균 매수가 ({currency_symbol})", min_value=0.0, value=float(stock_data['price'] * 0.95), step=100.0)
        
    if my_qty > 0 and my_buy_price > 0:
        total_buy = my_buy_price * my_qty
        total_eval = stock_data['price'] * my_qty
        pnl = total_eval - total_buy
        pnl_pct = (pnl / total_buy) * 100
        
        st.write("---")
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric("총 매수 금액", f"{currency_symbol}{total_buy:,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{total_buy:,.2f}")
        with m_col2:
            st.metric("현재 평가 금액", f"{currency_symbol}{total_eval:,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{total_eval:,.2f}")
        with m_col3:
            st.metric("실시간 평가 손익", f"{currency_symbol}{pnl:+,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{pnl:+,.2f}", delta=f"{pnl_pct:+.2f}%")
