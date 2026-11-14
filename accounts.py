"""계좌별 현황: 국내 종목 = ISA 계좌, 미국 종목 = 일반 계좌. 평가금액·투자원금·평가손익·수익률을 계좌별로, 그리고 합산으로 보여준다.
평가손익은 '평단 × 수량'을 원금으로 한 단순 계산이며 환차손익(미국주 평단의 환율)은 반영하지 않고 현재 환율로 환산한다."""
import pandas as pd
import streamlit as st

NAVY, TEAL, RED, BLUE = "#14213D", "#0F766E", "#B42318", "#1D4ED8"


def _krw(i, fx):
    k = fx if i["cur"] == "USD" else 1.0
    val = (i.get("value") or 0) * k
    cost = (i.get("avg") or 0) * (i.get("qty") or 0) * k
    return val, cost


def table(items, fx):
    rows = []
    for i in items:
        val, cost = _krw(i, fx)
        rows.append({"계좌": "ISA(국내)" if i["cur"] == "KRW" else "일반(미국)", "종목": i["name"], "수량": round(i["qty"], 4), "평단": i["avg"], "현재가": i["price"], "통화": i["cur"],
                     "평가금액(원)": val, "투자원금(원)": cost, "평가손익(원)": val - cost, "수익률(%)": ((val / cost - 1) * 100) if cost else None})
    return pd.DataFrame(rows)


def render(items, fx):
    import plotly.graph_objects as go
    df = table(items, fx)
    if df.empty:
        return
    st.markdown("#### 계좌별 현황 · 평가손익")
    st.caption("국내 종목은 ISA 계좌, 미국 종목은 일반 계좌로 묶었습니다. 평가손익 = 평가금액 − (평단 × 수량). 미국 종목은 오늘 환율({:,.0f}원)로 환산한 값이며 환율 변화에 따른 손익은 따로 분리하지 않았습니다.".format(fx or 0))
    groups = [("합계", df), ("ISA(국내)", df[df["계좌"] == "ISA(국내)"]), ("일반(미국)", df[df["계좌"] == "일반(미국)"])]
    cols = st.columns(3)
    for c, (nm, g) in zip(cols, groups):
        val, cost = g["평가금액(원)"].sum(), g["투자원금(원)"].sum()
        pl = val - cost
        with c:
            st.markdown("**{}**".format(nm))
            st.metric("평가금액", "{:,.0f}원".format(val))
            st.metric("평가손익", "{:+,.0f}원".format(pl), "{:+.1f}%".format(pl / cost * 100) if cost else None)
            st.caption("투자원금 {:,.0f}원 · {}종목".format(cost, len(g)))
    p1, p2, p3 = st.columns(3)
    for c, (nm, g) in zip((p1, p2, p3), groups):
        if g.empty or g["평가금액(원)"].sum() <= 0:
            continue
        fig = go.Figure(go.Pie(labels=g["종목"], values=g["평가금액(원)"], hole=0.5, textinfo="percent", sort=True))
        fig.update_layout(height=250, margin=dict(l=0, r=0, t=24, b=0), title=dict(text=nm + " 비중", font=dict(size=13)), showlegend=True, legend=dict(font=dict(size=10)), paper_bgcolor="rgba(0,0,0,0)")
        c.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    d2 = df.sort_values("평가손익(원)")
    fig = go.Figure(go.Bar(x=d2["평가손익(원)"], y=d2["종목"] + " (" + d2["계좌"].str[:3] + ")", orientation="h", marker_color=[RED if v < 0 else TEAL for v in d2["평가손익(원)"]],
                           text=[("{:+,.0f}원 ({:+.0f}%)".format(a, b) if pd.notna(b) else "{:+,.0f}원".format(a)) for a, b in zip(d2["평가손익(원)"], d2["수익률(%)"])], textposition="auto"))
    fig.update_layout(height=max(260, 26 * len(d2)), margin=dict(l=0, r=0, t=8, b=0), xaxis_title="평가손익(원)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with st.expander("종목별 평가손익 표"):
        show = df.copy()
        st.dataframe(show, use_container_width=True, hide_index=True, column_config={
            "평가금액(원)": st.column_config.NumberColumn(format="%d"), "투자원금(원)": st.column_config.NumberColumn(format="%d"),
            "평가손익(원)": st.column_config.NumberColumn(format="%+d"), "수익률(%)": st.column_config.NumberColumn(format="%+.1f%%")})
