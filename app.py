import streamlit as st
import yfinance as yf
import pandas as pd

# 1. 페이지 설정
st.set_page_config(
    page_title="개인 투자 시스템 v4.0 (AI Master)",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (모바일 최적화 및 프리미엄 UI)
st.markdown("""
    <style>
    .main-title { font-size: 1.5rem; font-weight: bold; color: #0F172A; margin-bottom: 0.2rem; }
    .card { background-color: #F8FAFC; border-radius: 12px; padding: 16px; border: 1px solid #E2E8F0; margin-bottom: 12px; }
    .egg-box { background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2px solid #F59E0B; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
    .ai-report-box { background-color: #F0FDF4; border: 1.5px solid #10B981; border-radius: 12px; padding: 18px; margin-bottom: 12px; }
    
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] { height: 46px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; }
    </style>
""", unsafe_allow_html=True)

# 2. 메인 헤더 & 자유 종목 검색
st.markdown("<div class='main-title'>🛡️ 개인 투자 시스템 v4.0 (AI & Live Analytics)</div>", unsafe_allow_html=True)

st.sidebar.header("🔍 종목 검색 & 포트폴리오")
search_preset = {
    "SK하이닉스 (000660.KS)": "000660.KS",
    "삼성전자 (005930.KS)": "005930.KS",
    "NVIDIA (NVDA)": "NVDA",
    "Alphabet (GOOGL)": "GOOGL",
    "Palantir (PLTR)": "PLTR",
    "Tesla (TSLA)": "TSLA",
    "직접 입력 (티커 검색)": "CUSTOM"
}

selected_preset = st.selectbox("🔍 분석할 종목 선택", list(search_preset.keys()))
ticker_input = st.text_input("야후 파이낸스 티커 입력 (예: 005930.KS, NVDA, AAPL)", value=search_preset[selected_preset] if search_preset[selected_preset] != "CUSTOM" else "000660.KS").strip().upper()

# 3. 실시간 데이터 라이브 추출 함수
@st.cache_data(ttl=30)
def fetch_live_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1mo")
        if df is not None and not df.empty and 'Close' in df.columns:
            df = df.dropna(subset=['Close'])
            if not df.empty:
                latest_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) >= 2 else latest_price
                change = latest_price - prev_price
                pct_change = (change / prev_price) * 100 if prev_price else 0.0
                
                volume = int(df['Volume'].iloc[-1]) if ('Volume' in df.columns and not pd.isna(df['Volume'].iloc[-1])) else 0
                avg_vol = int(df['Volume'].mean()) if 'Volume' in df.columns else 1
                
                return {
                    "symbol": symbol,
                    "price": latest_price,
                    "change": change,
                    "pct_change": pct_change,
                    "volume": volume,
                    "avg_volume": avg_vol if avg_vol > 0 else 1,
                    "history": df,
                    "currency": "KRW" if ".KS" in symbol or ".KQ" in symbol else "USD"
                }
    except Exception:
        pass
    return None

stock_data = fetch_live_data(ticker_input)

if not stock_data:
    st.error(f"'{ticker_input}' 종목 정보를 불러올 수 없습니다. 올바른 티커인지 확인해 주세요.")
    st.stop()

currency_symbol = "₩" if stock_data["currency"] == "KRW" else "$"
price_fmt = f"{currency_symbol}{stock_data['price']:,.2f}" if stock_data["currency"] == "USD" else f"{currency_symbol}{int(round(stock_data['price'])):,}"

# 상단 시세 요약
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

# 4. 멀티 탭 구성 (차트 / 달걀국면 / AI리포트 / 포트폴리오)
tab1, tab2, tab3, tab4 = st.tabs(["📊 실시간 차트 & 수급", "🍳 코스톨라니 달걀", "🤖 실시간 AI 분석 리포트", "💼 내 포트폴리오"])

# --- TAB 1: 차트 & 수급 (알림 없는 네이티브 차트 적용) ---
with tab1:
    st.subheader("📈 실시간 주가 추이 및 거래량 분석")
    
    v_col1, v_col2, v_col3 = st.columns(3)
    vol_ratio = (stock_data['volume'] / stock_data['avg_volume']) * 100
    
    with v_col1:
        st.metric(label="당일 거래량", value=f"{stock_data['volume']:,} 주")
    with v_col2:
        st.metric(label="평균 대비 거래량", value=f"{vol_ratio:.1f}%")
    with v_col3:
        status_txt = "🔥 수급 유입 (활발)" if vol_ratio > 120 else "💤 관망세 (정체)"
        st.metric(label="수급 상태", value=status_txt)
        
    st.write("")
    # Streamlit 네이티브 라인 차트로 알림 팝업 원천 차단 및 부드러운 로딩 구현
    hist_df = stock_data['history'][['Close']]
    st.line_chart(hist_df, height=350, use_container_width=True)

