import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

# Eggfolio integrated MVP: observable data is separated from interpretation.
DB_PATH = Path("eggfolio_journal.db")
UP, DOWN = "#E53935", "#1E88E5"  # Korean-market convention
MA_COLORS = {5:"#F59E0B", 20:"#8B5CF6", 60:"#10B981", 120:"#64748B", 200:"#64748B"}
TICKERS = {
    "NVIDIA":"NVDA", "Apple":"AAPL", "Microsoft":"MSFT", "Alphabet":"GOOGL",
    "Amazon":"AMZN", "Tesla":"TSLA", "Berkshire Hathaway B":"BRK-B",
    "S&P 500 ETF":"VOO", "Nasdaq-100 ETF":"QQQ",
    "삼성전자":"005930.KS", "SK하이닉스":"000660.KS", "삼성전기":"009150.KS",
    "KOSPI":"^KS11", "KOSDAQ":"^KQ11"
}
PERIODS = {"1개월":"1mo", "3개월":"3mo", "6개월":"6mo", "1년":"1y", "2년":"2y", "5년":"5y"}

st.set_page_config(page_title="Eggfolio", page_icon="🥚", layout="wide")


def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, ticker TEXT,
            horizon TEXT, price REAL, thesis TEXT, evidence_for TEXT,
            evidence_against TEXT, risks TEXT, invalidation TEXT, decision TEXT
        )""")
        con.commit()


def save_decision(row):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""INSERT INTO decisions
        (created_at,ticker,horizon,price,thesis,evidence_for,evidence_against,risks,invalidation,decision)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", row)
        con.commit()


def load_decisions():
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query("SELECT * FROM decisions ORDER BY id DESC", con)


@st.cache_data(ttl=300, show_spinner=False)
def get_prices(ticker, period):
    t0 = time.time()
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False, actions=False)
    elapsed = time.time() - t0
    if df is None or df.empty:
        raise ValueError("가격 데이터가 없습니다. 종목 코드나 Yahoo Finance 응답을 확인하세요.")
    needed = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError("필수 데이터 누락: " + ", ".join(missing))
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    for n in (5, 20, 60, 120, 200):
        df[f"MA{n}"] = df["Close"].rolling(n).mean()
    df["PrevClose"] = df["Close"].shift(1)
    df["IsUp"] = df["Close"] >= df["PrevClose"]
    if len(df):
        df.iloc[0, df.columns.get_loc("IsUp")] = df["Close"].iloc[0] >= df["Open"].iloc[0]
    df["VolumeMA20"] = df["Volume"].rolling(20).mean()
    df["VolumeRatio20"] = df["Volume"] / df["VolumeMA20"]
    df["Return20"] = df["Close"].pct_change(20) * 100
    df["Return60"] = df["Close"].pct_change(60) * 100
    return df, elapsed


@st.cache_data(ttl=900, show_spinner=False)
def get_fundamentals(ticker):
    return yf.Ticker(ticker).info


def fmt(v, digits=2):
    try:
        return "자료 없음" if v is None or pd.isna(v) else f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "자료 없음"


def fmt_large(v):
    try:
        if v is None or pd.isna(v): return "자료 없음"
        v = float(v)
        if abs(v) >= 1e12: return f"{v/1e12:,.2f}조"
        if abs(v) >= 1e8: return f"{v/1e8:,.2f}억"
        return f"{v:,.0f}"
    except (TypeError, ValueError):
        return "자료 없음"


def make_chart(df, mas, volume):
    fig = make_subplots(rows=2 if volume else 1, cols=1, shared_xaxes=volume,
                        vertical_spacing=.035, row_heights=[.74,.26] if volume else [1])
    fig.add_trace(go.Candlestick(
        x=df.index, open=df.Open, high=df.High, low=df.Low, close=df.Close,
        name="캔들", increasing_line_color=UP, increasing_fillcolor=UP,
        decreasing_line_color=DOWN, decreasing_fillcolor=DOWN
    ), row=1, col=1)
    for n in mas:
        fig.add_trace(go.Scatter(x=df.index, y=df[f"MA{n}"], mode="lines",
            name=f"{n}일선", line={"color":MA_COLORS[n],"width":1.5}), row=1, col=1)
    if volume:
        colors = [UP if bool(x) else DOWN for x in df.IsUp]
        fig.add_trace(go.Bar(x=df.index, y=df.Volume, name="거래량",
            marker_color=colors, opacity=.82), row=2, col=1)
        fig.update_yaxes(title_text="거래량", tickformat=",", row=2, col=1)
    fig.update_layout(height=720 if volume else 560, template="plotly_white",
        margin={"l":10,"r":10,"t":30,"b":10}, hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend={"orientation":"h","yanchor":"bottom","y":1.02,"xanchor":"left","x":0})
    fig.update_yaxes(title_text="가격", row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,.15)")
    return fig


def market_read(df):
    last = df.iloc[-1]
    close = float(last.Close)
    signals = []
    for n, label in [(20,"단기"),(60,"중기"),(120,"장기")]:
        ma = last[f"MA{n}"]
        signals.append((f"{label} 가격 위치", f"{n}일선 위" if pd.notna(ma) and close > ma else
                        (f"{n}일선 아래" if pd.notna(ma) else "관측 기간 부족")))
    for n in (20,60):
        v = last[f"Return{n}"]
        signals.append((f"{n}거래일 수익률", f"{v:+.2f}%" if pd.notna(v) else "자료 부족"))
    vr = last["VolumeRatio20"]
    signals.append(("거래량 / 20일 평균", f"{vr:.2f}배" if pd.notna(vr) else "자료 부족"))
    ma20, ma60 = last["MA20"], last["MA60"]
    if pd.notna(ma20) and pd.notna(ma60) and close > ma20 > ma60:
        label, desc = "상승 추세 신호", "종가가 20일선과 60일선 위이며 단기 평균이 중기 평균보다 높습니다."
    elif pd.notna(ma20) and pd.notna(ma60) and close < ma20 < ma60:
        label, desc = "하락 추세 신호", "종가가 20일선과 60일선 아래이며 단기 평균이 중기 평균보다 낮습니다."
    else:
        label, desc = "혼합 / 방향 불명확", "이동평균선 관계가 한 방향으로 정렬되지 않았습니다."
    return label, desc, signals


def render_fundamentals(ticker):
    st.subheader("기업 기초체력")
    if ticker.startswith("^"):
        st.info("지수에는 개별 기업 재무정보가 적용되지 않습니다."); return
    try:
        info = get_fundamentals(ticker)
        if not info:
            st.warning("재무 데이터가 제공되지 않았습니다."); return
        items = [
            ("회사명", info.get("longName") or info.get("shortName")),
            ("섹터", info.get("sector")), ("산업", info.get("industry")),
            ("시가총액", fmt_large(info.get("marketCap"))),
            ("매출", fmt_large(info.get("totalRevenue"))),
            ("영업현금흐름", fmt_large(info.get("operatingCashflow"))),
            ("PER (TTM)", fmt(info.get("trailingPE"))),
            ("선행 PER", fmt(info.get("forwardPE"))),
            ("주가매출비율", fmt(info.get("priceToSalesTrailing12Months"))),
            ("주가순자산비율", fmt(info.get("priceToBook"))),
            ("매출 성장률", f"{info['revenueGrowth']*100:.2f}%" if info.get("revenueGrowth") is not None else "자료 없음"),
            ("이익률", f"{info['profitMargins']*100:.2f}%" if info.get("profitMargins") is not None else "자료 없음"),
            ("부채비율", fmt(info.get("debtToEquity"))),
            ("애널리스트 목표가 평균", fmt(info.get("targetMeanPrice"))),
        ]
        a,b = st.columns(2)
        for i,(name,val) in enumerate(items):
            with (a if i%2==0 else b):
                st.write(f"**{name}:** {val if val is not None else '자료 없음'}")
        st.caption("Yahoo Finance 제공값이며 누락·지연·정의 차이가 있을 수 있습니다. 목표가는 외부 컨센서스 참고값이지 정답이 아닙니다.")
    except Exception as e:
        st.warning("재무 데이터를 가져오지 못했습니다."); st.caption(str(e))


init_db()
st.title("🥚 Eggfolio")
st.caption("투자 리서치 워크벤치 · 관측 데이터와 해석을 구분합니다.")

with st.sidebar:
    st.header("조회 설정")
    chosen = st.selectbox("종목 선택", list(TICKERS.keys()))
    custom = st.text_input("직접 입력 (선택사항)", placeholder="예: NVDA 또는 005930.KS")
    ticker = custom.strip().upper() if custom.strip() else TICKERS[chosen]
    period_name = st.selectbox("차트 기간", list(PERIODS.keys()), index=2)
    period = PERIODS[period_name]
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.cache_data.clear()
    st.caption("한국 종목은 .KS 또는 .KQ 접미사가 필요할 수 있습니다.")

try:
    with st.spinner(f"{ticker} 가격 데이터 조회 중..."):
        prices, elapsed = get_prices(ticker, period)
except Exception as e:
    st.error("가격 데이터를 불러오지 못했습니다.")
    st.write(f"종목 코드: `{ticker}`")
    st.write(f"오류: {e}")
    st.info("종목 코드와 데이터 제공자 상태를 확인한 뒤 새로고침해 주세요.")
    st.stop()

last = prices.iloc[-1]
close = float(last.Close)
prev = float(prices.Close.iloc[-2]) if len(prices)>1 else close
change = close-prev
pct = change/prev*100 if prev else 0
m1,m2,m3,m4 = st.columns(4)
m1.metric("최근 종가", fmt(close), f"{change:+,.2f} ({pct:+.2f}%)")
m2.metric("거래량", f"{int(last.Volume):,}")
m3.metric("표시 거래일", f"{len(prices):,}")
m4.metric("최근 데이터 날짜", prices.index[-1].strftime("%Y-%m-%d"))
st.caption(f"조회 소요 {elapsed:.2f}초 · 화면 시각 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 일봉은 장중 체결가와 다를 수 있습니다.")

tab_chart,tab_market,tab_company,tab_journal,tab_raw = st.tabs([
    "📈 차트","🥚 시장 국면 참고","🏢 기업 기초체력","📝 판단 기록","🧾 원자료"
])

with tab_chart:
    mas = st.multiselect("이동평균선", [5,20,60,120,200], default=[20,60,120],
                         format_func=lambda n:f"{n}일선")
    volume = st.checkbox("거래량 표시", True)
    st.plotly_chart(make_chart(prices, mas, volume), use_container_width=True,
                    config={"scrollZoom":True,"displaylogo":False,"responsive":True})
    st.caption("상승 빨강 / 하락 파랑. 첫 데이터 날짜는 전일 종가가 없어 시가와 종가를 비교합니다.")
    st.subheader("기술적 관측")
    for n in (20,60,120,200):
        ma = last[f"MA{n}"]
        if pd.notna(ma):
            st.write(f"• 종가는 {n}일선 { '위' if close > ma else '아래'}입니다.")
    vr = last["VolumeRatio20"]
    st.write(f"• 거래량은 20일 평균 대비 {vr:.2f}배입니다." if pd.notna(vr) else "• 거래량 평균을 계산하기에 데이터가 부족합니다.")

with tab_market:
    label,desc,signals = market_read(prices)
    st.subheader("가격 추세 관측")
    st.markdown(f"### {label}")
    st.write(desc)
    st.dataframe(pd.DataFrame(signals,columns=["관측 항목","판독"]), use_container_width=True, hide_index=True)
    st.warning("이 판독은 가격·거래량 기반의 단순 규칙 요약이며 검증된 예측 모델이 아닙니다.")
    st.subheader("코스톨라니 달걀 이론 · 민스키 가설")
    st.write("현재는 두 이론의 국면을 자동 확정하지 않습니다. 가격 데이터만으로는 투자심리, 신용 팽창, 레버리지, 대출 기준, 신용스프레드를 충분히 판별할 수 없습니다.")
    st.write("공매도, 투자자별 수급, 선물·옵션 포지셔닝, 신용스프레드, AI 종합 분석은 아직 연결되지 않았습니다. 데이터 출처와 기준일을 검증한 뒤 추가해야 하며 임의의 숫자는 표시하지 않습니다.")

with tab_company:
    render_fundamentals(ticker)
    st.subheader("뉴스 및 외부 정보")
    st.info("뉴스 제목을 임의로 만들지 않습니다. 우선 출처 확인이 가능한 외부 페이지를 제공합니다.")
    st.markdown(f"[Yahoo Finance에서 {ticker} 보기](https://finance.yahoo.com/quote/{ticker}/)")
    st.caption("외부 사이트의 기사 내용과 발표 시각을 직접 확인하세요.")

with tab_journal:
    st.subheader("투자 판단 기록")
    st.write("가설, 지지 근거, 반대 근거와 무효화 조건을 저장해 나중에 판단 품질을 검토합니다.")
    with st.form("decision_form", clear_on_submit=True):
        c1,c2 = st.columns(2)
        with c1:
            jt = st.text_input("종목 코드", value=ticker)
            horizon = st.selectbox("판단 기간", ["단기","중기","장기"])
            price = st.number_input("판단 당시 가격", min_value=0.0, value=close, step=0.01)
            decision = st.selectbox("현재 판단", ["관망","관심 등록","분할 매수 검토","보유","일부 매도 검토","매도 검토"])
        with c2:
            thesis = st.text_area("핵심 가설", placeholder="무엇이 일어날 것으로 보는가?")
            support = st.text_area("지지 근거", placeholder="확인된 사실과 출처")
            against = st.text_area("반대 근거", placeholder="가설이 틀릴 수 있는 이유")
        risks = st.text_area("주요 위험")
        invalidation = st.text_area("가설 무효화 조건", placeholder="어떤 사실이 확인되면 판단을 바꿀 것인가?")
        submitted = st.form_submit_button("판단 기록 저장")
        if submitted:
            if not jt.strip() or not thesis.strip():
                st.error("종목 코드와 핵심 가설을 입력해 주세요.")
            else:
                save_decision((datetime.now(timezone.utc).isoformat(),jt.strip().upper(),horizon,float(price),
                               thesis.strip(),support.strip(),against.strip(),risks.strip(),invalidation.strip(),decision))
                st.success("기록을 저장했습니다."); st.rerun()
    journal = load_decisions()
    if journal.empty:
        st.info("아직 기록이 없습니다.")
    else:
        st.dataframe(journal, use_container_width=True, hide_index=True)
        st.download_button("판단 기록 CSV 다운로드", journal.to_csv(index=False).encode("utf-8-sig"),
                           "eggfolio_decisions.csv", "text/csv")
    st.caption("Streamlit Cloud의 로컬 파일은 재배포·환경 변경 시 영구 보존이 보장되지 않습니다. 장기 보관에는 외부 DB가 필요합니다.")

with tab_raw:
    cols = ["Open","High","Low","Close","Volume","MA5","MA20","MA60","MA120","MA200"]
    st.dataframe(prices[[c for c in cols if c in prices.columns]].tail(20).sort_index(ascending=False),
                 use_container_width=True)
    st.download_button("전체 가격 데이터 CSV 다운로드", prices.to_csv(index=True).encode("utf-8-sig"),
                       f"{ticker}_{period}_prices.csv", "text/csv")
    st.caption("Yahoo Finance는 비공식 데이터 경로입니다. 지연·누락·수정·접속 제한이 발생할 수 있습니다. 값이 없으면 임의의 숫자를 만들지 않습니다.")

st.divider()
st.caption("Eggfolio는 투자 리서치 및 기록 도구이며 매수·매도 지시를 제공하지 않습니다.")
