"""전략 가드레일: 목표 비중 · 월 투입 계획 · 점검일 · '전략을 바꾸는 조건'을 숫자로 적어 두고, 앱이 매일 자동으로 대조한다.

목적: 반등장에서 "조금만 더 보자", 하락장에서 "그냥 다 팔까"로 흔들리지 않도록, 감정이 아니라 미리 적어 둔 기준으로 움직이게 한다.
에이전트(계획·대화)도 이 기준을 가장 우선하는 제약으로 읽는다. 예측이나 수익 보장이 아니라 '내가 정한 약속과 현재 상태의 비교'다.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import ai_agent
import market

KEY = "guardrail"
CORE_LINK = {"VOO": 0.35, "BRK": 0.10}  # market.DEFAULT_BUCKETS 의 가정값과 같다(VOO 0.35, 버크셔 0.10)
METRICS = {"ai_gap": "AI·반도체 연동 비중 − 목표 경로(%p)", "ai_total": "AI·반도체 연동 비중(%)", "top1": "최대 종목 비중(%)", "pl_pct": "전체 평가손익률(%)", "vix": "VIX", "manual": "직접 판단(수동)"}


def _default():
    t = date.today()
    return {
        "target_ai": 0.60, "target_date": (t + timedelta(days=365)).isoformat(), "base_ai": None, "base_date": t.isoformat(),
        "monthly": 2000000, "core_min": 1500000, "split_voo": 0.5, "rest_link": 0.5,
        "checks": [{"date": "2026-12-10", "what": "12/9 FOMC 결과 확인 후 1차 점검", "done": False}, {"date": "2027-03-02", "what": "분기 점검", "done": False},
                   {"date": "2027-06-01", "what": "분기 점검", "done": False}, {"date": "2027-09-01", "what": "분기 점검", "done": False}],
        "rules": [
            {"name": "AI·반도체 연동 비중이 목표 경로보다 10%p 이상 높음", "metric": "ai_gap", "op": ">=", "value": 10.0, "action": "신규 입금은 전부 VOO·버크셔로, 점검일을 앞당겨 비중 축소 여부를 검토", "flag": False},
            {"name": "한 종목이 전체의 40% 이상", "metric": "top1", "op": ">=", "value": 40.0, "action": "그 종목은 추가 매수 금지, 일부 정리·이전 여부를 점검일에 결정", "flag": False},
            {"name": "전체 평가손실이 −25% 이하", "metric": "pl_pct", "op": "<=", "value": -25.0, "action": "손실 확정 여부가 아니라 '월 투입액·비중이 내 감당 범위인지'를 다시 점검", "flag": False},
            {"name": "VIX 30 이상(공포 구간)", "metric": "vix", "op": ">=", "value": 30.0, "action": "그날 결정하지 않고 신규 투입은 2~3회로 나눈다", "flag": False},
            {"name": "반도체·AI 기업의 이익 전망 급락(가이던스 하향, 수출통제 확정 등)", "metric": "manual", "op": ">=", "value": 0.0, "action": "전략 재검토: 보유 종목별 '유지/축소' 기준표를 다시 작성", "flag": False},
            {"name": "연준이 12월 50bp 인상 또는 추가 인상 신호를 강하게 줌", "metric": "manual", "op": ">=", "value": 0.0, "action": "신규 자금은 분할 2회, 현금 비중 확대 검토", "flag": False},
        ],
    }


def load(c):
    g = _default()
    try:
        raw = json.loads((c or {}).get(KEY) or "{}")
        for k, v in raw.items():
            g[k] = v
    except Exception:  # noqa: BLE001
        pass
    return g


def save(get_conn, save_cfg, g):
    save_cfg(get_conn, KEY, json.dumps(g, ensure_ascii=False))


# ------------------------------------------------------------------ 현재 숫자
def metrics(items, fx, c):
    """보유 전체(원화 환산) 기준 현재 지표."""
    um = market.load_buckets(c or {})
    rows = []
    for i in items:
        if not i.get("value") or not i.get("qty"):
            continue
        k = fx if i["cur"] == "USD" else 1.0
        if not k:
            continue
        b, a = market.bucket_of(i, um)
        rows.append({"name": i["name"], "krw": i["value"] * k, "cost": (i.get("qty") or 0) * (i.get("avg") or 0) * k, "ai": a})
    total = sum(r["krw"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    if not total:
        return None
    top = max(rows, key=lambda r: r["krw"])
    return {"total": total, "cost": cost, "pl_pct": (total / cost - 1) * 100 if cost else 0.0, "ai_total": sum(r["krw"] * r["ai"] for r in rows) / total,
            "top1_name": top["name"], "top1": top["krw"] / total * 100}


def path_now(g, today=None):
    today = today or date.today()
    try:
        d0, d1 = date.fromisoformat(g["base_date"]), date.fromisoformat(g["target_date"])
        base = float(g["base_ai"])
        span = max(1, (d1 - d0).days)
        f = min(1.0, max(0.0, (today - d0).days / span))
        return base + (float(g["target_ai"]) - base) * f
    except Exception:  # noqa: BLE001
        return None


def sim(total, ai0, monthly, core, split_voo, rest_link, months, shock=0.0):
    """월 투입 시뮬레이션: ai(t) = (AI연동 평가액) / 전체. 새 돈 중 core는 VOO·버크셔(연동 0.35/0.10), 나머지는 rest_link."""
    a_amt, t_amt = ai0 * total, total
    if shock:
        t_amt += a_amt * shock
        a_amt *= 1 + shock
    a_core = split_voo * CORE_LINK["VOO"] + (1 - split_voo) * CORE_LINK["BRK"]
    out = []
    for _ in range(months):
        a_amt += core * a_core + max(0.0, monthly - core) * rest_link
        t_amt += monthly
        out.append(a_amt / t_amt)
    return out


def month_core_done(get_conn, fx):
    """이번 달에 기록한 VOO·버크셔 매수 합계(원화 환산)."""
    try:
        import journal
        df = journal.load(get_conn, 300)
        if df is None or df.empty:
            return 0.0
        ym = date.today().strftime("%Y-%m")
        tot = 0.0
        for _, r in df.iterrows():
            tk = str(r["ticker"]).upper()
            if r["side"] == "매수" and str(r["trade_date"])[:7] == ym and (tk.startswith("VOO") or tk.startswith("BRK")):
                tot += float(r["qty"]) * float(r["price"]) * (fx if str(r["currency"]).upper() == "USD" else 1.0)
        return tot
    except Exception:  # noqa: BLE001
        return 0.0


# ------------------------------------------------------------------ 규칙 평가
def evaluate(g, m, vix=None):
    out = []
    pn = path_now(g)
    for r in g.get("rules", []):
        mt, op, v = r.get("metric"), r.get("op", ">="), float(r.get("value") or 0)
        cur, trig, avail = None, False, True
        if mt == "manual":
            trig, avail = bool(r.get("flag")), True
        elif mt == "ai_gap" and m and pn is not None:
            cur = (m["ai_total"] - pn) * 100
        elif mt == "ai_total" and m:
            cur = m["ai_total"] * 100
        elif mt == "top1" and m:
            cur = m["top1"]
        elif mt == "pl_pct" and m:
            cur = m["pl_pct"]
        elif mt == "vix" and vix is not None:
            cur = vix
        else:
            avail = False
        if mt != "manual" and cur is not None:
            trig = (cur >= v) if op == ">=" else (cur <= v)
        out.append({"name": r.get("name"), "metric": mt, "op": op, "value": v, "cur": cur, "triggered": trig, "avail": avail, "action": r.get("action"), "manual": mt == "manual"})
    return out


def _vix():
    try:
        import strategist as S
        return ((S.market_facts().get("data") or {}).get("VIX(공포지수)") or {}).get("last")
    except Exception:  # noqa: BLE001
        return None


def packet(get_conn, g, items, fx, c):
    """에이전트(계획·대화)에 넘기는 내 전략 약속과 현재 상태."""
    m = metrics(items, fx, c)
    ev = evaluate(g, m, _vix())
    pn = path_now(g)
    nxt = None
    for ck in sorted(g.get("checks", []), key=lambda x: str(x.get("date"))):
        if not ck.get("done"):
            nxt = ck
            break
    notes = []
    try:
        df = ai_agent._run(get_conn, "SELECT created_at, content FROM market_archive WHERE kind='check' ORDER BY id DESC LIMIT 3", fetch=True)
        for _, r in df.iterrows():
            notes.append({"at": str(r["created_at"])[:10], **{k: v for k, v in json.loads(r["content"]).items() if k in ("note", "decision")}})
    except Exception:  # noqa: BLE001
        pass
    return {"note": "사용자가 직접 정한 전략 약속입니다. 계획·답변에서 가장 우선하는 제약으로 따르고, 어긋나는 제안은 이유와 함께 명시하세요.",
            "target_ai_link_pct": round(float(g["target_ai"]) * 100, 1), "target_date": g["target_date"], "path_today_pct": None if pn is None else round(pn * 100, 1),
            "current_ai_link_pct": None if not m else round(m["ai_total"] * 100, 1), "monthly_budget_krw": g["monthly"], "core_min_krw_to_VOO_BRK": g["core_min"],
            "core_split_voo": g["split_voo"], "this_month_core_done_krw": round(month_core_done(get_conn, fx)), "next_check": nxt,
            "triggered_rules": [{"name": e["name"], "action": e["action"]} for e in ev if e["triggered"]], "recent_check_notes": notes,
            "ai_link_note": "AI·반도체 연동 비중 = Σ(종목 평가액 × 내가 정한 연동도) / 전체. VOO 0.35, 버크셔 0.10, 반도체 직접 보유 0.9~1.0 가정."}


# ------------------------------------------------------------------ 화면
def summary_line(g, m, ev):
    """에이전트 탭 맨 위 한 줄 요약."""
    if not m:
        return
    pn = path_now(g)
    trig = [e for e in ev if e["triggered"]]
    nxt = next((ck for ck in sorted(g.get("checks", []), key=lambda x: str(x.get("date"))) if not ck.get("done")), None)
    parts = ["AI·반도체 연동 {:.1f}%".format(m["ai_total"] * 100)]
    if pn is not None:
        parts.append("오늘 목표 경로 {:.1f}% (최종 {:.0f}%, {})".format(pn * 100, float(g["target_ai"]) * 100, str(g["target_date"])[:7]))
    if nxt:
        try:
            dd = (date.fromisoformat(str(nxt["date"])) - date.today()).days
            parts.append("다음 점검 {} ({})".format(nxt["date"], "D-%d" % dd if dd >= 0 else "%d일 지남" % -dd))
        except Exception:  # noqa: BLE001
            pass
    (st.warning if trig else st.info)(("⚠ 전략 변경 조건 {}건 발동 — ".format(len(trig)) if trig else "전략 가드레일 — ") + " · ".join(parts))


def render(get_conn, items, fx, c, save_cfg, risk_args=None):
    g = load(c)
    m = metrics(items, fx, c)
    if m and g.get("base_ai") is None:
        g["base_ai"] = round(m["ai_total"], 4)
        g["base_date"] = date.today().isoformat()
        save(get_conn, save_cfg, g)
    st.markdown("#### 내 전략 약속 (감정이 아니라 기준으로 움직이기)")
    st.caption("방향만 있고 숫자가 없으면 반등장에선 '조금만 더', 하락장에선 '다 팔까'로 흔들립니다. 아래에 목표·월 투입·점검일·전략을 바꾸는 조건을 적어 두면 앱이 매일 현재 상태와 대조하고, 에이전트도 같은 약속을 가장 우선하는 제약으로 읽습니다. 예측이 아니라 내가 정한 약속과 현재의 비교입니다.")
    flash = st.session_state.pop("_gr_flash", None)
    if flash:
        st.success(flash)
    if not m:
        st.info("보유 평가액을 계산할 수 없어 아직 비교할 수 없습니다(가격을 불러온 뒤 다시 확인하세요).")
        return
    ev = evaluate(g, m, _vix())
    pn = path_now(g)
    # ---- 1. 상태
    a, b, c3, d = st.columns(4)
    a.metric("현재 AI·반도체 연동 비중", "{:.1f}%".format(m["ai_total"] * 100), help="종목 평가액 × 내가 정한 연동도의 가중 평균. VOO 0.35, 버크셔 0.10, 반도체 직접 보유 0.9~1.0(가정값).")
    b.metric("오늘의 목표 경로", "{:.1f}%".format(pn * 100) if pn is not None else "-", "{:+.1f}%p".format((m["ai_total"] - pn) * 100) if pn is not None else None, delta_color="inverse")
    c3.metric("최종 목표", "{:.0f}% 이하".format(float(g["target_ai"]) * 100), "기한 " + str(g["target_date"]), delta_color="off")
    d.metric("전체 평가손익률", "{:+.1f}%".format(m["pl_pct"]), "최대 종목 {} {:.0f}%".format(m["top1_name"], m["top1"]), delta_color="off")
    if pn is not None:
        st.caption("목표 경로 = 기준점({:.1f}%, {})에서 목표({:.0f}%, {})까지 직선으로 줄여 가는 선입니다. 경로보다 위면 '계획보다 느림', 아래면 '앞섬'입니다. 주가 하락으로 비중이 줄어든 것은 개선이 아니라 가격 변화입니다.".format(
            float(g["base_ai"]) * 100, g["base_date"], float(g["target_ai"]) * 100, g["target_date"]))
    # ---- 2. 전략 변경 조건
    st.markdown("**전략을 바꾸는 조건 (적어 둔 기준과 지금 상태)**")
    for e in ev:
        if e["manual"]:
            tag, cur = ("🔴 발생" if e["triggered"] else "⚪ 해당 없음"), "직접 판단"
        elif not e["avail"] or e["cur"] is None:
            tag, cur = "⚪ 자료 없음", "-"
        else:
            tag, cur = ("🔴 발동" if e["triggered"] else "🟢 정상"), "{:.1f} (기준 {} {:g})".format(e["cur"], e["op"], e["value"])
        st.write("{} **{}** — 현재 {}".format(tag, e["name"], cur))
        if e["triggered"]:
            st.error("정해 둔 행동: " + str(e["action"]))
    with st.expander("조건 고치기 · 추가 · 삭제 (수동 조건은 '발생' 체크)"):
        base = pd.DataFrame([{"이름": r.get("name"), "지표": METRICS.get(r.get("metric"), r.get("metric")), "기호": r.get("op", ">="), "기준값": float(r.get("value") or 0), "정해 둔 행동": r.get("action"), "발생(수동)": bool(r.get("flag"))} for r in g["rules"]])
        l2k = {v: k for k, v in METRICS.items()}
        out = st.data_editor(base, hide_index=True, use_container_width=True, num_rows="dynamic", key="gr_rules_ed",
                             column_config={"지표": st.column_config.SelectboxColumn("지표", options=list(METRICS.values())), "기호": st.column_config.SelectboxColumn("기호", options=[">=", "<="]),
                                            "기준값": st.column_config.NumberColumn(format="%.1f", help="%p·%·VIX 숫자 그대로. 수동 조건은 무시됨")})
        st.caption("지표 설명: 'AI·반도체 연동 비중 − 목표 경로'는 %p 차이(예: 10 = 경로보다 10%p 높음), 비중·손익률은 % 숫자, VIX는 지수 값입니다.")
        if st.button("조건 저장", key="gr_rules_save"):
            rules = []
            for _, r in out.iterrows():
                if pd.isna(r["이름"]) or not str(r["이름"]).strip():
                    continue
                rules.append({"name": str(r["이름"]), "metric": l2k.get(str(r["지표"]), "manual"), "op": str(r["기호"]) if not pd.isna(r["기호"]) else ">=",
                              "value": 0.0 if pd.isna(r["기준값"]) else float(r["기준값"]), "action": "" if pd.isna(r["정해 둔 행동"]) else str(r["정해 둔 행동"]), "flag": bool(r["발생(수동)"])})
            g["rules"] = rules
            save(get_conn, save_cfg, g)
            st.session_state["_gr_flash"] = "전략 변경 조건을 저장했습니다."
            st.rerun()
    # ---- 3. 월 투입 계획 + 시뮬레이션
    st.markdown("**월 투입 계획과 비중 시뮬레이션**")
    with st.form("gr_plan_form"):
        f1, f2, f3, f4 = st.columns(4)
        monthly = f1.number_input("월 투자 가능액 (원)", min_value=0, value=int(g["monthly"]), step=100000)
        core = f2.number_input("그중 VOO·버크셔 최소 (원)", min_value=0, value=int(g["core_min"]), step=100000)
        split = f3.slider("VOO 몫 (나머지는 버크셔)", 0, 100, int(round(float(g["split_voo"]) * 100)), 5)
        rest = f4.slider("나머지 돈의 AI 연동도 (현금=0, 반도체=1)", 0.0, 1.0, float(g["rest_link"]), 0.05)
        g1, g2 = st.columns(2)
        tai = g1.slider("목표: AI·반도체 연동 비중 (%) 이하", 20, 90, int(round(float(g["target_ai"]) * 100)), 1)
        tdate = g2.date_input("목표 기한", value=date.fromisoformat(str(g["target_date"])))
        if st.form_submit_button("약속 저장"):
            g.update({"monthly": int(monthly), "core_min": int(min(core, monthly)), "split_voo": split / 100, "rest_link": rest, "target_ai": tai / 100, "target_date": tdate.isoformat()})
            save(get_conn, save_cfg, g)
            st.session_state["_gr_flash"] = "전략 약속을 저장했습니다. 에이전트도 이 기준으로 계획을 짭니다."
            st.rerun()
    mo, co = int(g["monthly"]), int(min(g["core_min"], g["monthly"]))
    done = month_core_done(get_conn, fx)
    voo_w, brk_w = co * float(g["split_voo"]), co * (1 - float(g["split_voo"]))
    st.write("**이번 달 투입 가이드**: VOO {:,.0f}원 · 버크셔 {:,.0f}원 · 나머지 {:,.0f}원 (달러 환산 약 ${:,.0f} / ${:,.0f})".format(voo_w, brk_w, max(0, mo - co), voo_w / fx if fx else 0, brk_w / fx if fx else 0))
    st.progress(min(1.0, done / co) if co else 0.0, text="이번 달 VOO·버크셔 매수 기록 {:,.0f}원 / 목표 {:,.0f}원".format(done, co))
    months = 36
    base_s = sim(m["total"], m["ai_total"], mo, co, float(g["split_voo"]), float(g["rest_link"]), months)
    dn_s = sim(m["total"], m["ai_total"], mo, co, float(g["split_voo"]), float(g["rest_link"]), months, -0.2)
    up_s = sim(m["total"], m["ai_total"], mo, co, float(g["split_voo"]), float(g["rest_link"]), months, 0.2)
    hit = next((i + 1 for i, v in enumerate(base_s) if v <= float(g["target_ai"])), None)
    st.caption("현재 보유 {:,.0f}원, AI 연동 {:.1f}%에서 매달 {:,.0f}원을 위 방식으로 넣으면(가격 변화 없다고 가정) 목표 {:.0f}%에 {}.".format(
        m["total"], m["ai_total"] * 100, mo, float(g["target_ai"]) * 100, "약 {}개월 뒤 도달".format(hit) if hit else "{}개월 안에는 도달하지 못합니다(월 투입액·VOO 몫을 늘리거나 목표를 조정)".format(months)))
    rows = []
    for k in (1, 3, 6, 12, 24, 36):
        rows.append({"기간": "{}개월 뒤".format(k), "가격 변화 없음": "{:.1f}%".format(base_s[k - 1] * 100), "AI 연동 자산 −20% 먼저 발생": "{:.1f}%".format(dn_s[k - 1] * 100), "AI 연동 자산 +20% 먼저 발생": "{:.1f}%".format(up_s[k - 1] * 100)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("읽는 법: 새 돈은 VOO(연동 0.35)·버크셔(0.10)에 들어가므로 비중은 천천히 내려갑니다. 반도체가 +20% 오르면 비중이 다시 올라가고, −20% 내리면 비중은 내려가지만 그건 손실이 커진 결과일 뿐 안전해진 것이 아닙니다. 연동도는 내가 정한 가정값이며 공식 수치가 아닙니다.")
    try:
        import plotly.graph_objects as go
        xs = list(range(0, months + 1))
        fig = go.Figure()
        fig.add_scatter(x=xs, y=[m["ai_total"] * 100] + [v * 100 for v in base_s], name="가격 변화 없음", line=dict(color="#14213D"))
        fig.add_scatter(x=xs, y=[m["ai_total"] * 100] + [v * 100 for v in up_s], name="+20%", line=dict(color="#C0392B", dash="dot"))
        fig.add_hline(y=float(g["target_ai"]) * 100, line_dash="dash", line_color="#1A936F", annotation_text="목표 {:.0f}%".format(float(g["target_ai"]) * 100))
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="AI·반도체 연동 비중(%)", xaxis_title="개월", paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    except Exception:  # noqa: BLE001
        pass
    # ---- 4. 점검일
    st.markdown("**점검일과 점검 기록**")
    today = date.today()
    cks = sorted(g.get("checks", []), key=lambda x: str(x.get("date")))
    due = [ck for ck in cks if not ck.get("done") and str(ck.get("date")) <= today.isoformat()]
    if due:
        st.warning("점검일이 도래했습니다: " + ", ".join("{} ({})".format(ck["date"], ck["what"]) for ck in due) + " — 아래 점검 체크리스트를 확인하고 '점검 기록'을 남기세요.")
    base = pd.DataFrame([{"날짜": date.fromisoformat(str(ck["date"])) if ck.get("date") else None, "점검 내용": ck.get("what"), "완료": bool(ck.get("done"))} for ck in cks])
    out = st.data_editor(base, hide_index=True, use_container_width=True, num_rows="dynamic", key="gr_checks_ed",
                         column_config={"날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD")})
    if st.button("점검일 저장", key="gr_checks_save"):
        g["checks"] = [{"date": str(r["날짜"])[:10], "what": "" if pd.isna(r["점검 내용"]) else str(r["점검 내용"]), "done": bool(r["완료"])} for _, r in out.iterrows() if not pd.isna(r["날짜"])]
        save(get_conn, save_cfg, g)
        st.session_state["_gr_flash"] = "점검일을 저장했습니다."
        st.rerun()
    with st.expander("점검 체크리스트 · 점검 기록 남기기", expanded=bool(due)):
        st.markdown("1. 전략 변경 조건이 발동됐나? (위 목록) → 발동했다면 정해 둔 행동을 따른다\n2. 목표 경로 대비 현재 비중은? (위 숫자)\n3. 보유 종목마다: '오늘 현금이 있다면 이 가격·비중으로 새로 살 것인가?' → 아니면 비중 조정 검토\n4. 이번 달 VOO·버크셔 투입 목표를 채웠나?\n5. 오늘 결정이 '가격이 빠져서/올라서'가 아니라 기업·기준 때문인가?")
        with st.form("gr_check_form", clear_on_submit=True):
            dec = st.selectbox("결정", ["전략 유지", "월 투입액·비중 조정", "특정 종목 비중 축소", "추가 점검 필요"], key="gr_dec")
            note = st.text_area("점검 메모 (왜 그렇게 결정했는지 한두 줄)", key="gr_note")
            if st.form_submit_button("점검 기록 저장"):
                import strategist as S
                S.ensure_archive(get_conn)
                S._arch_add(get_conn, "check", {"note": note, "decision": dec, "ai_total": round(m["ai_total"] * 100, 1), "path": None if pn is None else round(pn * 100, 1), "triggered": [e["name"] for e in ev if e["triggered"]]})
                for ck in g["checks"]:
                    if not ck.get("done") and str(ck.get("date")) <= today.isoformat():
                        ck["done"] = True
                save(get_conn, save_cfg, g)
                st.session_state["_gr_flash"] = "점검 기록을 저장했습니다. 에이전트가 다음 계획·대화 때 이 결정과 메모를 읽습니다."
                st.rerun()
        try:
            df = ai_agent._run(get_conn, "SELECT created_at, content FROM market_archive WHERE kind='check' ORDER BY id DESC LIMIT 8", fetch=True)
            rows = []
            for _, r in df.iterrows():
                cc = json.loads(r["content"])
                rows.append({"날짜": str(r["created_at"])[:10], "결정": cc.get("decision"), "메모": cc.get("note"), "당시 AI 연동": cc.get("ai_total"), "당시 경로": cc.get("path")})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        except Exception:  # noqa: BLE001
            pass
    return g, m, ev
