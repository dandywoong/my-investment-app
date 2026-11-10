# -*- coding: utf-8 -*-
"""market.py — 시장 스트레스 · 포트폴리오 집중 위험 · 과거 급락 사례 (모두 검증 전 규칙, 예측 아님).

달걀 국면(심리 해석 틀)과 별개로, '지금 시장이 얼마나 충격 상태인가'와 '내 포트폴리오가 같은 위험에 얼마나 몰려 있는가'를 계산한다.
시장 스트레스가 높다는 것과 기업 펀더멘털이 훼손됐다는 것은 다른 문제이며, 이 모듈은 앞의 것만 다룬다.
"""
import json

import pandas as pd
import streamlit as st

LEVELS = ["NORMAL", "ELEVATED", "STRESS", "DISLOCATION"]
LEVEL_KO = {"NORMAL": "평상", "ELEVATED": "긴장", "STRESS": "스트레스", "DISLOCATION": "시장 기능 이상"}
LEVEL_ICON = {"NORMAL": "", "ELEVATED": "", "STRESS": "", "DISLOCATION": ""}
# 스트레스 단계별로 '오늘 새로 투입하는 비율'을 줄이는 계수(급락을 바닥으로 단정하지 않고 나눠서 접근)
DEPLOY_MULT = {"NORMAL": 1.0, "ELEVATED": 0.85, "STRESS": 0.6, "DISLOCATION": 0.5, None: 1.0}


# ---------------------------------------------------------------- 시계열 도우미
def _series(get_prices, sym, period="1y"):
    try:
        res = get_prices(sym, period)
        df = res[0] if isinstance(res, tuple) else res
        if df is None or len(df) == 0 or "Close" not in df.columns:
            return None
        return df["Close"].dropna()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 시장 스트레스
def stress(get_prices, region):
    """region 'KR'|'US'. -> {level, points, parts[(점수, 문장)], asof, missing[]}"""
    idx, vol = ("^KS11", "^VKOSPI") if region == "KR" else ("^GSPC", "^VIX")
    parts, pts, missing = [], 0, []
    c = _series(get_prices, idx)
    if c is None or len(c) < 60:
        return {"level": None, "points": 0, "parts": [], "asof": "-", "missing": [idx]}
    asof = str(c.index[-1])[:10]
    r1 = float(c.iloc[-1] / c.iloc[-2] - 1)
    r5 = float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) > 6 else 0.0
    dd20 = float(c.iloc[-1] / c.tail(20).max() - 1)
    dd52 = float(c.iloc[-1] / c.max() - 1)

    def add(p, text):
        nonlocal pts
        if p:
            pts += p
            parts.append((p, text))
    add(3 if r1 <= -0.06 else 2 if r1 <= -0.04 else 1 if r1 <= -0.02 else 0, "지수 하루 {:+.1f}%".format(r1 * 100))
    add(2 if r5 <= -0.10 else 1 if r5 <= -0.06 else 0, "지수 5거래일 {:+.1f}%".format(r5 * 100))
    add(2 if dd20 <= -0.15 else 1 if dd20 <= -0.08 else 0, "20일 고점 대비 {:+.1f}%".format(dd20 * 100))
    add(1 if dd52 <= -0.20 else 0, "52주 고점 대비 {:+.1f}%".format(dd52 * 100))
    rv = c.pct_change().rolling(20).std() * (252 ** 0.5)
    rvn, rvm = rv.dropna().iloc[-1], rv.dropna().median()
    add(1 if rvm and rvn / rvm >= 2.0 else 0, "20일 실현 변동성이 1년 중앙값의 {:.1f}배".format(rvn / rvm if rvm else 0))
    v = _series(get_prices, vol)
    if v is not None and len(v) > 20:
        lv, ch = float(v.iloc[-1]), float(v.iloc[-1] / v.iloc[-2] - 1)
        hi, mid = (40, 30) if region == "US" else (35, 25)
        add(3 if lv >= hi else 2 if lv >= mid else 1 if lv >= (22 if region == "US" else 20) else 0, "{} {:.1f}".format("VIX" if region == "US" else "VKOSPI", lv))
        add(1 if ch >= 0.25 else 0, "{} 하루 {:+.0f}%".format("VIX" if region == "US" else "VKOSPI", ch * 100))
    else:
        missing.append(vol)
    sox = _series(get_prices, "^SOX")
    if sox is not None and len(sox) > 3:
        rs = float(sox.iloc[-1] / sox.iloc[-2] - 1)
        add(1 if rs <= -0.08 else 0, "필라델피아 반도체지수 하루 {:+.1f}%".format(rs * 100))
    else:
        missing.append("^SOX")
    level = "NORMAL" if pts <= 1 else "ELEVATED" if pts <= 4 else "STRESS" if pts <= 8 else "DISLOCATION"
    return {"level": level, "points": pts, "parts": parts, "asof": asof, "missing": missing, "r1": r1, "dd20": dd20}


