"""내 자산 한눈에: 현금(CMA 원화 · 일반계좌 달러)과 계좌별 보유를 한 화면에 모으고, 입금·환전을 여기서 바로 기록한다.

원칙: 돈의 움직임은 모두 fx_events 한 줄 원장에 쌓인다(입금 → CMA 원화, 환전 → 원화 감소 + 달러 증가, 매매 → 해당 통화 감소/증가).
이 화면, 에이전트 화면, 매매 기록 화면은 같은 원장을 읽으므로 숫자가 어긋나지 않는다.
"""
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent
import fx as fxmod


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ins(get_conn, d, kind, krw, usd, rate, memo):
    ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (_now(), d.isoformat(), kind, float(krw), float(usd), rate, memo))


def ledger_df(get_conn, n=30):
    try:
        df = ai_agent._run(get_conn, "SELECT id, event_date, kind, krw_delta, usd_delta, rate, memo FROM fx_events ORDER BY id DESC LIMIT %s", (int(n),), fetch=True)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


def ledger_for_agent(get_conn, n=25):
    """에이전트·채팅에 넘길 최근 돈 기록(사람이 읽는 말로)."""
    df = ledger_df(get_conn, n)
    out = []
    for _, r in df.iterrows():
        out.append({"date": str(r["event_date"])[:10], "what": fxmod.KINDS.get(r["kind"], r["kind"]), "krw": round(float(r["krw_delta"] or 0)), "usd": round(float(r["usd_delta"] or 0), 2),
                    "rate": None if r["rate"] is None or pd.isna(r["rate"]) else round(float(r["rate"]), 1), "memo": r["memo"]})
    return out


def account_summary(items, fx):
    """계좌별 보유 요약(에이전트용): 원가·평가·손익·종목 수."""
    out = {}
    for nm, cur in (("ISA(국내, 원)", "KRW"), ("일반(미국, 달러)", "USD")):
        g = [i for i in items if i["cur"] == cur]
        k = fx if cur == "USD" else 1.0
        cost = sum((i.get("qty") or 0) * (i.get("avg") or 0) * k for i in g)
        val = sum((i.get("value") or 0) * k for i in g)
        out[nm] = {"n": len(g), "cost_krw": round(cost), "value_krw": round(val), "pl_krw": round(val - cost)}
    return out


