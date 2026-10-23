import streamlit as st
import yfinance as yf
import pandas as pd

# 1. 페이지 설정 (모바일 최적화 다크 모드)
st.set_page_config(
    page_title="SAVE 스타일 투자 시스템",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# SAVE 앱 특유의 다크 테마 및 카드 UI 스타일링 CSS
st.markdown("""
    <style>
    /* 전체 배경 다크 모드 설정 */
    .stApp { background-color: #0F1117; color: #F8FAFC; }
    
    /* 상단 헤더 및 타이틀 */
    .save-logo { font-size: 1.4rem; font-weight: 900; color: #FFFFFF; background: #000; padding: 4px 12px; border-radius: 6px; display: inline-block; border: 1px solid #333; }
    
    /* 카드 컴포넌트 디자인 */
    .save-card { background-color: #1A1D24; border-radius: 14px; padding: 16px; border: 1px solid #2A2F3B; margin-bottom: 12px; }
    .index-card { background-color: #1A1D24; border-radius: 12px; padding: 14px; border: 1px solid #2A2F3B; text-align: center; }
    
    /* 텍스트 컬러 */
    .text-muted { color: #94A3B8; font-size: 0.85rem; }
    .text-green { color: #10B981; font-weight: bold; }
    .text-red { color: #EF4444; font-weight: bold; }
    
    /* 탭 메뉴 스타일링 */
    .stTabs [data-baseweb="tab-list"] { background-color: #161922; border-radius: 10px; padding: 4px; gap: 4px; }
    .stTabs [data-baseweb="tab"] { height: 40px; border-radius: 8px; font-weight: bold; color: #94A3B8; font-size: 0.9rem; }
    .stTabs [aria-selected="true"] { background-color: #262B38 !important; color: #FFFFFF !important; }
    </style>
""", unsafe_allow_html=True)

# 2. 상단 로고 및 알람 바
col_logo, col_bell = st.columns([8, 2])
with col_logo:
    st.markdown("<div class='save-logo'>SAVE</div>", unsafe_allow_html=True)
with col_bell:
    st.markdown("<div style='text-align: right; font-size: 1.2rem; cursor: pointer;'>🔔 🔍</div>", unsafe_allow_html=True)

st.write("")

# 3. 하단 네비게이션 모사 탭 메뉴 (뉴스 / 증시 / 캘린더 / 내정보)
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(["📰 뉴스", "📈 증시 & 관심종목", "📅 캘린더", "👤 내 정보"])

# --- [TAB 1] 뉴스 피드 화면 ---
with main_tab1:
    st.markdown("<div class='text-muted'>🔥 실시간 트렌드 | 트럼프 · 반도체 · 스페이스X</div>", unsafe_allow_html=True)
    st.write("")
    
    # 주요 뉴스 카드 (SAVE PICK)
    st.markdown("""
    <div class='save-card'>
        <div style='display: flex; justify-content: space-between; align-items: center;'>
            <span style='background: #3B82F6; color: white; font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; font-weight: bold;'>SAVE PICK · 정보</span>
            <span class='text-muted'>2026. 10. 23. 07:41</span>
        </div>
        <div style='font-size: 1.05rem; font-weight: bold; color: #FFFFFF; margin-top: 8px;'>
            (카더라) 스페이스X, 자체 이동통신망 구축 위해 미국 내 기지국 8만 곳 확보 협상
        </div>
        <div style='margin-top: 10px;'>
            <span style='color: #94A3B8; font-size: 0.8rem;'>$SPCX  $T  $TMUS  +1</span>
            <span style='float: right; color: #94A3B8; font-size: 0.8rem;'>👁️ 11.4K</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 일반 뉴스 카드
    st.markdown("""
    <div class='save-card'>
        <div style='display: flex; justify-content: space-between; align-items: center;'>
            <span style='background: #D97706; color: white; font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; font-weight: bold;'>로이터 · 속보</span>
            <span class='text-muted'>3분 전</span>
        </div>
        <div style='font-size: 1rem; font-weight: bold; color: #FFFFFF; margin-top: 8px;'>
            ENI, 연료 가격 상한제 1년 내내 연장... CEO가 이탈리아 신문에 밝혀
        </div>
        <div style='margin-top: 10px;'>
            <span style='color: #94A3B8; font-size: 0.8rem;'>$E</span>
            <span style='float: right; color: #94A3B8; font-size: 0.8rem;'>👁️ 21</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- [TAB 2] 증시 & 관심종목 화면 (SAVE 앱 핵심) ---
with main_tab2:
    st.markdown("### 📊 주요 지수 (실시간)")
    
    # 주요 지수 3개 컬럼 배치 (QQQ, SPY, DIA)
    i_col1, i_col2, i_col3 = st.columns(3)
    with i_col1:
        st.markdown("""
        <div class='index-card'>
            <div class='text-muted'>QQQ ETF</div>
            <div style='font-size: 1rem; font-weight: bold;'>나스닥100</div>
            <div style='font-size: 1.1rem; font-weight: bold; margin-top: 4px;'>$706.99</div>
            <div class='text-green'>+0.36%</div>
        </div>
        """, unsafe_allow_html=True)
    with i_col2:
        st.markdown("""
        <div class='index-card'>
            <div class='text-muted'>SPY ETF</div>
            <div style='font-size: 1rem; font-weight: bold;'>S&P500</div>
            <div style='font-size: 1.1rem; font-weight: bold; margin-top: 4px;'>$762.12</div>
            <div class='text-red'>-0.24%</div>
        </div>
        """, unsafe_allow_html=True)
    with i_col3:
        st.markdown("""
        <div class='index-card'>
            <div class='text-muted'>DIA ETF</div>
            <div style='font-size: 1rem; font-weight: bold;'>다우존스</div>
            <div style='font-size: 1.1rem; font-weight: bold; margin-top: 4px;'>$522.41</div>
            <div class='text-red'>-1.04%</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.write("")
    st.markdown("### ⭐ 관심 종목 리스트")
    
    # 관심 종목 리스트 (엔비디아, 테슬라, 팔란티어 등)
    watchlist = [
        {"name": "엔비디아", "ticker": "NVDA", "price": 212.24, "change": 0.02},
        {"name": "테슬라", "ticker": "TSLA", "price": 373.11, "change": -0.39},
        {"name": "팔란티어 테크놀로지", "ticker": "PLTR", "price": 196.11, "change": -0.04},
        {"name": "알파벳 Class A", "ticker": "GOOGL", "price": 323.37, "change": -0.26}
    ]
    
    for item in watchlist:
        ch_color = "text-green" if item["change"] >= 0 else "text-red"
        sign = "+" if item["change"] >= 0 else ""
        st.markdown(f"""
        <div class='save-card' style='padding: 12px 16px; margin-bottom: 8px;'>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <div>
                    <span style='font-weight: bold; font-size: 1rem; color: #FFF;'>{item['name']}</span><br>
                    <span class='text-muted'>{item['ticker']}</span>
                </div>
                <div style='text-align: right;'>
                    <span style='font-weight: bold; font-size: 1rem; color: #FFF;'>${item['price']:,.2f}</span><br>
                    <span class='{ch_color}'>{sign}{item['change']}%</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# --- [TAB 3] 캘린더 화면 ---
with main_tab3:
    st.markdown("### 📅 경제 실적 및 이벤트 캘린더")
    st.markdown("""
    <div class='save-card'>
        <div style='font-weight: bold; color: #F59E0B;'>📌 다중 실적 발표 일정</div>
        <div class='text-muted' style='margin-top: 6px;'>
            • 10/28: SK하이닉스 3분기 실적 발표 대기<br>
            • 10/29: 삼성전자 확정 실적 및 파운드리 가이던스 공개<br>
            • 빅테크 CapEx 지출 성과 발표 집중 구간
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- [TAB 4] 내 정보 & 포트폴리오 트래커 ---
with main_tab4:
    st.markdown("### 👤 내 정보 및 자산 관리")
    st.markdown("""
    <div class='save-card'>
        <div style='font-weight: bold; font-size: 1rem; color: #FFF;'>🛡️ 개인 투자 시스템 계정</div>
        <div class='text-muted' style='margin-top: 4px;'>원칙 중심 장기 투자 모드 활성화됨</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.subheader("💼 포트폴리오 요약")
    my_shares = st.number_input("엔비디아(NVDA) 보유 수량", min_value=0, value=5)
    my_avg = st.number_input("평균 매수가 ($)", min_value=0.0, value=150.0)
    
    current_nvda_price = 212.24
    total_eval = my_shares * current_nvda_price
    total_invest = my_shares * my_avg
    profit = total_eval - total_invest
    profit_pct = (profit / total_invest * 100) if total_invest > 0 else 0
    
    st.markdown(f"""
    <div class='save-card'>
        <div class='text-muted'>총 평가 금액</div>
        <div style='font-size: 1.4rem; font-weight: bold; color: #FFF;'>${total_eval:,.2f}</div>
        <div style='margin-top: 8px;' class='text-green'>평가 손익: ${profit:+,.2f} ({profit_pct:+.2f}%)</div>
    </div>
    """, unsafe_allow_html=True)
