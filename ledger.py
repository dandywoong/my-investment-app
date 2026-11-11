"""기록과 성적표: 자산 스냅샷, 입금 기록, AI 제안의 사후 성과 점검(백테스트의 기초 자료).

- 앱을 여는 날마다 포트폴리오 스냅샷이 자동으로 쌓인다.
- 확정한 AI 제안(날짜·종목·행동·금액·당시 가격)을 저장해 두었다가, 시간이 지나면 같은 기간 시장지수와 비교한다.
- 표본이 30개가 되기 전의 수치는 통계적 의미가 없으며 승률로 해석하면 안 된다.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import ai_agent

MIN_SAMPLE = 30
BENCH = {"미국": ("^GSPC", "S&P500"), "한국": ("^KS11", "KOSPI")}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(get_conn):
    for sql in (
        "CREATE TABLE IF NOT EXISTS portfolio_snapshots (snap_date TEXT PRIMARY KEY, total_krw BIGINT, cost_krw BIGINT, fx REAL, detail TEXT)",
        "CREATE TABLE IF NOT EXISTS rec_log (id SERIAL PRIMARY KEY, rec_date TEXT, strategy_id INT, ticker TEXT, name TEXT, market TEXT, action TEXT, amount_krw BIGINT, price REAL, currency TEXT)",
        "CREATE TABLE IF NOT EXISTS cash_events (id SERIAL PRIMARY KEY, event_date TEXT, amount_krw BIGINT, memo TEXT, created_at TEXT)",
    ):
        ai_agent._run(get_conn, sql)


def save_snapshot(get_conn, items, fx):
    """하루 한 번(앱을 여는 세션마다 한 번) 현재 평가금액·원가를 기록한다."""
    key = "_snap_" + date.today().isoformat()
    if st.session_state.get(key) or not items:
        return
    try:
        k = lambda i: fx if (i["cur"] == "USD" and fx) else 1.0
        total = sum((i.get("value") or 0) * k(i) for i in items)
        cost = sum((i.get("qty") or 0) * (i.get("avg") or 0) * k(i) for i in items)
        detail = {i["name"]: round((i.get("value") or 0) * k(i)) for i in items}
        ai_agent._run(get_conn, "INSERT INTO portfolio_snapshots (snap_date,total_krw,cost_krw,fx,detail) VALUES (%s,%s,%s,%s,%s) "
                                "ON CONFLICT (snap_date) DO UPDATE SET total_krw=EXCLUDED.total_krw, cost_krw=EXCLUDED.cost_krw, fx=EXCLUDED.fx, detail=EXCLUDED.detail",
                      (date.today().isoformat(), int(total), int(cost), float(fx or 0), json.dumps(detail, ensure_ascii=False)))
        st.session_state[key] = True
    except Exception:  # noqa: BLE001
        pass


def log_recs(get_conn, strategy_id, strategy, items, fx):
    by_tk = {i["tk"]: i for i in items}
    exists = ai_agent._run(get_conn, "SELECT 1 FROM rec_log WHERE strategy_id=%s LIMIT 1", (strategy_id,), fetch=True)
    if exists is not None and len(exists):
        return
    for p in strategy.get("priorities") or []:
        it = by_tk.get(p.get("_item"))
        if not it or p.get("action") == "AI 미언급":
            continue
        ai_agent._run(get_conn, "INSERT INTO rec_log (rec_date,strategy_id,ticker,name,market,action,amount_krw,price,currency) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (date.today().isoformat(), strategy_id, it["tk"], it["name"], it["mkt"], str(p.get("action")), int(p.get("amount_krw") or 0), float(it.get("price") or 0), it["cur"]))


def _close(get_prices, tk):
    try:
        df, _ = get_prices(tk, "5y")
        c = df["Close"].dropna()
        c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
        return c
    except Exception:  # noqa: BLE001
        return None


def _at(c, d):
    """날짜 d 이후 첫 거래일의 종가(없으면 None)."""
    try:
        s = c[c.index >= pd.Timestamp(d)]
        return None if s.empty else float(s.iloc[0])
    except Exception:  # noqa: BLE001
        return None


def render_ledger(get_conn, items, fx, get_prices):
    import plotly.graph_objects as go
    ensure_tables(get_conn)
    st.markdown("### 기록과 성적표")
    st.caption("내 투자의 날짜·금액·제안을 쌓아 두었다가, 시간이 지난 뒤 실제로 어땠는지 점검하는 곳입니다. 기록이 충분히 쌓이기 전의 수치는 참고만 하세요.")
    t1, t2, t3 = st.tabs(["자산 추이", "입금 기록 vs 시장", "AI 제안 성적표"])
    with t1:
        df = ai_agent._run(get_conn, "SELECT snap_date, total_krw, cost_krw FROM portfolio_snapshots ORDER BY snap_date", fetch=True)
        if df is None or len(df) < 2:
            st.info("스냅샷이 {}개 쌓였습니다. 앱을 여는 날마다 자동으로 기록되며, 2개 이상이면 추이가 그려집니다.".format(0 if df is None else len(df)))
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["snap_date"], y=df["total_krw"], name="평가금액", line=dict(color="#14213D", width=2)))
            fig.add_trace(go.Scatter(x=df["snap_date"], y=df["cost_krw"], name="투입 원가", line=dict(color="#B8B4A8", width=2, dash="dot")))
            fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.12), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            last = df.iloc[-1]
            st.caption("최근 기록 기준 평가손익 {:+,.0f}원 ({:+.1f}%). 환율 변동이 섞여 있습니다.".format(last["total_krw"] - last["cost_krw"], (last["total_krw"] / last["cost_krw"] - 1) * 100 if last["cost_krw"] else 0))
    with t2:
        with st.form("past_deposit"):
            c1, c2, c3 = st.columns([1, 1, 2])
            d_ = c1.date_input("입금 날짜", value=date.today(), key="pd_date")
            a_ = c2.number_input("금액 (원)", min_value=0, value=0, step=100000, key="pd_amt")
            m_ = c3.text_input("메모", key="pd_memo")
            if st.form_submit_button("과거·오늘 입금 기록 추가") and a_ > 0:
                ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (d_.isoformat(), int(a_), m_, _now()))
                st.rerun()
        ev = ai_agent._run(get_conn, "SELECT id, event_date, amount_krw, memo FROM cash_events ORDER BY event_date", fetch=True)
        if ev is None or ev.empty:
            st.info("입금 기록이 없습니다. 위에서 날짜와 금액을 추가하면, 같은 날 같은 금액을 시장 지수(VOO, KODEX200 대용으로 코스피)에 넣었다면 지금 얼마였을지 비교해 줍니다.")
        else:
            rows, tot_in = [], 0
            voo, ks, usd = _close(get_prices, "VOO"), _close(get_prices, "^KS11"), _close(get_prices, "KRW=X")
            v_now = None if voo is None else float(voo.iloc[-1])
            k_now = None if ks is None else float(ks.iloc[-1])
            u_now = fx or (None if usd is None else float(usd.iloc[-1]))
            val_v = val_k = 0.0
            ok_v = ok_k = True
            for _, r in ev.iterrows():
                amt = float(r["amount_krw"])
                tot_in += amt
                pv, pk, pu = (_at(voo, r["event_date"]) if voo is not None else None), (_at(ks, r["event_date"]) if ks is not None else None), (_at(usd, r["event_date"]) if usd is not None else None)
                vv = (amt / (pv * pu) * v_now * u_now) if (pv and pu and v_now and u_now) else None
                kk = (amt / pk * k_now) if (pk and k_now) else None
                ok_v, ok_k = ok_v and vv is not None, ok_k and kk is not None
                val_v += vv or 0
                val_k += kk or 0
                rows.append({"날짜": r["event_date"], "입금(원)": int(amt), "VOO에 넣었다면 지금(원)": None if vv is None else round(vv), "코스피 지수에 넣었다면 지금(원)": None if kk is None else round(kk), "메모": r["memo"]})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            m1, m2, m3 = st.columns(3)
            m1.metric("입금 합계", "{:,.0f}원".format(tot_in))
            m2.metric("VOO 대용", "-" if not ok_v else "{:,.0f}원".format(val_v), delta=None if not ok_v else "{:+.1f}%".format((val_v / tot_in - 1) * 100), delta_color="off")
            m3.metric("코스피 대용", "-" if not ok_k else "{:,.0f}원".format(val_k), delta=None if not ok_k else "{:+.1f}%".format((val_k / tot_in - 1) * 100), delta_color="off")
            st.caption("같은 입금을 지수 하나에 전부 넣었다고 가정한 단순 비교입니다. 내 실제 포트폴리오의 같은 기간 성과와 비교해 보세요(환율·배당·수수료·세금 제외).")
    with t3:
        rl = ai_agent._run(get_conn, "SELECT rec_date, ticker, name, market, action, amount_krw, price FROM rec_log ORDER BY rec_date DESC, id", fetch=True)
        if rl is None or rl.empty:
            st.info("확정한 AI 제안이 아직 없습니다. AI 투자 에이전트에서 '이 계획을 확정하고 기록하기'를 누르면 그날의 제안이 가격과 함께 저장되고, 시간이 지나면 여기에 성과가 나옵니다.")
            return
        cache, out = {}, []
        for _, r in rl.iterrows():
            row = {"제안일": r["rec_date"], "종목": r["name"], "행동": r["action"], "금액(원)": int(r["amount_krw"] or 0), "제안가": r["price"]}
            bm = BENCH.get(r["market"], BENCH["미국"])
            for tk in (r["ticker"], bm[0]):
                if tk not in cache:
                    cache[tk] = _close(get_prices, tk)
            c, b = cache[r["ticker"]], cache[bm[0]]
            for n in (5, 20, 60):
                tgt = datetime.fromisoformat(r["rec_date"]) + timedelta(days=n)
                if tgt.date() > date.today() or c is None or b is None:
                    row["{}일 후".format(n)] = row["{}일 후 시장 대비".format(n)] = None
                    continue
                p0, p1, b0, b1 = _at(c, r["rec_date"]), _at(c, tgt), _at(b, r["rec_date"]), _at(b, tgt)
                if p0 and p1 and b0 and b1:
                    row["{}일 후".format(n)] = (p1 / p0 - 1) * 100
                    row["{}일 후 시장 대비".format(n)] = ((p1 / p0) - (b1 / b0)) * 100
                else:
                    row["{}일 후".format(n)] = row["{}일 후 시장 대비".format(n)] = None
            out.append(row)
        res = pd.DataFrame(out)
        st.dataframe(res, use_container_width=True, hide_index=True,
                     column_config={k: st.column_config.NumberColumn(k, format="%+.1f%%") for k in res.columns if "일 후" in k})
        done = res.dropna(subset=["20일 후 시장 대비"]) if "20일 후 시장 대비" in res else res.iloc[0:0]
        n_done = len(done)
        if n_done:
            buy = done[done["행동"] == "매수"]
            avoid = done[done["행동"].isin(["보류", "정리검토"])]
            a1, a2, a3 = st.columns(3)
            a1.metric("20일이 지난 제안 수", "{}개".format(n_done))
            a2.metric("매수 제안: 시장 초과 평균", "-" if buy.empty else "{:+.1f}%p".format(buy["20일 후 시장 대비"].mean()), delta="{}건".format(len(buy)), delta_color="off")
            a3.metric("보류·정리 제안: 시장 초과 평균", "-" if avoid.empty else "{:+.1f}%p".format(avoid["20일 후 시장 대비"].mean()), delta="{}건 (낮을수록 잘 피함)".format(len(avoid)), delta_color="off")
        st.caption("표본이 {}개가 되기 전에는 통계적 의미가 없고 승률로 읽으면 안 됩니다(현재 20일 경과 {}개). 같은 날 제안들은 서로 독립이 아니며, 과거 성과가 앞으로를 보장하지 않습니다.".format(MIN_SAMPLE, n_done))