# ---------------------------------------------------------------- 위험 묶음(내 가정값)
# 묶음, AI·반도체 연동도(0~1). 연동도는 내가 정하는 가정이며 공식 수치가 아니다.
DEFAULT_BUCKETS = {
    "000660": ("반도체·AI 공급망", 1.0), "005930": ("반도체·AI 공급망", 0.9), "009150": ("반도체·AI 공급망", 0.8),
    "0167A0": ("반도체·AI 공급망", 1.0), "NVDA": ("반도체·AI 공급망", 1.0), "MU": ("반도체·AI 공급망", 1.0),
    "000150": ("산업재·일부 반도체", 0.4),
    "GOOGL": ("AI·빅테크", 0.8), "PLTR": ("AI·빅테크", 0.8), "MSFT": ("AI·빅테크", 0.8), "AMZN": ("AI·빅테크", 0.7), "META": ("AI·빅테크", 0.8),
    "379810": ("나스닥100 ETF", 0.7), "QQQ": ("나스닥100 ETF", 0.7),
    "VOO": ("미국 대형주 전체", 0.35), "SPY": ("미국 대형주 전체", 0.35), "IVV": ("미국 대형주 전체", 0.35),
    "BRK-B": ("분산 복합(버크셔)", 0.1), "BRKB": ("분산 복합(버크셔)", 0.1),
    "TSLA": ("성장·고위험", 0.6), "IONQ": ("성장·고위험", 0.7),
}


def bucket_of(it, user_map=None):
    tk = str(it["tk"]).upper().replace(".KS", "").replace(".KQ", "")
    if user_map and tk in user_map:
        b, a = user_map[tk]
        return b, float(a)
    if tk in DEFAULT_BUCKETS:
        return DEFAULT_BUCKETS[tk]
    nm = str(it.get("name", ""))
    if "반도체" in nm:
        return "반도체·AI 공급망", 1.0
    return "미분류", 0.3


def load_buckets(cfg):
    try:
        raw = json.loads(cfg.get("bucket_map", "{}"))
        return {k: (v[0], float(v[1])) for k, v in raw.items()}
    except Exception:  # noqa: BLE001
        return {}


