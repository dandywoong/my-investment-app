"""탄력 목표 비중과 '오늘 투입' 안내.

고정 퍼센트 대신 현재 AI 연동 노출이 내가 정한 기준선을 얼마나 넘는지에 따라
코어(VOO·버크셔) 몫이 자동으로 변한다. 이 공식은 검증 전 가설이며 수익을 보장하지 않는다.
"""
import pandas as pd
import streamlit as st

DEFAULT_BAND = 45      # AI 연동 노출 기준선(%) — 사용자가 화면에서 바꾼다
CORE_MIN, CORE_MAX = 0.30, 0.85
DEFAULT_GOAL = 20_000_000


def core_share(ai_total, band_pct):
    """AI 노출이 기준선보다 높을수록 코어 몫을 키우고, 기준선 안으로 오면 줄인다(0이 되지는 않음)."""
    if ai_total is None:
        return 0.5, "AI 노출 자료 없음 → 기본 50%"
    gap = ai_total - band_pct / 100.0
    share = max(CORE_MIN, min(CORE_MAX, 0.40 + 1.6 * gap))
    if gap > 0.02:
        why = "AI 연동 노출 {:.0%}가 기준선 {:.0f}%보다 높아 코어 몫을 {:.0%}로 키웁니다.".format(ai_total, band_pct, share)
    elif gap < -0.05:
        why = "AI 연동 노출 {:.0%}가 기준선 {:.0f}% 아래라 코어 몫을 {:.0%}로 낮추고 기술주에 더 배분합니다.".format(ai_total, band_pct, share)
    else:
        why = "AI 연동 노출 {:.0%}가 기준선 {:.0f}% 부근이라 코어 몫 {:.0%}.".format(ai_total, band_pct, share)
    return share, why


def us_invested_krw(items, fx):
    """미국 보유의 원가(수량×평단)를 오늘 환율로 환산한 추정치. 실제 환전 원금과 다를 수 있다."""
    return sum((i.get("qty") or 0) * (i.get("avg") or 0) * (fx or 0) for i in items if i["cur"] == "USD")


def render_banner(box, P, kr_amt, us_amt, fx, core_names, share, share_why, risk, invested, goal, kr_freeze, stress):
    """메인 화면 맨 위: 오늘 투입 안내 + 미국 목표 진행률 + 비중 파이."""
    with box:
        st.markdown("### 오늘 투입 안내")
        if P is None:
            st.info("아래 '현금 배분 플래너'에 오늘 쓸 금액을 넣으면 여기에 오늘 할 일이 한 줄로 요약됩니다. 넣지 않은 금액은 현금으로 남습니다.")
        else:
            rows = P.get("rows") or []
            if rows:
                lines = ["{}. **{}** {} — {:,.0f}원".format(r["행동순서"], r["종목"], r["전략"], r["금액(원)"]) for r in rows]
                st.success("오늘 쓸 돈 {:,.0f}원 중 **{:,.0f}원 투입**, {:,.0f}원은 대기·보유".format(
                    kr_amt + us_amt, P["used"], P["reserved"] + P["hold_cash"]))
                st.markdown("\n".join(lines))
            else:
                st.warning("오늘은 사기에 적합한 종목이 없거나 금액이 부족합니다. 현금 {:,.0f}원을 유지합니다.".format(kr_amt + us_amt))
            if kr_freeze:
                st.caption("국장은 신규 매수 중지 상태입니다(보유는 유지). 아래 설정에서 바꿀 수 있습니다.")
        c1, c2, c3 = st.columns(3)
        c1.metric("코어 몫 (VOO·버크셔 등)", "{:.0%}".format(share), delta="AI 비중에 따라 자동 조정", delta_color="off")
        c2.metric("AI 연동 노출", "-" if not risk else "{:.0%}".format(risk["ai_total"]), delta="내 가정값 기준", delta_color="off")
        pct = (invested / goal) if goal else 0
        c3.metric("미국 순투자금", "{:,.0f}원".format(invested), delta="목표 {:,.0f}원의 {:.0%}".format(goal, min(pct, 9.99)), delta_color="off")
        st.progress(max(0.0, min(1.0, pct)))
        st.caption(share_why)
        if risk and risk.get("rows"):
            by_n = {}
            for r in risk["rows"]:
                by_n[r["name"]] = by_n.get(r["name"], 0) + r["krw"]
            import plotly.graph_objects as go
            fig = go.Figure(go.Pie(labels=list(by_n), values=list(by_n.values()), hole=0.5, textinfo="label+percent"))
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
            cc1, cc2 = st.columns([3, 2])
            cc1.plotly_chart(fig, use_container_width=True)
            core_set = set(core_names)
            core_w = sum(v for k, v in by_n.items() if k in core_set) / risk["total"]
            cc2.markdown("**현재 비중 요약**")
            cc2.write("코어(지정 종목): {:.0%}".format(core_w))
            cc2.write("AI 연동 노출: {:.0%} (기준선 대비 {:+.0f}%p)".format(risk["ai_total"], (risk["ai_total"] - st.session_state.get("_ai_band", DEFAULT_BAND) / 100) * 100))
            cc2.caption("파이는 원화 환산 평가금액 기준입니다. 목표 비중은 종목별 고정값이 아니라 위 '코어 몫'과 종목 점수로 새 돈을 나누는 방식으로 반영됩니다(1단계).")
        if stress:
            st.caption("시장 스트레스: " + " · ".join("{} {}".format(k, v.get("level") or "자료 없음") for k, v in stress.items()))
