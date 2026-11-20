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
import journal
import ledger
import strategist as S

DEFAULT_WATCH = [{"tk": "069500.KS", "name": "KODEX 200", "mkt": "한국", "cur": "KRW"}]


def _watch_list(cfg):
    try:
        w = json.loads(cfg.get("watchlist") or "null")
        return w if isinstance(w, list) else DEFAULT_WATCH
    except Exception:  # noqa: BLE001
        return DEFAULT_WATCH


def watch_items(get_prices, items, cfg):
    """보유하지 않은 관심 후보(기본: KODEX 200)를 보유 수량 0인 종목으로 만든다. 에이전트가 신규 매수 후보로 비교하고, 매매 기록에서도 고를 수 있다."""
    held = {i["tk"] for i in items}
    out = []
    for w in _watch_list(cfg):
        tk = str(w.get("tk", "")).strip()
        if not tk or tk in held:
            continue
        px = None
        try:
            df, _ = get_prices(tk, "5d")
            px = float(df["Close"].dropna().iloc[-1])
        except Exception:  # noqa: BLE001
            px = None
        out.append(dict(mkt=w.get("mkt", "한국"), tk=tk, dbtk=tk, name=w.get("name", tk), mode="신규 후보", qty=0.0, avg=0.0, cur=w.get("cur", "KRW"), price=px, value=0.0,
                        ret=None, score=None, plabel="-", sv_txt="미확인", sv_val="미확인", outlook="미확인", target=None, weight=None, kind="watch", label="관심 후보", is_candidate=True))
    return out


def _my_notes(get_conn):
    """기업 상태 기록·최근 판단 기록을 에이전트에 전달한다(앱 안에 쌓인 내 기록)."""
    out = {}
    try:
        st_ = ai_agent._run(get_conn, "SELECT ticker, stance, as_of, memo, invalidation FROM stance_log ORDER BY id DESC LIMIT 40", fetch=True)
        seen, rows = set(), []
        for _, r in st_.iterrows():
            if r["ticker"] in seen:
                continue
            seen.add(r["ticker"])
            rows.append({"ticker": r["ticker"], "stance": r["stance"], "as_of": str(r["as_of"])[:10], "memo": str(r["memo"] or "")[:200], "invalidation": str(r["invalidation"] or "")[:120]})
        out["company_stance_records"] = rows
    except Exception:  # noqa: BLE001
        pass
    try:
        dc = ai_agent._run(get_conn, "SELECT created_at, ticker, decision, thesis FROM decisions ORDER BY created_at DESC LIMIT 15", fetch=True)
        out["recent_decisions"] = [{"date": str(r["created_at"])[:10], "ticker": r["ticker"], "decision": r["decision"], "thesis": str(r["thesis"] or "")[:150]} for _, r in dc.iterrows()]
    except Exception:  # noqa: BLE001
        pass
    return out


_CLEAN_TABLES = ["fx_events", "cash_events", "strategy_log", "chat_log", "rec_log", "adjust_log", "cash_balance", "brief_log"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ev(get_conn, kind, krw, usd, rate=None, memo=""):
    ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (_now(), date.today().isoformat(), kind, float(krw), float(usd), rate, memo))


def _set_status(get_conn, sid, status):
    ai_agent._run(get_conn, "UPDATE strategy_log SET status=%s WHERE id=%s", (status, sid))



# ------------------------------------------------------------------ 시장·기업 브리핑 (맨 위, 접속하면 자동 갱신)
BRIEF_HOURS = 3


def _kst(ts):
    """UTC 문자열 -> 'MM-DD HH:MM KST'"""
    try:
        from datetime import timedelta
        d = datetime.fromisoformat(str(ts))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M") + " 한국시간"
    except Exception:  # noqa: BLE001
        return str(ts)[:16]