def risk_summary(items, fx, user_map, cash_krw, get_prices):
    """보유 전체(원화 환산)의 집중도. -> dict. 각 item 에 ctx(묶음 비중·AI 총노출)를 넣어 점수 계산에 쓴다."""
    k = lambda i: (fx if i["cur"] == "USD" else 1.0)
    rows = []
    for i in items:
        if not i.get("value"):
            continue
        b, a = bucket_of(i, user_map)
        rows.append(dict(it=i, name=i["name"], bucket=b, ai=a, krw=i["value"] * k(i)))
    total = sum(r["krw"] for r in rows)
    if not total:
        return None
    by_b = {}
    for r in rows:
        by_b[r["bucket"]] = by_b.get(r["bucket"], 0.0) + r["krw"]
    ai_total = sum(r["krw"] * r["ai"] for r in rows) / total
    ws = sorted((r["krw"] / total for r in rows), reverse=True)
    hhi = sum(w * w for w in ws)
    for r in rows:
        r["it"]["ctx"] = {"bucket": r["bucket"], "bucket_w": by_b[r["bucket"]] / total, "ai_total": ai_total, "ai_link": r["ai"]}
    # 상관관계(최근 1년 일간 수익률, 공통 거래일만)
    corr_pairs, avg_corr = [], None
    try:
        cols = {}
        for r in rows:
            s = _series(get_prices, _sym(r["it"]))
            if s is not None and len(s) > 60:
                cols[r["name"]] = s.pct_change()
        if len(cols) >= 2:
            df = pd.concat(cols, axis=1).dropna()
            if len(df) > 40:
                cm = df.corr()
                names = list(cm.columns)
                vals = []
                for a_ in range(len(names)):
                    for b_ in range(a_ + 1, len(names)):
                        vals.append((float(cm.iloc[a_, b_]), names[a_], names[b_]))
                if vals:
                    avg_corr = sum(v[0] for v in vals) / len(vals)
                    corr_pairs = sorted(vals, reverse=True)[:5]
    except Exception:  # noqa: BLE001
        pass
    cash_pct = (cash_krw / (total + cash_krw)) if (cash_krw and total) else 0.0
    return dict(total=total, by_bucket=by_b, ai_total=ai_total, top1=ws[0], top3=sum(ws[:3]), eff_n=(1 / hhi if hhi else 0), rows=rows,
                corr_pairs=corr_pairs, avg_corr=avg_corr, cash=cash_krw, cash_pct=cash_pct)


def _sym(it):
    try:
        from portfolio_book import _yf_symbol
        return _yf_symbol(it["tk"])
    except Exception:  # noqa: BLE001
        return it["tk"]


# ---------------------------------------------------------------- 과거 급락 사례
@st.cache_data(ttl=86400, show_spinner=False)
def _backtest(_get_prices, sym):
    c = None
    for per in ("max", "20y", "10y"):
        c = _series(_get_prices, sym, per)
        if c is not None and len(c) > 1500:
            break
    if c is None or len(c) < 1000:
        return None
    r1 = c.pct_change()
    dd20 = c / c.rolling(20).max() - 1
    out = {}
    for n in (20, 60, 120):
        out[n] = c.shift(-n) / c - 1
    fwd_min = c[::-1].rolling(60, min_periods=60).min()[::-1].shift(-1) / c - 1
    conds = [("하루 -6% 이하", r1 <= -0.06), ("하루 -4% 이하", r1 <= -0.04), ("하루 -3% 이하", r1 <= -0.03), ("하루 -2% 이하", r1 <= -0.02),
             ("20일 고점 대비 -15% 이하", dd20 <= -0.15), ("20일 고점 대비 -10% 이하", dd20 <= -0.10), ("전체 기간(기준선)", r1.notna())]
    rows = []
    for name, m in conds:
        ok = m & out[60].notna() & fwd_min.notna()
        n = int(ok.sum())
        if n < 5:
            rows.append({"조건": name, "사례(일)": n, "비고": "표본 부족"})
            continue
        rows.append({"조건": name, "사례(일)": n,
                     "이후 20일 중앙값": "{:+.1f}%".format(out[20][ok].median() * 100),
                     "이후 60일 중앙값": "{:+.1f}%".format(out[60][ok].median() * 100),
                     "이후 120일 중앙값": "{:+.1f}%".format(out[120][ok & out[120].notna()].median() * 100) if (ok & out[120].notna()).sum() else "-",
                     "60일 뒤 플러스 비율": "{:.0%}".format((out[60][ok] > 0).mean()),
                     "이후 60일 안에 -10% 더 하락한 비율": "{:.0%}".format((fwd_min[ok] <= -0.10).mean())})
    return {"table": pd.DataFrame(rows), "start": str(c.index[0])[:10], "end": str(c.index[-1])[:10]}


