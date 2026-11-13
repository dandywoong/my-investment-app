"""환전 판단 · CMA 원화 / 미국 달러 예수금 원장.

- 환전과 미국 주식 매수는 별개의 결정이다. 환율 매력도와 주식 매력도를 한 점수로 합치지 않는다.
- 환율은 정확히 예측할 수 없다. 이 화면의 등급은 '환율의 최근 위치'를 보는 참고 지표이며, 확신이 부족하면 '환전 보류'가 기본이다.
- 잔액은 '실제로 확인된 사건'(입금, 환전 완료, 매수 체결 등)만 더해서 계산한다. 계획·제안만으로는 아무 것도 차감하지 않는다(같은 사건을 두 번 넣지 않도록 사건마다 한 줄).
"""
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent

LEVELS = ["매우 낮음", "낮음", "보통", "양호", "매우 양호"]
KINDS = {"deposit": "원화 입금(CMA)", "fx_done": "환전 완료(원화→달러)", "usd_buy": "미국 주식 매수 체결(달러 사용)", "usd_in": "달러 유입(매도·배당)", "adjust": "잔액 바로잡기"}
_ONCE = {"done": False}


def ensure_tables(get_conn):
    if _ONCE["done"]:
        return
    try:
        ai_agent._run(get_conn, "CREATE TABLE IF NOT EXISTS fx_events (id SERIAL PRIMARY KEY, created_at TEXT, event_date TEXT, kind TEXT, krw_delta DOUBLE PRECISION, "
                                "usd_delta DOUBLE PRECISION, rate DOUBLE PRECISION, memo TEXT)")
    except Exception:  # noqa: BLE001
        pass
    _ONCE["done"] = True


def balances(get_conn):
    """-> (CMA 원화, 달러 예수금, 누적 입금 원화, 누적 환전 원화, 누적 매수 달러)"""
    try:
        df = ai_agent._run(get_conn, "SELECT kind, krw_delta, usd_delta FROM fx_events", fetch=True)
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, 0.0, 0.0, 0.0
    if df is None or not len(df):
        return 0.0, 0.0, 0.0, 0.0, 0.0
    dep = float(df.loc[df["kind"] == "deposit", "krw_delta"].sum())
    fxk = -float(df.loc[df["kind"] == "fx_done", "krw_delta"].sum())
    buy = -float(df.loc[df["kind"] == "usd_buy", "usd_delta"].sum())
    return float(df["krw_delta"].sum()), float(df["usd_delta"].sum()), dep, fxk, buy


# ------------------------------------------------------------------ 환율 위치(자체 계산)
@st.cache_data(ttl=1800, show_spinner=False)
def _hist(sym, period):
    import yfinance as yf
    h = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
    c = h["Close"].dropna()
    return c if len(c) else None


