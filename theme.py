# -*- coding: utf-8 -*-
"""theme.py — 화면 모양만 바꾸는 파일(기능에는 영향 없음). 문제가 생기면 app.py 의 theme.inject() 한 줄만 지우면 원래대로 돌아갑니다."""
import streamlit as st

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{
  --bg:#F4F5F7; --card:#FFFFFF; --ink:#191F28; --sub:#6B7684; --line:#E5E8EB;
  --accent:#3182F6; --up:#F04452; --down:#3182F6; --soft:#EEF4FF;
}
html, body, [class*="css"], .stApp, button, input, textarea, select{
  font-family:'Pretendard Variable','Pretendard','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif !important;
  letter-spacing:-0.01em;
}
.stApp{background:var(--bg); color:var(--ink);}
.block-container{max-width:1180px; padding-top:1.6rem; padding-bottom:4rem;}
header[data-testid="stHeader"]{background:transparent;}
h1{font-weight:800; font-size:1.7rem !important; letter-spacing:-0.03em;}
h2, h3{font-weight:800; letter-spacing:-0.03em; margin-top:1.6rem !important;}
h3{font-size:1.25rem !important;}
h4, h5{font-weight:700;}
[data-testid="stCaptionContainer"], .stCaption, small{color:var(--sub) !important; line-height:1.55;}

/* 탭: 알약 모양 */
.stTabs [data-baseweb="tab-list"]{gap:6px; background:transparent; border-bottom:none;}
.stTabs [data-baseweb="tab"]{background:#E9ECF0; border-radius:999px; padding:8px 16px; height:auto; color:var(--sub); font-weight:700;}
.stTabs [aria-selected="true"]{background:var(--ink); color:#fff !important;}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"]{display:none;}

/* 지표 카드 */
[data-testid="stMetric"]{background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px 18px; box-shadow:0 1px 2px rgba(0,0,0,.03);}
[data-testid="stMetricLabel"] p{color:var(--sub); font-weight:600; font-size:.85rem;}
[data-testid="stMetricValue"]{font-weight:800; letter-spacing:-0.03em; font-variant-numeric:tabular-nums;}

/* 접기 상자·표·입력 */
[data-testid="stExpander"]{background:var(--card); border:1px solid var(--line) !important; border-radius:16px; box-shadow:0 1px 2px rgba(0,0,0,.03);}
[data-testid="stExpander"] summary{font-weight:700;}
[data-testid="stDataFrame"]{border:1px solid var(--line); border-radius:14px; overflow:hidden; background:var(--card);}
[data-testid="stForm"]{background:var(--card); border:1px solid var(--line); border-radius:16px;}
.stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"]>button{
  border-radius:12px; font-weight:700; border:1px solid var(--line); background:var(--card); color:var(--ink); padding:.55rem 1rem;}
.stButton>button:hover, [data-testid="stFormSubmitButton"]>button:hover{border-color:var(--accent); color:var(--accent);}
.stButton>button[kind="primary"], [data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{background:var(--accent); color:#fff; border-color:var(--accent);}
[data-baseweb="select"]>div, [data-baseweb="input"]>div, textarea{border-radius:12px !important;}
div[data-testid="stAlert"]{border-radius:14px; border:none;}
hr{border-color:var(--line);}

/* 숫자 정렬 */
[data-testid="stDataFrame"], [data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;}

@media (max-width: 640px){
  .block-container{padding-left:.8rem; padding-right:.8rem;}
  h1{font-size:1.4rem !important;}
  .stTabs [data-baseweb="tab"]{padding:6px 12px; font-size:.85rem;}
}
</style>
"""


def inject():
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception:  # noqa: BLE001
        pass
