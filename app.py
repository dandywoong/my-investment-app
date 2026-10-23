import streamlit as st
import pandas as pd

# 1. 페이지 모바일 최적화 설정
st.set_page_config(
    page_title="개인 투자 시스템 v1.0",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 커스텀 CSS (모바일 가독성 강화)
st.markdown("""
    <style>
    .main-title { font-size: 1.6rem; font-weight: bold; color: #1E293B; margin-bottom: 0.5rem; }
    .card { background-color: #F8FAFC; border-radius: 12px; padding: 16px; border: 1px solid #E2E8F0; margin-bottom: 12px; }
    .egg-box { background-color: #FEF3C7; border-left: 6px solid #D97706; padding: 12px; border-radius: 8px; margin: 10px 0; }
    </style>
""", unsafe_allow_html=True)

# 2. 메인 타이틀 헤더
st.markdown("<div class='main-title'>🛡️ 개인 투자 시스템 v1.0</div>", unsafe_allow_html=True)
st.caption("기준일: 2026년 10월 23일 | 원칙: 상상력과 냉정함의 균형")

# 3. 종목 선택 드롭다운
selected_stock = st.selectbox(
    "🔍 분석 및 상태 점검할 종목 선택",
    ["SK하이닉스", "삼성전자", "NVIDIA (NVDA)", "Alphabet (GOOGL)", "Palantir (PLTR)", "Tesla (TSLA)", "IonQ (IONQ)"]
)

st.divider()

# 4. 종목별 기본 mock 데이터 및 달걀 국면 매핑
stock_data = {
    "SK하이닉스": {
        "egg": "A 국면 (투매 / 비관론 극대화 구간)",
        "egg_pin": "📍 A1 구간: 과매도 및 심리적 바닥 형성 진행 중",
        "corp": "3~5년 HBM 및 고성능 메모리 독점적 경쟁우위 가설 유지",
        "invest": "현재가 1,220,000원 (평단가 1,679,961원 대비 하락). 10/28 실적 발표 대기",
        "action": "기존 9주 보유 유지 / 10/28 실적 발표 후 HBM 공급 계약 확인 후 추매 결정",
    },
    "삼성전자": {
        "egg": "A 국면 (투매 / 비관론 극대화 구간)",
        "egg_pin": "📍 A1 구간: 메모리 가격 회복 기대 및 외국인 매도세 상존",
        "corp": "메모리+파운드리+디바이스 종합 생태계 복원 가능성",
        "invest": "현재가 214,500원. 10/29 확정 실적 발표 확인 필요",
        "action": "기존 20주 보유 / 저가 매수 서두르지 않고 실적 발표 확인 후 대응",
    },
    "NVIDIA (NVDA)": {
        "egg": "A 국면 (미 기술주 투매 영향)",
        "egg_pin": "📍 A2 구간: AI 펀더멘털 견고하나 미 증시 조정 여파",
        "corp": "AI 풀스택 컴퓨팅 플랫폼 독점력 지지",
        "invest": "주가 약 $222 수준. Big Tech CapEx 지속 여부 점검",
        "action": "장기 핵심 성장주 보유 유지 / 자동매수 및 비중 관리",
    }
}

info = stock_data.get(selected_stock, {
    "egg": "A~B 경계 (방향 판별 구간)",
    "egg_pin": "📍 관망 구간: 추세 전환 신호 확인 필요",
    "corp": "장기 성장 가설 점검 중",
    "invest": "현재 가격 밸류에이션 재평가 진행 중",
    "action": "보유 관점 유지 / 추가 매수 보류",
})

# 5. 대시보드 화면 구성
st.subheader(f"📊 {selected_stock} 현황 분석")

st.markdown(f"""
<div class='egg-box'>
    <span style='font-size:0.85rem; color:#92400E; font-weight:bold;'>🍳 코스톨라니 달걀 국면 판정</span><br>
    <span style='font-size:1.1rem; font-weight:bold; color:#78350F;'>{info['egg']}</span><br>
    <span style='font-size:0.95rem; color:#B45309;'>{info['egg_pin']}</span>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class='card'>
        <div style='font-weight:bold; color:#475569;'>💡 기업 판단 (3~5년 미래)</div>
        <div style='font-size:0.9rem; margin-top:6px;'>""" + info['corp'] + """</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class='card'>
        <div style='font-weight:bold; color:#475569;'>❄️ 투자 판단 (현재 냉정함)</div>
        <div style='font-size:0.9rem; margin-top:6px;'>""" + info['invest'] + """</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown(f"""
<div class='card' style='background-color:#EFF6FF; border-color:#BFDBFE;'>
    <div style='font-size:0.85rem; color:#1E40AF; font-weight:bold;'>🎯 시스템 최종 실행 가이드</div>
    <div style='font-size:1rem; font-weight:bold; color:#1E3A8A; margin-top:4px;'>{info['action']}</div>
</div>
""", unsafe_allow_html=True)

st.success("✅ 시스템이 정상 작동 중입니다.")