def render(get_conn, items, fx):
    fxmod.ensure_tables(get_conn)
    cma, usd = fxmod.balances(get_conn)[:2]
    st.markdown("### 내 자산 한눈에")
    st.caption("돈(현금)과 보유 종목이 계좌별로 한곳에 모여 있습니다. 입금·환전·매매를 기록하면 이 숫자가 바로 바뀌고, 에이전트(펀드매니저)도 같은 숫자를 읽습니다.")
    flash = st.session_state.pop("_asset_flash", None)
    if flash:
        st.success(flash)
    if usd < -0.005 or cma < -0.5:
        st.error("잔액이 마이너스입니다. 기록이 어긋난 상태입니다. 아래 '잔액 맞추기'로 증권사 앱 숫자에 맞춰 주세요.")
    a, b = st.columns(2)
    isa = [i for i in items if i["cur"] == "KRW"]
    us = [i for i in items if i["cur"] == "USD"]
    with a:
        st.markdown("**ISA (국내 · 원화)**")
        st.metric("원화 예수금 (CMA)", "{:,.0f}원".format(cma))
        v = sum((i.get("value") or 0) for i in isa)
        c = sum((i.get("qty") or 0) * (i.get("avg") or 0) for i in isa)
        st.caption("보유 평가 {:,.0f}원 · 투자원금 {:,.0f}원 · 현금 포함 합계 {:,.0f}원".format(v, c, v + max(cma, 0)))
        if isa:
            st.dataframe(pd.DataFrame([{"종목": i["name"], "수량": round(i["qty"], 4), "평단(원)": round(i["avg"]), "현재가(원)": None if i["price"] is None else round(i["price"]),
                                        "평가(원)": round(i.get("value") or 0)} for i in isa]), use_container_width=True, hide_index=True)
    with b:
        st.markdown("**일반 (미국 · 달러)**")
        st.metric("달러 예수금", "${:,.2f}".format(usd), "{:,.0f}원 상당(오늘 환율)".format(usd * fx) if fx else None, delta_color="off")
        v = sum((i.get("value") or 0) for i in us)
        c = sum((i.get("qty") or 0) * (i.get("avg") or 0) for i in us)
        st.caption("보유 평가 ${:,.2f} · 투자원금 ${:,.2f} · 현금 포함 합계 ${:,.2f}".format(v, c, v + max(usd, 0)))
        if us:
            st.dataframe(pd.DataFrame([{"종목": i["name"], "수량": round(i["qty"], 4), "평단($)": round(i["avg"], 2), "현재가($)": None if i["price"] is None else round(i["price"], 2),
                                        "평가($)": round(i.get("value") or 0, 2)} for i in us]), use_container_width=True, hide_index=True)
    with st.expander("돈 넣기 · 환전하기 · 잔액 맞추기 (여기서 기록)"):
        t1, t2, t3 = st.tabs(["입금 (원화 → CMA)", "환전 (원 → 달러)", "잔액 맞추기"])
        with t1:
            with st.form("as_dep", clear_on_submit=True):
                d1, d2 = st.columns(2)
                dd = d1.date_input("입금 날짜", value=date.today(), key="as_dep_d")
                da = d2.number_input("입금액 (원)", min_value=0, value=0, step=100000, key="as_dep_a")
                if st.form_submit_button("입금 기록") and da > 0:
                    _ins(get_conn, dd, "deposit", da, 0, None, "입금")
                    try:
                        ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (dd.isoformat(), int(da), "", _now()))
                    except Exception:  # noqa: BLE001
                        pass
                    st.session_state["_asset_flash"] = "입금 {:,.0f}원을 CMA에 기록했습니다.".format(da)
                    st.rerun()
        with t2:
            st.caption("증권사에서 실제로 환전한 결과를 넣으세요: 쓴 원화와 받은 달러. 환율은 자동 계산됩니다. 원화는 CMA에서 빠지고 달러는 일반계좌 달러 예수금으로 들어갑니다.")
            with st.form("as_fx", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                fd = f1.date_input("환전 날짜", value=date.today(), key="as_fx_d")
                fk = f2.number_input("쓴 원화 (원)", min_value=0, value=0, step=10000, key="as_fx_k")
                fu = f3.number_input("받은 달러 ($)", min_value=0.0, value=0.0, step=1.0, key="as_fx_u")
                if st.form_submit_button("환전 기록") and fk > 0 and fu > 0:
                    if fk > cma + 0.5:
                        st.error("CMA 원화 잔액({:,.0f}원)보다 많이 환전할 수 없습니다. 먼저 입금을 기록하거나 잔액을 맞추세요.".format(cma))
                    else:
                        _ins(get_conn, fd, "fx_done", -fk, fu, fk / fu, "환전(직접 기록)")
                        st.session_state["_asset_flash"] = "환전 기록: {:,.0f}원 → ${:,.2f} (환율 {:,.1f}원).".format(fk, fu, fk / fu)
                        st.rerun()
        with t3:
            st.caption("증권사 앱에 보이는 실제 잔액을 그대로 넣으세요. 지금 기록과의 차이만큼 한 줄이 추가됩니다.")
            with st.form("as_adj"):
                j1, j2 = st.columns(2)
                wk = j1.number_input("CMA 원화 잔액", min_value=0.0, value=float(max(0, round(cma))), step=10000.0, key="as_adj_k")
                wu = j2.number_input("달러 예수금 ($)", min_value=0.0, value=float(max(0.0, round(usd, 2))), step=1.0, key="as_adj_u")
                if st.form_submit_button("이 값으로 맞추기"):
                    _ins(get_conn, date.today(), "adjust", wk - cma, wu - usd, None, "잔액 맞추기")
                    st.session_state["_asset_flash"] = "잔액을 CMA {:,.0f}원 · ${:,.2f}로 맞췄습니다.".format(wk, wu)
                    st.rerun()
    with st.expander("돈 기록 내역 (원장 — 최근 30건)"):
        df = ledger_df(get_conn, 30)
        if df is None or df.empty:
            st.caption("아직 기록이 없습니다.")
        else:
            show = pd.DataFrame({"날짜": df["event_date"].astype(str).str[:10], "내용": df["kind"].map(lambda k: fxmod.KINDS.get(k, k)), "원화 증감": df["krw_delta"].round(0),
                                 "달러 증감($)": df["usd_delta"].round(2), "환율": df["rate"].round(1), "메모": df["memo"]})
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption("입금은 CMA 원화에, 환전은 원화 감소+달러 증가로, 매매는 해당 통화 예수금 증감으로 쌓입니다. 잔액 = 이 줄들의 합계입니다.")
