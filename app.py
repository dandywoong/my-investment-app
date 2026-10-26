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
# 종목 검색 목록: 국내 주식·ETF 및 미국 주요 종목
STOCK_DIRECTORY = {
    "삼성전자": "005930.KS",
    "삼성전기": "009150.KS",
    "삼성SDI": "006400.KS",
    "삼성바이오로직스": "207940.KS",
    "SK하이닉스": "000660.KS",
    "SK스퀘어": "402340.KS",
    "SK텔레콤": "017670.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "LG에너지솔루션": "373220.KS",
    "LG화학": "051910.KS",
    "NAVER": "035420.KS",
    "카카오": "035720.KS",
    "한화에어로스페이스": "012450.KS",
    "두산": "000150.KS",
    "두산에너빌리티": "034020.KS",
    "두산로보틱스": "454910.KS",
    "두산테스나": "131970.KQ",
    "POSCO홀딩스": "005490.KS",
    "셀트리온": "068270.KS",
    "KB금융": "105560.KS",
    "신한지주": "055550.KS",
    "이수페타시스": "007660.KS",
    "리노공업": "058470.KQ",
    "원익IPS": "240810.KQ",

    "KODEX 미국나스닥100": "379810.KS",
    "KODEX 미국S&P500": "379800.KS",
    "KODEX 반도체": "091160.KS",
    "KODEX 200": "069500.KS",
    "SOL AI반도체TOP2플러스": "0167A0.KS",
    "KODEX AI반도체TOP2플러스": "395160.KS",

    "NVIDIA": "NVDA",
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Alphabet": "GOOGL",
    "Amazon": "AMZN",
    "Tesla": "TSLA",
    "Meta Platforms": "META",
    "Broadcom": "AVGO",
    "Berkshire Hathaway B": "BRK-B",
    "S&P 500 ETF": "VOO",
    "Nasdaq-100 ETF": "QQQ",
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
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


@st.cache_data(ttl=3600, show_spinner=False)
def search_yahoo_stocks(query):
    """Search Yahoo Finance and return (display name, ticker) pairs."""
    query = query.strip()

    if len(query) < 2:
        return []

    try:
        results = yf.Search(query, max_results=10).quotes or []
    except Exception:
        return []

    matches = []
    seen = set()

    for item in results:
        symbol = str(item.get("symbol", "")).strip().upper()
        name = (
            item.get("longname")
            or item.get("shortname")
            or symbol
        )

        if not symbol or symbol in seen:
            continue

        # Keep common stocks and ETFs; skip unrelated result types.
        quote_type = str(item.get("quoteType", "")).upper()
        if quote_type and quote_type not in {"EQUITY", "ETF"}:
            continue

        matches.append((str(name), symbol))
        seen.add(symbol)

    return matches


def find_stock_matches(query):
    q = query.strip().lower().replace(" ", "")

    # Keep the local directory useful for Korean names and initials.
    local_matches = []
    for name, symbol in STOCK_DIRECTORY.items():
        if (
            not q
            or q in name.lower().replace(" ", "")
            or q in symbol.lower().replace(" ", "")
            or q in get_initials(name).replace(" ", "")
        ):
            local_matches.append((name, symbol))

    if not q:
        return local_matches

    # Add external results, avoiding duplicate tickers.
    external_matches = search_yahoo_stocks(query)
    seen = {symbol.upper() for _, symbol in local_matches}

    for name, symbol in external_matches:
        if symbol.upper() not in seen:
            local_matches.append((name, symbol))
            seen.add(symbol.upper())

    return local_matches

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


@st.cache_data(ttl=3600, show_spinner=False)
def load_korean_investor_flows():
    """한국 상장 보통주의 외국인·기관 순매수 집계 데이터."""
    import pandas as pd

    base_url = (
        "https://raw.githubusercontent.com/"
        "james-brand/korea-market-data/main/data"
    )
    url = f"{base_url}/foreign-flows-aggregates.csv"

    try:
        flows = pd.read_csv(url, comment="#")

        required = {
            "ticker", "name_en", "market",
            "f_1d_sh", "f_5d_sh", "f_20d_sh",
            "f_5d_val", "f_20d_val",
            "i_1d_sh", "i_5d_sh", "i_20d_sh",
        }

        missing = required - set(flows.columns)
        if missing:
            return None, f"필수 열 누락: {', '.join(sorted(missing))}"

        flows["ticker"] = (
            flows["ticker"]
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(6)
        )

        return flows, None

    except Exception as e:
        return None, str(e)


def render_investor_flow_check(ticker):
    """현재 종목의 수급 데이터와 연결 상태를 표시한다."""
    st.subheader("① 수급 검증")

    # 한국 주식만 지원하는 데이터셋이므로 시장을 먼저 구분한다.
    ticker_upper = ticker.strip().upper()

    if not ticker_upper.endswith((".KS", ".KQ")):
        st.warning(
            "미연결 · 현재 수급 데이터 연결은 .KS / .KQ "
            "한국 상장 보통주만 지원합니다."
        )
        st.caption(
            "미국 주식 등은 별도 데이터 공급원을 연결해야 합니다. "
            "수급이 중립이라는 뜻은 아닙니다."
        )
        return

    code = ticker_upper.rsplit(".", 1)[0]

    if not code.isdigit() or len(code) != 6:
        st.warning("미연결 · 종목 코드 형식을 확인할 수 없습니다.")
        return

    with st.spinner("외국인·기관 수급 데이터 확인 중..."):
        flows, error = load_korean_investor_flows()

    if flows is None:
        st.warning("데이터 조회 실패 · 수급 미연결")
        st.caption(f"오류 내용: {error}")
        return

    matched = flows.loc[flows["ticker"] == code]

    if matched.empty:
        st.warning(
            f"미연결 · 공개 데이터셋에서 종목 코드 {code}를 찾지 못했습니다."
        )
        return

    row = matched.iloc[0]

    # 필수 데이터가 실제로 숫자로 읽히는지 확인한다.
    fields = [
        "f_1d_sh", "f_5d_sh", "f_20d_sh",
        "f_5d_val", "f_20d_val",
        "i_1d_sh", "i_5d_sh", "i_20d_sh",
    ]

    values = pd.to_numeric(row[fields], errors="coerce")
    valid_count = int(values.notna().sum())

    if valid_count == 0:
        st.warning("부분 연결 · 수급 수치가 유효하지 않습니다.")
        return

    status = "연결됨" if valid_count == len(fields) else "부분 연결"
    st.success(f"수급 데이터 {status} · 유효 항목 {valid_count}/{len(fields)}")

    def fmt_shares(value):
        if pd.isna(value):
            return "자료 없음"
        return f"{value:+,.0f}주"

    def fmt_value(value):
        if pd.isna(value):
            return "자료 없음"
        return f"{value / 100_000_000:+,.1f}억원"

    c1, c2, c3 = st.columns(3)

    c1.metric("외국인 · 1일", fmt_shares(row["f_1d_sh"]))
    c2.metric("외국인 · 5일", fmt_shares(row["f_5d_sh"]))
    c3.metric("외국인 · 20일", fmt_shares(row["f_20d_sh"]))

    c1, c2, c3 = st.columns(3)

    c1.metric("기관 · 1일", fmt_shares(row["i_1d_sh"]))
    c2.metric("기관 · 5일", fmt_shares(row["i_5d_sh"]))
    c3.metric("기관 · 20일", fmt_shares(row["i_20d_sh"]))

    st.write("**순매수 금액 참고**")
    st.write(f"- 외국인 · 5일: {fmt_value(row['f_5d_val'])}")
    st.write(f"- 외국인 · 20일: {fmt_value(row['f_20d_val'])}")

    foreign_5d = pd.to_numeric(row["f_5d_sh"], errors="coerce")
    institution_5d = pd.to_numeric(row["i_5d_sh"], errors="coerce")

    if pd.notna(foreign_5d) and pd.notna(institution_5d):
        if foreign_5d > 0 and institution_5d > 0:
            interpretation = "외국인과 기관의 5일 누적 순매수가 모두 양수입니다."
        elif foreign_5d < 0 and institution_5d < 0:
            interpretation = "외국인과 기관의 5일 누적 순매도가 모두 관측됩니다."
        else:
            interpretation = "외국인과 기관의 5일 수급 방향이 서로 다릅니다."

        st.info(interpretation)

    st.caption(
        "출처: Korean Market Data / K-Export Stars, CC BY 4.0. "
        "일별 집계이며 장중 실시간 수급이 아닙니다. "
        "순매수는 투자심리의 직접 측정치가 아니며, "
        "데이터의 기준일을 확인한 후 해석해야 합니다."
    )

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
    """종목명과 티커를 이용한 간단한 카테고리 추정. 확정된 업종 정보는 아닙니다."""
    n = str(name).lower()
    t = str(ticker).upper()
    if t.startswith("^"):
        return "시장 지수"
    if any(x in n for x in ["s&p 500", "nasdaq-100", "total market", "전세계", "월드", "미국지수", "미국나스닥", "미국s&p"]):
        return "시장 지수 ETF"
    if any(x in n for x in ["채권", "국채", "bond", "treasury"]):
        return "채권"
    if any(x in n for x in ["배당", "고배당", "dividend"]):
        return "배당 ETF"
    if t in {"NVDA", "AMD", "AVGO", "QCOM", "MU", "ASML", "TSM", "000660.KS", "005930.KS", "009150.KS"} or any(x in n for x in ["반도체", "semiconductor", "엔비디아", "하이닉스", "삼성전자", "삼성전기", "브로드컴"]):
        return "반도체·하드웨어"
    if t in {"GOOG", "GOOGL", "MSFT", "AAPL", "META", "AMZN", "CRM", "NOW", "PLTR", "ORCL", "ADBE", "TSLA"} or any(x in n for x in ["alphabet", "google", "microsoft", "apple", "meta platforms", "amazon", "software", "소프트웨어", "테슬라"]):
        return "기술·성장주"
    if t in {"BRK-A", "BRK-B", "BRK.A", "BRK.B", "JPM", "BAC", "WFC", "GS", "MS", "105560.KS", "055550.KS"} or any(x in n for x in ["berkshire", "금융", "은행", "보험", "지주"]):
        return "금융·지주"
    if any(x in n for x in ["필수소비재", "식품", "생활용품", "walmart", "costco", "procter", "coca-cola", "pepsico"]):
        return "경기 방어주"
    if any(x in n for x in ["헬스케어", "제약", "바이오", "health", "pharma"]):
        return "헬스케어"
    if any(x in n for x in ["자동차", "항공", "철강", "화학", "에너지", "조선", "건설", "기아", "현대차", "posco"]):
        return "경기 민감주"
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
    st.caption(
        "여기서 선택한 종목은 차트·시장 국면·기업 기초체력·판단 기록의 공통 기준입니다."
    )

    # 기본 종목과 확장 종목 목록 통합
    sidebar_tickers = {**TICKERS, **STOCK_DIRECTORY}

    chosen = st.selectbox(
        "공통 종목 선택",
        list(sidebar_tickers.keys()),
        key="global_ticker_choice"
    )

    custom = st.text_input(
        "티커 직접 입력 (선택사항)",
        placeholder="예: NVDA 또는 005930.KS",
        key="global_ticker_custom"
    )

    ticker = (
        custom.strip().upper()
        if custom.strip()
        else sidebar_tickers[chosen]
    )

    selected_stock_name = (
        chosen
        if not custom.strip()
        else next(
            (
                name for name, symbol in sidebar_tickers.items()
                if symbol.upper() == ticker
            ),
            ticker
        )
    )

    period_name = st.selectbox(
        "차트 기간",
        list(PERIODS.keys()),
        index=2
    )
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
        
        st.subheader("보유 종목 직접 편집")
        st.caption(
            "종목명, 수량, 평단, 통화, 계좌를 수정한 뒤 저장하세요. "
            "종목 코드는 식별자이므로 여기서는 수정할 수 없습니다."
        )

        edit_cols = ["ticker", "name", "quantity", "avg_cost", "currency", "account"]
        edit_df = holdings[edit_cols].copy()
        edit_df = edit_df.rename(columns={
            "ticker": "종목 코드",
            "name": "종목명",
            "quantity": "보유 수량",
            "avg_cost": "평균 매입단가",
            "currency": "통화",
            "account": "계좌",
        })

        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="holdings_editor",
            column_config={
                "종목 코드": st.column_config.TextColumn(
                    "종목 코드", disabled=True
                ),
                "종목명": st.column_config.TextColumn("종목명"),
                "보유 수량": st.column_config.NumberColumn(
                    "보유 수량", min_value=0.0, format="%.4f"
                ),
                "평균 매입단가": st.column_config.NumberColumn(
                    "평균 매입단가", min_value=0.0, format="%.4f"
                ),
                "통화": st.column_config.SelectboxColumn(
                    "통화", options=["KRW", "USD"]
                ),
                "계좌": st.column_config.SelectboxColumn(
                    "계좌",
                    options=[
                        "삼성증권 ISA",
                        "삼성증권 일반계좌",
                        "삼성증권 CMA",
                        "기타 계좌",
                    ],
                ),
            },
        )

        if st.button("변경사항 저장", key="save_holdings_edits"):
            try:
                if edited["종목명"].astype(str).str.strip().eq("").any():
                    st.error("종목명은 비워둘 수 없습니다.")
                elif (
                    (edited["보유 수량"] <= 0).any()
                    or (edited["평균 매입단가"] <= 0).any()
                ):
                    st.error("보유 수량과 평균 매입단가는 0보다 커야 합니다.")
                else:
                    for _, row in edited.iterrows():
                        save_holding(
                            str(row["종목 코드"]),
                            str(row["종목명"]).strip(),
                            float(row["보유 수량"]),
                            float(row["평균 매입단가"]),
                            str(row["통화"]),
                            str(row["계좌"]),
                        )

                    st.success("보유 종목 변경사항을 저장했습니다.")
                    st.rerun()
            except Exception as e:
                st.error(f"변경사항 저장에 실패했습니다: {e}")

        
        st.subheader("계좌별 보유 현황")

        display_cols = [
            "종목", "코드", "수량", "평단",
            "현재가", "평가금액", "평가손익", "수익률(%)"
        ]

        account_order = [
            "삼성증권 ISA",
            "삼성증권 일반계좌",
            "삼성증권 CMA",
            "기타 계좌",
        ]

        for account_name in account_order:
            account_pf = pf[pf["계좌"] == account_name].copy()

            if account_pf.empty:
                continue

            account_value = account_pf["평가금액"].sum(min_count=1)
            account_pnl = account_pf["평가손익"].sum(min_count=1)

            with st.expander(
                f"{account_name} · 평가금액 {fmt_large(account_value)} · "
                f"평가손익 {fmt_large(account_pnl)}",
                expanded=True,
            ):
                st.dataframe(
                    account_pf[display_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "수량": st.column_config.NumberColumn(
                            "수량", format="%.4f"
                        ),
                        "평단": st.column_config.NumberColumn(
                            "평단", format="%.2f"
                        ),
                        "현재가": st.column_config.NumberColumn(
                            "현재가", format="%.2f"
                        ),
                        "평가금액": st.column_config.NumberColumn(
                            "평가금액", format="%.0f"
                        ),
                        "평가손익": st.column_config.NumberColumn(
                            "평가손익", format="%.0f"
                        ),
                        "수익률(%)": st.column_config.NumberColumn(
                            "수익률(%)", format="%.2f%%"
                        ),
                    },
                )

        st.subheader("포트폴리오 비중")
        st.caption("통화별로 차트를 분리했습니다. 안쪽은 자산 카테고리, 바깥쪽은 개별 종목입니다. 조각을 누르거나 마우스를 올리면 평가금액과 전체 비중을 확인할 수 있습니다.")

        category_colors = {
            "반도체·하드웨어": "#2563EB",
            "기술·성장주": "#7C3AED",
            "시장 지수 ETF": "#0D9488",
            "시장 지수": "#0F766E",
            "경기 방어주": "#16A34A",
            "헬스케어": "#22A06B",
            "금융·지주": "#D97706",
            "경기 민감주": "#EA580C",
            "배당 ETF": "#65A30D",
            "채권": "#64748B",
            "기타·분류 확인 필요": "#9CA3AF",
        }
        # 같은 종목이 여러 계좌에 있으면 차트에서는 한 종목으로 합산합니다.
        chart_cols = st.columns(2)
        for col, currency in zip(chart_cols, ["KRW", "USD"]):
            subset = pf[(pf["통화"] == currency) & pf["평가금액"].notna() & (pf["평가금액"] > 0)].copy()
            with col:
                st.markdown(f"**{currency} 자산 비중**")
                if subset.empty:
                    st.info(f"{currency} 평가 가능한 자산이 없습니다.")
                    continue

                subset["카테고리"] = subset.apply(
                    lambda row: classify_holding(row["종목"], row["코드"]), axis=1
                )
                chart_data = (
                    subset.groupby(["카테고리", "코드", "종목"], as_index=False)["평가금액"]
                    .sum()
                    .sort_values("평가금액", ascending=False)
                )
                total_value_chart = float(chart_data["평가금액"].sum())
                category_totals = chart_data.groupby("카테고리")["평가금액"].sum().sort_values(ascending=False)

                labels, ids, parents, values, colors, hover_text = [], [], [], [], [], []
                for category, category_value in category_totals.items():
                    category_id = f"category::{currency}::{category}"
                    category_weight = float(category_value) / total_value_chart
                    labels.append(f"{category} · {category_weight:.1%}")
                    ids.append(category_id)
                    parents.append("")
                    values.append(float(category_value))
                    base_color = category_colors.get(category, "#9CA3AF")
                    colors.append(base_color)
                    hover_text.append(
                        f"<b>{category}</b><br>평가금액: {category_value:,.2f} {currency}"
                        f"<br>전체 비중: {category_weight:.2%}"
                    )

                    children = chart_data[chart_data["카테고리"] == category]
                    for _, stock in children.iterrows():
                        stock_value = float(stock["평가금액"])
                        stock_weight = stock_value / total_value_chart
                        ticker = str(stock["코드"])
                        stock_name = str(stock["종목"])
                        stock_id = f"stock::{currency}::{category}::{ticker}"
                        # 차트 라벨은 티커 대신 사용자가 등록한 종목명을 표시합니다.
                        short_label = stock_name if len(stock_name) <= 16 else stock_name[:15] + "…"
                        labels.append(f"{short_label} · {stock_weight:.1%}")
                        ids.append(stock_id)
                        parents.append(category_id)
                        values.append(stock_value)
                        colors.append(base_color)
                        hover_text.append(
                            f"<b>{stock_name} ({ticker})</b><br>카테고리: {category}"
                            f"<br>평가금액: {stock_value:,.2f} {currency}"
                            f"<br>전체 비중: {stock_weight:.2%}"
                        )

                fig_pie = go.Figure(go.Sunburst(
                    ids=ids,
                    labels=labels,
                    parents=parents,
                    values=values,
                    branchvalues="total",
                    sort=False,
                    maxdepth=2,
                    insidetextorientation="radial",
                    textinfo="label",
                    marker={"colors": colors, "line": {"color": "white", "width": 1}},
                    customdata=hover_text,
                    hovertemplate="%{customdata}<extra></extra>",
                ))
                fig_pie.update_layout(
                    height=470,
                    margin={"l": 4, "r": 4, "t": 8, "b": 8},
                    showlegend=False,
                    uniformtext={"minsize": 9, "mode": "hide"},
                )
                st.plotly_chart(fig_pie, use_container_width=True)
                st.caption("작은 조각은 라벨이 숨겨질 수 있습니다. 해당 조각에 마우스를 올리면 종목명·평가금액·전체 비중이 표시됩니다. 자동 카테고리는 종목명과 티커를 바탕으로 한 추정이며, 미분류 항목은 별도 확인이 필요합니다.")
        st.caption("주의: 통화가 다른 종목의 합계는 환산 전 값이 섞일 수 있으므로 총액·손익 합계는 KRW와 USD를 분리해 해석해야 합니다. 가격 기준일과 제공자 데이터의 지연 가능성을 확인하세요. 세금·배당·환전 비용은 아직 반영하지 않습니다.")
        st.download_button("보유 현황 CSV 다운로드", pf.to_csv(index=False).encode("utf-8-sig"), "eggfolio_portfolio.csv", "text/csv")
       
        st.subheader("보유 종목 개별 삭제")
        st.caption("잘못 등록한 종목만 선택해 삭제할 수 있습니다. 삭제 후에는 복구할 수 없으므로 종목 코드와 이름을 확인하세요.")
        for _, item in holdings.iterrows():
            delete_col1, delete_col2 = st.columns([5, 1])
            with delete_col1:
                st.write(f"**{item['name']}** · `{item['ticker']}` · {item['account']}")
            with delete_col2:
                if st.button("삭제", key=f"delete_holding_{item['ticker']}", type="secondary"):
                    delete_holding(item["ticker"])
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
    render_investor_flow_check(ticker)
    st.subheader("시장 국면 분석")
    st.caption(
        "시장 심리를 중심에 두고, 가격 행동으로 간접 관측한 뒤 "
        "수급·실적·거시 자료로 검증해 나가는 분석 화면입니다. "
        "현재 연결된 가격 자료만으로 실제 대중심리를 확정하지 않습니다."
    )

    market_name, market_ticker = stock_search_widget(
        "market_regime_search",
        default_ticker=ticker,
        default_name=""
    )
    market_period_label = st.selectbox(
        "분석 기간",
        list(PERIODS.keys()),
        index=list(PERIODS.keys()).index("1년"),
        key="market_regime_period"
    )
    market_period = PERIODS[market_period_label]

    if not market_ticker:
        st.warning("먼저 분석할 종목을 검색하고 선택해 주세요.")
    else:
        try:
            market_prices, fetch_elapsed = get_prices(market_ticker, market_period)
            if market_prices is None or market_prices.empty:
                st.warning("선택한 종목의 가격 데이터가 없습니다.")
            else:
                market_last = market_prices.iloc[-1]
                market_close = float(market_last["Close"])
                market_date = str(market_prices.index[-1].date())
                ma20 = market_last["MA20"]
                ma60 = market_last["MA60"]
                ma120 = market_last["MA120"]
                ret20 = market_last["Return20"]
                ret60 = market_last["Return60"]
                volume_ratio = market_last["VolumeRatio20"]

                st.markdown(f"### {market_name} (`{market_ticker}`)")
                st.caption(
                    f"가격 데이터 기준일: {market_date} · 조회 소요: {fetch_elapsed:.2f}초 · "
                    "가격은 Yahoo Finance 제공 데이터이며 장중·장후 현재가와 다를 수 있습니다."
                )

                # 핵심 요약
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("최근 일봉 종가", f"{market_close:,.2f}")
                m2.metric("20거래일 수익률", f"{ret20:+.2f}%" if pd.notna(ret20) else "자료 부족")
                m3.metric("60거래일 수익률", f"{ret60:+.2f}%" if pd.notna(ret60) else "자료 부족")
                m4.metric("거래량 / 20일 평균", f"{volume_ratio:.2f}배" if pd.notna(volume_ratio) else "자료 부족")

                # 차트는 국면 판단 화면 상단에 배치해 국면 근거와 함께 확인할 수 있게 함
                st.subheader("가격 행동: 차트와 거래량")
                market_mas = st.multiselect(
                    "차트 이동평균선",
                    [5, 20, 60, 120, 200],
                    default=[20, 60, 120],
                    format_func=lambda n: f"{n}일선",
                    key="market_regime_mas"
                )
                market_volume = st.checkbox("차트에 거래량 표시", True, key="market_regime_volume")
                st.plotly_chart(
                    make_chart(market_prices, market_mas, market_volume),
                    use_container_width=True,
                    config={"scrollZoom": True, "displaylogo": False, "responsive": True},
                    key="market_regime_price_chart"
                )

                # 1) 가격 행동: 심리를 직접 측정하지 않고, 시장 행동에 남은 흔적을 관측
                st.subheader("① 시장 심리의 간접 신호")
                trend_label, trend_desc, trend_signals = market_read(market_prices)
                st.markdown(f"**가격 추세 판독: {trend_label}**")
                st.write(trend_desc)

                distance_ma120 = (
                    (market_close / float(ma120) - 1) * 100
                    if pd.notna(ma120) and float(ma120) != 0 else None
                )
                above_ma20 = bool(pd.notna(ma20) and market_close > float(ma20))
                above_ma60 = bool(pd.notna(ma60) and market_close > float(ma60))
                above_ma120 = bool(pd.notna(ma120) and market_close > float(ma120))
                strong_momentum = bool(pd.notna(ret20) and pd.notna(ret60) and ret20 > 8 and ret60 > 15)
                volume_spike = bool(pd.notna(volume_ratio) and volume_ratio >= 1.5)
                weak_momentum = bool(pd.notna(ret20) and pd.notna(ret60) and ret20 < 0 and ret60 < 0)
                below_short_medium = bool(pd.notna(ma20) and pd.notna(ma60) and market_close < ma20 and market_close < ma60)

                signal_rows = [
                    ["추세 구조", "20·60일선 위" if above_ma20 and above_ma60 else ("20·60일선 아래" if pd.notna(ma20) and pd.notna(ma60) and not above_ma20 and not above_ma60 else "혼합 / 자료 부족"), "추세 방향을 관측하며 심리 자체를 확정하지 않음"],
                    ["중기 추세 대비 위치", f"120일선 대비 {distance_ma120:+.1f}%" if distance_ma120 is not None else "자료 부족", "장기 평균에서 멀어진 정도를 확인"],
                    ["최근 상승 탄력", "강한 상승 탄력 관측" if strong_momentum else ("20·60일 수익률 모두 음수" if weak_momentum else "뚜렷한 극단 신호 없음"), "강한 추세와 과열을 동일시하지 않음"],
                    ["거래량 반응", f"20일 평균의 {volume_ratio:.2f}배" if pd.notna(volume_ratio) else "자료 부족", "거래량 급증은 방향만으로 해석하지 않음"],
                ]
                st.dataframe(
                    pd.DataFrame(signal_rows, columns=["관측 영역", "현재 관측", "해석 원칙"]),
                    use_container_width=True,
                    hide_index=True
                )

                # 단일 지표가 아니라 서로 다른 가격 행동 신호가 겹치는지 확인
                overheating_evidence = []
                if strong_momentum:
                    overheating_evidence.append("20·60거래일 수익률이 모두 강한 상승 구간")
                if distance_ma120 is not None and distance_ma120 >= 20:
                    overheating_evidence.append("종가가 120일선보다 20% 이상 위")
                if volume_spike:
                    overheating_evidence.append("거래량이 20일 평균의 1.5배 이상")

                downside_evidence = []
                if weak_momentum:
                    downside_evidence.append("20·60거래일 수익률이 모두 음수")
                if below_short_medium:
                    downside_evidence.append("종가가 20일선과 60일선 아래")
                if pd.notna(volume_ratio) and volume_ratio >= 1.5 and weak_momentum:
                    downside_evidence.append("약세 구간에서 거래량 증가")

                if len(overheating_evidence) >= 2:
                    psychology_read = "상승 과열 가능성 점검 필요"
                    psychology_detail = "가격 행동에서 상승 탄력·평균선 이격·거래량 중 여러 신호가 겹칩니다. 이것만으로 고점이나 하락 전환을 뜻하지는 않습니다."
                    st.warning(psychology_read + " — " + psychology_detail)
                    confidence_note = "가격 행동 신호 일부가 같은 방향을 가리킴. 직접 심리·수급 자료가 없어 신뢰도는 제한적."
                elif len(downside_evidence) >= 2:
                    psychology_read = "약세·위험 회피 가능성 점검 필요"
                    psychology_detail = "하락 탄력과 추세 약화가 함께 관측됩니다. 단기 반등 여부만으로 국면 전환을 확정하지 않습니다."
                    st.warning(psychology_read + " — " + psychology_detail)
                    confidence_note = "약세 관련 가격 행동 신호가 겹침. 직접 심리·수급 자료가 없어 신뢰도는 제한적."
                else:
                    psychology_read = "심리 국면 판단 보류"
                    psychology_detail = "현재 연결된 가격 행동만으로 과열 또는 공포가 충분히 확인되지 않습니다. 수급·심리 조사·실적 등 독립 근거가 필요합니다."
                    st.info(psychology_read + " — " + psychology_detail)
                    confidence_note = "판단을 뒷받침할 독립적인 심리·수급 자료가 아직 연결되지 않음."

                st.markdown("**판단 근거**")
                if overheating_evidence:
                    st.write("상승·과열 후보 신호: " + "; ".join(overheating_evidence))
                if downside_evidence:
                    st.write("약세 후보 신호: " + "; ".join(downside_evidence))
                if not overheating_evidence and not downside_evidence:
                    st.write("현재 규칙에서 여러 신호가 동시에 충족되지 않았습니다.")
                st.caption("판단 신뢰도: " + confidence_note)

                # 2) 코스톨라니 달걀: 이론적 틀과 관측 자료를 분리
                st.subheader("② 코스톨라니 달걀 관점")
                st.caption(
                    "아래 표시는 코스톨라니의 실제 심리 단계를 측정한 결과가 아니라, "
                    "현재 가격 행동을 이론적 틀과 비교하기 위한 참고용 요약입니다."
                )
                egg_fig = go.Figure()
                egg_fig.add_shape(type="circle", x0=0.12, y0=0.10, x1=0.88, y1=0.90,
                                  line=dict(color="#64748B", width=2), fillcolor="rgba(148,163,184,0.08)")
                egg_fig.add_shape(type="line", x0=0.50, y0=0.12, x1=0.50, y1=0.88,
                                  line=dict(color="#94A3B8", dash="dot"))
                egg_fig.add_shape(type="line", x0=0.14, y0=0.50, x1=0.86, y1=0.50,
                                  line=dict(color="#94A3B8", dash="dot"))
                egg_fig.add_trace(go.Scatter(
                    x=[0.30, 0.50, 0.70, 0.50, 0.30], y=[0.70, 0.82, 0.50, 0.18, 0.70],
                    mode="lines+markers", name="개념적 사이클",
                    line=dict(color="#64748B", width=2), marker=dict(size=7), hoverinfo="skip"
                ))
                if len(overheating_evidence) >= 2:
                    egg_stage, egg_x, egg_y = "상승 과열 가능성 점검", 0.70, 0.75
                elif len(downside_evidence) >= 2:
                    egg_stage, egg_x, egg_y = "약세 가능성 점검", 0.68, 0.28
                elif above_ma20 and above_ma60:
                    egg_stage, egg_x, egg_y = "상승 추세 관측 · 심리 판단 보류", 0.36, 0.72
                elif below_short_medium:
                    egg_stage, egg_x, egg_y = "약세 추세 관측 · 심리 판단 보류", 0.64, 0.28
                else:
                    egg_stage, egg_x, egg_y = "전환·혼합 · 판단 보류", 0.50, 0.50
                egg_fig.add_trace(go.Scatter(
                    x=[egg_x], y=[egg_y], mode="markers+text", name="가격 행동 참고 위치",
                    text=[market_name], textposition="top center",
                    marker=dict(size=18, color="#F59E0B", line=dict(color="#FFFFFF", width=2)),
                    hovertemplate=f"<b>{market_name}</b><br>참고 해석: {egg_stage}<br>기준일: {market_date}<extra></extra>"
                ))
                for x, y, label in [(0.50, 0.96, "상승·낙관 가능 영역"), (0.50, 0.04, "하락·공포 가능 영역"), (0.04, 0.50, "회복"), (0.96, 0.50, "약세")]:
                    egg_fig.add_annotation(x=x, y=y, text=label, showarrow=False)
                egg_fig.update_layout(
                    height=420, template="plotly_white", margin=dict(l=20, r=20, t=40, b=30),
                    xaxis=dict(range=[0, 1], visible=False, fixedrange=True),
                    yaxis=dict(range=[0, 1], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
                    showlegend=True
                )
                st.plotly_chart(egg_fig, use_container_width=True, key="market_egg_cycle")
                st.markdown(f"**현재 가격 행동 참고: {egg_stage}**")
                st.write("이 판단은 가격·거래량 기반의 간접 관측입니다. 실제 대중심리·자금 흐름 자료가 연결되기 전에는 코스톨라니 국면을 확정하지 않습니다.")

                # 3) 민스키는 가격 차트만으로 분류하지 않음
                st.subheader("③ 민스키 금융 불안정 관점")
                st.info(
                    "현재 종목별 신용·레버리지·부채 상환 능력 자료가 연결되지 않아 "
                    "민스키 국면은 **판단 보류**입니다. 주가 상승이나 거래량 증가만으로 "
                    "투기 금융·폰지 금융 단계라고 분류하지 않습니다."
                )

                # 4) 다음 데이터 연결 시 검증할 항목을 명시
                st.subheader("④ 다음 검증 단계")
                review_rows = [
                    ["가격 행동", "연결됨", "추세·수익률·거래량으로 간접 관측"],
                    ["직접 심리 자료", "미연결", "투자심리 조사·변동성·시장 심리 지표"],
                    ["수급 자료", "미연결", "외국인·기관·개인 흐름, 공매도·대차"],
                    ["실적·밸류에이션", "미연결", "가격 상승이 이익 전망으로 뒷받침되는지 검증"],
                    ["거시·신용 자료", "미연결", "금리·유동성·신용 팽창과 레버리지 위험"],
                ]
                st.dataframe(pd.DataFrame(review_rows, columns=["분석 영역", "연결 상태", "활용 목적"]),
                             use_container_width=True, hide_index=True)
                st.caption(
                    "이 화면은 매수·매도 신호나 수익 보장을 제공하지 않습니다. "
                    "데이터가 늘어날 때마다 과거 사례에서 경고의 적시성·오경보 빈도를 검증하고, "
                    "판단 개선에 도움이 되는 자료만 추가합니다."
                )
        except Exception as e:
            st.error(f"시장 국면 데이터를 불러오지 못했습니다: {e}")
            st.caption("종목 코드, Yahoo Finance 응답, 데이터 제공 상태를 확인해 주세요.")

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
