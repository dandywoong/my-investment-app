# -*- coding: utf-8 -*-
"""theme.py — 화면 모양만 바꾸는 파일(기능에는 영향 없음). 문제가 생기면 app.py 의 theme.inject() 한 줄만 지우면 원래대로 돌아갑니다."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');
:root{
  --bg:#F6F5F1; --card:#FFFFFF; --ink:#14213D; --sub:#5F6675; --line:#DAD7CE;
  --accent:#0F766E; --up:#B42318; --down:#1D4ED8;
}
html, body, [class*="css"], .stApp, button, input, textarea, select{
  font-family:'IBM Plex Sans KR','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif !important;
  letter-spacing:-0.005em;
}
.stApp{background:var(--bg); color:var(--ink);}
/* 가로 여백 최소화: 화면 폭을 거의 전부 사용 */
.block-container{max-width:100% !important; padding:1.2rem 2.2rem 4rem 2.2rem !important;}
header[data-testid="stHeader"]{background:transparent;}
h1{font-weight:700; font-size:1.5rem !important;}
h2, h3{font-weight:700; margin-top:1.4rem !important; padding-bottom:.35rem; border-bottom:2px solid var(--ink); display:block;}
h3{font-size:1.1rem !important; letter-spacing:.01em;}
h4, h5{font-weight:600;}
[data-testid="stCaptionContainer"], .stCaption, small{color:var(--sub) !important; line-height:1.55;}

/* 탭: 밑줄 */
.stTabs [data-baseweb="tab-list"]{gap:22px; background:transparent; border-bottom:1px solid var(--line);}
.stTabs [data-baseweb="tab"]{background:transparent; padding:8px 2px; height:auto; color:var(--sub); font-weight:600; border-radius:0;}
.stTabs [aria-selected="true"]{color:var(--ink) !important;}
.stTabs [data-baseweb="tab-highlight"]{background:var(--ink) !important; height:3px;}
.stTabs [data-baseweb="tab-border"]{display:none;}

/* 지표 */
[data-testid="stMetric"]{background:var(--card); border:1px solid var(--line); border-left:3px solid var(--ink); border-radius:4px; padding:10px 14px;}
[data-testid="stMetricLabel"] p{color:var(--sub); font-weight:500; font-size:.8rem; text-transform:none;}
[data-testid="stMetricValue"]{font-weight:700; font-variant-numeric:tabular-nums;}

/* 상자·표·입력: 각진 모서리, 그림자 없음 */
[data-testid="stExpander"]{background:var(--card); border:1px solid var(--line) !important; border-radius:4px;}
[data-testid="stExpander"] summary{font-weight:600;}
[data-testid="stDataFrame"]{border:1px solid var(--line); border-radius:4px; overflow:hidden; background:var(--card);}
[data-testid="stForm"]{background:var(--card); border:1px solid var(--line); border-radius:4px;}
.stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"]>button{
  border-radius:4px; font-weight:600; border:1px solid var(--ink); background:var(--card); color:var(--ink); padding:.45rem .9rem;}
.stButton>button:hover, [data-testid="stFormSubmitButton"]>button:hover{background:var(--ink); color:#fff; border-color:var(--ink);}
.stButton>button[kind="primary"], [data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{background:var(--accent); color:#fff; border-color:var(--accent);}
[data-baseweb="select"]>div, [data-baseweb="input"]>div, textarea{border-radius:4px !important;}
div[data-testid="stAlert"]{border-radius:4px; border:1px solid var(--line);}
hr{border-color:var(--line);}
[data-testid="stDataFrame"], [data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;}

@media (max-width: 640px){
  .block-container{padding-left:.8rem !important; padding-right:.8rem !important;}
  h1{font-size:1.3rem !important;}
  .stTabs [data-baseweb="tab-list"]{gap:12px;}
}
</style>
"""


def inject():
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception:  # noqa: BLE001
        pass