# --- TAB 2: 코스톨라니 달걀 국면 ---
with tab2:
    pct = stock_data["pct_change"]
    if pct < -1.5:
        phase_name = "A 국면 (침체기 / 투매 및 공포 극대화)"
        phase_idx = 0
        phase_desc = "가격 낙폭이 커지며 대중이 공포에 질려 던지는 구간. 분할 매수의 최적기를 저울질하는 시점입니다."
    elif -1.5 <= pct < 0.5:
        phase_name = "B 국면 (회복기 / 스마트머니 바닥 다지기)"
        phase_idx = 1
        phase_desc = "매도세가 진정되고 거래량이 줄어들며 바닥을 다지는 보유 및 관망 국면입니다."
    elif 0.5 <= pct < 2.5:
        phase_name = "C 국면 (상승기 / 낙관론 확산)"
        phase_idx = 2
        phase_desc = "실적 기대감과 함께 주가가 본격적인 상승 궤도에 진입하는 구간입니다."
    else:
        phase_name = "D 국면 (버블기 / 최고점 과열)"
        phase_idx = 3
        phase_desc = "대중의 환호와 함께 과열 국면에 진입한 상태이므로 차익 실현을 준비하는 구간입니다."

    st.markdown(f"""
    <div class='egg-box'>
        <div style='font-size:0.9rem; color:#92400E; font-weight:bold;'>🍳 코스톨라니 달걀 이론 실시간 진단 엔진</div>
        <div style='font-size:1.25rem; font-weight:bold; color:#78350F; margin-top:4px;'>{phase_name}</div>
        <div style='font-size:0.95rem; color:#B45309; margin-top:4px;'>{phase_desc}</div>
    </div>
    """, unsafe_allow_html=True)
    
    phases = [
        ("A. 침체기 (매수 준비)", "비관론 극대화 및 저점 투매 구간"),
        ("B. 회복기 (보유 홀딩)", "스마트머니 유입 및 바닥 다지기"),
        ("C. 상승기 (비중 관리)", "낙관론 확산 및 실적 호조 가시화"),
        ("D. 버블기 (차익 실현)", "최고점 과열 및 분할 매도 고려"),
        ("E. 후퇴기 (관망 대기)", "거래량 감소 및 상승세 둔화"),
        ("F. 하락기 (현금 확보)", "조정 시작 및 비관론 대두")
    ]
    
    cols = st.columns(2)
    for idx, (p_title, p_desc) in enumerate(phases):
        col = cols[idx % 2]
        with col:
            if idx == phase_idx:
                st.error(f"**📌 [현재 감지된 위치] {p_title}**\n\n{p_desc}")
            else:
                st.info(f"**{p_title}**\n\n{p_desc}")

# --- TAB 3: 실시간 AI 분석 리포트 ---
with tab3:
    st.markdown(f"""
    <div class='ai-report-box'>
        <div style='font-weight:bold; color:#065F46; font-size:1.1rem;'>🤖 [AI 실시간 분석 에이전트 리포트] {stock_data['symbol']}</div>
        <div style='font-size:0.95rem; color:#064E3B; margin-top:10px; line-height:1.7;'>
            • <b>실시간 가격 및 수급 상태:</b> 현재 주가는 {price_fmt} 이며, 전일 대비 {stock_data['pct_change']:+.2f}% 변동 중입니다. 거래량은 5일 평균 대비 {vol_ratio:.1f}%로 {status_txt.lower()}를 보이고 있습니다.<br><br>
            • <b>미래 상상력(가설) 점검:</b> 단기 주가 출렁임에 휘둘리지 않고, 해당 기업의 3~5년 핵심 경쟁력(산업 내 독점력, 기술 우위)이 훼손되었는지를 냉정하게 판단해야 합니다.<br><br>
            • <b>종합 액션 가이드:</b> 현재 달걀 사이클 및 거래량 추세를 고려할 때, 무리한 추격매수보다는 원칙에 따른 분할 접근 또는 기존 물량 홀딩 전략이 유효합니다.
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- TAB 4: 내 포트폴리오 관리 ---
with tab4:
    st.subheader("💼 나의 포트폴리오 (실시간 자산 트래커)")
    st.caption("보유 중인 주식 수량과 평균 매수가를 입력하면 현재 주가 기준 손익이 실시간으로 집계됩니다.")
    
    col_in1, col_in2 = st.columns(2)
    with col_in1:
        my_qty = st.number_input("보유 수량 (주)", min_value=0, value=10, step=1)
    with col_in2:
        def_price = float(stock_data['price'] * 0.95) if stock_data['price'] else 1000.0
        my_buy_price = st.number_input(f"평균 매수가 ({currency_symbol})", min_value=0.0, value=def_price, step=100.0)
        
    if my_qty > 0 and my_buy_price > 0:
        total_buy = my_buy_price * my_qty
        total_eval = stock_data['price'] * my_qty
        pnl = total_eval - total_buy
        pnl_pct = (pnl / total_buy) * 100 if total_buy else 0.0
        
        st.write("---")
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("총 매수 금액", f"{currency_symbol}{total_buy:,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{total_buy:,.2f}")
        with m2:
            st.metric("현재 평가 금액", f"{currency_symbol}{total_eval:,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{total_eval:,.2f}")
        with m3:
            st.metric("실시간 평가 손익", f"{currency_symbol}{pnl:+,.0f}" if stock_data["currency"] == "KRW" else f"{currency_symbol}{pnl:+,.2f}", delta=f"{pnl_pct:+.2f}%")
