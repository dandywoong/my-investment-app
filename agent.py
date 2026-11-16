"""AI 투자 에이전트 화면 — 하나의 흐름으로 이어지는 단순한 구조.

  ① 내 돈(CMA 원화·달러)  →  ② 입금액만 넣고 '계획 받기'(AI가 환전·투자·남길 돈까지 결정)
  →  ③ 계획 확인 후 '주문하기'(확정)  →  ④ 다음날 체결 내용 입력(보유 수량·평단·예수금이 한 번에 저장)
  →  ⑤ 시간이 지나면 성과 복기(백테스트) → AI가 다음 판단에 반영

돈의 기록은 fx_events 한 곳에만 쌓고(입금·환전·매수 체결), 잔액은 그 합계로만 계산한다. 계획·확정만으로는 잔액이 바뀌지 않는다.
"""
import json
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent
import fx as fxmod
import ledger
import strategist as S

_CLEAN_TABLES = ["fx_events", "cash_events", "strategy_log", "chat_log", "rec_log", "adjust_log", "cash_balance"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ev(get_conn, kind, krw, usd, rate=None, memo=""):
    ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (_now(), date.today().isoformat(), kind, float(krw), float(usd), rate, memo))


def _set_status(get_conn, sid, status):
    ai_agent._run(get_conn, "UPDATE strategy_log SET status=%s WHERE id=%s", (status, sid))



# ------------------------------------------------------------------ 시장·기업 브리핑 (맨 위, 접속하면 자동 갱신)
BRIEF_HOURS = 6


