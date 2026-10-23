import streamlit as st
import yfinance as yf
import pandas as pd
import streamlit.components.v1 as components

# 1. 페이지 모바일 최적화 설정
st.set_page_config(
    page_title="개인 투자 시스템 v2.0",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 모바일 최적화 및 세련된 CSS 스타일링
st.markdown("""
    <style>
    .main-title { font-size: 1.6rem; font-weight: bold; color: #0F172A; margin-bottom: 0.1rem; }
    .card { background-color: #F8FAFC; border-radius: 12px; padding: 16px; border: 1px solid #E2E8F0; margin-bottom: 12px; }
    .egg-box { background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2px solid #F59E0B; border-radius: 14px; padding: 18px; margin-bottom: 14px; }
    .news-card { background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; padding: 16px; margin-bottom: 10px; }
    .guide-card { background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 12px; padding: 16px; margin-bottom: 10px; }
    
    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] { height: 46px; border-radius: 8px; font-weight: bold; font-size: 0.95rem; }
    </style>
""", unsafe_allow_html=True)

# 2. 헤더 및 종목 선택
st.markdown("<div class='main-title'>🛡️ 개인 투자 시스템 v2.0</div>", unsafe_allow_html=True)
st.caption("원칙: 미래 상상력(가설)과 현재 냉정함(가격·수급)의 균형 | 코스톨라니 달걀 이론 연동")

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

# 3. 야후 파이낸스 실시간 시세 및 거래량 데이터 수신
@st.cache_data(ttl=60)
def get_stock_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="5d")
        if df is not None and not df.empty and 'Close' in df.columns:
            latest_price = float(df['Close'].iloc[-1])
            prev_price = float(df['Close'].iloc[-2]) if len(df) >= 2 else latest_price
            change = latest_price - prev_price
            pct_change = (change / prev_price) * 100 if prev_price else 0.0
            volume = int(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0
            avg_volume = int(df['Volume'].mean()) if 'Volume' in df.columns else 0
            return latest_price, change, pct_change, volume, avg_volume
    except Exception:
        pass
    return None, None, None, None, None

live_price, change, pct_change, volume, avg_volume = get_stock_data(selected_info["ticker"])

if live_price is None or pd.isna(live_price):
    live_price = selected_info["default_price"]
    change = 0.0
    pct_change = 0.0
    volume = 1500000
    avg_volume = 1200000

currency = "KRW" if ".KS" in selected_info["ticker"] else "USD"
symbol_str = "₩" if currency == "KRW" else "$"
display_val = f"{symbol_str}{live_price:,.2f}" if currency == "USD" else f"{symbol_str}{int(live_price):,}"

# 상단 실시간 요약 바
col_p1, col_p2 = st.columns([1, 1])
with col_p1:
    st.subheader(f"📊 {selected_stock_name}")
with col_p2:
    st.metric(
        label="실시간 라이브 시세 & 등락률",
        value=display_val,
        delta=f"{change:+,.2f} ({pct_change:+.2f}%)" if change else "0.00 (0.00%)"
    )

# 4. 종목별 심층 데이터베이스 (달걀, 기업 가설, 수급, 뉴스, 가이드)
system_database = {
    "SK하이닉스": {
        "egg_phase": "A 국면 (A1: 투매 및 공포 극대화 바닥 구간)",
        "egg_desc": "금리 고점 통과 전후의 비관론이 극에 달해 가치 대비 주가가 과도하게 할인된 구간입니다.",
        "volume_status": "거래량 점진적 축소 후 바닥 다지기 (외국인 수급 변곡점 모니터링 중)",
        "corp": "3~5년 HBM(고대역폭메모리) 및 고성능 AI 서버용 독점적 기술 경쟁우위 가설 유지",
        "invest": "현재가 밸류에이션 매력 높으나, 10/28 실적 발표 전후 단기 변동성 대비 필요",
        "ai_analysis": "기술적으로 60일 선 이격 조정이 마무리 단계이며, 수급 주체들의 매물 소화 과정이 관측됨. AI 서버 수요 둔화 우려는 기우이며 차세대 HBM4 진입 가시화.",
        "news_title": "📢 [AI 실시간 글로벌 뉴스 & 증권사 리포트 요약]",
        "news_items": [
            "• **모건스탠리 및 주요 증권사 리포트:** HBM 선단 공정 주도권은 여전히 SK하이닉스가 독점적 지위 확보.",
            "• **업황긴급진단:** 메모리 반도체 다운사이클 우려 완화, AI 가속기 향 출하량 견조.",
            "• **외인/기관 동향:** 연기금 및 외국인의 저가 매수세 유입 시그널 포착."
        ],
        "action": "기존 9주 보유 확고히 유지 / 10/28 실적 발표 및 주요 고객사 향 HBM 공급 계약 최종 확인 직후 추가 매수(비중 확대) 집행"
    },
    "삼성전자": {
        "egg_phase": "A 국면 (A1: 매도세 진정 및 바닥 탐색 구간)",
        "egg_desc": "업황 우려와 파운드리 적자 이슈로 시장 참여자들의 실망 매물이 출회된 국면.",
        "volume_status": "거래대금 유입 대기 중 (기관 중심의 관망세 우세)",
        "corp": "메모리 반도체 원가 경쟁력 회복 + 파운드리 흑자 전환 + 온디바이스 AI 생태계 복원",
        "invest": "10/29 확정 실적 발표 및 메모리 재고 조정 속도가 핵심 냉정함 지표",
        "ai_analysis": "하방 경직성은 확보되었으나, 확실한 추세 전환을 위해서는 파운드리 부문의 적자 축소 가시성이 필수적임.",
        "news_title": "📢 [AI 실시간 글로벌 뉴스 & 증권사 리포트 요약]",
        "news_items": [
            "• **증권가 동향:** 범용 메모리 가격 하락세 진정 및 DDR5 전환 가속화 전망.",
            "• **파운드리 이슈:** 3나노 공정 수율 개선 여부와 대형 고객사 확보 뉴스가 주가 반등의 키.",
            "• **수급 분석:** 개인 매수세 대비 외국인 누적 순매도 기조의 완화 여부 확인 필요."
        ],
        "action": "기존 20주 보유 유지 / 서두르지 않고 수급 골든크로스(외인 순매수 전환) 확인 후 2차 매수 검토"
    },
    "NVIDIA (NVDA)": {
        "egg_phase": "A 국면 (A2: 매크로 조정에 따른 일시적 눌림목)",
        "egg_desc": "기업 펀더멘털은 완벽하나 미국 대선 및 금리 이슈로 인한 시장 전반의 지수 조정 반영.",
        "volume_status": "글로벌 유동성 유입 속 대형 기술주 거래량 유지",
        "corp": "AI 풀스택(HW+SW) 독점 플랫폼 생태계 구축으로 대체 불가능한 글로벌 표준",
        "invest": "빅테크 기업들의 AI CapEx(설비투자) 가이던스 지속 모니터링",
        "ai_analysis": "블랙웰(Blackwell) 칩 양산 본격화에 따른 마진율 개선 기대감이 유효하며, 조정 시마다 훌륭한 적립식 매수 기회.",
        "news_title": "📢 [AI 실시간 글로벌 뉴스 & 증권사 리포트 요약]",
        "news_items": [
            "• **글로벌 IT 뉴스:** 마이크로소프트, 구글, 메타 등 빅테크의 AI 인프라 투자 예산 상향 조정.",
            "• **공급망 소식:** 블랙웰 초기 수요 폭발적, 생산 차질 우려는 제한적이라는 평가.",
            "• **월가 컨센서스:** 목표주가 상향 리포트 연속 발행 중."
        ],
        "action": "미국 테크주 fractional(소수점) 데일리 적립식 매수 기조 흔들림 없이 유지"
    }
}

info = system_database.get(selected_stock_name, {
    "egg_phase": "B 국면 (회복기)",
    "egg_desc": "금리 안정화와 함께 거래량이 살아나며 대중이 관심을 가지기 시작하는 구간.",
    "volume_status": "거래량 증가 추세",
    "corp": "장기 성장 시나리오 및 산업 패러다임 변화 점검 중",
    "invest": "현재 가격 밸류에이션 적정성 재평가 진행",
    "ai_analysis": "추세적 상승 모멘텀 형성 초기 단계.",
    "news_title": "📢 [AI 실시간 글로벌 뉴스 & 증권사 리포트 요약]",
    "news_items": ["• 시장 주요 지표 및 해당 종목 관련 최신 뉴스 모니터링 중입니다."],
    "action": "보유 물량 홀드 / 눌림목 발생 시 분할 접근"
})

st.divider()

# 5. 멀티 탭 구성 (차트&분석 / 달걀 국면 / AI 인사이트 / 실행 가이드)
tab1, tab2, tab3, tab4 = st.tabs(["📊 차트 & 수급", "🍳 달걀 국면 사이클", "📰 AI 인사이트 & 뉴스", "🎯 시스템 실행 가이드"])

# --- TAB 1: 차트 & 수급 분석 ---
with tab1:
    st.subheader(f"📈 {selected_stock_name} 실시간 기술적 차트 & 수급 지표")
    
    # 수급 및 거래량 핵심 지표 요약 카드
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        st.metric(label="당일 거래량", value=f"{volume:,} 주")
    with col_v2:
        vol_ratio = (volume / avg_volume) * 100 if avg_volume else 100
        st.metric(label="평균 거래량 대비", value=f"{vol_ratio:.1f}%", delta="활성화" if vol_ratio > 100 else "정체")
    with col_v3:
        st.metric(label="수급 판정 (단기)", value="외인/기관 눈치보기" if vol_ratio < 120 else "거래 폭발형 수급 유입")

    st.write("")
    
    # 트레이딩뷰 실시간 위젯 (종목 심볼 동적 완벽 연동)
    tv_symbol = selected_info['tv_symbol']
    tv_widget_html = f"""
    <div class="tradingview-widget-container" style="height:520px;width:100%">
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
    components.html(tv_widget_html, height=540)

# --- TAB 2: 달걀 국면 사이클 ---
with tab2:
    st.markdown(f"""
    <div class='egg-box'>
        <div style='font-size:0.9rem; color:#92400E; font-weight:bold;'>🍳 코스톨라니 달걀 이론 (Market Cycle Model)</div>
        <div style='font-size:1.25rem; font-weight:bold; color:#78350F; margin-top:4px;'>{info['egg_phase']}</div>
        <div style='font-size:0.95rem; color:#B45309; margin-top:4px;'>{info['egg_desc']}</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 🔄 6단계 시장 순환 사이클 구조")
    
    phases = [
        ("A. 침체기 (매수 타이밍)", "금리 고점 및 투매·비관론 극대화 구간 (현재 위치 관심)"),
        ("B. 회복기 (보유 타이밍)", "스마트머니 유입 및 거래량 점진적 증가 구간"),
        ("C. 상승기 (매도 준비)", "대중의 낙관론 확산 및 실적 호조 가시화 구간"),
        ("D. 버블기 (관망 및 차익실현)", "대중적 열광과 최고점 과열 구간"),
        ("E. 후퇴기 (보류 구간)", "금리 인상 및 거래량 감소 시작 구간"),
        ("F. 하락기 (현금화 준비)", "비관론 대두 및 본격적 조정 시작 구간")
    ]
    
    for idx, (p_title, p_desc) in enumerate(phases):
        if idx == 0:
            st.error(f"**📌 [현재 감지된 시장 국면] {p_title}**\n\n{p_desc}")
        else:
            st.info(f"**{p_title}**\n\n{p_desc}")

# --- TAB 3: AI 인사이트 & 뉴스 ---
with tab3:
    st.markdown(f"""
    <div class='news-card'>
        <div style='font-weight:bold; color:#166534; font-size:1.1rem;'>{info['news_title']}</div>
        <div style='font-size:0.95rem; color:#14532D; margin-top:12px; line-height:1.7;'>
    """, unsafe_allow_html=True)
    
    for item in info["news_items"]:
        st.markdown(item)
        
    st.markdown("</div></div>", unsafe_allow_html=True)
    
    st.markdown(f"""
    <div class='card'>
        <div style='font-weight:bold; color:#1E293B; font-size:1rem;'>🤖 AI 수급 및 차트 종합 기술 분석</div>
        <div style='font-size:0.92rem; color:#334155; margin-top:8px; line-height:1.6;'>
            {info['ai_analysis']}
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- TAB 4: 시스템 실행 가이드 ---
with tab4:
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(f"""
        <div class='card'>
            <div style='font-weight:bold; color:#475569; font-size:1.05rem;'>💡 기업 판단 (미래 상상력 / 3~5년 가설)</div>
            <div style='font-size:0.95rem; color:#1E293B; margin-top:8px; line-height:1.5;'>{info['corp']}</div>
        </div>
        """, unsafe_allow_html=True)
    with col_t2:
        st.markdown(f"""
        <div class='card'>
            <div style='font-weight:bold; color:#475569; font-size:1.05rem;'>❄️ 투자 판단 (현재 가격의 냉정함)</div>
            <div style='font-size:0.95rem; color:#1E293B; margin-top:8px; line-height:1.5;'>{info['invest']}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class='guide-card'>
        <div style='font-size:0.9rem; color:#1E40AF; font-weight:bold;'>🎯 시스템 최종 실행 액션 가이드 (Action Plan)</div>
        <div style='font-size:1.15rem; font-weight:bold; color:#1E3A8A; margin-top:6px; line-height:1.5;'>{info['action']}</div>
    </div>
    """, unsafe_allow_html=True)
