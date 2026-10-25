import sqlite3
import time
import json
import os
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

# Curated starter directory. Search works offline against this list; it is not an exhaustive live exchange directory.
STOCK_DIRECTORY = {
    "삼성전자":"005930.KS", "삼성전기":"009150.KS", "삼성SDI":"006400.KS",
    "삼성바이오로직스":"207940.KS", "SK하이닉스":"000660.KS", "SK텔레콤":"017670.KS",
    "현대차":"005380.KS", "기아":"000270.KS", "LG에너지솔루션":"373220.KS",
    "LG화학":"051910.KS", "NAVER":"035420.KS", "카카오":"035720.KS",
    "한화에어로스페이스":"012450.KS", "두산에너빌리티":"034020.KS", "POSCO홀딩스":"005490.KS",
    "셀트리온":"068270.KS", "KB금융":"105560.KS", "신한지주":"055550.KS",
    "NVIDIA":"NVDA", "Apple":"AAPL", "Microsoft":"MSFT", "Alphabet":"GOOGL",
    "Amazon":"AMZN", "Tesla":"TSLA", "Meta Platforms":"META", "Broadcom":"AVGO",
    "Berkshire Hathaway B":"BRK-B", "S&P 500 ETF":"VOO", "Nasdaq-100 ETF":"QQQ",
    "KOSPI":"^KS11", "KOSDAQ":"^KQ11"
}

CHOSEONG = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")

def get_initials(text):
    out = []
    for ch in str(text):
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171:
            out.append(CHOSEONG[code // 588])
        else:
            out.append(ch.lower())
    return "".join(out)

def find_stock_matches(query):
    q = query.strip().lower().replace(" ", "")
    if not q:
        return list(STOCK_DIRECTORY.items())
    matches = []
    for name, symbol in STOCK_DIRECTORY.items():
        if q in name.lower().replace(" ", "") or q in symbol.lower().replace(" ", "") or q in get_initials(name).replace(" ", ""):
            matches.append((name, symbol))
    return matches

st.set_page_config(page_title="Eggfolio", page_icon="🥚", layout="wide")


def stock_search_widget(key_prefix, default_ticker="", default_name=""):
    """Search curated directory by name, ticker, or Korean initials, then select a match."""
    query = st.text_input("종목 검색 (이름·초성·티커)", value="", placeholder="예: 삼성전기 / ㅅㅅㅈㄱ / 009150 / NVDA", key=f"{key_prefix}_query")
    matches = find_stock_matches(query)
    if default_ticker and not query:
        found = [(n, t) for n, t in matches if t == default_ticker]
        if found:
            matches = found + [(n, t) for n, t in matches if t != default_ticker]
    if matches:
        labels = [f"{name} · {symbol}" for name, symbol in matches]
        selected = st.selectbox("검색 결과 선택", labels, key=f"{key_prefix}_selected")
        idx = labels.index(selected)
        return matches[idx][0], matches[idx][1]
    st.warning("검색 결과가 없습니다. 직접 티커를 입력할 수 있습니다.")
    manual_ticker = st.text_input("직접 입력할 티커", value=default_ticker, key=f"{key_prefix}_manual_ticker").strip().upper()
    manual_name = st.text_input("직접 입력할 종목명", value=default_name, key=f"{key_prefix}_manual_name")
    return manual_name.strip(), manual_ticker


def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS holdings (
            ticker TEXT PRIMARY KEY, name TEXT, quantity REAL NOT NULL DEFAULT 0,
            avg_cost REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'KRW',
            account TEXT NOT NULL DEFAULT '삼성증권 ISA', updated_at TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, traded_at TEXT, ticker TEXT NOT NULL,
            name TEXT, side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0, account TEXT, note TEXT
        )""")
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


def load_holdings():
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query("SELECT * FROM holdings WHERE quantity > 0 ORDER BY name", con)


def save_holding(ticker, name, quantity, avg_cost, currency, account):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""INSERT INTO holdings(ticker,name,quantity,avg_cost,currency,account,updated_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET
            name=excluded.name, quantity=excluded.quantity, avg_cost=excluded.avg_cost,
            currency=excluded.currency, account=excluded.account, updated_at=excluded.updated_at""",
            (ticker, name, quantity, avg_cost, currency, account, datetime.now(timezone.utc).isoformat()))
        con.commit()


def delete_holding(ticker):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM holdings WHERE ticker=?", (ticker,))
        con.commit()


def load_trades():
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", con)


def save_trade(traded_at, ticker, name, side, quantity, price, fee, account, note):
    """Record trade and update holding using weighted-average cost; sale cannot exceed holdings."""
    ticker = ticker.strip().upper()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("BEGIN")
        row = con.execute("SELECT quantity, avg_cost, name, currency, account FROM holdings WHERE ticker=?", (ticker,)).fetchone()
        old_qty, old_avg = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
        if side == "매수":
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price) + fee) / new_qty if new_qty else 0.0
        else:
            if quantity > old_qty + 1e-9:
                raise ValueError(f"매도 수량({quantity:g})이 보유 수량({old_qty:g})보다 많습니다.")
            new_qty = max(0.0, old_qty - quantity)
            new_avg = old_avg if new_qty > 0 else 0.0
        con.execute("INSERT INTO trades(traded_at,ticker,name,side,quantity,price,fee,account,note) VALUES(?,?,?,?,?,?,?,?,?)",
                    (traded_at, ticker, name, side, quantity, price, fee, account, note))
        if new_qty <= 1e-9:
            con.execute("DELETE FROM holdings WHERE ticker=?", (ticker,))
        else:
            con.execute("""INSERT INTO holdings(ticker,name,quantity,avg_cost,currency,account,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET
                name=excluded.name, quantity=excluded.quantity, avg_cost=excluded.avg_cost,
                currency=excluded.currency, account=excluded.account, updated_at=excluded.updated_at""",
                (ticker, name, new_qty, new_avg, "USD" if not ticker.endswith((".KS", ".KQ")) and not ticker.isdigit() else "KRW", account, datetime.now(timezone.utc).isoformat()))
        con.commit()