def _age_hours(ts):
    try:
        t = datetime.fromisoformat(str(ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return 9999.0


def _section_brief(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, get_prices):
    st.markdown("#### 오늘의 시장·기업 브리핑")
    ts, brief = S.load_brief(get_conn)
    stale = brief is None or _age_hours(ts) > BRIEF_HOURS
    c1, c2 = st.columns([1, 4])
    manual = c1.button("지금 새로 조사", key="ag_brief_now")
    tried = st.session_state.get("_brief_tried")
    if manual or (stale and not tried):
        st.session_state["_brief_tried"] = True
        try:
            packet = S.build_packet(items, risk, stress, fx, cfg_pk, 0, "", cash_map, c.get("policy_text") or S.DEFAULT_POLICY, None, get_prices)
            with st.spinner("접속했으니 시장·뉴스·내 보유 종목을 먼저 조사하는 중... (30초~1분)"):
                nb, err, warns = S.make_brief(get_conn, packet, force=manual)
            if err:
                st.error("브리핑을 만들지 못했습니다: " + err + (" (이전 브리핑을 보여 드립니다)" if brief else ""))
            else:
                ts, brief = S.load_brief(get_conn)
                for w in warns:
                    st.warning(w)
        except Exception as e:  # noqa: BLE001
            st.error("브리핑 중 문제가 생겼습니다: " + str(e)[:120])
    if not brief:
        st.info("아직 브리핑이 없습니다. '지금 새로 조사'를 눌러 주세요.")
        return
    age = _age_hours(ts)
    c2.caption("작성 {} UTC ({}) · 뉴스 헤드라인 {}건 · 참조 매체: {} · 제목·매체·날짜만 읽음(본문 못 읽음). 접속할 때 {}시간이 지났으면 자동으로 새로 조사합니다.".format(
        str(ts)[:16].replace("T", " "), "방금" if age < 0.1 else "{:.0f}시간 전".format(age), brief.get("_headlines_total") or 0, ", ".join(brief.get("_coverage") or []) or "없음", BRIEF_HOURS))
    if not brief.get("_research_ok"):
        st.error("뉴스를 가져오지 못해 앱 자료(시세·점수)만으로 만든 브리핑입니다. 참고만 하세요.")
    st.markdown("**{}**".format(brief.get("headline", "")))
    m = brief.get("market") or {}
    if m.get("summary"):
        st.write("**시장** — " + str(m["summary"]))
    if m.get("mood"):
        st.write("**분위기** — " + str(m["mood"]))
    if (brief.get("fx") or {}).get("summary"):
        st.write("**환율** — " + str(brief["fx"]["summary"]))
    kh = brief.get("kr_hold_check") or {}
    if kh:
        st.info("**국내(ISA) 보유 점검: {}** — {}  (바뀌는 조건: {})".format(kh.get("verdict", "-"), kh.get("reason", ""), kh.get("trigger", "-")))
    ur = brief.get("us_ranking") or []
    if ur:
        st.markdown("**미국 투자 후보 순위**")
        st.dataframe(pd.DataFrame([{"종목": u.get("name"), "매력": u.get("attractiveness"), "이유": u.get("why"), "반대 근거": u.get("counter")} for u in ur]), use_container_width=True, hide_index=True,
                     column_config={"이유": st.column_config.TextColumn("이유", width="large"), "반대 근거": st.column_config.TextColumn("반대 근거", width="large")})
    with st.expander("종목별 상태 · 주요 사건 · 위험 · 확인 못한 것"):
        cs = brief.get("companies") or []
        if cs:
            st.dataframe(pd.DataFrame([{"종목": x.get("name"), "상태": x.get("status"), "판단": x.get("view"), "반대 근거": x.get("counter")} for x in cs]), use_container_width=True, hide_index=True)
        for e in m.get("key_events") or []:
            if isinstance(e, dict):
                st.write("- {} ({} {})".format(e.get("what", ""), e.get("source", ""), e.get("date", "")))
        for r in brief.get("risks") or []:
            st.caption("위험: " + str(r))
        for u in brief.get("unknowns") or []:
            st.caption("확인 못함: " + str(u))


# ------------------------------------------------------------------ ① 내 돈
def _section_money(get_conn, fx, c, save_cfg):
    cma, usd = fxmod.balances(get_conn)[:2]
    reserve = int(float(c.get("fx_reserve", 0) or 0))
    st.markdown("#### 1. 내 돈")
    m1, m2, m3 = st.columns(3)
    m1.metric("CMA 원화", "{:,.0f}원".format(cma))
    m2.metric("달러 예수금", "${:,.2f}".format(usd), "{:,.0f}원 상당".format(usd * fx) if fx else None)
    m3.metric("투자에 쓸 수 있는 합계", "{:,.0f}원".format(max(0.0, cma - reserve) + max(0.0, usd) * (fx or 0)), "비상금 {:,.0f}원 제외".format(reserve) if reserve else None)
    if usd < -0.005 or cma < -0.5:
        st.error("잔액이 마이너스입니다. 기록이 꼬인 상태이니 아래 '설정·정리'에서 '잔액 맞추기'로 실제 잔액에 맞춰 주세요.")
    with st.expander("설정 · 잔액 맞추기 · 테스트 기록 정리"):
        t1, t2, t3 = st.tabs(["잔액 맞추기", "고급 설정", "기록 정리"])
        with t1:
            st.caption("증권사 앱에 보이는 실제 잔액을 그대로 넣으세요. 지금 기록과의 차이만큼 한 줄이 추가됩니다. 처음 시작할 때와 잔액이 어긋났을 때만 쓰면 됩니다.")
            with st.form("money_adjust"):
                a1, a2 = st.columns(2)
                w_krw = a1.number_input("CMA 원화 잔액", min_value=0.0, value=float(max(0, round(cma))), step=10000.0)
                w_usd = a2.number_input("달러 예수금 ($)", min_value=0.0, value=float(max(0.0, round(usd, 2))), step=1.0)
                ok = st.form_submit_button("이 값으로 맞추기")
            if ok:
                _ev(get_conn, "adjust", w_krw - cma, w_usd - usd, None, "잔액 맞추기")
                st.rerun()
        with t2:
            r1 = st.number_input("CMA 중 투자에 쓰지 않을 돈 (비상금·부채 상환 예정액, 원)", min_value=0, value=reserve, step=100000, key="ag_reserve")
            sp0 = float(c.get("fx_spread", 0.25) or 0.25)
            sp = st.number_input("증권사 환전 스프레드 (우대 반영, %)", min_value=0.0, max_value=3.0, value=sp0, step=0.05, key="ag_spread")
            if int(r1) != reserve or abs(sp - sp0) > 1e-9:
                if st.button("설정 저장", key="ag_save_set"):
                    save_cfg(get_conn, "fx_reserve", str(int(r1)))
                    save_cfg(get_conn, "fx_spread", str(float(sp)))
                    st.rerun()
            st.checkbox("계획 받을 때 뉴스를 새로 모으기 (끄면 30분 안에 모은 헤드라인 재사용)", value=False, key="ag_force")
        with t3:
            st.caption("테스트로 넣은 입금·환전·AI 계획·채팅 기록을 모두 지우고 처음부터 시작합니다. 지워지는 것: 예수금 기록, 입금 기록, AI 계획 기록, 채팅, 제안 성과 기록, 조절 기록. "
                       "**지워지지 않는 것: 보유 종목(국장·미국) 수량·평단, 거래·판단 기록, 기업 상태 메모.**")
            sure = st.checkbox("위 내용을 이해했고 지우겠습니다", key="ag_clean_ok")
            if st.button("테스트 기록 정리하기", key="ag_clean", disabled=not sure):
                for t_ in _CLEAN_TABLES:
                    try:
                        ai_agent._run(get_conn, "DELETE FROM " + t_)
                    except Exception:  # noqa: BLE001
                        pass
                st.session_state.pop("_strat_warn", None)
                st.rerun()
    return cma, usd


# ------------------------------------------------------------------ ② 계획 받기
def _run_plan(get_conn, items, risk, stress, fx, cfg_pk, cash_map, policy, strat, get_prices, c, new_dep, memo):
    cma, usd = fxmod.balances(get_conn)[:2]
    reserve = int(float(c.get("fx_reserve", 0) or 0))
    spread = float(c.get("fx_spread", 0.25) or 0.25)
    cma_av = max(0.0, cma - reserve)
    pool = int(cma_av + max(0.0, usd) * (fx or 0))
    pool_info = {"cma_krw": round(cma), "cma_available_krw": round(cma_av), "reserve_excluded_krw": reserve, "usd_cash_usd": round(max(0.0, usd), 2),
                 "usd_cash_krw": round(max(0.0, usd) * (fx or 0)), "new_deposit_today_krw": new_dep, "fx_spread_pct": spread, "total_pool_krw": pool}
    try:  # 과거 제안 성과와 지난번 복기를 AI에게 돌려준다(스스로 논리를 다듬는 고리)
        tr = ledger.track_record(get_conn, get_prices) if get_prices else None
        prev_review = ((strat or {}).get("master") or {}).get("track_record_review")
        st.session_state["_lessons"] = json.dumps({"track_record": tr, "previous_review": prev_review}, ensure_ascii=False)[:4000]
    except Exception:  # noqa: BLE001
        st.session_state["_lessons"] = None
    packet = S.build_packet(items, risk, stress, fx, cfg_pk, pool, memo, cash_map, c.get("policy_text") or S.DEFAULT_POLICY, strat, get_prices)
    packet["cash_pool"] = pool_info
    _bt, _bf = S.load_brief(get_conn)
    if _bf:
        packet["morning_briefing"] = {"written_at_utc": _bt, "content": {k: _bf.get(k) for k in ("headline", "market", "fx", "companies", "kr_hold_check", "us_ranking", "risks", "unknowns")}}
    packet["new_deposit"]["note"] = "amount_krw는 이번에 배분할 전체 가용 자금(CMA 사용 가능 원화 + 보유 달러의 원화 환산)이며, 오늘 새로 들어온 돈은 new_deposit_today_krw입니다."
    with st.spinner("뉴스를 모으고 전략을 짜는 중... (30초~1분)"):
        res, err, warns = S.make_strategy(get_conn, packet, items, pool, fx, force_research=bool(st.session_state.get("ag_force")))
    return err, warns


def _section_plan_form(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices):
    st.markdown("#### 2. 오늘 계획 받기")
    with st.form("plan_form"):
        d1, d2 = st.columns([1, 2])
        ev_date = d1.date_input("입금 날짜", value=date.today(), key="ag_dep_date")
        amt = d2.number_input("새로 입금한 돈 (원) — 입금이 없으면 0으로 두세요", min_value=0, value=0, step=100000, key="ag_dep_amt")
        go = st.form_submit_button("계획 받기", type="primary")
    st.caption("입금액만 넣으면 됩니다. 환전할지, 얼마를 어디에 투자할지, 얼마를 남길지는 AI가 정책 안에서 정합니다.")
    if not go:
        return
    new_dep = int(amt)
    if new_dep > 0:
        try:
            ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                          (_now(), ev_date.isoformat(), "deposit", new_dep, 0, None, "입금"))
            ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (ev_date.isoformat(), new_dep, "", _now()))
        except Exception as e:  # noqa: BLE001
            st.error("입금 기록 실패: " + str(e)[:100])
            return
    err, warns = _run_plan(get_conn, items, risk, stress, fx, cfg_pk, cash_map, None, strat, get_prices, c, new_dep, "")
    if err:
        st.error("전략을 만들지 못했습니다: " + err)
    else:
        st.session_state["_strat_warn"] = warns
        st.rerun()