def _age_hours(ts):
    try:
        t = datetime.fromisoformat(str(ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return 9999.0


def _section_brief(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, get_prices):
    st.markdown("#### 시장·기업 브리핑 (누를 때마다 그 시점의 최신 뉴스로 새로 작성)")
    ts, brief = S.load_brief(get_conn)
    stale = brief is None or _age_hours(ts) > BRIEF_HOURS
    c1, c2 = st.columns([1, 4])
    manual = c1.button("지금 새로 조사", key="ag_brief_now")
    tried = st.session_state.get("_brief_tried")
    if manual or (stale and not tried):
        st.session_state["_brief_tried"] = True
        try:
            packet, _pool = _base_packet(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, None, get_prices)
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
    c2.caption("작성 {} ({}) · 뉴스 헤드라인 {}건 · 참조 매체: {} · 제목·매체·날짜만 읽음(본문 못 읽음). 접속할 때 {}시간이 지났으면 자동으로 새로 조사합니다.".format(
        _kst(ts), "방금" if age < 0.1 else "{:.0f}시간 전".format(age), brief.get("_headlines_total") or 0, ", ".join(brief.get("_coverage") or []) or "없음", BRIEF_HOURS))
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
    st.markdown("#### 1. 내 돈 (입금 → 환전 → 계획 → 매매 기록 순서로 진행)")
    import assets
    assets.render_money(get_conn, fx, c, "ag_", adjust=False)
    with st.expander("설정 · 잔액 맞추기 · 테스트 기록 정리"):
        t1, t2, t4, t3 = st.tabs(["잔액 맞추기", "고급 설정", "관심 후보", "기록 정리"])
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
            st.caption("계획·브리핑은 누를 때마다 최신 뉴스를 새로 모읍니다(별도 설정 없음).")
        with t4:
            st.caption("보유하지 않았지만 에이전트가 매번 함께 비교할 종목입니다(기본: KODEX 200). 야후 파이낸스 코드로 추가하세요. 예: 069500.KS, 005930.KS, QQQ")
            wl = _watch_list(c)
            for w_ in wl:
                st.write("- {} ({})".format(w_.get("name"), w_.get("tk")))
            n1, n2, n3 = st.columns([1.2, 1.5, 1])
            ntk = n1.text_input("티커", key="wl_tk")
            nnm = n2.text_input("이름", key="wl_nm")
            if n3.button("추가", key="wl_add") and ntk.strip():
                tk_ = ntk.strip()
                kr_ = tk_.endswith((".KS", ".KQ"))
                wl = [w for w in wl if w.get("tk") != tk_] + [{"tk": tk_, "name": nnm.strip() or tk_, "mkt": "한국" if kr_ else "미국", "cur": "KRW" if kr_ else "USD"}]
                save_cfg(get_conn, "watchlist", json.dumps(wl, ensure_ascii=False))
                st.rerun()
            if wl:
                rm = st.selectbox("목록에서 뺄 종목", ["(선택 안 함)"] + [w.get("name") for w in wl], key="wl_rm")
                if rm != "(선택 안 함)" and st.button("뺀다", key="wl_rm_btn"):
                    save_cfg(get_conn, "watchlist", json.dumps([w for w in wl if w.get("name") != rm], ensure_ascii=False))
                    st.rerun()
        with t3:
            st.caption("테스트로 넣은 입금·환전·AI 계획·채팅 기록을 모두 지우고 처음부터 시작합니다. 지워지는 것: 예수금 기록, 입금 기록, AI 계획·브리핑 기록, 채팅, 제안 성과 기록, 조절 기록. **매매 일지는 지우지 않습니다.** "
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
def _base_packet(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices, new_dep=0, memo=""):
    """계획·브리핑·대화가 모두 같은 자료를 읽도록 한 곳에서 만든다(포트폴리오·돈·정책·브리핑·내 기록·매매 일지·성적표·기술 지표·지수 숫자). -> (packet, pool)"""
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
    try:
        st.session_state["_journal"] = json.dumps(journal.summarize(get_conn, get_prices), ensure_ascii=False)[:4000]
    except Exception:  # noqa: BLE001
        st.session_state["_journal"] = None
    packet = S.build_packet(items, risk, stress, fx, cfg_pk, pool, memo, cash_map, c.get("policy_text") or S.DEFAULT_POLICY, strat, get_prices)
    packet["my_notes"] = _my_notes(get_conn)
    try:
        import assets
        packet["cash_ledger_recent"] = assets.ledger_for_agent(get_conn, 25)
        packet["accounts_summary"] = assets.account_summary(items, fx)
        jdf = journal.load(get_conn, 400)
        _bt0, _ = S.load_brief(get_conn)
        _ar = S.load_archive(get_conn)
        packet["app_manifest"] = {
            "note": "이 목록이 당신(펀드매니저 AI)이 실제로 읽는 앱 자료의 전부입니다. 여기에 없는 것은 볼 수 없습니다. 당신은 앱의 숫자를 직접 바꾸거나 주문할 수 없고, 기록은 사용자가 입력합니다. 모델 자체가 학습하는 것이 아니라 매 호출마다 아래 기록의 요약을 읽습니다.",
            "pages_and_data": {"에이전트 탭": "브리핑·계획·이 대화", "내 포트폴리오 탭": "계좌별 보유·예수금·입금/환전·매매 기록(이유 포함)", "종목 분석 탭": "앱 점수·달걀 국면·코스톨라니 심리(packet의 holdings/sentiment로 전달)", "기록·복기 탭": "매매 일지·제안 성과(my_trade_journal/past_lessons로 전달)"},
            "counts": {"trade_journal_rows": 0 if jdf is None else int(len(jdf)), "archive_days": len(_ar), "last_brief_utc": _bt0, "cash_ledger_rows_shown": len(packet["cash_ledger_recent"])},
            "learning_status": "통계적 복기는 평가 가능한 매매(10일 경과) 30건 이상부터 의미가 있습니다. 그 전에는 기록을 읽고 참고만 합니다."}
    except Exception:  # noqa: BLE001
        pass
    packet["archive"] = {"note": "앱이 접속할 때마다 쌓은 과거 기록(날짜별 지수 숫자 시작/마지막, 브리핑·계획 요약). 오늘 자료와 비교해 흐름을 보되 과거 문장의 사실을 현재 사실로 쓰지 마세요.", "days": S.load_archive(get_conn)}
    packet["cash_pool"] = pool_info
    _bt, _bf = S.load_brief(get_conn)
    if _bf:
        packet["morning_briefing"] = {"written_at_utc": _bt, "content": {k: _bf.get(k) for k in ("headline", "market", "fx", "companies", "kr_hold_check", "us_ranking", "risks", "unknowns")}}
    packet["new_deposit"]["note"] = "amount_krw는 이번에 배분할 전체 가용 자금(CMA 사용 가능 원화 + 보유 달러의 원화 환산)이며, 오늘 새로 들어온 돈은 new_deposit_today_krw입니다."
    return packet, pool


def _run_plan(get_conn, items, risk, stress, fx, cfg_pk, cash_map, policy, strat, get_prices, c, new_dep, memo):
    warns0 = []
    _bts, _bold = S.load_brief(get_conn)
    _need = (_bold is None) or _age_hours(_bts) > 0.25
    with st.spinner("최신 뉴스·지수를 새로 모으는 중... (1~2분)" if _need else "방금 만든 브리핑 자료를 이어 쓰는 중..."):
        try:  # 1) 브리핑을 먼저 새로 만든다(실패해도 계획은 계속 진행)
            berr = None
            if _need:
                bp, _p = _base_packet(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, None, get_prices)
                _nb, berr, _bw = S.make_brief(get_conn, bp, force=True)
            if berr:
                warns0.append("브리핑 새로 쓰기 실패(이전 브리핑은 계획 근거에서 제외): " + str(berr)[:100])
        except Exception as e:  # noqa: BLE001
            warns0.append("브리핑 새로 쓰기 중 문제: " + str(e)[:100])
    packet, pool = _base_packet(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices, new_dep, memo)
    if warns0:
        packet.pop("morning_briefing", None)
    with st.spinner("새 전략을 짜는 중... (30초~1분)"):
        res, err, warns = S.make_strategy(get_conn, packet, items, pool, fx, force_research=True)
    return err, warns0 + list(warns or [])


def _section_plan_form(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices):
    st.markdown("#### 2. 오늘 계획 받기")
    st.caption("위 '내 돈'에 기록된 잔액 전체가 재원입니다. 일반계좌 달러는 미장 투자금으로, CMA 원화는 국장(ISA)과 미장(필요하면 환전) 어디에든 쓸 수 있는 돈으로 보고 배분합니다. 입금·환전은 위에서 먼저 기록하세요.")
    go = st.button("계획 받기", type="primary", key="ag_plan_go")
    if not go:
        return
    err, warns = _run_plan(get_conn, items, risk, stress, fx, cfg_pk, cash_map, None, strat, get_prices, c, 0, "")
    if err:
        st.error("새 계획을 만들지 못했습니다: {} — 아래 계획은 이전에 만든 것(작성 시각 확인)이며 오늘 자료가 아닙니다. 잠시 뒤 다시 눌러 주세요.".format(err))
    else:
        st.session_state["_strat_warn"] = warns
        st.session_state["_plan_flash"] = "새 계획을 방금 만들었습니다(최신 뉴스·지수 기준, 브리핑도 함께 갱신)."
        st.session_state["_brief_tried"] = True
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
    st.caption("상태: {} · 작성 {} · 신뢰도 {}".format(badge, _kst(created), strat.get("confidence", "-")))
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
        _p0 = strat.get("_pool") or {}
        _cma_now, _usd_now = fxmod.balances(get_conn)[:2]
        if _p0 and (abs(_cma_now - float(_p0.get("cma_krw", _cma_now))) > 1 or abs(_usd_now - float(_p0.get("usd_cash_usd", _usd_now))) > 0.01):
            st.warning("이 계획은 잔액이 바뀌기 전에 만든 것입니다(계획 당시 CMA {:,.0f}원·${:,.2f} → 지금 CMA {:,.0f}원·${:,.2f}). 숫자가 어긋나 보이면 '계획 받기'를 다시 눌러 새로 받으세요.".format(
                float(_p0.get("cma_krw", 0)), float(_p0.get("usd_cash_usd", 0)), _cma_now, _usd_now))
        if dep > 0 and fx:
            pool_ = strat.get("_pool") or {}
            gap_ = max(0.0, float(cfg_pk.get("goal") or 0) - float(cfg_pk.get("invested") or 0))
            pl_ = fxmod.plan(al, fx, float(pool_.get("cma_available_krw", 0)), float(pool_.get("usd_cash_usd", 0)), float(pool_.get("fx_spread_pct", 0.25)), fxmod.fx_view(), strat.get("_ai_fx"), 0)
            fxmod.render_plan(get_conn, pl_, dep, "p%s" % sid, with_form=False)
        elif dep <= 0:
            st.info("배분할 수 있는 돈이 없습니다(CMA·달러 예수금 0원). 위 '내 돈'에서 잔액을 맞추거나 입금액을 넣고 다시 계획을 받으세요.")
    except Exception as e:  # noqa: BLE001
        st.caption("자금 계획을 표시하지 못했습니다: " + str(e)[:100])
    ex = S.execution_rows(strat, items, fx, (pl_ or {}).get("us_scale", 1.0))
    if ex:
        df = pd.DataFrame(ex)
        main = [k for k in ("순위", "종목", "행동", "금액(원)", "금액(USD)", "수량", "현재가", "지정가 계획(국내)", "앱 규칙 판단(심리)", "근거") if k in df.columns]
        st.dataframe(df[main], use_container_width=True, hide_index=True,
                     column_config={"금액(원)": st.column_config.NumberColumn("금액(원)", format="%d"), "금액(USD)": st.column_config.NumberColumn("금액(USD)", format="$%.2f"),
                                    "근거": st.column_config.TextColumn("근거", width="large")})
        with st.expander("상세 근거표 (다른 후보와의 비교 · 3~5년 시나리오 · 증거 · 반대 근거 · 판단이 바뀌는 조건)"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    for nc in strat.get("new_candidates") or []:
        if isinstance(nc, dict) and nc.get("name"):
            st.info("새 후보 제안(앱에 없음, 배분에는 넣지 않음): **{}** {} — {} / 위험: {}  → 마음에 들면 위 '설정 → 관심 후보'에서 티커로 추가하세요.".format(nc.get("name"), nc.get("ticker_hint") or "", nc.get("why", ""), nc.get("risk", "")))
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
def _section_fill(get_conn, items, fx, sid, strat, pl_, apply_trade):
    by_tk = {i["tk"]: i for i in items}
    scale = (pl_ or {}).get("us_scale", 1.0)
    buys = []  # (item, 계획 수량, 계획 단가, 이유)
    for p in strat.get("priorities") or []:
        it = by_tk.get(p.get("_item"))
        amt = int(p.get("amount_krw") or 0)
        if not (it and p.get("action") == "매수" and amt > 0):
            continue
        why = str(p.get("reason") or "")[:70]
        if it["cur"] == "USD" and it.get("price"):
            buys.append((it, (amt * scale / fx if fx else 0.0) / it["price"], it["price"], why))
        elif it["cur"] == "KRW":
            lp = p.get("limit_plan") or {}
            try:
                px = float(str(lp.get("first_price")).replace(",", "")) if lp.get("first_price") else float(it.get("price") or 0)
            except Exception:  # noqa: BLE001
                px = float(it.get("price") or 0)
            if px > 0:
                buys.append((it, float(int(amt // px)), px, why))
    st.markdown("#### 4. 체결 반영 (주문이 체결된 뒤)")
    st.caption("체결 내용을 아래에 입력하면 **보유 수량·평단, 달러·원화 예수금, 매매 일지, 성과 기록이 한 번에 저장**됩니다. 미리 채워진 값은 계획 기준(국내는 1차 지정가)이니 실제 체결 값으로 고치세요. "
               "**체결이 안 된 종목은 수량을 0으로 두세요.** 미체결은 실패가 아닙니다. 당일 가격을 올려 다시 사지 말고 다음 거래일에 새 계획을 받으세요.")
    with st.form("fill_form_%s" % sid):
        e1, e2 = st.columns(2)
        ex_krw = e1.number_input("실제 환전한 원화 (환전 안 했으면 0)", min_value=0.0, value=float(round((pl_ or {}).get("exchange_total_krw", 0))), step=10000.0)
        ex_usd = e2.number_input("환전으로 받은 달러 ($)", min_value=0.0, value=float(round((pl_ or {}).get("usd_from_exchange", 0), 2)), step=1.0)
        rows = []
        for it, q, px, why in buys:
            us_ = it["cur"] == "USD"
            f1, f2, f3, f4 = st.columns([2, 1, 1, 2])
            f1.markdown("**{}**  (계획 {})".format(it["name"], "{:.4f}주".format(q) if us_ else "{:g}주".format(q)))
            fq = f2.number_input("체결 수량", min_value=0.0, value=float(round(q, 4)), step=0.0001 if us_ else 1.0, format="%.4f" if us_ else "%.0f", key="fq_%s_%s" % (sid, it["tk"]))
            fp = f3.number_input("체결 단가 ($)" if us_ else "체결 단가 (원)", min_value=0.0, value=float(round(px, 2)), step=0.01 if us_ else 10.0, key="fp_%s_%s" % (sid, it["tk"]))
            fr = f4.text_input("이유 (고치면 일지에 저장)", value=why, key="fr_%s_%s" % (sid, it["tk"]))
            rows.append((it, fq, fp, fr))
        c1, c2 = st.columns(2)
        ok = c1.form_submit_button("체결 내용 저장", type="primary")
        cancel = c2.form_submit_button("이번 계획은 주문하지 않음")
    if not buys:
        st.caption("이번 계획에는 매수 주문이 없습니다. 환전만 했다면 위 칸에 환전액을 넣고 저장하세요. 매도는 '내 포트폴리오' 탭의 매매 기록에서 남깁니다.")
    if cancel:
        _set_status(get_conn, sid, "cancelled")
        st.rerun()
    if not ok:
        return
    done = [(it, q, p, r) for it, q, p, r in rows if q > 0 and p > 0]
    cma, usd = fxmod.balances(get_conn)[:2]
    cost_usd = sum(q * p for it, q, p, _ in done if it["cur"] == "USD")
    cost_krw = sum(q * p for it, q, p, _ in done if it["cur"] == "KRW")
    if ex_krw > cma + 0.5:
        st.error("환전한 원화({:,.0f}원)가 CMA 잔액({:,.0f}원)보다 큽니다. 잔액을 먼저 맞춰 주세요.".format(ex_krw, cma))
        return
    if cost_usd > usd + ex_usd + 0.01:
        st.error("미국 매수 금액(${:,.2f})이 사용 가능한 달러(${:,.2f})를 넘습니다. 환전 내용이나 체결 값을 확인하세요. (보유 달러를 넘는 매수는 기록할 수 없습니다)".format(cost_usd, usd + ex_usd))
        return
    if cost_krw > cma - ex_krw + 0.5:
        st.error("국내 매수 금액({:,.0f}원)이 원화 예수금({:,.0f}원)을 넘습니다.".format(cost_krw, cma - ex_krw))
        return
    try:
        if ex_krw > 0 or ex_usd > 0:
            _ev(get_conn, "fx_done", -ex_krw, ex_usd, (ex_krw / ex_usd) if ex_usd else None, "AI 계획 환전")
        msgs = []
        spent_so_far = 0.0
        for it, q, p, r in done:
            good, msg = journal.record_trade(get_conn, apply_trade, it, "매수", q, p, date.today(), r or "AI 계획 체결", journal.FOLLOW[0], True, False, sid, "에이전트 계획 체결")
            if not good:
                st.error(msg)
                return
            if it["cur"] == "USD":
                spend = min(q * p, max(0.0, usd + ex_usd - spent_so_far))  # 반올림 때문에 생기는 1~2센트 차이는 잔액이 마이너스가 되지 않게 맞춤
                spent_so_far += spend
                _ev(get_conn, "usd_buy", 0, -spend, None, "{} 매수".format(it["name"]))
            else:
                _ev(get_conn, "kr_buy", -(q * p), 0, None, "{} 매수".format(it["name"]))
            msgs.append(msg)
        _set_status(get_conn, sid, "filled")
        st.session_state["_ctx_dirty"] = True
        st.session_state["_fill_flash"] = "체결을 반영했습니다 — " + " / ".join(msgs) if msgs else "환전만 반영했습니다."
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error("저장 중 문제가 생겼습니다: " + str(e)[:150] + " — 내 돈 잔액과 보유 수량을 확인하세요.")


# ------------------------------------------------------------------ 채팅
def _section_chat(get_conn, items, risk, stress, fx, cfg_pk, dep, cash_map, c, strat, get_prices):
    st.markdown("#### 펀드매니저와 대화")
    st.caption("투자·시장에 관한 어떤 이야기든 가능합니다. 답을 쓸 때 앱이 방금 가져온 지수 숫자와 뉴스 제목, 내 포트폴리오·돈·정책·매매 일지·브리핑을 모두 읽고, 낙관과 비관 근거를 함께 제시하도록 설정되어 있습니다. 계획을 바꾸려면 '계획 다시 짜줘'라고 분명히 말해 주세요.")
    hist = S._load_chat(get_conn)
    for h in hist[-10:]:
        with st.chat_message("user" if h["role"] == "user" else "assistant"):
            st.write(h["text"])
    if hist:
        dc1, dc2 = st.columns([1, 4])
        if dc1.button("대화 모두 지우기", key="chat_clear"):
            st.session_state["_chat_clear_ask"] = True
        if st.session_state.get("_chat_clear_ask"):
            st.warning("지난 대화를 모두 지웁니다(AI 계획과 매매 기록은 그대로). 계속할까요?")
            y1, y2 = st.columns(2)
            if y1.button("네, 지웁니다", key="chat_clear_yes", type="primary"):
                S.clear_chat(get_conn)
                st.session_state["_chat_clear_ask"] = False
                st.rerun()
            if y2.button("취소", key="chat_clear_no"):
                st.session_state["_chat_clear_ask"] = False
                st.rerun()
    msg = st.chat_input("투자·시장에 관한 무엇이든 물어보세요 (예: 지금 코스피 상황과 내 계좌 위험을 균형 있게 설명해줘)", key="mgr_chat")
    if msg:
        packet, _pool = _base_packet(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices, 0, "")
        S._log_chat(get_conn, "user", msg)
        with st.spinner("지수·뉴스를 확인하고 답을 정리하는 중..."):
            out, err, warns = S.chat_reply(get_conn, packet, strat, hist, msg, items, fx)
        if err:
            st.error("답을 받지 못했습니다: " + err)
            return
        text = out["reply"]
        if out.get("headlines"):
            text += "\n\n참고한 헤드라인(제목·매체·날짜만): " + " / ".join("{} ({} {})".format(h["title"][:50], h["source"], h["date"]) for h in out["headlines"][:5])
        if out.get("wants_revision"):
            err2, w2 = _run_plan(get_conn, items, risk, stress, fx, cfg_pk, cash_map, None, strat, get_prices, c, 0, "사용자 요청에 따른 재작성: " + msg[:300])
            text += "\n\n" + ("(계획을 다시 짜지 못했습니다: {})".format(err2) if err2 else "(요청에 따라 계획을 새 초안으로 다시 만들었습니다. 위에서 확인 후 주문하세요.)")
            warns = (warns or []) + (w2 or [])
        S._log_chat(get_conn, "assistant", text)
        st.session_state["_strat_warn"] = warns
        st.rerun()


# ------------------------------------------------------------------ 진입점
def _section_record(get_conn, items, fx, apply_trade):
    import assets
    st.markdown("#### 4. 매매 기록 · 내 보유")
    st.caption("플랜대로(또는 다르게) 매매했다면 체결 결과를 기록하세요. 저장하면 아래 보유 수량·평단, 계좌별 예수금(미국=달러, 국내=원화)이 바로 바뀌고, 이유는 에이전트가 읽고 복기합니다.")
    if apply_trade is not None:
        try:
            journal.render_entry(get_conn, [dict(i) for i in items], apply_trade, "ag_te_")
        except Exception as e:  # noqa: BLE001
            st.error("매매 기록 화면을 표시하지 못했습니다: " + str(e)[:120])
    assets.render_holdings(items, fx)


def render(get_conn, items, risk, stress, fx, cfg, cash_map, save_cfg, load_cfg, hub, get_prices=None, apply_trade=None):
    S.ensure_tables(get_conn)
    fxmod.ensure_tables(get_conn)
    ledger.ensure_tables(get_conn)
    S.ensure_brief_table(get_conn)
    S.archive_numbers(get_conn)
    c = load_cfg(get_conn)
    if get_prices is not None:
        items = list(items) + watch_items(get_prices, items, c)  # 관심 후보(예: KODEX 200)도 에이전트가 함께 비교한다
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
    _bt0, _b0 = S.load_brief(get_conn)
    with st.expander("오늘 AI가 고른 주목 인물·기관 (뉴스를 보고 매번 새로 선정)"):
        _f0 = (_b0 or {}).get("_focus") or []
        if _f0:
            for f_ in _f0:
                st.markdown("**{}** — {}".format(f_.get("name", ""), f_.get("why", "")))
            st.caption("선정 시각: " + _kst(_bt0) + ". 이 선정에 따라 후속 검색어도 자동으로 만들어 추가 조사합니다.")
        else:
            st.caption("아직 없습니다(브리핑을 새로 만들면 채워집니다).")
    with st.expander("기본 조사 대상 목록 (고정 출발점 — 위 자동 선정이 매번 보완)"):
        for k_, v_ in S.SOURCES.items():
            st.markdown("**{}** — {}".format(k_, ", ".join(v_)))
    pf_ = st.session_state.pop("_plan_flash", None)
    if pf_:
        st.success(pf_)
    flash = st.session_state.pop("_fill_flash", None)
    if flash:
        st.success(flash)
    _section_brief(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, get_prices)
    with st.expander("에이전트 아카이브 (날마다 쌓이는 장기 기억)"):
        _arc = S.load_archive(get_conn)
        st.caption("접속할 때마다 지수·환율·금리 숫자와 브리핑·계획의 핵심을 저장합니다. AI가 바빠도 숫자 기록은 계속 쌓이고, 계획·브리핑·대화 때 에이전트가 이 기록을 읽습니다. 지금 {}일치.".format(len(_arc)))
        _rows = []
        for d_ in reversed(_arc):
            n_ = d_.get("numbers_last") or {}
            v_ = d_.get("view") or {}
            _rows.append({"날짜": d_["date"], "코스피": (n_.get("코스피") or {}).get("last"), "S&P500": (n_.get("S&P500") or {}).get("last"), "환율": (n_.get("원달러환율") or {}).get("last"),
                          "VIX": (n_.get("VIX(공포지수)") or {}).get("last"), "그날의 요약": v_.get("headline"), "분위기": v_.get("mood")})
        if _rows:
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
    st.divider()
    st.caption("↑ 위는 시장·기업 자료(접속하면 자동 갱신), ↓ 아래는 내 돈을 넣고 배분하는 곳입니다. 배분은 위 브리핑을 근거로 합니다.")
    _section_money(get_conn, fx, c, save_cfg)
    sid, status, strat, created = S.load_latest(get_conn)
    _section_plan_form(get_conn, items, risk, stress, fx, cfg_pk, cash_map, c, strat, get_prices)
    if not strat:
        st.info("아직 계획이 없습니다. 위에서 '계획 받기'를 누르세요.")
        _section_record(get_conn, items, fx, apply_trade)
        return None
    pl_ = _section_plan(get_conn, items, fx, cfg_pk, hub, sid, status, strat, created, c)
    if status == "confirmed" and apply_trade is not None:
        _section_fill(get_conn, items, fx, sid, strat, pl_, apply_trade)
    elif status == "filled":
        st.success("이 계획의 체결이 반영되었습니다. 성과는 며칠~몇 주 뒤 아래 '기록·성적표'에서 시장과 비교해 볼 수 있고, 다음 계획 때 AI가 그 결과를 읽습니다.")
    _section_record(get_conn, items, fx, apply_trade)
    _section_chat(get_conn, items, risk, stress, fx, cfg_pk, int(strat.get("_deposit", 0) or 0), cash_map, c, strat, get_prices)
    return strat if status == "confirmed" else None