# ---------------------------------------------------------------- 화면
def _gauge(title, s):
    import plotly.graph_objects as go
    if not s or not s.get("level"):
        return None
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=s["points"], number={"font": {"size": 26}},
        title={"text": "{} · {}".format(title, LEVEL_KO[s["level"]]), "font": {"size": 14}},
        gauge={"axis": {"range": [0, 12], "tickvals": [0, 2, 5, 9, 12]}, "bar": {"color": "#14213D", "thickness": 0.25},
               "steps": [{"range": [0, 2], "color": "#D8EBDD"}, {"range": [2, 5], "color": "#F4E7B8"},
                         {"range": [5, 9], "color": "#F2C9A0"}, {"range": [9, 12], "color": "#E9A3A3"}]}))
    fig.update_layout(height=170, margin=dict(l=10, r=10, t=40, b=0), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def render_overview(items, risk, stress_kr, stress_us, fx, get_conn, cfg, save_cfg, get_prices):
    import plotly.graph_objects as go
    st.markdown("### 시장 상황과 내 위험")
    st.caption("스트레스가 높다는 것은 기업이 나빠졌다는 뜻이 아니고, 급락 자체는 바닥 신호가 아닙니다. 기준은 모두 검증 전 규칙입니다.")
    band = float(st.session_state.get("_ai_band", 45))
    g1, g2, g3 = st.columns([1, 1, 1.3])
    for col, nm, s in ((g1, "한국", stress_kr), (g2, "미국", stress_us)):
        with col:
            fig = _gauge(nm + " 시장 스트레스", s)
            if fig is None:
                st.metric(nm + " 시장 스트레스", "판단 보류")
                st.caption("자료 없음: " + ", ".join(s.get("missing", [])) if s else "자료 없음")
            else:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                st.caption("신규 투입은 평소의 {:.0%}로 제한".format(DEPLOY_MULT[s["level"]]))
    with g3:
        if risk:
            ai = risk["ai_total"] * 100
            f = go.Figure()
            f.add_trace(go.Bar(y=["AI 연동 노출"], x=[ai], orientation="h", marker_color="#B42318" if ai > band else "#0F766E", text=["{:.0f}%".format(ai)], textposition="inside", width=0.5))
            f.add_vline(x=band, line_dash="dash", line_color="#14213D", annotation_text="기준선 {:.0f}%".format(band), annotation_position="top")
            f.update_layout(height=110, margin=dict(l=0, r=10, t=30, b=0), xaxis=dict(range=[0, 100], ticksuffix="%"), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(f, use_container_width=True, config={"displayModeBar": False})
            m1, m2, m3 = st.columns(3)
            m1.metric("상위 3종목", "{:.0%}".format(risk["top3"]))
            m2.metric("실질 종목 수", "{:.1f}개".format(risk["eff_n"]))
            m3.metric("대기 현금", "{:.0%}".format(risk["cash_pct"]))
    if risk:
        by = sorted(risk["by_bucket"].items(), key=lambda kv: kv[1])
        sc_x = ["-10%", "-20%", "-30%"]
        sc_y = [sum(r["krw"] * r["ai"] * sh for r in risk["rows"]) / 10000 for sh in (-0.10, -0.20, -0.30)]
        b1, b2 = st.columns([3, 2])
        with b1:
            fb = go.Figure(go.Bar(y=[k for k, _ in by], x=[v / risk["total"] * 100 for _, v in by], orientation="h", marker_color="#14213D",
                                  text=["{:.0f}%".format(v / risk["total"] * 100) for _, v in by], textposition="outside"))
            fb.update_layout(title=dict(text="위험 묶음별 비중", font=dict(size=14)), height=max(170, 34 * len(by) + 60), margin=dict(l=0, r=30, t=36, b=0),
                             xaxis=dict(showticklabels=False, showgrid=False), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fb, use_container_width=True, config={"displayModeBar": False})
        with b2:
            fs = go.Figure(go.Bar(x=sc_x, y=sc_y, marker_color="#B42318", text=["{:,.0f}만".format(v) for v in sc_y], textposition="outside"))
            fs.update_layout(title=dict(text="AI 연동 자산 하락 시 평가금액 변화(만원)", font=dict(size=14)), height=max(170, 34 * len(by) + 60), margin=dict(l=0, r=0, t=36, b=0),
                             yaxis=dict(showgrid=False, showticklabels=False), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fs, use_container_width=True, config={"displayModeBar": False})
        if risk["ai_total"] * 100 > band:
            st.warning("보유의 {:.0%}가 AI·반도체와 같은 위험에 연동되어 있습니다(내 가정값 기준). 새 돈은 이 위험을 더 키우지 않는 쪽의 점수가 높게 계산됩니다. 기존 보유를 팔라는 뜻은 아닙니다.".format(risk["ai_total"]))
        with st.expander("판정 근거 · 상관관계 · 가정 수정 · 과거 사례", expanded=False):
            for nm, s in (("한국", stress_kr), ("미국", stress_us)):
                if s and s.get("level"):
                    st.markdown("**{} 스트레스 {}점**".format(nm, s["points"]))
                    for p_, t_ in s["parts"]:
                        st.caption("+{} {}".format(p_, t_))
                    st.caption("기준 {} · 야후 일봉(지연·누락 가능)".format(s["asof"]) + (" · 자료 없음: " + ", ".join(s["missing"]) if s["missing"] else ""))
            if risk["corr_pairs"]:
                st.caption("최근 1년 일간 수익률 상관: 평균 {:.2f} · 높은 쌍 ".format(risk["avg_corr"]) + " / ".join("{}-{} {:.2f}".format(a, b, v) for v, a, b in risk["corr_pairs"][:3]))
            _assumptions_and_backtest(risk, cfg, get_conn, save_cfg, get_prices)


def _assumptions_and_backtest(risk, cfg, get_conn, save_cfg, get_prices):
    if True:
        if True:
            pass
        if st.checkbox("위험 묶음·AI 연동도 가정 수정", key="bk_show"):
            um = load_buckets(cfg)
            rows = []
            for r in risk["rows"]:
                tk = str(r["it"]["tk"]).upper().replace(".KS", "").replace(".KQ", "")
                rows.append({"종목코드": tk, "종목": r["name"], "묶음": r["bucket"], "AI 연동도(0~1)": r["ai"]})
            ed = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True, disabled=["종목코드", "종목"], key="bucket_editor_{}".format(st.session_state.get("_ed_v", 0)),
                                column_config={"AI 연동도(0~1)": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.05)})
            if st.button("가정 저장", key="bucket_save"):
                try:
                    save_cfg(get_conn, "bucket_map", json.dumps({str(r["종목코드"]): [str(r["묶음"]), float(r["AI 연동도(0~1)"])] for _, r in ed.iterrows()}, ensure_ascii=False))
                    st.session_state["_ed_v"] = st.session_state.get("_ed_v", 0) + 1
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error("저장하지 못했습니다: " + str(e)[:100])
            st.caption("연동도는 '그 종목이 AI·반도체 투자 사이클과 얼마나 같이 움직인다고 보는지'에 대한 내 판단입니다. 기본값은 제가 임의로 둔 가정이며 공식 수치가 아닙니다.")
    if st.checkbox("과거 급락 이후엔 어땠나 (이 기준을 믿어도 되는지 점검)", key="bt_show"):
        st.caption("지수 일간 자료로 '급락한 날' 이후 20·60·120일을 과거 전체에서 세어 봅니다. 사건이 몰려 있어(예: 2008, 2020) 독립 표본이 아니며 오늘의 결과를 예측하지 않습니다. "
                   "급락 직후가 바닥이었는지, 더 떨어졌는지의 비율을 보고 '급락 = 매수 신호'가 성립하는지 확인하는 용도입니다.")
        which = st.radio("지수", ["코스피(^KS11)", "S&P500(^GSPC)"], horizontal=True, key="bt_which")
        if st.button("과거 사례 계산", key="bt_run"):
            with st.spinner("과거 자료를 계산하는 중..."):
                res = _backtest(get_prices, "^KS11" if which.startswith("코스피") else "^GSPC")
            if res is None:
                st.error("과거 자료를 충분히 가져오지 못했습니다.")
            else:
                st.dataframe(res["table"], use_container_width=True, hide_index=True)
                st.caption("자료 기간 {} ~ {} · 출처: 야후 파이낸스 일봉".format(res["start"], res["end"]))
