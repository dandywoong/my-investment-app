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


def _hold_tables(items, fx):
    a, b = st.columns(2)
    isa = [i for i in items if i["cur"] == "KRW"]
    us = [i for i in items if i["cur"] == "USD"]
    with a:
        st.markdown("**ISA (국내 · 원화) 보유**")
        v = sum((i.get("value") or 0) for i in isa)
        c = sum((i.get("qty") or 0) * (i.get("avg") or 0) for i in isa)
        st.caption("평가 {:,.0f}원 · 투자원금 {:,.0f}원".format(v, c))
        if isa:
            st.dataframe(pd.DataFrame([{"종목": i["name"], "수량": round(i["qty"], 4), "평단(원)": round(i["avg"]), "현재가(원)": None if i["price"] is None else round(i["price"]),
                                        "평가(원)": round(i.get("value") or 0)} for i in isa]), use_container_width=True, hide_index=True)
    with b:
        st.markdown("**일반 (미국 · 달러) 보유**")
        v = sum((i.get("value") or 0) for i in us)
        c = sum((i.get("qty") or 0) * (i.get("avg") or 0) for i in us)
        st.caption("평가 ${:,.2f} · 투자원금 ${:,.2f}".format(v, c))
        if us:
            st.dataframe(pd.DataFrame([{"종목": i["name"], "수량": round(i["qty"], 4), "평단($)": round(i["avg"], 2), "현재가($)": None if i["price"] is None else round(i["price"], 2),
                                        "평가($)": round(i.get("value") or 0, 2)} for i in us]), use_container_width=True, hide_index=True)


def render_holdings(items, fx):
    _hold_tables(items, fx)