@st.cache_data(ttl=300, show_spinner=False)
def latest_close(ticker):
    hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
    if hist is None or hist.empty or "Close" not in hist:
        return None, None
    return float(hist["Close"].dropna().iloc[-1]), str(hist.index[-1].date())


def summarize_with_gemini(raw_note):
    """Optional AI summary. Requires GEMINI_API_KEY in Streamlit secrets or environment."""
    key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    if not key:
        return None, "AI 요약을 사용하려면 Streamlit Secrets에 GEMINI_API_KEY를 설정해야 합니다. 키를 설정하지 않아도 원문과 직접 작성한 요약은 저장할 수 있습니다."
    try:
        import requests
        prompt = "다음 투자 메모를 한국어로 요약해 JSON으로 반환하세요. 키는 thesis, supporting_evidence, opposing_evidence, risks, invalidation_conditions, follow_up_questions 입니다. 사실을 추가하거나 추정하지 말고, 메모에 없는 항목은 빈 문자열 또는 빈 목록으로 두세요. JSON 외 텍스트는 쓰지 마세요.\n메모:\n" + raw_note
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            params={"key": key}, json={"contents":[{"parts":[{"text":prompt}]}], "generationConfig":{"responseMimeType":"application/json"}}, timeout=30)
        response.raise_for_status()
        data = response.json()
        result = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(result), None
    except Exception as e:
        return None, f"AI 요약에 실패했습니다. 원문은 유지됩니다. 오류: {e}"


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



