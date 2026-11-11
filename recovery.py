"""손실 종목 회복 점검: 평단까지 필요한 상승률 vs 외부 애널리스트 컨센서스 목표가(야후 집계).

예측이 아니라 '시장 전문가들의 평균 시각이 내 평단 위인가 아래인가'를 보여 주는 참고 자료다.
목표가는 집계 시점이 늦거나 비어 있을 수 있고, 한국 종목은 자료가 없는 경우가 많다.
"""
import streamlit as st


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def consensus(symbol):
    """야후 파이낸스 컨센서스(평균·최저·최고 목표가, 의견 수, 추천). 없으면 None."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001
        return None
    g = lambda k: (float(info[k]) if info.get(k) not in (None, "") else None)
    mean, low, high = g("targetMeanPrice"), g("targetLowPrice"), g("targetHighPrice")
    n = info.get("numberOfAnalystOpinions")
    if mean is None and low is None and high is None:
        return None
    return {"mean": mean, "low": low, "high": high, "n": int(n) if n else None, "rec": info.get("recommendationKey")}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def hist_rate(symbol, need):
    """과거 10년 중, 어느 날 샀다면 이후 6개월/12개월 안에 고가가 +need 이상 오른 적이 있던 날의 비율(%). 과거 빈도이지 예측이 아니다."""
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="10y", auto_adjust=True)
        c, hi = h["Close"].dropna(), h["High"].dropna()
    except Exception:  # noqa: BLE001
        return None
    if len(c) < 400:
        return None
    out = {"표본": int(len(c))}
    for lab, d in (("6개월", 126), ("12개월", 252)):
        fut = hi[::-1].rolling(d, min_periods=d).max()[::-1].shift(-1)
        ok = (fut / c - 1).dropna()
        out[lab] = None if ok.empty else float((ok >= need).mean() * 100)
    return out


def assess(it, cons, ai_target=None, hist=None):
    """한 종목의 회복 점검 결과(dict). 손실 종목이 아니면 None."""
    price, avg, ret = it.get("price"), it.get("avg"), it.get("ret")
    if not price or not avg or ret is None or ret >= 0:
        return None
    need = avg / price - 1
    out = {"종목": it["name"], "평단 대비": ret, "평단까지 필요한 상승": need, "목표가(평균)": None, "여력": None, "범위": None, "판정": "자료 없음", "출처": "", "과거빈도6m": None, "과거빈도12m": None, "표본": None}
    if hist:
        out["과거빈도6m"], out["과거빈도12m"], out["표본"] = hist.get("6개월"), hist.get("12개월"), hist.get("표본")
    mean = (cons or {}).get("mean")
    src = "야후 집계 컨센서스" + (" ({}명)".format(cons["n"]) if cons and cons.get("n") else "")
    if mean is None and ai_target:
        mean, src = ai_target, "AI 검색 분석의 외부 목표가"
    if mean is None:
        out["판정"] = "목표가 자료 없음 — 회복 가능성은 판단 보류"
        return out
    out["목표가(평균)"] = mean
    out["여력"] = mean / price - 1
    out["출처"] = src
    lo, hi = (cons or {}).get("low"), (cons or {}).get("high")
    if lo and hi:
        out["범위"] = (lo, hi)
    if lo and lo >= avg:
        out["판정"] = "전문가 최저 목표가도 평단 위 — 회복 근거 비교적 견고(예측 아님)"
    elif mean >= avg * 1.05:
        out["판정"] = "평균 목표가가 평단 위 — 회복 여지(목표 달성 보장 없음)"
    elif mean >= avg * 0.95:
        out["판정"] = "평균 목표가가 평단 부근 — 본전 회복은 가능하나 여유 적음"
    else:
        out["판정"] = "평균 목표가가 평단 아래 — 전문가 평균은 평단 회복을 기대하지 않음, 보유 가설 재점검"
    return out
