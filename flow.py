"""오늘의 실행안: 입금 잔액 → 환전 → 국장 매수 → 미국 매수 → 남는 돈이 한 줄로 딱 맞게 이어지는 표.
- 시작 숫자는 '내 돈' 장부의 현재 잔액(이미 기록한 입금·환전이 자동 반영됨).
- 수량·단가는 칸에서 바로 고쳐 가며 시험할 수 있고, 고칠 때마다 아래 대조표가 다시 계산된다.
- 장부에는 '체결 기록' 버튼을 눌러야만 반영된다(그 전에는 몇 번을 고쳐도 아무것도 바뀌지 않는다).
"""
import math
from datetime import date

import pandas as pd
import streamlit as st

import fx as fxmod
import journal


def _px_default(it, p):
    """국내는 지정가 1차 가격, 없으면 현재가. 미국은 현재가."""
    px = float(it.get("price") or 0)
    if it["cur"] == "KRW":
        lp = (p or {}).get("limit_plan") or {}
        try:
            if lp.get("first_price"):
                px = float(str(lp["first_price"]).replace(",", ""))
        except Exception:  # noqa: BLE001
            pass
    return px


def build_rows(items, strat, fx, avail_krw, usd_now, applied):
    """AI 계획을 실행 가능한 수량으로 바꾼 기본값. 국내=정수 주(1주 값이 모자라면 0주), 미국=소수 4자리."""
    pri = {p.get("_item"): p for p in (strat.get("priorities") or [])}
    order = [p.get("_item") for p in (strat.get("priorities") or [])]
    rows = []
    for it in sorted(items, key=lambda i: (order.index(i["tk"]) if i["tk"] in order else 999)):
        if not it.get("price"):
            continue
        p = pri.get(it["tk"])
        amt = int((p or {}).get("amount_krw") or 0) if (p or {}).get("action") == "매수" else 0
        px = _px_default(it, p)
        q = 0.0
        if amt > 0 and px > 0:
            if it["cur"] == "USD" and fx:
                q = math.floor(amt / fx / px * 10000) / 10000
            elif it["cur"] == "KRW":
                q = float(int(amt // px))
        ai = "-"
        if p:
            ai = "{} {}".format(p.get("action") or "", "{:,.0f}원".format(amt) if amt else "").strip()
        rows.append({"tk": it["tk"], "종목": it["name"], "통화": it["cur"], "현재가": float(it["price"]), "AI 제안": ai, "실행 수량": q, "단가": round(px, 2 if it["cur"] == "USD" else 0),
                     "이유": str((p or {}).get("reason") or "")[:70], "_it": it, "_amt": amt})
    # 기본값이 CMA를 넘으면(환전 스프레드 때문에 몇백 원 모자라는 경우) 미국 수량을 아주 조금 줄여 딱 맞춘다.
    kr = sum(r["실행 수량"] * r["단가"] for r in rows if r["통화"] == "KRW")
    us = sum(r["실행 수량"] * r["단가"] for r in rows if r["통화"] == "USD")
    if us > 0 and applied:
        max_us = usd_now + max(0.0, avail_krw - kr) / applied
        if us > max_us:
            k = max_us / us
            for r in rows:
                if r["통화"] == "USD" and r["실행 수량"] > 0:
                    r["실행 수량"] = math.floor(r["실행 수량"] * k * 10000) / 10000
    return rows


def compute(rows, avail_krw, usd_now, applied, ex_override=None):
    """-> dict. 환전액은 '미국 매수 달러 − 보유 달러'를 채우는 만큼(자동), 또는 직접 입력값."""
    kr = sum(r["q"] * r["px"] for r in rows if r["cur"] == "KRW")
    us = sum(r["q"] * r["px"] for r in rows if r["cur"] == "USD")
    need = max(0.0, us - usd_now)
    ex_krw = float(ex_override) if ex_override is not None else math.ceil(need * applied / 10.0) * 10.0 if need > 0.005 else 0.0
    ex_usd = ex_krw / applied if applied else 0.0
    krw_end = avail_krw - ex_krw - kr
    usd_end = usd_now + ex_usd - us
    return {"kr": kr, "us": us, "ex_krw": ex_krw, "ex_usd": ex_usd, "krw_end": krw_end, "usd_end": usd_end}


def render(get_conn, items, fx, c, sid, status, strat, pl_, apply_trade, set_status, ev, kp="ag_"):
    if not fx:
        st.info("환율을 불러오지 못해 실행안을 계산할 수 없습니다.")
        return
    cma, usd_now = fxmod.balances(get_conn)[:2]
    reserve = int(float(c.get("fx_reserve", 0) or 0))
    sp = float(c.get("fx_spread", 0.25) or 0.25)
    avail = max(0.0, cma - reserve)
    applied = fx * (1 + sp / 100.0)
    ver = st.session_state.get("_flow_ver", 0)
    st.markdown("#### 4. 오늘의 실행안 — 입금 잔액 → 환전 → 매수 → 남는 돈")
    st.caption("출발점은 위 '내 돈'의 현재 잔액입니다(이미 기록한 입금·환전은 자동 반영). **'실행 수량'과 '단가', '이유' 칸은 바로 고칠 수 있고**, 고치면 아래 계산표가 즉시 다시 맞춰집니다. "
               "여기서 아무리 고쳐도 '체결 기록' 버튼을 누르기 전에는 장부·보유 수량이 바뀌지 않으니 마음껏 시험해 보세요. 국내 주식은 정수 주, 미국 주식은 소수점(증권사 금액 주문) 기준입니다.")
    rows0 = build_rows(items, strat, fx, avail, usd_now, applied)
    if not rows0:
        st.info("실행안에 넣을 종목 가격을 불러오지 못했습니다.")
        return
    base = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_") and k != "tk"} for r in rows0])
    ed_key = "flow_ed_{}_{}".format(sid, ver)
    out = st.data_editor(base, hide_index=True, use_container_width=True, num_rows="fixed", key=ed_key,
                         disabled=["종목", "통화", "현재가", "AI 제안"],
                         column_config={"실행 수량": st.column_config.NumberColumn("실행 수량 (주)", min_value=0.0, format="%.4f", help="국내는 정수 주로 맞춰집니다. 0이면 사지 않음"),
                                        "단가": st.column_config.NumberColumn("단가 (원/$)", min_value=0.0, format="%.2f"),
                                        "현재가": st.column_config.NumberColumn("현재가", format="%.2f"), "이유": st.column_config.TextColumn("이유 (일지에 저장)", width="large")})
    rows = []
    warn = []
    for i, r in out.reset_index(drop=True).iterrows():
        o = rows0[i]
        q = 0.0 if pd.isna(r["실행 수량"]) else float(r["실행 수량"])
        px = 0.0 if pd.isna(r["단가"]) else float(r["단가"])
        if o["통화"] == "KRW" and q != int(q):
            warn.append("{}: 국내 주식은 정수 주만 가능해 {:g}주를 {}주로 내림했습니다.".format(o["종목"], q, int(q)))
            q = float(int(q))
        rows.append({"q": q, "px": px, "cur": o["통화"], "name": o["종목"], "it": o["_it"], "why": "" if pd.isna(r["이유"]) else str(r["이유"])})
    for w in warn:
        st.caption(w)
    short = [o for o in rows0 if o["_amt"] > 0 and o["통화"] == "KRW" and o["실행 수량"] == 0]
    for o in short:
        st.info("{}: AI가 {:,.0f}원 매수를 제안했지만 1주가 {:,.0f}원이라 살 수 없어 0주로 두었습니다. 사려면 수량을 1주로 바꿔 보세요(아래 표가 부족액을 바로 알려 줍니다).".format(o["종목"], o["_amt"], o["단가"]))
    auto = st.checkbox("환전액 자동 계산 (미국 매수에 모자라는 달러만큼, 환전 비용 포함)", value=True, key="flow_auto_{}_{}".format(sid, ver))
    ov = None
    if not auto:
        ov = st.number_input("환전할 원화 (직접 입력)", min_value=0, value=0, step=10000, key="flow_ex_{}_{}".format(sid, ver))
    r = compute(rows, avail, usd_now, applied, ov)
    steps = [{"단계": "시작 (내 돈 장부의 현재 잔액{})".format(", 비상금 {:,.0f}원 제외".format(reserve) if reserve else ""), "원화 변동": None, "달러 변동": None, "원화 잔액": round(avail), "달러 잔액": round(usd_now, 2)},
             {"단계": "① 환전 (적용 환율 {:,.1f}원/$ = 현재 {:,.1f} + 비용 {:.2f}%)".format(applied, fx, sp), "원화 변동": -round(r["ex_krw"]), "달러 변동": round(r["ex_usd"], 2), "원화 잔액": round(avail - r["ex_krw"]), "달러 잔액": round(usd_now + r["ex_usd"], 2)},
             {"단계": "② 국장 매수 합계", "원화 변동": -round(r["kr"]), "달러 변동": None, "원화 잔액": round(avail - r["ex_krw"] - r["kr"]), "달러 잔액": round(usd_now + r["ex_usd"], 2)},
             {"단계": "③ 미국 매수 합계 (≈{:,.0f}원)".format(r["us"] * fx), "원화 변동": None, "달러 변동": -round(r["us"], 2), "원화 잔액": round(avail - r["ex_krw"] - r["kr"]), "달러 잔액": round(r["usd_end"], 2)},
             {"단계": "= 남는 돈", "원화 변동": None, "달러 변동": None, "원화 잔액": round(r["krw_end"]), "달러 잔액": round(r["usd_end"], 2)}]
    st.dataframe(pd.DataFrame(steps), hide_index=True, use_container_width=True,
                 column_config={"원화 변동": st.column_config.NumberColumn(format="%d"), "달러 변동": st.column_config.NumberColumn(format="$%.2f"),
                                "원화 잔액": st.column_config.NumberColumn(format="%d"), "달러 잔액": st.column_config.NumberColumn(format="$%.2f")})
    ok = True
    if r["krw_end"] < -0.5:
        ok = False
        st.error("원화가 {:,.0f}원 모자랍니다. 국내 수량을 줄이거나 미국 수량을 줄이세요(또는 위 '내 돈'에서 입금을 먼저 기록).".format(-r["krw_end"]))
    if r["usd_end"] < -0.005:
        ok = False
        st.error("달러가 ${:,.2f} 모자랍니다. '환전액 자동 계산'을 켜거나 환전액을 늘리세요.".format(-r["usd_end"]))
    if ok:
        st.success("맞습니다 — 환전 {:,.0f}원 → 달러 ${:,.2f}, 국장 {:,.0f}원, 미국 ${:,.2f} 매수 후 남는 돈 원화 {:,.0f}원 · 달러 ${:,.2f}".format(r["ex_krw"], r["ex_usd"], r["kr"], r["us"], r["krw_end"], r["usd_end"]))
    b1, b2 = st.columns(2)
    if r["ex_krw"] > 0:
        def _fill(k=int(round(r["ex_krw"])), a=round(applied, 1)):
            st.session_state[kp + "fx_k"] = k
            st.session_state[kp + "fx_r"] = a
        b1.button("이 환전({:,.0f}원)을 위 '③ 환전 기록' 칸에 채우기".format(r["ex_krw"]), key="flow_fill_{}_{}".format(sid, ver), on_click=_fill,
                  help="증권사에서 실제로 환전한 뒤, 실제 환율로 고쳐서 기록하세요. 기록하면 위 시작 잔액이 바뀌고 이 표가 다시 계산됩니다.")
    if b2.button("표를 AI 제안 기본값으로 되돌리기", key="flow_reset_{}_{}".format(sid, ver)):
        st.session_state["_flow_ver"] = ver + 1
        st.rerun()
    if status == "filled":
        st.success("이 계획의 체결은 이미 장부에 반영되었습니다. 새 계획이 필요하면 '계획 받기'를 누르세요.")
        return
    if status != "confirmed":
        st.warning("아직 초안입니다. 위 '3. 오늘의 계획'에서 **'이 계획으로 주문하기'**를 누르면 아래 '체결 기록' 버튼이 열립니다. 그 전까지는 시험용입니다.")
        return
    st.markdown("**증권사에서 주문·체결을 마쳤다면** — 위 표의 수량·단가가 실제 체결 값과 같게 고친 뒤 기록하세요. 체결 안 된 종목은 수량을 0으로 두면 됩니다.")
    s1, s2 = st.columns(2)
    go = s1.button("체결 기록 (환전·보유 수량·평단·예수금·일지에 한 번에 반영)", key="flow_save_{}_{}".format(sid, ver), type="primary", disabled=not ok)
    cancel = s2.button("이번 계획은 주문하지 않음", key="flow_cancel_{}_{}".format(sid, ver))
    if cancel:
        set_status(get_conn, sid, "cancelled")
        st.rerun()
    if not go:
        return
    done = [x for x in rows if x["q"] > 0 and x["px"] > 0]
    try:
        if r["ex_krw"] > 0:
            ev(get_conn, "fx_done", -r["ex_krw"], r["ex_usd"], applied, "실행안 환전")
        msgs, spent = [], 0.0
        usd_pool = usd_now + r["ex_usd"]
        for x in done:
            good, msg = journal.record_trade(get_conn, apply_trade, x["it"], "매수", x["q"], x["px"], date.today(), x["why"] or "AI 계획 체결", journal.FOLLOW[0], True, False, sid, "에이전트 계획 체결")
            if not good:
                st.error(msg)
                return
            if x["cur"] == "USD":
                sp_ = min(x["q"] * x["px"], max(0.0, usd_pool - spent))
                spent += sp_
                ev(get_conn, "usd_buy", 0, -sp_, None, "{} 매수".format(x["name"]))
            else:
                ev(get_conn, "kr_buy", -(x["q"] * x["px"]), 0, None, "{} 매수".format(x["name"]))
            msgs.append(msg)
        set_status(get_conn, sid, "filled")
        st.session_state["_ctx_dirty"] = True
        st.session_state["_fill_flash"] = ("체결을 반영했습니다 — " + " / ".join(msgs)) if msgs else "환전만 반영했습니다."
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error("저장 중 문제가 생겼습니다: " + str(e)[:150] + " — 내 돈 장부와 보유 수량을 확인하세요.")