# ------------------------------------------------------------------ 환전 판단(AI가 환율·환전 매력도를 조사해 오늘 환전할 금액을 제안)
def fx_advice(get_conn, fx, cma_avail, spread):
    """-> (dict | None, 오류문구 | None)"""
    import json
    import strategist as S
    import newsfeed
    S.refresh_caches()
    view = fxmod.fx_view()
    mf = (S.market_facts().get("data") or {})
    heads = {"ko": newsfeed.fetch("원달러 환율 전망 외국인 달러", "ko", 10, 3), "en": newsfeed.fetch("USD KRW won dollar outlook Fed", "en", 8, 3),
             "dxy": newsfeed.fetch("dollar index DXY Treasury yield Fed", "en", 8, 2)}
    hist = [r for r in ledger_for_agent(get_conn, 60) if r["what"].startswith("환전")][:8]
    kst = datetime.now(timezone.utc).astimezone(timezone(__import__("datetime").timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    pk = {"now": kst, "cma_krw_available_to_exchange": int(cma_avail), "app_rate": fx, "fx_spread_pct": spread, "fx_rule_view": view,
          "usdkrw_and_rates": {k: mf.get(k) for k in ("원달러환율", "미국10년금리(%)", "VIX(공포지수)") if mf.get(k)}, "headlines": heads, "my_past_exchanges": hist,
          "recent_archive": S.load_archive(get_conn, 10)}
    prompt = ("당신은 장기 투자자의 환전 담당 보조입니다. 오늘 원화→달러 환전 타이밍을 판단합니다. 환율은 정확히 예측할 수 없으므로 맞히려 하지 말고, 지금 위치·추세·금리/달러 흐름·수급 뉴스·환전 비용(스프레드)을 근거로 "
              "'오늘 CMA 원화 중 얼마를 환전하면 합리적인가'를 정하세요. 한 번에 몰아서 하지 않고 분할을 기본으로 하며, 위치가 불리하거나 근거가 약하면 0원(보류)도 정답입니다. "
              "[방향 규칙] 원/달러 환율이 오르면 달러가 비싸지는 것(환전 불리), 내리면 달러가 싸지는 것(환전 유리)입니다. 환율 하락 압력(수출업체 네고 물량, 연준 완화 기대, 달러 약세)은 '기다리면 더 싸질 수 있다'는 뜻이므로 환전을 미루거나 나누는 근거이고, 상승 압력(달러 강세, 금리 상승)은 '지금이 더 싸거나 앞으로 비싸질 수 있다'는 뜻이므로 지금 환전하는 근거입니다. 근거와 반대 근거의 방향을 뒤집어 쓰지 마세요. "
              "금액은 cma_krw_available_to_exchange 이하의 1만원 단위 정수. 승률·확률·수익 보장 표현 금지, 반대 근거를 반드시 쓰고, 헤드라인에 없는 사실은 추측하지 마세요. 이미 발표된 일은 결과로 쓰세요.\n"
              "자료(JSON):\n" + json.dumps(pk, ensure_ascii=False, default=str)[:14000] +
              '\n출력 JSON만: {"lean":"환전 유리|분할 환전|보류|판단 불가","recommend_krw":0,"split":[{"when":"오늘/며칠 뒤/조건 충족 시","krw":0}],"reason":"","counter":"","watch":"판단이 바뀌는 조건","confidence":"낮음|보통|높음","evidence":[{"name":"","date":""}]}')
    res, err = S._gemini(prompt)
    if err or not isinstance(res, dict):
        return None, err or "응답 해석 실패"
    try:
        rec = int(float(res.get("recommend_krw") or 0))
    except Exception:  # noqa: BLE001
        rec = 0
    rec = max(0, min(int(cma_avail), (rec // 10000) * 10000))
    res["recommend_krw"] = rec
    res["_at"] = _now()
    try:
        S.ensure_archive(get_conn)
        S._arch_add(get_conn, "fx", {k: res.get(k) for k in ("lean", "recommend_krw", "reason", "confidence")} | {"rate": fx})
    except Exception:  # noqa: BLE001
        pass
    return res, None


def _render_ledger_delete(get_conn, df, kp):
    """잘못 입력했거나 테스트로 넣은 줄을 골라 지운다. 잔액은 남은 줄의 합계로 자동 다시 계산된다."""
    st.markdown("**지울 줄 고르기** (왼쪽 '삭제' 칸에 체크 → 아래 확인 → 삭제 버튼)")
    ed = pd.DataFrame({"삭제": False, "번호": df["id"].astype(int), "날짜": df["event_date"].astype(str).str[:10], "내용": df["kind"].map(lambda k: fxmod.KINDS.get(k, k)),
                       "원화 증감": pd.to_numeric(df["krw_delta"], errors="coerce").round(0), "달러 증감($)": pd.to_numeric(df["usd_delta"], errors="coerce").round(2),
                       "환율": pd.to_numeric(df["rate"], errors="coerce").round(1), "메모": df["memo"]})
    out = st.data_editor(ed, hide_index=True, use_container_width=True, key=kp + "led_ed", disabled=[c for c in ed.columns if c != "삭제"],
                         column_config={"삭제": st.column_config.CheckboxColumn("삭제", default=False)})
    pick = out[out["삭제"] == True]  # noqa: E712
    n = len(pick)
    if n:
        d_k, d_u = float(pick["원화 증감"].sum()), float(pick["달러 증감($)"].sum())
        st.warning("{}줄을 지우면 CMA 원화가 {:+,.0f}원, 달러 예수금이 {:+.2f}$ 만큼 바뀝니다(지운 줄의 반대). 매매와 연결된 줄(매수·매도 체결)을 지워도 보유 수량·평단은 자동으로 되돌아가지 않습니다.".format(n, -d_k, -d_u))
        ok = st.checkbox("위 내용을 확인했고 {}줄을 삭제합니다".format(n), key=kp + "led_ok")
        if st.button("선택한 줄 삭제", key=kp + "led_del", disabled=not ok):
            for i_ in pick["번호"].tolist():
                ai_agent._run(get_conn, "DELETE FROM fx_events WHERE id=%s", (int(i_),))
            st.session_state["_asset_flash"] = "{}줄을 삭제했습니다. 잔액이 다시 계산되었습니다.".format(n)
            st.rerun()
    with st.expander("모두 지우고 처음부터 (돈 기록 전체 삭제)"):
        st.caption("돈 기록(입금·환전·매매 예수금 증감)을 전부 지웁니다. 보유 종목 수량·평단은 그대로입니다. 지운 뒤 '잔액 맞추기'로 실제 잔액을 넣으세요.")
        ok2 = st.checkbox("전부 지우겠습니다", key=kp + "led_all_ok")
        if st.button("돈 기록 전체 삭제", key=kp + "led_all", disabled=not ok2):
            ai_agent._run(get_conn, "DELETE FROM fx_events")
            st.session_state["_asset_flash"] = "돈 기록을 모두 지웠습니다. 잔액 맞추기로 실제 잔액을 넣어 주세요."
            st.rerun()


def render_money(get_conn, fx, c, kp="as_", adjust=True):
    """내 돈: CMA 원화 · 일반계좌 달러 · 입금 기록 · 환전 판단 · 환전 기록."""
    fxmod.ensure_tables(get_conn)
    cma, usd = fxmod.balances(get_conn)[:2]
    reserve = int(float((c or {}).get("fx_reserve", 0) or 0))
    spread = float((c or {}).get("fx_spread", 0.25) or 0.25)
    avail = max(0.0, cma - reserve)
    flash = st.session_state.pop("_asset_flash", None)
    if flash:
        st.success(flash)
    m1, m2, m3 = st.columns(3)
    m1.metric("CMA 원화 (국장·미장 모두 쓸 수 있는 돈)", "{:,.0f}원".format(cma), "비상금 {:,.0f}원 제외 시 {:,.0f}원".format(reserve, avail) if reserve else None, delta_color="off")
    m2.metric("일반계좌 달러 예수금 (미장 투자금)", "${:,.2f}".format(usd), "{:,.0f}원 상당 (오늘 환율 {:,.0f})".format(usd * (fx or 0), fx or 0) if fx else None, delta_color="off")
    m3.metric("투자 가능 합계 (원화 환산)", "{:,.0f}원".format(avail + max(usd, 0) * (fx or 0)))
    if usd < -0.005 or cma < -0.5:
        st.error("잔액이 마이너스입니다. 기록이 어긋난 상태입니다. '잔액 맞추기'로 증권사 앱 숫자에 맞춰 주세요.")
    st.markdown("**① 돈이 생기면 — 입금 기록 (CMA로 들어감)**")
    with st.form(kp + "dep", clear_on_submit=True):
        d1, d2, d3 = st.columns([1, 1, 1])
        dd = d1.date_input("입금 날짜", value=date.today(), key=kp + "dep_d")
        da = d2.number_input("입금액 (원)", min_value=0, value=0, step=100000, key=kp + "dep_a")
        d3.write("")
        if d3.form_submit_button("입금 기록") and da > 0:
            _ins(get_conn, dd, "deposit", da, 0, None, "입금")
            try:
                ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (dd.isoformat(), int(da), "", _now()))
            except Exception:  # noqa: BLE001
                pass
            st.session_state["_asset_flash"] = "입금 {:,.0f}원을 CMA에 기록했습니다.".format(da)
            st.rerun()
    st.markdown("**② 환전 — 에이전트에게 오늘 환전해도 되는지, 얼마나 할지 묻기**")
    cA, cB = st.columns([1, 3])
    ask = cA.button("환전 판단 받기", key=kp + "fx_ask", disabled=avail < 10000)
    if avail < 10000:
        cB.caption("환전에 쓸 수 있는 CMA 원화가 없습니다. 먼저 ①에서 입금을 기록하세요.")
    else:
        cB.caption("오늘 환율 위치, 달러·금리 흐름, 환율 뉴스, 환전 비용을 조사해 CMA 중 얼마를 지금 환전하면 좋은지 제안합니다(분할 기본, 보류도 가능).")
    if ask:
        with st.spinner("환율·달러 흐름·뉴스를 조사하는 중... (30초~1분)"):
            adv, err = fx_advice(get_conn, fx, avail, spread)
        if err:
            st.error("환전 판단을 받지 못했습니다: " + str(err) + " — 잠시 뒤 다시 눌러 주세요.")
        else:
            st.session_state["_fx_advice_ui"] = adv
    adv = st.session_state.get("_fx_advice_ui")
    if adv:
        st.info("**환전 판단: {}** — 오늘 권장 {:,.0f}원 (신뢰도 {}) · 판단 시각 {}".format(adv.get("lean", "-"), adv.get("recommend_krw", 0), adv.get("confidence", "-"), str(adv.get("_at", ""))[:16].replace("T", " ") + " UTC"))
        _v = fxmod.fx_view()
        if _v:
            _ai_buy = adv.get("recommend_krw", 0) > 0
            _rule_ok = _v.get("level") in ("양호", "매우 양호")
            _rule_bad = _v.get("level") in ("낮음", "매우 낮음")
            st.caption("앱 규칙 점검(AI와 별개의 기계적 기준): 환율 등급 '{}' — {}".format(_v.get("level"), " / ".join(_v.get("notes") or [])))
            if (_ai_buy and _rule_bad) or ((not _ai_buy) and _rule_ok):
                st.warning("AI 판단과 앱 규칙 등급이 서로 다른 방향입니다. 한쪽만 믿지 말고 근거를 비교해 보세요.")
        st.write("**근거** — " + str(adv.get("reason", "")))
        st.write("**반대 근거** — " + str(adv.get("counter", "")))
        for s_ in adv.get("split") or []:
            if isinstance(s_, dict):
                st.caption("분할안: {} — {:,.0f}원".format(s_.get("when", ""), float(s_.get("krw") or 0)))
        if adv.get("watch"):
            st.caption("판단이 바뀌는 조건: " + str(adv["watch"]))
        if adv.get("recommend_krw", 0) > 0:
            def _fill(v=int(adv["recommend_krw"])):
                st.session_state[kp + "fx_k"] = v
            st.button("권장 금액 {:,.0f}원을 아래 환전 칸에 채우기".format(adv["recommend_krw"]), key=kp + "fx_fill", on_click=_fill)
    st.markdown("**③ 환전했다면 — 실제 환전 결과 기록 (CMA에서 빠지고 일반계좌 달러로 들어감)**")
    with st.form(kp + "fx", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        fd = f1.date_input("환전 날짜", value=date.today(), key=kp + "fx_d")
        fk = f2.number_input("환전한 원화 (원)", min_value=0, value=int(st.session_state.get(kp + "fx_k", 0) or 0), step=10000, key=kp + "fx_k")
        fr = f3.number_input("실제 적용 환율 (원/달러)", min_value=0.0, value=float(round(fx, 1)) if fx else 0.0, step=0.1, key=kp + "fx_r")
        st.caption("받은 달러 = 환전한 원화 ÷ 적용 환율 로 자동 계산됩니다(예: 300,000원 ÷ 1,335 = $224.72).")
        if st.form_submit_button("환전 기록") and fk > 0 and fr > 0:
            if fk > cma + 0.5:
                st.error("CMA 원화 잔액({:,.0f}원)보다 많이 환전할 수 없습니다.".format(cma))
            else:
                got = round(fk / fr, 2)
                _ins(get_conn, fd, "fx_done", -fk, got, fr, "환전(직접 기록)")
                st.session_state["_asset_flash"] = "환전 기록: {:,.0f}원 → ${:,.2f} (환율 {:,.1f}원). CMA {:,.0f}원, 달러 예수금 ${:,.2f}.".format(fk, got, fr, cma - fk, usd + got)
                st.rerun()
    if adjust:
        with st.expander("잔액 맞추기 (증권사 앱 실제 잔액과 어긋났을 때)"):
            with st.form(kp + "adj"):
                j1, j2 = st.columns(2)
                wk = j1.number_input("CMA 원화 잔액", min_value=0.0, value=float(max(0, round(cma))), step=10000.0, key=kp + "adj_k")
                wu = j2.number_input("달러 예수금 ($)", min_value=0.0, value=float(max(0.0, round(usd, 2))), step=1.0, key=kp + "adj_u")
                if st.form_submit_button("이 값으로 맞추기"):
                    _ins(get_conn, date.today(), "adjust", wk - cma, wu - usd, None, "잔액 맞추기")
                    st.session_state["_asset_flash"] = "잔액을 CMA {:,.0f}원 · ${:,.2f}로 맞췄습니다.".format(wk, wu)
                    st.rerun()
    with st.expander("돈 기록 내역 · 삭제 (원장 — 최근 60건)"):
        df = ledger_df(get_conn, 60)
        if df is None or df.empty:
            st.caption("아직 기록이 없습니다.")
        else:
            _render_ledger_delete(get_conn, df, kp)
            st.caption("잔액 = 이 줄들의 합계입니다. 입금은 CMA 원화, 환전은 원화 감소+달러 증가, 매매는 해당 통화 증감으로 쌓입니다.")


def render(get_conn, items, fx, c=None):
    """내 포트폴리오 탭용: 돈 + 계좌별 보유."""
    st.markdown("### 내 자산 한눈에")
    st.caption("현금과 보유 종목이 계좌별로 모여 있습니다. 에이전트도 같은 장부를 읽습니다.")
    render_money(get_conn, fx, c or {}, "pf_")
    _hold_tables(items, fx)
