
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


st.set_page_config(
    page_title="Eggfolio | Data Test",
    page_icon="🥚",
    layout="wide",
)

st.title("🥚 Eggfolio")
st.caption("1차 테스트 · Yahoo Finance 데이터 연결 및 종목 변경 검증")

st.info(
    "이 버전은 데이터 연결을 검증하기 위한 테스트입니다. "
    "조회 시각은 데이터를 받아온 시각이며, 실시간 시세를 의미하지 않습니다."
)


@st.cache_data(ttl=300, show_spinner=False)
def load_stock_data(ticker: str, period: str):
    """Yahoo Finance에서 주가 데이터를 조회한다."""
    stock = yf.Ticker(ticker)
    data = stock.history(
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
        raise_errors=True,
    )

    if data is None or data.empty:
        raise ValueError(
            "조회된 데이터가 없습니다. 티커가 맞는지 확인하거나 잠시 후 다시 시도하세요."
        )

    data = data.copy()
    data.index = pd.to_datetime(data.index)

    # 주가와 거래량에 필요한 값이 실제로 존재하는지 확인한다.
    required_columns = ["Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in required_columns if col not in data.columns]
    if missing:
        raise ValueError(f"필수 데이터 항목이 없습니다: {', '.join(missing)}")

    data = data.dropna(subset=["Close"])

    if data.empty:
        raise ValueError("유효한 종가 데이터가 없습니다.")

    return data


with st.sidebar:
    st.header("조회 설정")

    presets = {
        "NVDA · NVIDIA": "NVDA",
        "AAPL · Apple": "AAPL",
        "MSFT · Microsoft": "MSFT",
        "GOOGL · Alphabet": "GOOGL",
        "AMZN · Amazon": "AMZN",
        "TSLA · Tesla": "TSLA",
        "005930.KS · Samsung Electronics": "005930.KS",
        "000660.KS · SK Hynix": "000660.KS",
        "직접 입력": "CUSTOM",
    }

    selected = st.selectbox("종목 선택", list(presets.keys()))

    if presets[selected] == "CUSTOM":
        ticker_input = st.text_input(
            "티커 입력",
            value="NVDA",
            help="예: NVDA, AAPL, 005930.KS, 000660.KS",
        )
    else:
        ticker_input = presets[selected]

    period_label = st.selectbox(
        "조회 기간",
        ["1개월", "3개월", "6개월", "1년", "2년", "5년"],
        index=1,
    )

    periods = {
        "1개월": "1mo",
        "3개월": "3mo",
        "6개월": "6mo",
        "1년": "1y",
        "2년": "2y",
        "5년": "5y",
    }
    period = periods[period_label]

    refresh = st.button("데이터 새로 조회", use_container_width=True)

ticker = ticker_input.strip().upper()

if not ticker:
    st.warning("먼저 조회할 종목의 티커를 입력하세요.")
    st.stop()

if refresh:
    # 사용자가 명시적으로 새로 조회할 때 해당 종목의 캐시를 비운다.
    load_stock_data.clear()

st.subheader(f"조회 종목: {ticker}")

try:
    with st.spinner(f"{ticker} 데이터를 Yahoo Finance에서 조회하고 있습니다..."):
        started_at = time.time()
        data = load_stock_data(ticker, period)
        elapsed = time.time() - started_at
        retrieved_at = datetime.now().astimezone()

except Exception as exc:
    st.error("데이터 조회에 실패했습니다.")
    st.write("**조회 티커:**", ticker)
    st.write("**오류 내용:**")
    st.code(str(exc))

    st.markdown(
        """
        **확인할 사항**
        - 티커 표기가 맞는지 확인하세요.
        - 잠시 기다렸다가 다시 조회하세요.
        - 반복적으로 실패한다면 Yahoo Finance의 요청 제한이나 연결 문제일 수 있습니다.
        """
    )
    st.stop()

latest = data.iloc[-1]
previous = data.iloc[-2] if len(data) >= 2 else None

latest_close = float(latest["Close"])
latest_volume = latest["Volume"]

if previous is not None and float(previous["Close"]) != 0:
    change_pct = (
        latest_close / float(previous["Close"]) - 1
    ) * 100
else:
    change_pct = None

latest_date = pd.Timestamp(data.index[-1])
if latest_date.tzinfo is not None:
    latest_date = latest_date.tz_convert("UTC")

latest_date_text = latest_date.strftime("%Y-%m-%d %H:%M UTC")

st.subheader("데이터 상태")

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "최근 종가",
    f"{latest_close:,.2f}",
    delta=None if change_pct is None else f"{change_pct:+.2f}%",
)

m2.metric(
    "최근 일봉 거래량",
    "없음" if pd.isna(latest_volume) else f"{float(latest_volume):,.0f}",
)

m3.metric(
    "조회된 일봉 수",
    f"{len(data):,}개",
)

m4.metric(
    "조회 소요 시간",
    f"{elapsed:.2f}초",
)

st.write("**데이터 기준 시각:**", latest_date_text)
st.write(
    "**Eggfolio 조회 시각:**",
    retrieved_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
)

st.caption(
    "기준 시각은 Yahoo Finance가 반환한 가장 최근 일봉의 날짜입니다. "
    "조회 시각은 이 앱이 요청을 수행한 시각입니다. "
    "두 시각은 다를 수 있으며, 이 정보만으로 실시간 여부를 보장할 수 없습니다."
)

st.divider()
st.subheader(f"{ticker} 주가 차트")

fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=data.index,
        y=data["Close"],
        mode="lines",
        name="종가",
        hovertemplate="날짜: %{x}<br>종가: %{y:,.2f}<extra></extra>",
    )
)

fig.update_layout(
    xaxis_title="날짜",
    yaxis_title="가격",
    hovermode="x unified",
    margin=dict(l=10, r=10, t=20, b=10),
)

st.plotly_chart(fig, use_container_width=True)

st.subheader("거래량")

volume_fig = go.Figure()
volume_fig.add_trace(
    go.Bar(
        x=data.index,
        y=data["Volume"],
        name="거래량",
        hovertemplate="날짜: %{x}<br>거래량: %{y:,.0f}<extra></extra>",
    )
)
volume_fig.update_layout(
    xaxis_title="날짜",
    yaxis_title="거래량",
    margin=dict(l=10, r=10, t=20, b=10),
)
st.plotly_chart(volume_fig, use_container_width=True)

with st.expander("최근 10개 일봉 원본 데이터"):
    display_data = data.tail(10).reset_index()
    st.dataframe(display_data, use_container_width=True, hide_index=True)

    st.download_button(
        "원본 데이터 CSV 다운로드",
        data=display_data.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"eggfolio_{ticker}_daily.csv",
        mime="text/csv",
    )

st.caption(
    "데이터 제공처: Yahoo Finance 비공식 인터페이스(yfinance). "
    "데이터 제공 여부, 지연 시간 및 정확성은 제공처의 조건에 영향을 받습니다."
)
