"""AI 펀드매니저: 앱의 모든 데이터를 모아 큰 전략·세부 전략·입금 배분·우선순위를 짜고, 채팅으로 의견을 주고받는다.

- 숫자 계산(평단, 손실률, 합계)은 앱이 하고 AI는 해석과 전략만 맡는다. AI의 금액은 앱이 다시 검증한다.
- 보내는 정보: 종목명·비중·수량·평단·평가금액·현금·입금액 등. 계좌번호·로그인·이름은 보내지 않는다.
- 승률·확률·수익 보장 표현은 쓰지 않게 하고, 반대 근거를 반드시 함께 받는다.
"""
import json
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent
import recovery

DEFAULT_POLICY = (
    "1) 국장(ISA) 보유 종목은 손실이 커도 기업 가치가 견고하면 손절하지 않고 보유한다. 국장 신규 매수는 기본적으로 중지한다.\n"
    "2) 미국 순투자금이 2000만원이 될 때까지 새 돈은 미국에 먼저 투자해 국장과 비율을 맞춘다.\n"
    "3) VOO와 버크셔 해서웨이 B는 위험이 상대적으로 낮은 코어이므로 새 돈이 생길 때마다 가장 높은 비중으로 적립한다. 기술주(AI) 비중이 너무 크면 이 비중을 더 키우고, 적정 수준이 되면 줄인다.\n"
    "4) 기술주는 그때그때 데이터 분석으로 투자금액에 따라 비중을 정한다. 투자 매력이 크면 비중을 더 줄 수 있다.\n"
    "5) 두산, SOL AI반도체TOP2는 평단 회복 시 정리가 기본이다. 단 그때 상승 여력이 크면 더 보유할 수 있고, 매도하면 그 현금을 어디로 옮길지 제안한다.\n"
    "6) 평단가는 참고일 뿐 매수·매도 근거가 아니다. 물타기도 산업·가격대·기업 상태를 분석해 유리한 국면일 때만 전략에 포함한다.\n"
    "7) 모든 돈을 투자할지, 현금을 얼마 둘지도 시장 상황에 따라 정한다."
)

