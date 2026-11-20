"""매매 일지 — 내가 실제로 한 매매와 그때 적은 이유를 쌓고, 에이전트가 읽는 복기 요약을 만든다.

- 한 번의 저장으로: 보유 수량·평단 + (선택) 예수금 + 일지 + (계획이 있었다면) 제안 성과 기록의 체결가까지 함께 바뀐다.
- 에이전트는 '학습'하는 것이 아니라 이 기록의 요약(summarize)을 매번 읽고 판단에 반영한다. 표본이 30건 미만이면 관찰일 뿐 결론이 아니다.
"""
import json
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent
import fx as fxmod
import ledger

_ONCE = {"done": False}
FOLLOW = ["계획대로 (에이전트·GPT 계획)", "계획과 다르게 (내 판단)", "계획 없었음"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(get_conn):
    if _ONCE["done"]:
        return
    try:
        ai_agent._run(get_conn, "CREATE TABLE IF NOT EXISTS trade_journal (id SERIAL PRIMARY KEY, created_at TEXT, trade_date TEXT, ticker TEXT, name TEXT, market TEXT, "
                                "side TEXT, qty DOUBLE PRECISION, price DOUBLE PRECISION, currency TEXT, reason TEXT, followed TEXT, strategy_id BIGINT, source TEXT)")
    except Exception:  # noqa: BLE001
        pass
    _ONCE["done"] = True


def add(get_conn, trade_date, tk, name, market, side, qty, price, cur, reason, followed, strategy_id=None, source="직접 입력"):
    ensure_tables(get_conn)
    ai_agent._run(get_conn, "INSERT INTO trade_journal (created_at,trade_date,ticker,name,market,side,qty,price,currency,reason,followed,strategy_id,source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (_now(), str(trade_date), tk, name, market, side, float(qty), float(price), cur, (reason or "").strip(), followed, strategy_id, source))


def load(get_conn, n=200):
    ensure_tables(get_conn)
    try:
        return ai_agent._run(get_conn, "SELECT * FROM trade_journal ORDER BY id DESC LIMIT %s", (int(n),), fetch=True)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def _cash_effect(get_conn, side, cur, qty, price, name):
    """예수금 반영. 잔액이 모자라 마이너스가 되면 반영하지 않고 이유를 돌려준다. -> (반영했는가, 메시지)"""
    amt = float(qty) * float(price)
    cma, usd = fxmod.balances(get_conn)[:2]
    now, today = _now(), date.today().isoformat()

    def ev(kind, k, u, memo):
        ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (now, today, kind, k, u, None, memo))
    if cur == "USD":
        if side == "매수":
            if amt > usd + 0.01:
                return False, "달러 예수금(${:,.2f})이 매수액(${:,.2f})보다 적어 예수금에는 반영하지 않았습니다(내 돈에서 '잔액 맞추기' 후 확인).".format(usd, amt)
            ev("usd_buy", 0, -min(amt, max(usd, 0)), "{} 매수".format(name))
        else:
            ev("usd_in", 0, amt, "{} 매도".format(name))
    else:
        if side == "매수":
            if amt > cma + 0.5:
                return False, "원화 예수금({:,.0f}원)이 매수액({:,.0f}원)보다 적어 예수금에는 반영하지 않았습니다.".format(cma, amt)
            ev("kr_buy", -amt, 0, "{} 매수".format(name))
        else:
            ev("kr_sell", amt, 0, "{} 매도".format(name))
    return True, ""


def record_trade(get_conn, apply_trade, ch, side, qty, price, trade_date, reason, followed, to_holdings=True, to_cash=True, strategy_id=None, source="직접 입력"):
    """매매 한 건을 모두 반영한다. -> (성공, 메시지)"""
    if qty <= 0 or price <= 0:
        return False, "수량과 체결 단가를 0보다 크게 입력하세요."
    msgs = []
    if to_holdings:
        ok, m = apply_trade(get_conn, ch, side, qty, price)
        if not ok:
            return False, m
        msgs.append(m)
    if to_cash:
        ok, m = _cash_effect(get_conn, side, ch["cur"], qty, price, ch["name"])
        msgs.append("예수금 반영 완료" if ok else m)
    sid = strategy_id
    if followed == FOLLOW[0] and side == "매수" and sid is None:
        try:
            import strategist as S
            _sid, _status, _st, _c = S.load_latest(get_conn)
            if _sid and _status in ("confirmed", "filled"):
                sid = _sid
        except Exception:  # noqa: BLE001
            pass
    if sid and side == "매수":
        try:
            ledger.record_fill(get_conn, sid, ch["tk"], qty, price)
        except Exception:  # noqa: BLE001
            pass
    add(get_conn, trade_date, ch["tk"], ch["name"], ch["mkt"], side, qty, price, ch["cur"], reason, followed, sid, source)
    return True, " · ".join(x for x in msgs if x)


def render_entry(get_conn, choices, apply_trade, kp="te_"):
    """내 포트폴리오 탭 맨 위의 '매매 기록' 양식. choices = [{tk,name,mkt,cur,price,qty,...}]"""
    st.markdown("#### 매매 기록 (체결된 것만)")
    st.caption("증권사에서 체결된 매매를 한 번에 저장합니다. 보유 수량·평단, 예수금, 일지가 같이 바뀌고, 적어 둔 이유는 에이전트가 읽고 복기합니다. 계획 단계(주문 전)는 기록하지 마세요.")
    flash = st.session_state.pop("_trade_flash", None)
    if flash:
        st.success(flash)
    labels = ["{} ({})".format(c["name"], "미국" if c["cur"] == "USD" else "국내") + (" · 보유 중 {:g}주".format(round(c["qty"], 4)) if c.get("qty") else " · 신규") for c in choices]
    with st.form("trade_entry_form" + kp, clear_on_submit=True):
        r1 = st.columns([3, 1.3, 1.5])
        pick = r1[0].selectbox("종목", range(len(choices)), format_func=lambda i: labels[i], key=kp + "pick")
        side = r1[1].radio("구분", ["매수", "매도"], horizontal=True, key=kp + "side")
        tdate = r1[2].date_input("체결 날짜", value=date.today(), key=kp + "date")
        r2 = st.columns(3)
        qty = r2[0].number_input("체결 수량", min_value=0.0, value=0.0, step=0.0001, format="%.4f", key=kp + "qty")
        price = r2[1].number_input("체결 단가 (국내 원 / 미국 $)", min_value=0.0, value=0.0, step=0.01, key=kp + "price")
        followed = r2[2].selectbox("계획 대비", FOLLOW, key=kp + "follow")
        reason = st.text_input("이유 (한 줄이면 충분합니다. 예: 급락으로 분할 1차 / 과열이라 일부 정리 / 계획된 적립)", key=kp + "reason")
        c1, c2 = st.columns(2)
        to_h = c1.checkbox("보유 수량·평단에 반영", value=True, key=kp + "h")
        to_c = c2.checkbox("예수금에도 반영", value=True, key=kp + "c")
        ok = st.form_submit_button("매매 기록 저장", type="primary")
    if ok:
        ch = choices[int(pick)]
        good, msg = record_trade(get_conn, apply_trade, ch, side, qty, price, tdate, reason, followed, to_h, to_c)
        if good:
            st.session_state["_trade_flash"] = "저장했습니다 — {} {} {:g} @ {:,.2f}. {}".format(ch["name"], side, qty, price, msg)
            st.rerun()
        else:
            st.error(msg)
    df = load(get_conn, 8)
    if df is not None and len(df):
        with st.expander("최근 매매 기록 {}건".format(len(df))):
            show = df[["trade_date", "name", "side", "qty", "price", "currency", "reason", "followed", "source"]].rename(columns={"trade_date": "날짜", "name": "종목", "side": "구분", "qty": "수량", "price": "단가", "currency": "통화", "reason": "이유", "followed": "계획 대비", "source": "입력"})
            st.dataframe(show, use_container_width=True, hide_index=True)
    render_delete(get_conn, kp)


def render_delete(get_conn, kp="te_"):
    """잘못 기록한 매매 일지 줄 수정·삭제(일지·복기 자료에서만 바뀐다)."""
    df = load(get_conn, 30)
    if df is None or not len(df):
        return
    with st.expander("매매 기록 수정 · 삭제 (잘못 입력했거나 테스트로 넣은 줄)"):
        st.caption("날짜·수량·단가·이유·계획 대비를 직접 고치고 '수정 저장', 지울 줄은 '삭제'에 체크하세요. 일지(복기 자료)만 바뀝니다. 이미 반영된 보유 수량·평단·예수금은 자동으로 되돌아가지 않으므로, 보유는 '내 포트폴리오 탭 → 미국주/국내 보유 수정'에서, 돈은 위 '돈 기록 내역'에서 같이 고쳐 주세요.")
        base = pd.DataFrame({"삭제": False, "번호": df["id"].astype(int), "종목": df["name"], "구분": df["side"], "날짜": df["trade_date"].astype(str).str[:10], "수량": df["qty"].astype(float),
                             "단가": df["price"].astype(float), "계획 대비": df["followed"].fillna(FOLLOW[2]), "이유": df["reason"].fillna("")})
        out = st.data_editor(base, hide_index=True, use_container_width=True, key=kp + "jd_ed", disabled=["번호", "종목", "구분"],
                             column_config={"삭제": st.column_config.CheckboxColumn("삭제", default=False), "계획 대비": st.column_config.SelectboxColumn("계획 대비", options=FOLLOW)})
        edits = []
        for k_ in range(len(base)):
            a, b = base.iloc[k_], out.iloc[k_]
            if bool(b["삭제"]):
                continue
            if any(str(a[c]) != str(b[c]) for c in ("날짜", "수량", "단가", "계획 대비", "이유")):
                edits.append((str(b["날짜"])[:10], float(b["수량"]), float(b["단가"]), str(b["계획 대비"]), str(b["이유"] or ""), int(b["번호"])))
        if edits and st.button("수정 저장 ({}줄)".format(len(edits)), key=kp + "jd_save", type="primary"):
            for e_ in edits:
                ai_agent._run(get_conn, "UPDATE trade_journal SET trade_date=%s, qty=%s, price=%s, followed=%s, reason=%s WHERE id=%s", e_)
            st.session_state["_trade_flash"] = "{}줄을 수정했습니다(일지만).".format(len(edits))
            st.rerun()
        pick = out[out["삭제"] == True]  # noqa: E712
        if len(pick):
            st.warning("일지(복기 자료)에서만 지워집니다. 보유 수량·평단·예수금은 그대로입니다.")
            ok = st.checkbox("{}줄을 삭제합니다".format(len(pick)), key=kp + "jd_ok")
            if st.button("선택한 매매 기록 삭제", key=kp + "jd_del", disabled=not ok):
                for i_ in pick["번호"].tolist():
                    ai_agent._run(get_conn, "DELETE FROM trade_journal WHERE id=%s", (int(i_),))
                st.session_state["_trade_flash"] = "{}줄을 삭제했습니다.".format(len(pick))
                st.rerun()


def summarize(get_conn, get_prices, min_days=10):
    """에이전트에게 돌려줄 매매 복기 요약. -> dict | None"""
    df = load(get_conn, 400)
    if df is None or df.empty:
        return {"n_trades": 0, "note": "아직 기록된 매매 없음"}
    cache = {}
    rows = []
    for _, r in df.iloc[::-1].iterrows():
        try:
            age = (date.today() - datetime.fromisoformat(str(r["trade_date"])[:10]).date()).days
        except Exception:  # noqa: BLE001
            continue
        res = {"date": str(r["trade_date"])[:10], "name": r["name"], "side": r["side"], "price": round(float(r["price"]), 2), "reason": str(r["reason"] or "")[:200], "followed": r["followed"], "days": age}
        if get_prices is not None and age >= 1:
            tk, mk = r["ticker"], r["market"]
            bm = ledger.BENCH.get(mk, ledger.BENCH["미국"])[0]
            for t_ in (tk, bm):
                if t_ not in cache:
                    cache[t_] = ledger._close(get_prices, t_)
            c, b = cache.get(tk), cache.get(bm)
            if c is not None and len(c) and float(r["price"]) > 0:
                p1 = float(c.iloc[-1])
                move = (p1 / float(r["price"]) - 1) * 100
                res["since_trade_pct"] = round(move, 1)
                b0 = ledger._at(b, str(r["trade_date"])[:10]) if b is not None else None
                if b0:
                    res["market_since_pct"] = round((float(b.iloc[-1]) / b0 - 1) * 100, 1)
        rows.append(res)
    ev = [x for x in rows if x["days"] >= min_days and "since_trade_pct" in x]
    buys = [x for x in ev if x["side"] == "매수"]
    sells = [x for x in ev if x["side"] == "매도"]
    out = {"n_trades": len(rows), "n_buys": sum(1 for x in rows if x["side"] == "매수"), "n_sells": sum(1 for x in rows if x["side"] == "매도"),
           "n_evaluable(10일 이상 경과)": len(ev), "recent_trades": rows[-12:]}
    if buys:
        ex = [x["since_trade_pct"] - x.get("market_since_pct", 0) for x in buys]
        out["buys_avg_return_since_pct"] = round(sum(x["since_trade_pct"] for x in buys) / len(buys), 1)
        out["buys_avg_excess_vs_market_pctp"] = round(sum(ex) / len(ex), 1)
    if sells:
        out["sells_avg_price_move_after_sale_pct"] = round(sum(x["since_trade_pct"] for x in sells) / len(sells), 1)
        out["sells_note"] = "양수면 판 뒤에 올랐다는 뜻(너무 일찍 판 경향), 음수면 판 뒤에 내려 잘 판 것"
    fl = {}
    for x in ev:
        if x["side"] == "매수":
            fl.setdefault(x["followed"], []).append(x["since_trade_pct"] - x.get("market_since_pct", 0))
    if fl:
        out["buys_excess_by_plan_following"] = {k: {"n": len(v), "avg_excess_pctp": round(sum(v) / len(v), 1)} for k, v in fl.items()}
    out["note"] = "표본 {}건. 30건 미만이면 통계적 의미가 없으므로 습관을 돌아보는 관찰로만 쓰세요(같은 시기 매매는 서로 독립이 아님).".format(len(ev))
    return out


def render_review(get_conn, get_prices):
    st.markdown("#### 내 매매 복기 — 에이전트가 읽는 자료")
    s = summarize(get_conn, get_prices)
    if not s or not s.get("n_trades"):
        st.info("아직 기록된 매매가 없습니다. '내 포트폴리오' 탭의 '매매 기록'에 체결 내용과 이유를 남기면 여기에 쌓이고, 에이전트가 계획을 짤 때마다 읽습니다.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("기록된 매매", "{}건".format(s["n_trades"]), "매수 {} · 매도 {}".format(s["n_buys"], s["n_sells"]), delta_color="off")
    c2.metric("평가 가능(10일 이상 경과)", "{}건".format(s["n_evaluable(10일 이상 경과)"]))
    if "buys_avg_excess_vs_market_pctp" in s:
        c3.metric("매수 후 시장 대비 평균", "{:+.1f}%p".format(s["buys_avg_excess_vs_market_pctp"]))
    if "sells_avg_price_move_after_sale_pct" in s:
        st.write("매도한 종목의 매도 후 평균 변화: **{:+.1f}%** — {}".format(s["sells_avg_price_move_after_sale_pct"], s["sells_note"]))
    if s.get("buys_excess_by_plan_following"):
        st.dataframe(pd.DataFrame([{"계획 대비": k, "건수": v["n"], "시장 대비 평균(%p)": v["avg_excess_pctp"]} for k, v in s["buys_excess_by_plan_following"].items()]), use_container_width=True, hide_index=True)
    st.dataframe(pd.DataFrame(s["recent_trades"]).rename(columns={"date": "날짜", "name": "종목", "side": "구분", "price": "단가", "reason": "이유", "followed": "계획 대비", "days": "경과일", "since_trade_pct": "이후 변화(%)", "market_since_pct": "같은 기간 시장(%)"}), use_container_width=True, hide_index=True)
    st.caption(s["note"])