def fx_view():
    """원/달러 최근 위치와 규칙 기반 등급. 자료가 없거나 오래되면 등급을 내지 않는다. -> dict | None"""
    try:
        c = _hist("KRW=X", "1y")
        if c is None or len(c) < 120:
            return None
        last_dt = c.index[-1]
        try:
            age = (pd.Timestamp.now(tz=last_dt.tz) - last_dt).days
        except Exception:  # noqa: BLE001
            age = 0
        px = float(c.iloc[-1])
        out = {"rate": px, "asof": str(last_dt)[:10], "stale": age > 4, "source": "Yahoo Finance(KRW=X)"}
        ranges = {}
        for nm, n in (("1개월", 21), ("3개월", 63), ("6개월", 126), ("1년", len(c))):
            t_ = c.tail(n)
            ranges[nm] = (float(t_.min()), float(t_.max()), float((t_ <= px).mean()))  # (최저, 최고, 현재 이하 비율)
        out["ranges"] = ranges
        pct = ranges["1년"][2]
        ma120 = float(c.tail(120).mean())
        dev = px / ma120 - 1
        mom5 = float(px / c.iloc[-6] - 1)
        pts = 0
        pts += 2 if pct <= 0.2 else 1 if pct <= 0.4 else -2 if pct >= 0.8 else -1 if pct >= 0.6 else 0
        pts += 1 if dev <= -0.02 else -1 if dev >= 0.02 else 0
        notes = ["1년 범위에서 현재 환율은 하위 {:.0f}% 위치(낮을수록 달러가 상대적으로 쌈)".format(pct * 100), "120일 평균 대비 {:+.1f}%".format(dev * 100)]
        if mom5 <= -0.015:
            notes.append("최근 5일 {:+.1f}% 하락 중: 더 내려갈 수도 있어 한 번에 몰아서 환전하지 않는 편이 안전".format(mom5 * 100))
        if pts >= 3:
            lvl = "매우 양호"
        elif pts == 2:
            lvl = "양호"
        elif pts <= -3:
            lvl = "매우 낮음"
        elif pts == -2:
            lvl = "낮음"
        else:
            lvl = "보통"
        ctx = {}
        for nm, sym in (("달러지수(DXY)", "DX-Y.NYB"), ("미 10년물 금리(%)", "^TNX")):
            try:
                s_ = _hist(sym, "6mo")
                if s_ is not None and len(s_) > 22:
                    ctx[nm] = {"현재": round(float(s_.iloc[-1]), 2), "1개월 변화": round(float(s_.iloc[-1] / s_.iloc[-22] - 1) * 100, 1)}
            except Exception:  # noqa: BLE001
                pass
        out.update({"level": lvl, "points": pts, "notes": notes, "context": ctx, "mom5": mom5, "pct1y": pct})
        out["confidence"] = "낮음" if out["stale"] else "보통"
        return out
    except Exception:  # noqa: BLE001
        return None


def suggest(view, ai_fx, cma_krw, reserve_krw, usd_cash, us_demand_krw, spread_pct):
    """오늘 환전 권장액. 고정 비율이 아니라 '필요한 달러 − 이미 가진 달러'에 환율 등급 가중을 곱하고, 비상금은 제외한다.
    -> dict(amount, hold, reasons[], usd_expected, cost_krw)"""
    reasons = []
    if not view or view.get("stale"):
        return {"amount": 0, "hold": True, "reasons": ["환율 자료가 없거나 오래돼 환전 권고를 만들지 않습니다."], "usd_expected": 0.0, "cost_krw": 0}
    avail = max(0.0, cma_krw - reserve_krw)
    need = max(0.0, us_demand_krw - usd_cash * view["rate"])
    mult = {"매우 낮음": 0.0, "낮음": 0.25, "보통": 0.5, "양호": 0.8, "매우 양호": 1.2}[view["level"]]
    lean = (ai_fx or {}).get("lean") if isinstance(ai_fx, dict) else None
    if lean == "환전 불리":
        mult *= 0.5
        reasons.append("AI 조사 의견이 '환전 불리'여서 환전액을 절반으로 줄였습니다(의견 불일치).")
    elif lean == "환전 유리" and view["level"] in ("양호", "매우 양호"):
        reasons.append("AI 조사 의견도 '환전 유리'로 같은 방향입니다.")
    if view["mom5"] <= -0.015:
        mult *= 0.7
        reasons.append("환율이 빠르게 내리는 중이라 분할 환전 쪽으로 줄였습니다.")
    amount = min(avail, need * mult)
    if amount < 10000:
        amount = 0.0
    reasons.insert(0, "필요 달러(원화 환산) {:,.0f}원 − 이미 보유한 달러 {:,.0f}원 = {:,.0f}원, 환율 등급 '{}' 가중 {:.2f} → 환전 {:,.0f}원 (비상금 {:,.0f}원 제외 후 사용 가능 {:,.0f}원)".format(
        us_demand_krw, usd_cash * view["rate"], need, view["level"], mult, amount, reserve_krw, avail))
    cost = amount * spread_pct / 100.0
    usd = (amount - cost) / view["rate"] if view["rate"] else 0.0
    return {"amount": round(amount), "hold": amount == 0, "reasons": reasons, "usd_expected": usd, "cost_krw": round(cost)}