def classify_holding(name, ticker):
    """Best-effort portfolio category from ticker/name; unverified cases stay unclassified."""
    n = str(name).lower()
    t = str(ticker).upper()

    # Broad-market and sector ETFs are identified before individual-company rules.
    if any(x in n for x in ["s&p 500", "nasdaq-100", "total market", "전세계", "월드", "미국지수"]):
        return "시장 지수 ETF"
    if any(x in n for x in ["채권", "국채", "bond", "treasury"]):
        return "채권"
    if any(x in n for x in ["배당", "고배당", "dividend"]):
        return "배당 ETF"

    if t in {"NVDA", "AMD", "AVGO", "QCOM", "MU", "ASML", "TSM", "000660.KS", "005930.KS", "009150.KS"} or any(
        x in n for x in ["반도체", "semiconductor", "엔비디아", "하이닉스", "삼성전자", "삼성전기", "브로드컴"]
    ):
        return "반도체·하드웨어"
    if t in {"GOOG", "GOOGL", "MSFT", "AAPL", "META", "AMZN", "CRM", "NOW", "PLTR", "ORCL", "ADBE"} or any(
        x in n for x in ["alphabet", "google", "microsoft", "apple", "meta platforms", "amazon", "software", "소프트웨어", "테슬라"]
    ):
        return "기술·성장주"
    if t in {"BRK-A", "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "105560.KS", "055550.KS"} or any(
        x in n for x in ["berkshire", "금융", "은행", "보험", "지주"]
    ):
        return "금융·지주"
    if any(x in n for x in ["필수소비재", "식품", "생활용품", "walmart", "costco", "procter", "coca-cola", "pepsico"]):
        return "경기 방어주"
    if any(x in n for x in ["헬스케어", "제약", "바이오", "health", "pharma"]):
        return "헬스케어"
    if any(x in n for x in ["자동차", "자동차", "항공", "철강", "화학", "에너지", "조선", "건설", "기아", "현대차", "posco"]):
        return "경기 민감주"
    if t.startswith("^"):
        return "시장 지수"
    return "기타·분류 확인 필요"

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

tab_portfolio,tab_chart,tab_market,tab_company,tab_journal,tab_raw = st.tabs([
    "💼 내 포트폴리오", "📈 차트","🥚 시장 국면 참고","🏢 기업 기초체력","📝 판단 기록","🧾 원자료"
])

