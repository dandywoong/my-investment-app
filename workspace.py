"""종목 보드(우선순위 표) + 종목을 누르면 펼쳐지는 요약, 손실 종목 회복 점검."""
import pandas as pd
import streamlit as st

import recovery
import signals

KIND_TEXT = {"sell": "익절·축소 검토", "buy": "분할 매수 후보", "stop": "재검증", "wait": "대기", "hold": "보유"}


def _yf(tk):
    t = str(tk).strip().upper()
    if t in ("BRKB", "BRK B"):
        return "BRK-B"
    return t if t.endswith((".KS", ".KQ")) else t.replace(".", "-")


def krw_value(it, fx):
    return (it.get("value") or 0) * (fx if it["cur"] == "USD" else 1.0)


def _pct(v):
    return "-" if v is None else "{:+.1f}%".format(v * 100)


def render_recovery_overview(items, fx):
    """손실 종목마다: 평단까지 필요한 상승 vs 전문가 평균 목표가 상승여력."""
    import plotly.graph_objects as go
    loss = [i for i in items if i.get("ret") is not None and i["ret"] < 0 and i.get("price")]
    if not loss:
        return {}
    res = {}
    with st.spinner("손실 종목의 전문가 목표가를 확인하는 중... (6시간마다 갱신)"):
        for i in loss:
            res[i["name"]] = recovery.assess(i, recovery.consensus(_yf(i["tk"])), i.get("target"))
    rows = [r for r in res.values() if r]
    if not rows:
        return res
    rows.sort(key=lambda r: r["평단까지 필요한 상승"], reverse=True)
    st.markdown("### 손실 종목 회복 점검")
    st.caption("막대 비교: 평단까지 필요한 상승률 대 전문가 평균 목표가까지의 여력. 목표가가 평단보다 위일수록 본전 회복 근거가 큽니다. 예측이 아니며 목표가는 야후 집계(지연·누락 가능)입니다.")
    names = [r["종목"] for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="평단까지 필요한 상승", x=names, y=[r["평단까지 필요한 상승"] * 100 for r in rows], marker_color="#B42318"))
    fig.add_trace(go.Bar(name="평균 목표가까지 여력", x=names, y=[(r["여력"] * 100 if r["여력"] is not None else 0) for r in rows], marker_color="#0F766E",
                         text=[("자료 없음" if r["여력"] is None else "{:+.0f}%".format(r["여력"] * 100)) for r in rows], textposition="outside"))
    fig.update_layout(barmode="group", height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(ticksuffix="%"), legend=dict(orientation="h", y=1.12),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    return res


def render_board(items, fx, P):
    """우선순위 보드. 행을 누르면 그 종목이 반환된다."""
    today = {}
    for b in (P or {}).get("board", []) or []:
        today[b.get("종목")] = b.get("오늘 행동", "")
    total = sum(krw_value(i, fx) for i in items) or 1.0
    order = sorted(items, key=lambda i: -(i["score"]["total"] if i.get("score") else -99))
    rows = []
    for n, i in enumerate(order, 1):
        sc = i.get("score")
        rows.append({"순위": n, "종목": i["name"], "시장": i["mkt"], "오늘": today.get(i["name"], ""), "판단": KIND_TEXT.get(i["kind"], i["kind"]),
                     "점수": None if not sc else round(sc["total"], 1), "비중": krw_value(i, fx) / total * 100,
                     "평단 대비": None if i.get("ret") is None else i["ret"] * 100, "달걀 국면": i["plabel"], "기업 상태": i["sv_txt"]})
    df = pd.DataFrame(rows)
    st.markdown("### 종목 보드")
    st.caption("점수가 높은 순서입니다. 행을 누르면 아래에 그 종목의 비중, 국면, AI 분석, 회복 점검이 펼쳐집니다. 점수는 검증 전 규칙입니다.")
    ev = st.dataframe(df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="board_sel",
                      column_config={"비중": st.column_config.ProgressColumn("비중", format="%.1f%%", min_value=0, max_value=max(40.0, float(df["비중"].max()))),
                                     "평단 대비": st.column_config.NumberColumn("평단 대비", format="%+.1f%%"),
                                     "점수": st.column_config.NumberColumn("점수", format="%.1f")})
    sel = None
    try:
        r = ev.selection.rows
        if r:
            sel = order[r[0]]
            st.session_state["_board_tk"] = sel["tk"]
    except Exception:  # noqa: BLE001
        sel = None
    if sel is None:
        keep = st.session_state.get("_board_tk")
        sel = next((i for i in order if i["tk"] == keep), order[0])
    return sel


def render_summary(it, items, fx, risk, rec):
    """선택 종목 한 화면 요약."""
    import plotly.graph_objects as go
    sym = "$" if it["cur"] == "USD" else ""
    total = sum(krw_value(i, fx) for i in items) or 1.0
    my_w = krw_value(it, fx) / total
    c1, c2 = st.columns([1, 2])
    with c1:
        names = [i["name"] for i in items]
        fig = go.Figure(go.Pie(labels=names, values=[krw_value(i, fx) for i in items], hole=0.62, textinfo="none",
                               pull=[0.12 if i["tk"] == it["tk"] else 0 for i in items], sort=False))
        fig.update_layout(height=230, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                          annotations=[dict(text="{:.1%}".format(my_w), x=0.5, y=0.5, showarrow=False, font=dict(size=22))])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("{} 비중 (원화 환산 전체 기준)".format(it["name"]))
    with c2:
        st.markdown("#### {} · {}".format(it["name"], it["label"]))
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("현재가", "-" if it["price"] is None else "{}{:,.2f}".format(sym, it["price"]) if it["cur"] == "USD" else "{:,.0f}원".format(it["price"]),
                  delta=("≈{:,.0f}원".format(it["price"] * fx) if (it["cur"] == "USD" and it["price"] and fx) else None), delta_color="off")
        m2.metric("평단 대비", _pct(it.get("ret")))
        m3.metric("종합 점수", "-" if not it.get("score") else "{:.1f}".format(it["score"]["total"]), delta=None if not it.get("score") else signals.grade(it["score"]["total"]), delta_color="off")
        m4.metric("달걀 국면", it["plabel"])
        for w in it["why"][:4]:
            st.write("· " + w)
        sc = it.get("score")
        if sc and sc.get("gate"):
            st.caption("매수 제외 사유: " + sc["gate"])
    sc = it.get("score")
    if sc:
        parts = list(sc["parts"].items())
        fb = go.Figure(go.Bar(y=[k for k, _ in parts], x=[v[0] for _, v in parts], orientation="h",
                              marker_color=["#0F766E" if v[0] >= 0 else "#B42318" for _, v in parts],
                              text=["{:+.1f}".format(v[0]) for _, v in parts], textposition="outside"))
        fb.update_layout(title=dict(text="점수 구성 (왜 이 순위인지)", font=dict(size=14)), height=240, margin=dict(l=0, r=30, t=34, b=0),
                         xaxis=dict(zeroline=True, showgrid=False), yaxis=dict(autorange="reversed"), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fb, use_container_width=True, config={"displayModeBar": False})
        with st.expander("점수 근거 자세히"):
            for k, (pt, why) in parts:
                st.markdown("**{} ({:+.1f})**".format(k, pt))
                for w_ in why or ["해당 없음"]:
                    st.caption("· " + w_)
    r = (rec or {}).get(it["name"])
    if r:
        st.markdown("#### 손실 회복 점검")
        a, b, c, d = st.columns(4)
        a.metric("평단까지 필요한 상승", _pct(r["평단까지 필요한 상승"]))
        a2 = r["목표가(평균)"]
        b.metric("전문가 평균 목표가", "자료 없음" if a2 is None else ("${:,.2f}".format(a2) if it["cur"] == "USD" else "{:,.0f}원".format(a2)),
                 delta=None if r["여력"] is None else "현재가 대비 {:+.0f}%".format(r["여력"] * 100), delta_color="off")
        if r["범위"]:
            lo, hi = r["범위"]
            c.metric("목표가 범위", "{:,.0f} ~ {:,.0f}".format(lo, hi))
        if it.get("target"):
            d.metric("AI 검색 분석 목표가", "{:,.2f}".format(it["target"]))
        st.write("**" + r["판정"] + "**")
        st.caption("{} · 예측이나 수익 보장이 아닙니다. 목표가는 수시로 바뀌므로 6시간마다 다시 가져옵니다.".format(r["출처"] or "출처 없음"))