def packet_part(get_conn, view, ai_fx):
    cma, usd, dep, fxk, buy = balances(get_conn)
    return {"cma_krw": round(cma), "usd_cash": round(usd, 2), "fx_rule_level": None if not view else view["level"], "fx_rate": None if not view else round(view["rate"], 1),
            "fx_notes": None if not view else view["notes"], "fx_ai_research": ai_fx, "note": "환전 결정과 주식 매수 결정은 별개입니다. 달러 예수금이 있으면 환전 없이 그 달러로 매수 가능."}


# ------------------------------------------------------------------ 화면
def render(get_conn, items, fx_use, us_alloc_krw=0, ai_fx=None):
    """환전·달러 예수금 섹션(요청서 A~E). us_alloc_krw: 전략가가 정한 오늘 미국 배분(원)."""
    ensure_tables(get_conn)
    view = fx_view()
    cma, usd, dep, fxk, buy = balances(get_conn)
    st.markdown("#### 환전 · CMA 원화 · 달러 예수금")
    st.caption("환전과 미국 주식 매수는 별개의 결정입니다. 환율이 좋다고 꼭 사야 하는 것도, 사고 싶은 날 꼭 환전해야 하는 것도 아닙니다. 잔액은 '실제로 일어난 일'을 기록해야만 바뀝니다.")
    stock_usd = sum((i.get("value") or 0) for i in items if i["cur"] == "USD")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CMA 원화 예수금", "{:,.0f}원".format(cma))
    c2.metric("달러 예수금", "${:,.2f}".format(usd), "{:,.0f}원 환산".format(usd * fx_use) if fx_use else None)
    c3.metric("미국 주식 평가액", "${:,.0f}".format(stock_usd))
    c4.metric("투자 가능 현금(원화 환산)", "{:,.0f}원".format(cma + usd * (fx_use or 0)))
    st.caption("누적 입금 {:,.0f}원 · 누적 환전 {:,.0f}원 · 누적 미국 매수 ${:,.2f}".format(dep, fxk, buy))
    st.markdown("**오늘의 환율 분석**")
    if not view:
        st.info("환율 자료를 가져오지 못해 환전 권고를 만들지 않습니다(자료 누락 시 임의 권고 금지).")
    else:
        a1, a2, a3 = st.columns(3)
        a1.metric("원/달러(시장 기준)", "{:,.1f}".format(view["rate"]), "기준일 " + view["asof"])
        a2.metric("환전 매력도(규칙 기반 참고)", view["level"])
        a3.metric("판단 신뢰도", view["confidence"])
        rg = pd.DataFrame([{"기간": k, "최저": round(v[0], 1), "최고": round(v[1], 1), "현재 위치(하위 %)": round(v[2] * 100)} for k, v in view["ranges"].items()])
        st.dataframe(rg, hide_index=True, use_container_width=True)
        for n_ in view["notes"]:
            st.write("- " + n_)
        if view["context"]:
            st.write("- 참고 지표: " + ", ".join("{} {} (1개월 {:+.1f}%)".format(k, v["현재"], v["1개월 변화"]) for k, v in view["context"].items()))
        if ai_fx:
            st.write("**AI 검색 조사(참고 의견)**: 환전 방향 {} · 신뢰도 {}".format(ai_fx.get("lean", "-"), ai_fx.get("confidence", "-")))
            if ai_fx.get("level_note"):
                st.write(ai_fx["level_note"])
            for v in (ai_fx.get("institution_views") or [])[:6]:
                st.write("- {} ({}): {}".format(v.get("name", ""), v.get("date", ""), v.get("view", "")))
        else:
            st.caption("AI 환율 조사 의견은 '내 투자'의 AI 전략을 만들 때 검색 조사와 함께 받아옵니다(없으면 규칙 계산만 표시).")
        st.caption("환율은 정확히 예측할 수 없습니다. 아래 권장액은 고정 비율이 아니라 필요한 달러·보유 달러·환율 위치를 함께 본 값이고, 확신이 부족하면 0원(보류)일 수 있습니다.")
        cc1, cc2, cc3 = st.columns(3)
        reserve = cc1.number_input("CMA 비상금·부채 상환 예정액(투자 제외)", min_value=0, value=int(st.session_state.get("fx_reserve", 0)), step=100000, key="fx_reserve_in")
        spread = cc2.number_input("증권사 환전 스프레드(우대 반영, %)", min_value=0.0, max_value=3.0, value=float(st.session_state.get("fx_spread", 0.25)), step=0.05, key="fx_spread_in")
        demand = cc3.number_input("앞으로 미국 매수에 쓸 금액(원화)", min_value=0, value=int(us_alloc_krw or 0), step=100000, key="fx_demand_in")
        st.session_state["fx_reserve"], st.session_state["fx_spread"] = reserve, spread
        sg = suggest(view, ai_fx, cma, reserve, usd, demand, spread)
        m1, m2, m3 = st.columns(3)
        m1.metric("오늘 환전 권장", "보류" if sg["hold"] else "{:,.0f}원".format(sg["amount"]))
        m2.metric("환전 후 예상 달러", "${:,.2f}".format(usd + sg["usd_expected"]))
        m3.metric("예상 환전 비용", "{:,.0f}원".format(sg["cost_krw"]))
        for r_ in sg["reasons"]:
            st.write("- " + r_)
        st.caption("증권사가 실제로 적용한 환율은 시장 기준과 다릅니다. 환전을 마친 뒤 아래에 '환전 완료'로 실제 값을 입력하세요.")
    with st.expander("실제로 있었던 일 기록하기 (입금 · 환전 완료 · 매수 체결 · 달러 유입 · 잔액 바로잡기)"):
        with st.form("fx_form", clear_on_submit=True):
            kind = st.selectbox("종류", list(KINDS.keys()), format_func=lambda k: KINDS[k])
            d = st.date_input("날짜", value=date.today())
            k1, k2, k3 = st.columns(3)
            krw = k1.number_input("원화 금액(원)", min_value=0.0, value=0.0, step=10000.0, help="입금·환전 완료에서 사용한 원화")
            usd_v = k2.number_input("달러 금액($)", min_value=0.0, value=0.0, step=1.0, help="환전으로 받은 달러 / 매수에 쓴 달러 / 유입된 달러")
            rate = k3.number_input("실제 적용 환율(선택)", min_value=0.0, value=0.0, step=0.1)
            memo = st.text_input("메모")
            st.caption("'잔액 바로잡기'는 입력한 값이 현재 잔액이 되도록 차이만큼 한 줄을 추가합니다.")
            ok = st.form_submit_button("기록 저장")
        if ok:
            kd, ud = 0.0, 0.0
            if kind == "deposit":
                kd = krw
            elif kind == "fx_done":
                kd, ud = -krw, usd_v
            elif kind == "usd_buy":
                ud = -usd_v
            elif kind == "usd_in":
                ud = usd_v
            else:
                kd, ud = krw - cma, usd_v - usd
            try:
                ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                              (datetime.now(timezone.utc).isoformat(timespec="seconds"), d.isoformat(), kind, kd, ud, rate or None, memo))
                st.success("기록했습니다. 새로고침하면 잔액에 반영됩니다.")
            except Exception as e:  # noqa: BLE001
                st.error("기록 실패: " + str(e)[:150])
        try:
            ev = ai_agent._run(get_conn, "SELECT id, event_date, kind, krw_delta, usd_delta, rate, memo FROM fx_events ORDER BY id DESC LIMIT 30", fetch=True)
            if ev is not None and len(ev):
                ev["kind"] = ev["kind"].map(lambda k: KINDS.get(k, k))
                st.dataframe(ev, hide_index=True, use_container_width=True)
                del_id = st.number_input("잘못 넣은 기록 번호(id) 삭제", min_value=0, value=0, step=1, key="fx_del_id")
                if st.button("이 기록 삭제", key="fx_del") and del_id:
                    ai_agent._run(get_conn, "DELETE FROM fx_events WHERE id=%s", (int(del_id),))
                    st.success("삭제했습니다. 새로고침하세요.")
        except Exception:  # noqa: BLE001
            pass