with tab_portfolio:
    st.subheader("내 보유 종목")
    st.caption("보유 수량·평단·평가손익은 입력한 거래와 조회된 가격을 기준으로 계산합니다. 가격 제공자는 Yahoo Finance이며 삼성증권 계좌와 직접 연결된 것이 아닙니다.")
    with st.expander("➕ 보유 종목 직접 등록 / 수정", expanded=not bool(len(load_holdings()))):
        hname, hticker = stock_search_widget("holding_search")
        with st.form("holding_form"):
            hc1, hc2 = st.columns(2)
            with hc1:
                st.text_input("선택한 종목명", value=hname, disabled=True)
                st.text_input("종목 코드", value=hticker, disabled=True)
                hqty = st.number_input("현재 보유 수량", min_value=0.0, step=1.0, format="%.4f")
            with hc2:
                havg = st.number_input("평균 매입단가", min_value=0.0, step=100.0, format="%.4f")
                hcurrency = st.selectbox("통화", ["KRW", "USD"], index=0 if hticker.endswith((".KS", ".KQ")) or hticker.startswith("^") else 1)
                haccount = st.selectbox("계좌 구분", ["삼성증권 ISA", "삼성증권 일반계좌", "삼성증권 CMA", "기타 계좌"])
            hsubmit = st.form_submit_button("보유 정보 저장")
            if hsubmit:
                if not hticker or not hname.strip() or hqty <= 0 or havg <= 0:
                    st.error("검색 결과 또는 종목명·티커·보유 수량·평단을 확인해 주세요.")
                else:
                    save_holding(hticker, hname.strip(), hqty, havg, hcurrency, haccount)
                    st.success("보유 정보가 저장되었습니다. 같은 티커는 기존 보유 정보를 갱신합니다.")
                    st.rerun()
    holdings = load_holdings()
    if holdings.empty:
        st.info("등록된 보유 종목이 없습니다. 위에서 종목명·코드·수량·평단을 입력하세요.")
    else:
        if st.button("🔄 보유 종목 가격 새로고침"):
            latest_close.clear()
        rows=[]
        with st.spinner("보유 종목 가격 조회 중..."):
            for _, h in holdings.iterrows():
                px, pxdate = latest_close(str(h.ticker))
                qty, avg = float(h.quantity), float(h.avg_cost)
                market_value = px*qty if px is not None else None
                pnl = (px-avg)*qty if px is not None else None
                pnl_pct = (px/avg-1)*100 if px is not None and avg else None
                rows.append({"종목":h["name"],"코드":h.ticker,"계좌":h.account,"수량":qty,
                             "평단":avg,"현재가":px,"평가금액":market_value,"평가손익":pnl,
                             "수익률(%)":pnl_pct,"가격 기준일":pxdate or "자료 없음","통화":h.currency})
        pf = pd.DataFrame(rows)
        valid = pf.dropna(subset=["평가금액"])
        total_value = valid["평가금액"].sum() if not valid.empty else None
        total_pnl = valid["평가손익"].sum() if not valid.empty else None
        k1,k2,k3 = st.columns(3)
        k1.metric("조회 가능한 보유 종목 평가금액", fmt_large(total_value))
        k2.metric("평가손익 합계", fmt_large(total_pnl))
        base = valid["평가금액"].sum()-valid["평가손익"].sum() if not valid.empty else 0
        k3.metric("가중 평가수익률", f"{total_pnl/base*100:+.2f}%" if base else "자료 없음")
        st.dataframe(pf, use_container_width=True, hide_index=True)
        st.subheader("포트폴리오 비중")
        st.caption("평가금액 기준 비중입니다. 서로 다른 통화는 환율 환산 전에는 합산하지 않고 별도로 표시합니다.")
        pie_cols = st.columns(2)
        for col, currency in zip(pie_cols, ["KRW", "USD"]):
            subset = pf[(pf["통화"] == currency) & pf["평가금액"].notna() & (pf["평가금액"] > 0)]
            with col:
                st.markdown(f"**{currency} 자산 비중**")
                if subset.empty:
                    st.info(f"{currency} 평가 가능한 자산이 없습니다.")
                else:
                    # Aggregate duplicate tickers across accounts, then show category and ticker
                    # as two nested rings. Percentages for every ticker are relative to this currency's total.
                    chart_data = subset.copy()
                    chart_data["카테고리"] = chart_data.apply(
                        lambda row: classify_holding(row["종목"], row["코드"]), axis=1
                    )
                    chart_data = (chart_data.groupby(["카테고리", "코드", "종목"], as_index=False)
                                  ["평가금액"].sum())
                    category_totals = chart_data.groupby("카테고리")["평가금액"].sum()
                    total_chart_value = float(chart_data["평가금액"].sum())
                    labels = ["전체 자산"]
                    ids = ["portfolio_root"]
                    parents = [""]
                    values = [total_chart_value]
                    hover_names = [f"{currency} 전체 자산"]
                    category_colors = {
                        "반도체·하드웨어": "#2563EB", "기술·성장주": "#7C3AED",
                        "시장 지수 ETF": "#0D9488", "시장 지수": "#0D9488",
                        "경기 방어주": "#16A34A", "헬스케어": "#22A06B",
                        "금융·지주": "#D97706", "경기 민감주": "#EA580C",
                        "배당 ETF": "#65A30D", "채권": "#64748B",
                        "기타·분류 확인 필요": "#9CA3AF",
                    }
                    colors = ["#FFFFFF"]
                    for category, category_value in category_totals.items():
                        category_id = f"category::{category}"
                        category_weight = float(category_value) / total_chart_value
                        labels.append(f"{category} · {category_weight:.1%}")
                        ids.append(category_id)
                        parents.append("portfolio_root")
                        values.append(float(category_value))
                        hover_names.append(f"{category}: {category_value / total_chart_value:.1%} of portfolio")
                        colors.append(category_colors.get(category, "#9CA3AF"))
                        children = chart_data[chart_data["카테고리"] == category]
                        for _, stock in children.iterrows():
                            ticker_id = f"stock::{category}::{stock['코드']}"
                            weight = float(stock["평가금액"]) / total_chart_value
                            labels.append(f"{stock['코드']} · {weight:.1%}")
                            ids.append(ticker_id)
                            parents.append(category_id)
                            values.append(float(stock["평가금액"]))
                            hover_names.append(
                                f"{stock['종목']} ({stock['코드']})<br>카테고리: {category}"
                                f"<br>평가금액: {stock['평가금액']:,.2f} {currency}"
                                f"<br>전체 비중: {weight:.2%}"
                            )
                            # Same category color family; individual holdings vary by opacity.
                            colors.append(category_colors.get(category, "#9CA3AF"))

                    fig_pie = go.Figure(go.Sunburst(
                        ids=ids, labels=labels, parents=parents, values=values,
                        branchvalues="total", sort=False, maxdepth=2,
                        insidetextorientation="radial",
                        textinfo="label",
                        marker={"colors": colors, "line": {"color": "white", "width": 1}},
                        customdata=hover_names,
                        hovertemplate="%{customdata}<extra></extra>",
                        leaf={"opacity": 0.88},
                    ))
                    fig_pie.update_layout(
                        height=430, margin={"l":5,"r":5,"t":10,"b":5},
                        showlegend=False, uniformtext={"minsize": 9, "mode": "hide"},
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                    st.caption("안쪽은 카테고리, 바깥쪽은 티커입니다. 각 종목 비중은 해당 통화 포트폴리오 전체 기준이며, 작은 조각은 마우스를 올려 확인하세요. 카테고리는 이름·티커 기반의 자동 추정이므로 ‘분류 확인 필요’ 항목은 검토가 필요합니다.")
        st.caption("주의: 통화가 다른 종목의 합계는 환산 전 값이 섞일 수 있으므로 총액·손익 합계는 KRW와 USD를 분리해 해석해야 합니다. 가격 기준일과 제공자 데이터의 지연 가능성을 확인하세요. 세금·배당·환전 비용은 아직 반영하지 않습니다.")
        st.download_button("보유 현황 CSV 다운로드", pf.to_csv(index=False).encode("utf-8-sig"), "eggfolio_portfolio.csv", "text/csv")
        with st.expander("보유 종목 삭제"):
            delete_code = st.selectbox("삭제할 종목", holdings.ticker.tolist(), format_func=lambda x: f"{holdings.loc[holdings.ticker==x, 'name'].iloc[0]} ({x})")
            if st.button("선택한 보유 종목 삭제"):
                delete_holding(delete_code)
                st.rerun()
    st.divider()
    st.subheader("매수·매도 기록")
    st.write("거래를 기록하면 수량과 가중평균 매입원가가 자동 갱신됩니다. 직접 등록한 보유 정보는 기준값이며, 과거 거래를 소급 계산한 값은 아닙니다.")
    trade_name, trade_ticker = stock_search_widget("trade_search")
    with st.form("trade_form", clear_on_submit=True):
        tc1,tc2 = st.columns(2)
        with tc1:
            st.text_input("선택한 종목명", value=trade_name, disabled=True)
            st.text_input("종목 코드", value=trade_ticker, disabled=True)
            trade_side = st.selectbox("거래 유형", ["매수", "매도"])
            trade_qty = st.number_input("거래 수량", min_value=0.0001, value=1.0, step=1.0)
        with tc2:
            trade_price = st.number_input("거래 단가", min_value=0.0001, value=1.0, step=100.0)
            trade_fee = st.number_input("수수료 등 비용", min_value=0.0, value=0.0, step=1.0)
            trade_account = st.selectbox("거래 계좌", ["삼성증권 ISA", "삼성증권 일반계좌", "삼성증권 CMA", "기타 계좌"])
            trade_date = st.date_input("거래일", value=datetime.now().date())
        trade_note = st.text_area("거래 메모 (선택)", placeholder="매매 이유나 당시 상황. 비워도 됩니다.")
        trade_submit = st.form_submit_button("거래 저장 및 자동 계산")
        if trade_submit:
            if not trade_ticker or not trade_name.strip():
                st.error("검색 결과 또는 종목명과 티커를 확인해 주세요.")
            else:
                try:
                    save_trade(str(trade_date), trade_ticker, trade_name.strip(), trade_side, float(trade_qty), float(trade_price), float(trade_fee), trade_account, trade_note.strip())
                    st.success("거래가 저장되었고 보유 수량·평단이 갱신되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"거래를 저장하지 못했습니다: {e}")
    trades = load_trades()
    if not trades.empty:
        st.subheader("최근 거래 내역")
        st.dataframe(trades.head(100), use_container_width=True, hide_index=True)
        st.download_button("거래 내역 CSV 다운로드", trades.to_csv(index=False).encode("utf-8-sig"), "eggfolio_trades.csv", "text/csv")

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
        invalidation = st.text_area("가설 무효화 조건 (선택)", placeholder="어떤 사실이 확인되면 판단을 바꿀 것인가?")
        raw_note = st.text_area("자유 메모 (선택 · 길게 작성 가능)", placeholder="생각나는 대로 적으세요. 매 기록마다 작성할 필요는 없습니다.")
        submitted = st.form_submit_button("판단 기록 저장")
        if submitted:
            if not jt.strip() or not thesis.strip():
                st.error("종목 코드와 핵심 가설을 입력해 주세요.")
            else:
                ai_summary_text = ""
                if raw_note.strip():
                    summary_obj, summary_error = summarize_with_gemini(raw_note.strip())
                    if summary_obj:
                        ai_summary_text = "\n\n[AI 요약 · Gemini]\n" + json.dumps(summary_obj, ensure_ascii=False, indent=2)
                        st.success("자유 메모의 AI 요약을 생성했습니다. 원문도 함께 저장합니다.")
                    elif summary_error:
                        st.warning(summary_error + " 원문과 직접 입력한 항목은 계속 저장합니다.")
                combined_thesis = thesis.strip() + ai_summary_text + ("\n\n[자유 메모 원문]\n" + raw_note.strip() if raw_note.strip() else "")
                save_decision((datetime.now(timezone.utc).isoformat(),jt.strip().upper(),horizon,float(price),
                               combined_thesis,support.strip(),against.strip(),risks.strip(),invalidation.strip(),decision))
                st.success("기록을 저장했습니다."); st.rerun()
    journal = load_decisions()
    if journal.empty:
        st.info("아직 기록이 없습니다.")
    else:
        st.dataframe(journal, use_container_width=True, hide_index=True)
        st.download_button("판단 기록 CSV 다운로드", journal.to_csv(index=False).encode("utf-8-sig"),
                           "eggfolio_decisions.csv", "text/csv")
    st.caption("종목 검색은 앱 내 기본 종목 목록을 사용하며 전체 상장 종목을 망라하지 않습니다. Streamlit Cloud의 로컬 SQLite는 재배포·환경 변경 시 영구 보존이 보장되지 않으므로 실제 자산을 입력하기 전 외부 DB 또는 백업을 추가해야 합니다.")

with tab_raw:
    cols = ["Open","High","Low","Close","Volume","MA5","MA20","MA60","MA120","MA200"]
    st.dataframe(prices[[c for c in cols if c in prices.columns]].tail(20).sort_index(ascending=False),
                 use_container_width=True)
    st.download_button("전체 가격 데이터 CSV 다운로드", prices.to_csv(index=True).encode("utf-8-sig"),
                       f"{ticker}_{period}_prices.csv", "text/csv")
    st.caption("Yahoo Finance는 비공식 데이터 경로입니다. 지연·누락·수정·접속 제한이 발생할 수 있습니다. 값이 없으면 임의의 숫자를 만들지 않습니다.")

st.divider()
st.caption("Eggfolio는 투자 리서치 및 기록 도구이며 매수·매도 지시를 제공하지 않습니다.")