# ------------------------------------------------------------------ ③ 계획 표시 + 확정
def _section_plan(get_conn, items, fx, cfg_pk, hub, sid, status, strat, created, c):
    for w in st.session_state.get("_strat_warn", []):
        st.warning(w)
    mstr = strat.get("master") or {}
    al = strat.get("allocation") or {}
    dep = int(strat.get("_deposit", 0) or 0)
    badge = {"confirmed": "주문 대기(확정됨)", "filled": "체결 반영 완료", "cancelled": "취소됨"}.get(status, "초안(아직 확정 전)")
    st.markdown("#### 3. 오늘의 계획")
    st.markdown("**{}**".format(strat.get("headline", "")))
    st.caption("상태: {} · 작성 {} UTC · 신뢰도 {}".format(badge, created[:16].replace("T", " "), strat.get("confidence", "-")))
    if strat.get("_research_ok"):
        cov = strat.get("_coverage") or []
        st.caption("뉴스 반영: 헤드라인 {}건 · 참조된 지정 기관·매체: {} (제목·매체·날짜만 읽음, 기사 본문은 읽지 못함)".format(strat.get("_headlines_total") or 0, ", ".join(cov) if cov else "없음"))
    else:
        st.error("뉴스 자료를 가져오지 못했습니다. 이 전략은 앱 자료(시세·점수·컨센서스)에만 근거하므로 참고만 하세요.")
    if strat.get("research_summary"):
        st.write(strat["research_summary"])
    if mstr.get("market_view") or al.get("market_view"):
        st.write("**시장 판단** — " + str(mstr.get("market_view") or al.get("market_view")))
    pl_ = None
    try:
        if dep > 0 and fx:
            pool_ = strat.get("_pool") or {}
            gap_ = max(0.0, float(cfg_pk.get("goal") or 0) - float(cfg_pk.get("invested") or 0))
            pl_ = fxmod.plan(al, fx, float(pool_.get("cma_available_krw", 0)), float(pool_.get("usd_cash_usd", 0)), float(pool_.get("fx_spread_pct", 0.25)), fxmod.fx_view(), strat.get("_ai_fx"), gap_)
            fxmod.render_plan(get_conn, pl_, dep, "p%s" % sid, with_form=False)
        elif dep <= 0:
            st.info("배분할 수 있는 돈이 없습니다(CMA·달러 예수금 0원). 위 '내 돈'에서 잔액을 맞추거나 입금액을 넣고 다시 계획을 받으세요.")
    except Exception as e:  # noqa: BLE001
        st.caption("자금 계획을 표시하지 못했습니다: " + str(e)[:100])
    ex = S.execution_rows(strat, items, fx, (pl_ or {}).get("us_scale", 1.0))
    if ex:
        df = pd.DataFrame(ex)
        main = [k for k in ("순위", "종목", "행동", "금액(원)", "금액(USD)", "수량", "현재가", "앱 규칙 판단(심리)", "근거") if k in df.columns]
        st.dataframe(df[main], use_container_width=True, hide_index=True,
                     column_config={"금액(원)": st.column_config.NumberColumn("금액(원)", format="%d"), "금액(USD)": st.column_config.NumberColumn("금액(USD)", format="$%.2f"),
                                    "근거": st.column_config.TextColumn("근거", width="large")})
        with st.expander("상세 근거표 (다른 후보와의 비교 · 3~5년 시나리오 · 증거 · 반대 근거 · 판단이 바뀌는 조건)"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    with st.expander("AI 전략 설명 · 정책과 다른 점 · 물타기 검토 · 위험"):
        for d_ in strat.get("policy_deviations") or []:
            st.warning("정책과 다른 제안: " + str(d_))
        for gc_ in (mstr.get("guideline_changes") or []):
            if isinstance(gc_, dict):
                st.info("가이드라인 조정 — {}: {} (근거: {} / 추가 위험: {} / 철회 조건: {})".format(gc_.get("guideline", ""), gc_.get("why", ""), gc_.get("evidence", ""), gc_.get("extra_risk", ""), gc_.get("revert_if", "")))
        st.write(mstr.get("summary", ""))
        for k, lab in (("phase_goal", "지금 단계 목표"), ("kr_policy", "국장"), ("us_policy", "미국"), ("core_policy", "코어(VOO·버크셔)"), ("tech_policy", "기술주"), ("cash_policy", "현금")):
            if mstr.get(k):
                st.markdown("**{}** — {}".format(lab, mstr[k]))
        if al.get("cash_reason"):
            st.markdown("**현금으로 남기는 이유** — " + str(al["cash_reason"]))
        if mstr.get("track_record_review"):
            st.markdown("**과거 제안 복기와 이번에 반영한 점** — " + str(mstr["track_record_review"]))
        ad = strat.get("avg_down_review") or []
        if ad:
            st.markdown("**손실 종목 물타기 검토**")
            st.dataframe(pd.DataFrame([{"종목": a.get("name"), "판정": a.get("verdict"), "회복 가능성 수치": a.get("recovery_pct_note"), "근거": a.get("reason"), "성립 조건": a.get("conditions")} for a in ad]),
                         use_container_width=True, hide_index=True)
        for r in mstr.get("risk_notes") or []:
            st.caption("위험: " + str(r))
        for u in strat.get("unknowns") or []:
            st.caption("확인 못함: " + str(u))
    checks_ = []
    if dep > 0:
        try:
            checks_ = S.verify_plan(strat, items, fx, pl_, bool(hub.get("freeze")))
        except Exception as e:  # noqa: BLE001
            checks_ = [{"등급": "필수", "항목": "검증 실행", "결과": "실패", "설명": str(e)[:100]}]
        hard_fail = [x for x in checks_ if x["등급"] == "필수" and x["결과"] != "통과"]
        soft = [x for x in checks_ if x["등급"] == "주의" and x["결과"] != "통과"]
        if hard_fail:
            st.error("자동 검증 실패 — " + ", ".join(x["항목"] for x in hard_fail) + " → 이 계획은 확정할 수 없습니다.")
        else:
            st.success("자동 검증 통과" + (" (주의 {}건: {})".format(len(soft), ", ".join(x["항목"] for x in soft)) if soft else ""))
        with st.expander("자동 검증 항목 전체"):
            st.dataframe(pd.DataFrame(checks_), use_container_width=True, hide_index=True)
    blocked = any(x["등급"] == "필수" and x["결과"] != "통과" for x in checks_)
    if status not in ("confirmed", "filled", "cancelled") and dep > 0:
        if st.button("이 계획으로 주문하기", key="ag_confirm", type="primary", disabled=blocked):
            try:
                _set_status(get_conn, sid, "confirmed")
                ledger.log_recs(get_conn, sid, strat, items, fx)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("반영하지 못했습니다: " + str(e)[:120])
        st.caption("'주문하기'는 계획을 확정·기록만 합니다. 실제 주문은 증권사 앱에서 하고, 체결되면 아래 4번에 입력하세요. 이 단계에서는 잔액이 바뀌지 않습니다.")
    return pl_


# ------------------------------------------------------------------ ④ 체결 반영
def _section_fill(get_conn, items, fx, sid, strat, pl_, apply_fill):
    by_tk = {i["tk"]: i for i in items}
    scale = (pl_ or {}).get("us_scale", 1.0)
    buys = []
    for p in strat.get("priorities") or []:
        it = by_tk.get(p.get("_item"))
        amt = int(p.get("amount_krw") or 0)
        if it and p.get("action") == "매수" and amt > 0 and it["cur"] == "USD" and it.get("price"):
            usd = amt * scale / fx if fx else 0.0
            buys.append((it, usd / it["price"], it["price"]))
    kr_buys = [p.get("name") for p in strat.get("priorities") or [] if p.get("action") == "매수" and int(p.get("amount_krw") or 0) > 0 and (by_tk.get(p.get("_item")) or {}).get("cur") == "KRW"]
    st.markdown("#### 4. 체결 반영 (주문이 체결된 뒤)")
    st.caption("보통 미국 주식은 예약주문 → 다음날 체결됩니다. 체결 내용을 아래에 입력하면 **보유 수량·평단, 달러·원화 예수금, 성과 기록이 한 번에 저장**됩니다. 미리 채워진 값은 계획 기준이니 실제 체결 값으로 고치세요. 체결이 안 된 종목은 수량을 0으로 두세요.")
    with st.form("fill_form_%s" % sid):
        e1, e2 = st.columns(2)
        ex_krw = e1.number_input("실제 환전한 원화 (환전 안 했으면 0)", min_value=0.0, value=float(round((pl_ or {}).get("exchange_total_krw", 0))), step=10000.0)
        ex_usd = e2.number_input("환전으로 받은 달러 ($)", min_value=0.0, value=float(round((pl_ or {}).get("usd_from_exchange", 0), 2)), step=1.0)
        rows = []
        for it, q, px in buys:
            f1, f2, f3 = st.columns([2, 1, 1])
            f1.markdown("**{}**  (계획 {:.4f}주)".format(it["name"], q))
            fq = f2.number_input("체결 수량", min_value=0.0, value=float(round(q, 4)), step=0.0001, format="%.4f", key="fq_%s_%s" % (sid, it["tk"]))
            fp = f3.number_input("체결 단가 ($)", min_value=0.0, value=float(round(px, 2)), step=0.01, key="fp_%s_%s" % (sid, it["tk"]))
            rows.append((it, fq, fp))
        c1, c2 = st.columns(2)
        ok = c1.form_submit_button("체결 내용 저장", type="primary")
        cancel = c2.form_submit_button("이번 계획은 주문하지 않음")
    if kr_buys:
        st.caption("국장 매수({})는 '보유·거래 입력' 탭에서 수량·평단을 직접 고쳐 주세요.".format(", ".join(map(str, kr_buys))))
    if cancel:
        _set_status(get_conn, sid, "cancelled")
        st.rerun()
    if not ok:
        return
    done = [(it, q, p) for it, q, p in rows if q > 0 and p > 0]
    cost = sum(q * p for _, q, p in done)
    cma, usd = fxmod.balances(get_conn)[:2]
    if ex_krw > cma + 0.5:
        st.error("환전한 원화({:,.0f}원)가 CMA 잔액({:,.0f}원)보다 큽니다. 잔액을 먼저 맞춰 주세요.".format(ex_krw, cma))
        return
    if cost > usd + ex_usd + 0.01:
        st.error("매수 금액(${:,.2f})이 사용 가능한 달러(${:,.2f})를 넘습니다. 환전 내용이나 체결 값을 확인하세요. (보유 달러를 넘는 매수는 기록할 수 없습니다)".format(cost, usd + ex_usd))
        return
    try:
        if ex_krw > 0 or ex_usd > 0:
            _ev(get_conn, "fx_done", -ex_krw, ex_usd, (ex_krw / ex_usd) if ex_usd else None, "AI 계획 환전")
        msgs = []
        spent_so_far = 0.0
        for it, q, p in done:
            okk, msg = apply_fill(get_conn, it["tk"], q, p)
            if not okk:
                st.error(msg)
                return
            spend = min(q * p, max(0.0, usd + ex_usd - spent_so_far))  # 반올림 때문에 생기는 1~2센트 차이는 잔액이 마이너스가 되지 않게 맞춤
            spent_so_far += spend
            _ev(get_conn, "usd_buy", 0, -spend, None, "{} 매수".format(it["name"]))
            ledger.record_fill(get_conn, sid, it["tk"], q, p)
            try:
                ai_agent._run(get_conn, "INSERT INTO adjust_log (created_at,trade_date,ticker,name,side,qty,price,currency,bucket,valuation,sentiment,weight_before,cash_change,reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                              (_now(), date.today().isoformat(), it["tk"], it["name"], "매수", q, p, "USD", "미분류", None, None, None, -(q * p * fx), "AI 계획 체결 반영"))
            except Exception:  # noqa: BLE001
                pass
            msgs.append(msg)
        _set_status(get_conn, sid, "filled")
        st.session_state["_fill_flash"] = "체결을 반영했습니다 — " + " / ".join(msgs) if msgs else "환전만 반영했습니다."
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error("저장 중 문제가 생겼습니다: " + str(e)[:150] + " — 내 돈 잔액과 보유 수량을 확인하세요.")


# ------------------------------------------------------------------ 채팅
def _section_chat(get_conn, items, risk, stress, fx, cfg_pk, dep, cash_map, c, strat, get_prices):
    st.markdown("#### 펀드매니저와 의견 나누기")
    hist = S._load_chat(get_conn)
    for h in hist[-10:]:
        with st.chat_message("user" if h["role"] == "user" else "assistant"):
            st.write(h["text"])
    msg = st.chat_input("의견을 적어 주세요 (예: 오늘 엔비디아가 빠진 이유가 일시적인지 찾아보고 비중을 다시 짜줘)", key="mgr_chat")
    if msg:
        packet = S.build_packet(items, risk, stress, fx, cfg_pk, dep, "", cash_map, c.get("policy_text") or S.DEFAULT_POLICY, None, get_prices)
        S._log_chat(get_conn, "user", msg)
        with st.spinner("펀드매니저가 확인하고 답을 정리하는 중..."):
            out, err, warns = S.chat_reply(get_conn, packet, strat, hist, msg, items, fx)
        if err:
            st.error("답을 받지 못했습니다: " + err)
        else:
            text = out["reply"] + ("\n\n(전략이 수정되어 새 초안으로 저장했습니다. 위에서 확인 후 주문하세요.)" if out["revised"] else "")
            S._log_chat(get_conn, "assistant", text)
            st.session_state["_strat_warn"] = warns
            st.rerun()


# ------------------------------------------------------------------ 진입점
def render(get_conn, items, risk, stress, fx, cfg, cash_map, save_cfg, load_cfg, hub, get_prices=None, apply_fill=None):
    S.ensure_tables(get_conn)
    fxmod.ensure_tables(get_conn)
    ledger.ensure_tables(get_conn)
    S.ensure_brief_table(get_conn)
    c = load_cfg(get_conn)
    if c.get("policy_ver") != S.POLICY_VER:  # 예전 정책(고정 비율 포함)을 새 정책으로 교체
        save_cfg(get_conn, "policy_text", S.DEFAULT_POLICY)
        save_cfg(get_conn, "policy_ver", S.POLICY_VER)
        c = dict(c)
        c["policy_text"] = S.DEFAULT_POLICY
    cfg_pk = {"goal": hub.get("goal"), "invested": hub.get("invested"), "band": st.session_state.get("_ai_band"), "freeze": hub.get("freeze"), "core": hub.get("core")}
    try:
        _l = S.load_latest(get_conn)
        st.session_state["_fx_packet"] = fxmod.packet_part(get_conn, fxmod.fx_view(), (_l[2] or {}).get("_ai_fx") if _l and _l[2] else None)
    except Exception:  # noqa: BLE001
        pass
    st.markdown("### AI 투자 에이전트")
    st.caption("접속하면 AI가 먼저 시장·뉴스·내 보유를 조사해 브리핑을 만들고, 입금액을 넣으면 그 브리핑을 근거로 환전·투자·남길 돈까지 계획합니다. 주문은 내가 하고, 체결 내용을 입력하면 모든 기록이 한 번에 저장됩니다. "
               "AI에는 종목명·비중·수량·평단·평가금액·현금·정책 메모를 보냅니다(계좌번호·로그인·이름은 보내지 않음). 무료 API 입력은 구글 서비스 개선에 쓰일 수 있습니다.")
    policy = c.get("policy_text") or S.DEFAULT_POLICY
    with st.expander("내 투자 정책 (큰 방향만 — 비율은 AI가 정함)"):
        with st.form("policy_text_form"):
            txt = st.text_area("정책", value=policy, height=260, key="policy_text_area")
            c_a, c_b = st.columns(2)
            if c_a.form_submit_button("정책 저장"):
                save_cfg(get_conn, "policy_text", txt)
                st.rerun()
            if c_b.form_submit_button("기본 문구로 되돌리기"):
                save_cfg(get_conn, "policy_text", S.DEFAULT_POLICY)
                st.rerun()
    with st.expander("검색 조사 대상으로 지정한 기관·매체·인물"):
        for k_, v_ in S.SOURCES.items():
            st.markdown("**{}** — {}".format(k_, ", ".join(v_)))
    flash = st.session_state.pop("_fill_flash", None)
    if flash:
        st.success(flash)
    _section_brief(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, get_prices)
    st.divider()
    st.caption("↑ 위는 시장·기업 자료(접속하면 자동 갱신), ↓ 아래는 내 돈을 넣고 배분하는 곳입니다. 배분은 위 브리핑을 근거로 합니다.")
    _section_money(get_conn, fx, c, save_cfg)
    sid, status, strat, created = S.load_latest(get_conn)
    _section_plan_form(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices)
    if not strat:
        st.info("아직 계획이 없습니다. 위에서 '계획 받기'를 누르세요(입금이 없으면 0원으로 두고 누르면 됩니다).")
        return None
    pl_ = _section_plan(get_conn, items, fx, cfg_pk, hub, sid, status, strat, created, c)
    if status == "confirmed" and apply_fill is not None:
        _section_fill(get_conn, items, fx, sid, strat, pl_, apply_fill)
    elif status == "filled":
        st.success("이 계획의 체결이 반영되었습니다. 성과는 며칠~몇 주 뒤 아래 '기록·성적표'에서 시장과 비교해 볼 수 있고, 다음 계획 때 AI가 그 결과를 읽습니다.")
    _section_chat(get_conn, items, risk, stress, fx, cfg_pk, int(strat.get("_deposit", 0) or 0), cash_map, c, strat, get_prices)
    return strat if status == "confirmed" else None
