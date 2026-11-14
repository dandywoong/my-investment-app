"""코스톨라니 심리 분석 · 주가와 기업가치 괴리 · 핵심/조절 물량 · 종목별 운용 판단 · 조절 기록.

원칙(요청서 11장 반영)
- 소신파/부화뇌동파 우위는 '관찰된 사실'이 아니라 가격·거래량 패턴으로 추정한 상태다. 직접 확인되지 않는 자료는 '확인 못함'으로 표시한다.
- 과매수·과매도는 매매 명령이 아니다. 단일 신호로 판정하지 않고, 여러 신호가 같은 방향일 때만 단계를 올리며 신뢰도를 함께 낸다.
- 비중만으로, 평단만으로, 주가 하락만으로 매도·매수 결론을 내지 않는다.
- 규칙은 검증 전이라 '실험 신호'다. 승률·확률 표현을 쓰지 않는다.
"""
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

import ai_agent

STAGES = {1: "극단적 공포 / 과매도 가능성", 2: "비관 / 매도 압력 완화", 3: "중립 / 균형", 4: "낙관 / 매수 쏠림 확대", 5: "극단적 낙관 / 과매수·분배 가능성"}
CORE_TICKERS = ("VOO", "BRK-B", "BRK.B", "BRKB")
DEFAULT_CORE_PCT = 70  # 핵심 보유 기본 비율(%). 종목별로 직접 바꿀 수 있다.
_ONCE = {"done": False}


# ------------------------------------------------------------------ 표(DB)
def ensure_tables(get_conn):
    if _ONCE["done"]:
        return
    for sql in (
        "CREATE TABLE IF NOT EXISTS hold_split (ticker TEXT PRIMARY KEY, core_pct INTEGER, updated_at TEXT)",
        "CREATE TABLE IF NOT EXISTS adjust_log (id SERIAL PRIMARY KEY, created_at TEXT, trade_date TEXT, ticker TEXT, name TEXT, side TEXT, qty DOUBLE PRECISION, price DOUBLE PRECISION, "
        "currency TEXT, bucket TEXT, valuation TEXT, sentiment TEXT, weight_before DOUBLE PRECISION, cash_change DOUBLE PRECISION, reason TEXT)",
        "CREATE TABLE IF NOT EXISTS sentiment_hist (id SERIAL PRIMARY KEY, day TEXT, ticker TEXT, stage INTEGER, confidence TEXT)",
    ):
        try:
            ai_agent._run(get_conn, sql)
        except Exception:  # noqa: BLE001
            pass
    _ONCE["done"] = True


def load_split(get_conn):
    try:
        df = ai_agent._run(get_conn, "SELECT ticker, core_pct FROM hold_split", fetch=True)
        return {r["ticker"]: int(r["core_pct"]) for _, r in df.iterrows()}
    except Exception:  # noqa: BLE001
        return {}


def split_of(tk, saved):
    if tk in saved:
        return saved[tk]
    return 100 if str(tk).upper() in CORE_TICKERS else DEFAULT_CORE_PCT


# ------------------------------------------------------------------ 시장심리(가격·거래량 패턴 기반 추정)
def _rsi(c, n=14):
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(n).mean(), (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, float("nan"))
    r = 100 - 100 / (1 + rs)
    return float(r.iloc[-1]) if pd.notna(r.iloc[-1]) else None