SCHEMA = """{
 "headline": "한 줄 결론",
 "master": {"summary": "큰 전략 요약(3~5문장)", "phase_goal": "지금 단계의 목표", "kr_policy": "국장 운용", "us_policy": "미국 운용",
            "core_policy": "코어(VOO·버크셔) 운용", "tech_policy": "기술주 운용", "cash_policy": "현금 보유 원칙과 이상적 비율", "risk_notes": ["주요 위험"]},
 "detail_rules": [{"topic": "주제", "rule": "세부 규칙(조건 포함)"}],
 "allocation": {"kr_krw": 0, "us_krw": 0, "cash_krw": 0, "reason": "왜 이렇게 나눴는지"},
 "priorities": [{"rank": 1, "name": "종목명", "ticker": "티커", "action": "매수|보류|홀드|정리검토", "amount_krw": 0, "weight_hint": "목표 비중 방향(예: 늘림/유지/줄임)", "reason": "근거", "counter": "반대 근거"}],
 "avg_down_review": [{"name": "손실 종목", "verdict": "유리|조건부|불리", "reason": "근거", "conditions": "물타기가 성립하려면 필요한 조건"}],
 "questions_to_user": ["내게 확인하고 싶은 것"],
 "confidence": "낮음|보통|높음",
 "unknowns": ["확인하지 못한 것"]
}"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(get_conn):
    for sql in (
        "CREATE TABLE IF NOT EXISTS strategy_log (id SERIAL PRIMARY KEY, created_at TEXT, status TEXT, deposit BIGINT, content TEXT)",
        "CREATE TABLE IF NOT EXISTS cash_events (id SERIAL PRIMARY KEY, event_date TEXT, amount_krw BIGINT, memo TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS chat_log (id SERIAL PRIMARY KEY, created_at TEXT, role TEXT, text TEXT)",
    ):
        ai_agent._run(get_conn, sql)


# ------------------------------------------------------------------ 자료 꾸러미
def _avg_down(it, n_list):
    qty, avg, price = it.get("qty") or 0, it.get("avg") or 0, it.get("price") or 0
    if not (qty and avg and price):
        return []
    out = []
    for n in n_list:
        nq = qty + n
        na = (qty * avg + n * price) / nq
        out.append({"추가 수량": n, "추가 비용(현지통화)": round(n * price, 2), "새 평단": round(na, 2), "새 평단 대비 손익률(%)": round((price / na - 1) * 100, 1)})
    return out


def build_packet(items, risk, stress, fx, cfg, deposit, memo, cash_map, policy_text, prev_strategy):
    total = sum((i.get("value") or 0) * (fx if i["cur"] == "USD" else 1.0) for i in items) or 1.0
    rows = []
    for i in items:
        k = fx if i["cur"] == "USD" else 1.0
        sc = i.get("score")
        a = {"name": i["name"], "ticker": i["tk"], "market": i["mkt"], "mode": i["mode"], "qty": round(i["qty"], 4),
             "avg": round(i["avg"], 2), "price": None if i["price"] is None else round(i["price"], 2), "currency": i["cur"],
             "value_krw": round((i.get("value") or 0) * k), "weight_pct": round((i.get("value") or 0) * k / total * 100, 1),
             "return_vs_avg_pct": None if i.get("ret") is None else round(i["ret"] * 100, 1),
             "score_total": None if not sc else round(sc["total"], 1), "score_parts": None if not sc else {p: round(v[0], 1) for p, v in sc["parts"].items()},
             "excluded_reason": None if not sc else sc.get("gate"), "egg_phase": i.get("plabel"), "company_stance": i.get("sv_txt"),
             "ai_industry_outlook": i.get("outlook"), "ai_target_price": i.get("target")}
        if i.get("ret") is not None and i["ret"] < 0:
            try:
                r = recovery.assess(i, recovery.consensus(i["tk"] if str(i["tk"]).endswith((".KS", ".KQ")) else str(i["tk"]).replace(".", "-")), i.get("target"))
            except Exception:  # noqa: BLE001
                r = None
            if r:
                a["recovery_check"] = {"need_rise_to_avg_pct": round(r["평단까지 필요한 상승"] * 100, 1), "consensus_mean_target": r["목표가(평균)"],
                                       "upside_to_target_pct": None if r["여력"] is None else round(r["여력"] * 100, 1), "verdict": r["판정"], "source": r["출처"]}
            a["average_down_simulation"] = _avg_down(i, [1, 2, 3] if i["cur"] == "KRW" else [])
        rows.append(a)
    pk = {
        "today": date.today().isoformat(),
        "fx_krw_per_usd": round(fx, 1) if fx else None,
        "portfolio_total_krw": round(total),
        "holdings": rows,
        "risk": None if not risk else {"ai_exposure_pct": round(risk["ai_total"] * 100, 1), "top3_weight_pct": round(risk["top3"] * 100, 1),
                                        "effective_holdings": round(risk["eff_n"], 1),
                                        "buckets_pct": {b: round(v / risk["total"] * 100, 1) for b, v in risk["by_bucket"].items()}},
        "market_stress": {k: {"level": v.get("level"), "points": v.get("points"), "why": [t for _, t in v.get("parts", [])]} for k, v in (stress or {}).items()},
        "us_goal": {"target_net_invested_krw": cfg.get("goal"), "current_estimate_krw": cfg.get("invested")},
        "ai_exposure_comfort_band_pct": cfg.get("band"),
        "kr_new_buying_frozen": cfg.get("freeze"),
        "core_names": cfg.get("core"),
        "waiting_cash_krw": {"kr": cash_map.get("KR_KRW", 0), "us": cash_map.get("US_KRW", 0)},
        "new_deposit": {"amount_krw": int(deposit), "memo": memo},
        "user_policy_text": policy_text,
        "previous_strategy": prev_strategy,
    }
    return pk


def _prompt(packet, task, extra=""):
    return (
        "당신은 장기 투자자를 돕는 펀드매니저 보조입니다. 아래 JSON 자료는 앱이 계산한 사실이며, 모든 수치 계산(평단·손익률·합계)은 이미 끝나 있으니 새로 계산하지 말고 주어진 값만 인용하세요.\n"
        "원칙: (1) 승률·확률·수익 보장 표현 금지. (2) 모든 판단에 반대 근거를 함께 적는다. (3) 평단가는 참고일 뿐 매수·매도 근거가 아니다. 가격이 내렸다는 것만으로 싸다고 하지 않는다. "
        "(4) 산업 성장성, 기업의 이익 포착 능력, 주가 매력을 구분한다. (5) 시장 스트레스가 높다는 것은 기업이 나빠졌다는 뜻이 아니다. 급락을 바닥이라고 단정하지 않고 나눠 투입한다. "
        "(6) 자료가 없는 것은 '자료 없음'이라 쓰고 추측으로 채우지 않는다. (7) user_policy_text는 사용자가 정한 큰 틀이다. 따르되, 강한 데이터가 있어 벗어나는 제안은 '정책과 다른 제안'이라고 명시하고 이유와 조건을 적는다. "
        "(8) 금액은 원화 정수. allocation의 kr_krw+us_krw+cash_krw는 new_deposit.amount_krw와 정확히 같아야 한다(입금이 0이면 모두 0). "
        "(9) 한국 주식은 정수 주 단위, 미국 주식은 소수점 가능. 자동 주문은 없고 사람이 직접 실행한다.\n\n"
        "과제: " + task + "\n" + extra + "\n\n자료(JSON):\n" + json.dumps(packet, ensure_ascii=False)[:60000]
    )


def _gemini(prompt, want_json=True):
    key = ai_agent.get_api_key()
    if not key:
        return None, "GEMINI_API_KEY 가 설정되지 않았습니다."
    try:
        models = ai_agent.pick_models(key)
    except Exception as e:  # noqa: BLE001
        return None, "모델 목록 조회 실패: " + str(e)[:120]
    last = "사용 가능한 모델 없음"
    for m in models:
        try:
            r = ai_agent._call(key, m, prompt, False)
        except Exception as e:  # noqa: BLE001
            last = "연결 오류: " + str(e)[:100]
            continue
        if r.status_code >= 400:
            last = "{} {} [모델 {}]".format(r.status_code, ai_agent._err_text(r), m)
            continue
        try:
            cand = r.json()["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
            return (ai_agent._extract_json(text) if want_json else text), None
        except Exception as e:  # noqa: BLE001
            last = "응답 해석 실패: " + str(e)[:100]
    return None, last


# ------------------------------------------------------------------ 검증(AI 숫자를 앱이 다시 확인)
def validate(strategy, deposit, items):
    """AI 배분 금액이 입금액과 맞는지 보정하고 경고 문구를 돌려준다."""
    warns = []
    al = strategy.get("allocation") or {}
    vals = []
    for k in ("kr_krw", "us_krw", "cash_krw"):
        try:
            vals.append(max(0, int(float(al.get(k, 0) or 0))))
        except Exception:  # noqa: BLE001
            vals.append(0)
    s = sum(vals)
    if deposit <= 0:
        vals = [0, 0, 0]
    elif s != deposit:
        warns.append("AI가 낸 배분 합계({:,}원)가 입금액({:,}원)과 달라 앱이 비율대로 보정했습니다.".format(s, deposit))
        if s > 0:
            vals = [int(v * deposit / s) for v in vals]
            vals[2] += deposit - sum(vals)
        else:
            vals = [0, 0, deposit]
    al["kr_krw"], al["us_krw"], al["cash_krw"] = vals
    strategy["allocation"] = al
    names = {i["name"] for i in items} | {i["tk"] for i in items}
    for p in strategy.get("priorities") or []:
        if p.get("name") not in names and p.get("ticker") not in names:
            warns.append("'{}'은(는) 현재 보유 종목에 없습니다(신규 종목 제안). 직접 검토가 필요합니다.".format(p.get("name")))
    return strategy, warns


def make_strategy(get_conn, packet, items, deposit):
    res, err = _gemini(_prompt(packet, "입금 {:,}원을 포함해 현재 포트폴리오의 큰 전략·세부 전략·배분·우선순위를 새로 짜세요. 큰 틀은 user_policy_text를 기반으로 하고 데이터로 점검하세요. "
                               "손실 종목마다 물타기가 유리한지 불리한지도 avg_down_review에 검토하세요.".format(deposit), "반드시 아래 JSON 스키마만 출력하세요.\n" + SCHEMA))
    if err:
        return None, err, []
    res, warns = validate(res, deposit, items)
    res["_deposit"] = int(deposit)
    ai_agent._run(get_conn, "INSERT INTO strategy_log (created_at,status,deposit,content) VALUES (%s,%s,%s,%s)",
                  (_now(), "draft", int(deposit), json.dumps(res, ensure_ascii=False)))
    return res, None, warns


def load_latest(get_conn):
    try:
        df = ai_agent._run(get_conn, "SELECT id, created_at, status, deposit, content FROM strategy_log ORDER BY id DESC LIMIT 1", fetch=True)
        if df is not None and len(df):
            r = df.iloc[0]
            return int(r["id"]), str(r["status"]), json.loads(r["content"]), str(r["created_at"])
    except Exception:  # noqa: BLE001
        pass
    return None, None, None, None


def chat_reply(get_conn, packet, strategy, history, msg, items):
    hist = "\n".join("{}: {}".format("나" if h["role"] == "user" else "펀드매니저", h["text"]) for h in history[-8:])
    extra = ("지금 확정 전 전략(JSON):\n" + json.dumps(strategy, ensure_ascii=False)[:20000] + "\n\n지금까지 대화:\n" + hist + "\n\n사용자 의견: " + msg +
             "\n\n사용자의 의견이 타당하면 반영하고, 근거가 약하면 이유를 들어 정중히 반대하세요. 정책과 충돌하면 그 점을 말하세요. 아래 JSON으로만 답하세요.\n"
             '{"reply": "사용자에게 하는 답(간결하게)", "revised_strategy": null 또는 위 전략 스키마 전체(전략을 바꿔야 할 때만)}\n전략 스키마:\n' + SCHEMA)
    res, err = _gemini(_prompt(packet, "사용자와 전략에 대해 대화하세요.", extra))
    if err:
        return None, err, []
    warns = []
    rs = res.get("revised_strategy")
    if isinstance(rs, dict) and rs.get("master"):
        rs, warns = validate(rs, int(strategy.get("_deposit", 0) or 0), items)
        rs["_deposit"] = strategy.get("_deposit", 0)
        ai_agent._run(get_conn, "INSERT INTO strategy_log (created_at,status,deposit,content) VALUES (%s,%s,%s,%s)",
                      (_now(), "draft", int(rs["_deposit"] or 0), json.dumps(rs, ensure_ascii=False)))
    else:
        rs = None
    return {"reply": str(res.get("reply", "")), "revised": rs}, None, warns


# ------------------------------------------------------------------ 화면
def _log_chat(get_conn, role, text):
    ai_agent._run(get_conn, "INSERT INTO chat_log (created_at,role,text) VALUES (%s,%s,%s)", (_now(), role, text[:4000]))


def _load_chat(get_conn, n=30):
    try:
        df = ai_agent._run(get_conn, "SELECT role, text FROM chat_log ORDER BY id DESC LIMIT {}".format(int(n)), fetch=True)
        return [{"role": r["role"], "text": r["text"]} for _, r in df.iloc[::-1].iterrows()]
    except Exception:  # noqa: BLE001
        return []


def render_panel(get_conn, items, risk, stress, fx, cfg, cash_map, save_cfg, load_cfg, hub):
    import plotly.graph_objects as go
    ensure_tables(get_conn)
    c = load_cfg(get_conn)
    policy = c.get("policy_text") or DEFAULT_POLICY
    st.markdown("### AI 펀드매니저")
    st.caption("앱의 모든 데이터(보유·점수·국면·시장 스트레스·손실 종목 회복 점검·물타기 시뮬레이션)를 모아 큰 전략과 입금 배분, 우선순위를 짭니다. 최종 결정과 주문은 내가 합니다. "
               "AI에 보내는 내용: 종목명·비중·수량·평단·평가금액·현금·입금액·내 정책 메모(계좌번호·로그인 정보·이름은 보내지 않음). 무료 API는 입력이 구글 서비스 개선에 쓰일 수 있습니다.")
    with st.expander("내 투자 정책 메모 (AI가 전략의 큰 틀로 삼습니다)", expanded=False):
        with st.form("policy_text_form"):
            txt = st.text_area("정책", value=policy, height=220, key="policy_text_area")
            if st.form_submit_button("정책 저장"):
                save_cfg(get_conn, "policy_text", txt)
                st.rerun()
    sid, status, strat, created = load_latest(get_conn)
    with st.form("deposit_form"):
        d1, d2, d3 = st.columns([1, 1, 2])
        ev_date = d1.date_input("입금 날짜", value=date.today(), key="dep_date")
        amt = d2.number_input("새로 생긴 투자금 (원, 없으면 0)", min_value=0, value=0, step=100000, key="dep_amt")
        memo = d3.text_input("메모 (선택)", key="dep_memo")
        b1, b2 = st.columns(2)
        go_new = b1.form_submit_button("기록하고 AI 전략·배분 받기")
        go_chk = b2.form_submit_button("입금 없이 전략만 다시 점검")
    if go_new or go_chk:
        dep = int(amt) if go_new else 0
        if go_new and dep > 0:
            try:
                ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (ev_date.isoformat(), dep, memo, _now()))
            except Exception as e:  # noqa: BLE001
                st.error("입금 기록 실패: " + str(e)[:100])
        packet = build_packet(items, risk, stress, fx, {"goal": hub.get("goal"), "invested": hub.get("invested"), "band": st.session_state.get("_ai_band"),
                                                          "freeze": hub.get("freeze"), "core": hub.get("core")}, dep, memo, cash_map, policy, strat)
        with st.spinner("AI가 전체 데이터를 분석해 전략을 짜는 중... (최대 1~2분)"):
            res, err, warns = make_strategy(get_conn, packet, items, dep)
        if err:
            st.error("전략을 만들지 못했습니다: " + err)
        else:
            st.session_state["_strat_warn"] = warns
            st.rerun()
    sid, status, strat, created = load_latest(get_conn)
    if not strat:
        st.info("아직 전략이 없습니다. 위에서 '입금 없이 전략만 다시 점검'을 눌러도 현재 포트폴리오 기준의 큰 전략을 받을 수 있습니다.")
        return
    for w in st.session_state.get("_strat_warn", []):
        st.warning(w)
    mstr = strat.get("master") or {}
    st.markdown("#### {}".format(strat.get("headline", "")))
    st.caption("상태: {} · 작성 {} UTC · 신뢰도 {} · AI 초안이며 검증 전입니다".format("확정" if status == "confirmed" else "초안(확정 전)", created[:16].replace("T", " "), strat.get("confidence", "-")))
    col1, col2 = st.columns([3, 2])
    with col1:
        st.write(mstr.get("summary", ""))
        for k, lab in (("phase_goal", "지금 단계 목표"), ("kr_policy", "국장"), ("us_policy", "미국"), ("core_policy", "코어(VOO·버크셔)"), ("tech_policy", "기술주"), ("cash_policy", "현금")):
            if mstr.get(k):
                st.markdown("**{}** — {}".format(lab, mstr[k]))
    with col2:
        al = strat.get("allocation") or {}
        dep = int(strat.get("_deposit", 0) or 0)
        if dep > 0:
            fig = go.Figure(go.Pie(labels=["국장", "미국", "현금 보유"], values=[al.get("kr_krw", 0), al.get("us_krw", 0), al.get("cash_krw", 0)], hole=0.55,
                                   textinfo="label+percent", sort=False, marker=dict(colors=["#14213D", "#0F766E", "#B8B4A8"])))
            fig.update_layout(height=250, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                              annotations=[dict(text="{:,}원".format(dep), x=0.5, y=0.5, showarrow=False, font=dict(size=14))])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption("국장 {:,}원 · 미국 {:,}원 · 현금 {:,}원 — {}".format(al.get("kr_krw", 0), al.get("us_krw", 0), al.get("cash_krw", 0), al.get("reason", "")))
        else:
            st.caption("이번 전략은 입금 없이 만든 점검이라 배분 금액이 없습니다.")
    pri = strat.get("priorities") or []
    if pri:
        st.markdown("**우선순위와 비중 방향**")
        st.dataframe(pd.DataFrame([{"순위": p.get("rank"), "종목": p.get("name"), "행동": p.get("action"), "금액(원)": p.get("amount_krw"), "비중 방향": p.get("weight_hint"),
                                    "근거": p.get("reason"), "반대 근거": p.get("counter")} for p in pri]), use_container_width=True, hide_index=True)
    ad = strat.get("avg_down_review") or []
    if ad:
        st.markdown("**손실 종목 물타기 검토**")
        st.dataframe(pd.DataFrame([{"종목": a.get("name"), "판정": a.get("verdict"), "근거": a.get("reason"), "성립 조건": a.get("conditions")} for a in ad]), use_container_width=True, hide_index=True)
        st.caption("물타기 시뮬레이션(추가 수량별 새 평단)은 앱이 계산해 AI에 전달한 값입니다. 평단을 낮추는 것 자체는 근거가 되지 못하므로 조건이 충족될 때만 참고하세요.")
    with st.expander("세부 규칙 · 위험 · AI가 확인하고 싶은 것"):
        for r in strat.get("detail_rules") or []:
            st.markdown("**{}** — {}".format(r.get("topic"), r.get("rule")))
        for r in mstr.get("risk_notes") or []:
            st.caption("위험: " + str(r))
        for q in strat.get("questions_to_user") or []:
            st.caption("질문: " + str(q))
        for u in strat.get("unknowns") or []:
            st.caption("확인 못함: " + str(u))
    if status != "confirmed" and dep > 0:
        if st.button("이 배분을 확정하고 현금 플래너에 반영", key="strat_confirm", type="primary"):
            try:
                for key_, val_ in (("KR_KRW", al.get("kr_krw", 0)), ("US_KRW", al.get("us_krw", 0))):
                    ai_agent._run(get_conn, "INSERT INTO cash_balance (currency,amount,updated_at) VALUES (%s,%s,%s) ON CONFLICT (currency) DO UPDATE SET amount=EXCLUDED.amount, updated_at=EXCLUDED.updated_at",
                                  (key_, float(val_), _now()))
                save_cfg(get_conn, "kr_freeze", "1" if not al.get("kr_krw") else "0")
                ai_agent._run(get_conn, "UPDATE strategy_log SET status='confirmed' WHERE id=%s", (sid,))
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("반영하지 못했습니다: " + str(e)[:120])
    elif status == "confirmed" and dep > 0:
        st.success("확정되어 아래 현금 플래너에 국내·미국 금액으로 반영되었습니다. 종목별 수량은 플래너가 점수로 계산합니다.")
    # ---- 채팅 ----
    st.markdown("#### 펀드매니저와 의견 나누기")
    hist = _load_chat(get_conn)
    for h in hist[-10:]:
        with st.chat_message("user" if h["role"] == "user" else "assistant"):
            st.write(h["text"])
    msg = st.chat_input("의견을 적어 주세요 (예: 두산은 3주만 더 사면 평단이 80만원대인데 이번엔 어떻게 보나?)", key="mgr_chat")
    if msg:
        packet = build_packet(items, risk, stress, fx, {"goal": hub.get("goal"), "invested": hub.get("invested"), "band": st.session_state.get("_ai_band"),
                                                          "freeze": hub.get("freeze"), "core": hub.get("core")}, int(strat.get("_deposit", 0) or 0), "", cash_map, policy, None)
        _log_chat(get_conn, "user", msg)
        with st.spinner("펀드매니저가 답을 정리하는 중..."):
            out, err, warns = chat_reply(get_conn, packet, strat, hist, msg, items)
        if err:
            st.error("답을 받지 못했습니다: " + err)
        else:
            text = out["reply"] + ("\n\n(전략이 수정되어 새 초안으로 저장했습니다. 위에서 확인 후 확정하세요.)" if out["revised"] else "")
            _log_chat(get_conn, "assistant", text)
            st.session_state["_strat_warn"] = warns
            st.rerun()