def sentiment(get_prices, sym, core=False):
    """-> dict(stage, label, score, hot[], cold[], camp, confidence, unknown[], next[], facts{}) 또는 None(자료 없음)."""
    try:
        df, _ = get_prices(sym, "1y")
    except Exception:  # noqa: BLE001
        return None
    try:
        c = df["Close"].dropna()
        if len(c) < 80:
            return None
        v = df["Volume"].fillna(0) if "Volume" in df.columns else None
        has_v = v is not None and float(v.tail(60).sum()) > 0
        px = float(c.iloc[-1])
        m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
        width = float(4 * s20.iloc[-1])
        pctb = float((px - (m20.iloc[-1] - 2 * s20.iloc[-1])) / width) if width > 0 else None
        rsi = _rsi(c)
        r20 = float(c.iloc[-1] / c.iloc[-21] - 1)
        r60 = float(c.iloc[-1] / c.iloc[-61] - 1) if len(c) > 61 else None
        r5 = float(c.iloc[-1] / c.iloc[-6] - 1)
        r10 = float(c.iloc[-1] / c.iloc[-11] - 1)
        ma60 = float(px / c.rolling(60).mean().iloc[-1] - 1)
        dd60 = float(px / c.tail(60).max() - 1)
        dd250 = float(px / c.max() - 1)
        hot, cold, facts = [], [], {"RSI14": None if rsi is None else round(rsi, 1), "볼린저 %B": None if pctb is None else round(pctb, 2),
                                    "20일 수익률": round(r20 * 100, 1), "60일 수익률": None if r60 is None else round(r60 * 100, 1), "60일 고점 대비": round(dd60 * 100, 1)}
        # --- 과열 쪽 신호(서로 독립적인 관점별로 1점씩)
        if r60 is not None and r60 > 0.30:
            hot.append("60일 상승률 +{:.0f}%로 짧은 기간 상승이 큼".format(r60 * 100))
        if (rsi is not None and rsi >= 70) or (pctb is not None and pctb >= 1.0):
            hot.append("RSI·볼린저 상단: 단기 과열권(RSI {})".format("-" if rsi is None else int(rsi)))
        if ma60 > 0.20:
            hot.append("60일선 대비 +{:.0f}% 이격".format(ma60 * 100))
        # --- 냉각 쪽 신호
        if dd60 <= -0.20:
            cold.append("60일 고점 대비 {:.0f}% 하락".format(dd60 * 100))
        if (rsi is not None and rsi <= 30) or (pctb is not None and pctb <= 0.0):
            cold.append("RSI·볼린저 하단: 단기 과매도권(RSI {})".format("-" if rsi is None else int(rsi)))
        if ma60 < -0.15:
            cold.append("60일선 대비 {:.0f}% 이격".format(ma60 * 100))
        # --- 가격×거래량 관계(거래량만으로는 판정하지 않고, 가격 맥락과 묶어서만 해석)
        vol_note = "거래량 자료 없음"
        if has_v:
            vr = v / v.rolling(20).mean().replace(0, float("nan"))
            vr_now, vr_max15 = float(vr.tail(5).mean()), float(vr.tail(15).max())
            facts["거래량(5일/20일 평균)"] = round(vr_now, 2)
            if r60 is not None and r60 > 0.20 and abs(r10) < 0.03 and vr_now > 1.2:
                hot.append("많이 오른 뒤 거래량은 높은데 최근 10일 횡보(분배 가능성 — 다른 신호로 검증 필요)")
                vol_note = "상승 후 횡보 + 거래량 높음"
            elif vr_now > 1.5 and r5 > 0.05:
                hot.append("거래량 급증과 함께 5일 +{:.0f}% 급등(추격 매수 쏠림 가능성)".format(r5 * 100))
                vol_note = "급등 + 거래량 급증"
            elif dd60 <= -0.15 and vr_max15 >= 2.0 and vr_now < 1.0 and r5 > -0.03:
                cold.append("급락 중 거래량 폭증(투매) 뒤 거래량이 가라앉고 추가 하락이 둔화")
                vol_note = "투매 후 거래량 정상화"
            elif dd60 <= -0.15 and vr_now < 0.8 and abs(r5) < 0.03:
                cold.append("하락 뒤 거래량이 줄며 가격 안정(매집 확정은 아님)")
                vol_note = "하락 후 거래량 감소·안정"
            elif r5 < -0.05 and vr_now > 1.5:
                vol_note = "하락 + 거래량 증가(투매 진행 중일 수 있음)"
            else:
                vol_note = "뚜렷한 패턴 없음"
        facts["가격·거래량 해석"] = vol_note
        score = 22 * len(hot) - 22 * len(cold)  # -66~+66, 3점 이상 동시 신호면 극단
        score = max(-100, min(100, score + (8 if (rsi or 50) >= 60 else 0) - (8 if (rsi or 50) <= 40 else 0)))
        # 신호 하나만으로는 단계를 올리지 않는다: 4·2단계는 서로 다른 신호 2개 이상, 5·1단계는 3개 이상이 필요하다.
        stage = 3
        if len(hot) >= 3 and score >= 60:
            stage = 5
        elif len(hot) >= 2 and score >= 25:
            stage = 4
        elif len(cold) >= 3 and score <= -60:
            stage = 1
        elif len(cold) >= 2 and score <= -25:
            stage = 2
        n_same = max(len(hot), len(cold))
        conf = "높음" if n_same >= 3 and len(c) >= 200 else "보통" if n_same >= 2 else "낮음"
        if stage == 3 and not hot and not cold:
            conf = "보통"
        if hot and cold:
            conf = "낮음"
        # 어느 쪽 투자자가 우세할지는 '추정'
        if stage <= 2 and any("거래량이 가라앉" in x or "거래량이 줄며" in x for x in cold):
            camp = "소신파 우위로 넘어가는 중일 가능성(추정)"
        elif stage >= 4:
            camp = "부화뇌동파(추격 매수) 우위 가능성(추정)"
        elif stage <= 2:
            camp = "부화뇌동파의 공포 매도 비중이 큰 상태일 가능성(추정)"
        else:
            camp = "뚜렷하지 않음"
        nxt = {1: "투매 거래량이 정상화되고 추가 하락이 멈추면 2단계로 이동", 2: "60일선을 회복하고 RSI가 40~50대로 오르면 3단계로 이동", 3: "상승 폭·RSI가 커지면 4단계, 하락하면 2단계로 이동",
               4: "상승이 둔화되면서 거래량이 높게 유지되면 5단계(분배 가능성) 검증 필요", 5: "RSI·이격이 식고 거래량이 줄면 4단계로 이동. 다만 실적이 뒷받침되면 과열이 길어질 수 있음"}[stage]
        unknown = ["투자자 유형(소신파/부화뇌동파)은 직접 관찰할 수 없어 가격·거래량 패턴으로만 추정", "기관·외국인·개인 수급, 공매도·옵션 포지셔닝은 이 계산에 반영되지 않음(검색 조사 참고)",
                   "호재·악재에 대한 가격 반응은 실적 발표 일정을 모르면 계산하지 못함"]
        if not has_v:
            unknown.insert(0, "거래량 자료 없음")
        return {"stage": stage, "label": STAGES[stage], "score": score, "hot": hot, "cold": cold, "camp": camp, "confidence": conf, "unknown": unknown, "next": nxt,
                "facts": facts, "core": core, "price": px, "dd250": dd250}
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ 주가 vs 기업가치(예상 이익 수정) 괴리
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def value_gap(symbol):
    """최근 90일 주가 변화를 '예상 이익(Forward EPS) 수정'과 '밸류에이션 배수 변화'로 나눈다.
    Yahoo의 eps_trend(애널리스트 예상 이익의 90일 전 대비 변화)를 쓰며, 없으면 '자료 없음'. -> dict | None"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        h = t.history(period="6mo", interval="1d", auto_adjust=False)
        c = h["Close"].dropna()
        if len(c) < 70:
            return None
        p90 = float(c.iloc[-1] / c.iloc[-64] - 1)
        out = {"price_chg_90d": p90, "source": "Yahoo Finance(주가·eps_trend)", "asof": date.today().isoformat()}
        try:
            tr = t.eps_trend
            row = tr.loc["+1y"] if "+1y" in tr.index else tr.loc["0y"]
            cur, old = float(row["current"]), float(row["90daysAgo"])
            if old and old > 0 and cur > 0:
                rev = cur / old - 1
                out["eps_rev_90d"] = rev
                out["mult_chg_90d"] = (1 + p90) / (1 + rev) - 1
        except Exception:  # noqa: BLE001
            pass
        try:
            info = t.info or {}
            out["fwd_pe"] = info.get("forwardPE")
            out["trail_pe"] = info.get("trailingPE")
            out["target_mean"] = info.get("targetMeanPrice")
            out["price"] = info.get("currentPrice") or float(c.iloc[-1])
            out["rev_growth"] = info.get("revenueGrowth")
            out["fcf"] = info.get("freeCashflow")
        except Exception:  # noqa: BLE001
            pass
        return out
    except Exception:  # noqa: BLE001
        return None


def classify_gap(g):
    """요청서 3장의 네 가지 유형으로 분류. -> (유형, 설명)"""
    if not g:
        return "자료 없음", "가격·예상이익 자료를 가져오지 못했습니다. 검색 조사 결과를 참고하세요."
    p = g["price_chg_90d"]
    e = g.get("eps_rev_90d")
    if e is None:
        return "자료 없음", "주가는 90일간 {:+.0f}%이지만 예상 이익 수정 자료가 없어 원인을 나눌 수 없습니다(ETF·한국 종목은 자료가 없는 경우가 많음).".format(p * 100)
    m = g["mult_chg_90d"]
    base = "90일간 주가 {:+.0f}% = 예상 이익 수정 {:+.0f}% × 밸류에이션 배수 변화 {:+.0f}%".format(p * 100, e * 100, m * 100)
    if p >= 0.10:
        if e >= 0.6 * p and e > 0.03:
            return "가치 성장에 따른 상승", base + ". 상승의 상당 부분을 이익 전망 상향이 설명합니다."
        if m >= 0.15 and e < 0.3 * p:
            return "기대감 과열에 따른 상승", base + ". 이익 전망보다 주가·배수가 빨리 올랐습니다(추격 매수 주의)."
        return "혼재(이익·배수 모두 기여)", base + "."
    if p <= -0.10:
        if e <= -0.05:
            return "기업가치 훼손 가능성에 따른 하락", base + ". 이익 전망이 내려갔으므로 저평가로 단정하지 말고 투자 논리를 다시 확인해야 합니다."
        if e >= -0.02:
            return "시장심리에 따른 과도한 하락 가능성", base + ". 이익 전망은 거의 유지되는데 주가만 내렸습니다(적정가 괴리 확대 가능성, 검증 필요)."
        return "혼재(전망 일부 하향)", base + "."
    return "뚜렷한 괴리 없음", base + "."


# ------------------------------------------------------------------ 종목별 운용 판단(5가지 비중 출력 + 최종)
def judge(it, sen, gap_type, weight_pct, alert_w=25.0):
    """규칙 기반 운용 판단. 단일 신호·비중만·평단만으로 결론 내지 않는다. -> dict"""
    tk = str(it["tk"]).upper()
    core = tk in CORE_TICKERS
    stance = str(it.get("sv_txt") or "")
    thesis = "훼손" if "훼손" in stance else "주의" if "주의" in stance else "유지" if any(k in stance for k in ("견고", "유지", "양호")) else "판단 보류"
    quality = "훼손" if thesis == "훼손" else "견고" if "견고" in stance else "보통" if stance else "미확인"
    wlab = "과도" if weight_pct >= alert_w * 1.4 else "주의" if weight_pct >= alert_w else "적정"
    why, flip = [], []
    if not sen:
        return {"quality": quality, "thesis": thesis, "valuation": "판단 보류", "sentiment": "자료 없음", "weight": wlab, "final": "유지", "why": ["가격·거래량 자료가 부족해 판단을 보류합니다."],
                "flip": ["자료가 확보되면 다시 판단"], "bucket_note": "", "conf": "판단 보류"}
    st_ = sen["stage"]
    sent_lab = {1: "극단적 공포", 2: "비관", 3: "중립", 4: "낙관", 5: "극단적 낙관"}[st_]
    if gap_type in ("기대감 과열에 따른 상승",) and st_ >= 4:
        val = "과열" if st_ == 5 else "부담"
    elif gap_type == "가치 성장에 따른 상승":
        val = "적정" if st_ >= 4 else "적정"
    elif gap_type == "시장심리에 따른 과도한 하락 가능성":
        val = "매력적" if st_ <= 2 else "적정"
    elif gap_type == "기업가치 훼손 가능성에 따른 하락":
        val = "판단 보류"
    else:
        val = "적정" if st_ == 3 else ("부담" if st_ >= 4 else "판단 보류" if gap_type == "자료 없음" else "적정")
    if gap_type == "자료 없음" and st_ <= 2:
        val = "판단 보류"
    conf = sen["confidence"]
    if thesis == "훼손" or gap_type == "기업가치 훼손 가능성에 따른 하락":
        final = "재평가"
        why.append("투자 논리 또는 이익 전망이 훼손됐을 가능성: 가격이 싸 보여도 매수하지 않고 전면 재평가")
        flip.append("실적·이익 전망이 안정되면 재판단")
    elif core:
        final = "정기 적립" if st_ <= 4 else "정기 적립(속도 조절 검토)"
        why.append("코어 자산은 단기 심리 신호로 매도하지 않습니다. 적립 속도만 조절합니다.")
        flip.append("시장 전체 위험이 극단이면 적립 속도 조절")
    elif st_ == 5 and conf != "낮음" and len(sen["hot"]) >= 3 and gap_type != "가치 성장에 따른 상승" and wlab in ("주의", "과도"):
        final = "일부 축소 검토"
        why.append("과열 신호 {}개가 동시에 관찰되고 비중도 {}입니다. 핵심 보유분은 유지하고 '조절 물량' 범위에서만 검토합니다.".format(len(sen["hot"]), wlab))
        flip.append("이익 전망이 계속 상향되고 가격 부담이 줄면 유지")
    elif st_ >= 4:
        final = "추가 매수 중단(유지)" if st_ == 5 else "유지"
        why.append("과열 쪽 신호는 있으나 매도 근거로는 부족합니다(단일·소수 신호). 새 돈 투입만 신중히.")
        flip.append("과열 신호가 3개 이상 겹치고 이익 전망 상향이 멈추면 조절 물량 축소 검토")
    elif st_ <= 2 and thesis in ("유지", "판단 보류") and gap_type == "시장심리에 따른 과도한 하락 가능성":
        final = "적극적인 매수 기회 검토" if (st_ == 1 and conf != "낮음") else "추가 매수 검토"
        why.append("이익 전망은 유지되는데 주가만 내려 심리 위축 가능성. 단 분할로 접근하고 바닥은 단정하지 않습니다.")
        flip.append("이익 전망이 하향되면 보류로 전환")
    elif st_ <= 2:
        final = "대기"
        why.append("공포 쪽 신호는 있으나 가치 괴리를 확인할 자료가 부족합니다. 펀더멘털 재확인 전까지 보류.")
        flip.append("예상 이익이 유지되는 것이 확인되면 매수 검토")
    else:
        final = "정기 적립" if str(it.get("mode")) == "적립형" else "유지"
        why.append("뚜렷한 과열·공포 신호가 없습니다.")
    if sen["hot"]:
        why += ["과열 신호: " + x for x in sen["hot"][:3]]
    if sen["cold"]:
        why += ["공포 신호: " + x for x in sen["cold"][:3]]
    return {"quality": quality, "thesis": thesis, "valuation": val, "sentiment": sent_lab, "weight": wlab, "final": final, "why": why, "flip": flip, "conf": conf}


# ------------------------------------------------------------------ 계산 묶음(AI 전략가에게도 전달)
def analyze_all(items, get_prices, fx_use):
    """모든 보유 종목의 심리·괴리·판단. -> {ticker: dict}"""
    total = sum((i.get("value") or 0) * (fx_use if i["cur"] == "USD" else 1.0) for i in items) or 1.0
    out = {}
    for i in items:
        sym = i["tk"] if str(i["tk"]).endswith((".KS", ".KQ")) else str(i["tk"]).replace(".", "-")
        core = str(i["tk"]).upper() in CORE_TICKERS
        sen = sentiment(get_prices, sym, core)
        g = value_gap(sym) if not str(i["tk"]).upper() in ("VOO",) else None
        gt, gx = classify_gap(g)
        w = (i.get("value") or 0) * (fx_use if i["cur"] == "USD" else 1.0) / total * 100
        out[i["tk"]] = {"sen": sen, "gap": g, "gap_type": gt, "gap_text": gx, "judge": judge(i, sen, gt, w), "weight": w}
    return out


def cached_analysis(items, get_prices, fx_use):
    """15분 동안 결과를 재사용한다(처음 한 번은 종목 수만큼 시세·예상이익 조회로 수십 초 걸릴 수 있음)."""
    import time
    sig = (tuple(sorted(str(i["tk"]) for i in items)), round(float(fx_use or 0), -1))
    c = st.session_state.get("_kost_cache")
    if c and c["sig"] == sig and time.time() - c["t"] < 900:
        return c["an"]
    an = analyze_all(items, get_prices, fx_use)
    st.session_state["_kost_cache"] = {"sig": sig, "t": time.time(), "an": an}
    st.session_state["_kost_compact"] = compact(an)
    return an


def compact(an):
    """AI에게 보낼 요약(필요한 것만)."""
    d = {}
    for tk, a in an.items():
        s = a["sen"]
        d[tk] = {"sentiment_stage": None if not s else s["stage"], "sentiment_label": None if not s else s["label"], "sentiment_confidence": None if not s else s["confidence"],
                 "hot_signals": None if not s else s["hot"], "cold_signals": None if not s else s["cold"], "camp_estimate": None if not s else s["camp"],
                 "price_vs_value": a["gap_type"], "price_vs_value_detail": a["gap_text"], "rule_final": a["judge"]["final"], "rule_valuation": a["judge"]["valuation"]}
    return d


# ------------------------------------------------------------------ 화면
def _snapshot_stage(get_conn, an):
    """하루 한 번 단계 이력 저장(변화 이력용)."""
    try:
        today = date.today().isoformat()
        df = ai_agent._run(get_conn, "SELECT ticker FROM sentiment_hist WHERE day=%s", (today,), fetch=True)
        have = set(df["ticker"]) if df is not None and len(df) else set()
        for tk, a in an.items():
            if a["sen"] and tk not in have:
                ai_agent._run(get_conn, "INSERT INTO sentiment_hist (day,ticker,stage,confidence) VALUES (%s,%s,%s,%s)", (today, tk, int(a["sen"]["stage"]), a["sen"]["confidence"]))
    except Exception:  # noqa: BLE001
        pass


def render_sentiment_board(get_conn, items, an, fx_use):
    """A·B·C 화면: 시장심리 + 가치 괴리 + 종목별 운용 판단."""
    ensure_tables(get_conn)
    _snapshot_stage(get_conn, an)
    st.markdown("#### 코스톨라니 심리 · 가치 괴리 · 운용 판단")
    st.caption("가격·거래량 패턴으로 '추정'한 상태입니다(소신파·부화뇌동파 우위는 직접 관찰할 수 없음). 규칙은 검증 전이라 매매 명령이 아니라 판단 재료입니다. 신호 하나만으로는 단계를 올리지 않습니다.")
    rows = []
    for i in items:
        a = an.get(i["tk"])
        if not a:
            continue
        s, j = a["sen"], a["judge"]
        rows.append({"종목": i["name"], "심리 단계": "자료 없음" if not s else "{} {}".format(s["stage"], j["sentiment"]), "신뢰도": j["conf"], "주가 vs 가치": a["gap_type"], "밸류에이션": j["valuation"],
                     "비중": "{} ({:.0f}%)".format(j["weight"], a["weight"]), "최종 판단": j["final"]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    names = [i["name"] for i in items if an.get(i["tk"])]
    if not names:
        return
    pick = st.selectbox("종목별 자세히 보기", names, key="kost_pick")
    it = next(i for i in items if i["name"] == pick)
    render_detail(get_conn, it, an[it["tk"]])


def render_detail(get_conn, it, a):
    """종목 하나의 코스톨라니 판단 상세(심리 단계·근거·가치 괴리·다음 조건·변화 이력)."""
    s, j = a["sen"], a["judge"]
    c1, c2, c3 = st.columns(3)
    c1.metric("시장심리(추정)", "자료 없음" if not s else "{}단계".format(s["stage"]), None if not s else s["label"])
    c2.metric("판단 신뢰도", j["conf"])
    c3.metric("최종 판단(규칙)", j["final"])
    if s:
        st.write("**우위 추정**: " + s["camp"])
        st.write("**가격·거래량 관계**: " + str(s["facts"].get("가격·거래량 해석")))
        st.write("**근거**: " + " / ".join(j["why"]))
        st.write("**주가 vs 기업가치**: [{}] {}".format(a["gap_type"], a["gap_text"]))
        st.write("**다음 단계로 이동할 조건**: " + s["next"])
        st.write("**판단이 바뀌는 조건**: " + " / ".join(j["flip"]))
        with st.expander("확인하지 못한 것 · 계산 수치"):
            for u in s["unknown"]:
                st.write("- " + u)
            st.write(s["facts"])
            st.caption("출처: Yahoo Finance 일봉(1년) 자체 계산. 기준일 {}.".format(date.today().isoformat()))
    try:
        h = ai_agent._run(get_conn, "SELECT day, stage, confidence FROM sentiment_hist WHERE ticker=%s ORDER BY day DESC LIMIT 12", (it["tk"],), fetch=True)
        if h is not None and len(h) > 1:
            st.caption("최근 심리 단계 변화: " + " ← ".join("{}({})".format(r["stage"], r["day"][5:]) for _, r in h.iterrows()))
    except Exception:  # noqa: BLE001
        pass


def render_split_and_log(get_conn, items, an, fx_use):
    """D 화면: 핵심/조절 물량 설정 + 조절 기록. 기록은 보유 수량을 바꾸지 않는다(실제 체결을 입력한 뒤 보유 입력 탭에서 수량 반영)."""
    ensure_tables(get_conn)
    saved = load_split(get_conn)
    st.markdown("#### 핵심 보유 · 전략적 조절 물량")
    st.caption("핵심 보유는 투자 논리가 유지되는 동안 단기 과열 신호로 팔지 않는 물량, 조절 물량은 과열·공포 국면에서 늘리거나 줄일 수 있는 범위입니다. 종목마다 직접 정합니다(코어 ETF·버크셔는 기본 100%).")
    rows = []
    for i in items:
        p = split_of(i["tk"], saved)
        rows.append({"티커": i["tk"], "종목": i["name"], "수량": round(i["qty"], 4), "핵심 %": p, "조절 가능 수량": round(i["qty"] * (100 - p) / 100, 4)})
    ed = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True, key="split_ed_v1", disabled=["티커", "종목", "수량", "조절 가능 수량"],
                        column_config={"핵심 %": st.column_config.NumberColumn(min_value=0, max_value=100, step=5)})
    if st.button("핵심 비율 저장", key="split_save"):
        try:
            for _, r in ed.iterrows():
                ai_agent._run(get_conn, "INSERT INTO hold_split (ticker,core_pct,updated_at) VALUES (%s,%s,%s) ON CONFLICT (ticker) DO UPDATE SET core_pct=EXCLUDED.core_pct, updated_at=EXCLUDED.updated_at",
                              (r["티커"], int(r["핵심 %"]), datetime.now(timezone.utc).isoformat(timespec="seconds")))
            st.success("저장했습니다.")
        except Exception as e:  # noqa: BLE001
            st.error("저장 실패: " + str(e)[:150])
    with st.expander("조절 기록 남기기 (실제로 체결한 매수·매도만)"):
        st.caption("여기에 기록해도 보유 수량·예수금은 자동으로 바뀌지 않습니다. 수량은 '보유·거래 입력' 탭에서, 달러·원화 잔액은 '환전·달러 예수금'에서 반영하세요(이중 차감 방지).")
        with st.form("adj_form", clear_on_submit=True):
            nm = st.selectbox("종목", [i["name"] for i in items])
            c1, c2, c3 = st.columns(3)
            side = c1.selectbox("구분", ["매수", "매도"])
            qty = c2.number_input("수량", min_value=0.0, value=0.0, step=0.001, format="%.4f")
            px = c3.number_input("실제 체결 가격", min_value=0.0, value=0.0, step=0.01)
            bucket = st.selectbox("물량 구분", ["핵심 보유분", "전략적 조절분"])
            cash_ch = st.number_input("현금 잔액 변화(원화 환산, 매수는 −, 매도는 +)", value=0.0, step=1000.0)
            why = st.text_area("실행 이유")
            ok = st.form_submit_button("기록 저장")
        if ok:
            it = next(i for i in items if i["name"] == nm)
            a = an.get(it["tk"]) or {}
            j = a.get("judge") or {}
            try:
                ai_agent._run(get_conn, "INSERT INTO adjust_log (created_at,trade_date,ticker,name,side,qty,price,currency,bucket,valuation,sentiment,weight_before,cash_change,reason) "
                                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                              (datetime.now(timezone.utc).isoformat(timespec="seconds"), date.today().isoformat(), it["tk"], nm, side, qty, px, it["cur"], bucket, j.get("valuation"),
                               "{} (신뢰도 {})".format(j.get("sentiment"), j.get("conf")), a.get("weight"), cash_ch, why))
                st.success("기록했습니다. 당시 심리·밸류에이션·비중도 함께 저장했어요.")
            except Exception as e:  # noqa: BLE001
                st.error("기록 실패: " + str(e)[:150])
        try:
            lg = ai_agent._run(get_conn, "SELECT trade_date, name, side, qty, price, bucket, valuation, sentiment, weight_before, cash_change, reason FROM adjust_log ORDER BY id DESC LIMIT 30", fetch=True)
            if lg is not None and len(lg):
                st.dataframe(lg, use_container_width=True, hide_index=True)
        except Exception:  # noqa: BLE001
            pass
