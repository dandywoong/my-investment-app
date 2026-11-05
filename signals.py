# -*- coding: utf-8 -*-
"""signals.py — 종목별 차트 신호 · 시장 심리 · 종합 점수 (검증 전 규칙).

모든 점수는 '지금 추가 매수 우선순위'를 비교하기 위한 상대 점수일 뿐,
수익·승률·확률이 아닙니다. 각 항목은 근거 문장과 함께 나옵니다.
"""
import math

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------- 지표 계산
def _ohlc(get_prices, sym, period="1y"):
    res = get_prices(sym, period)
    df = res[0] if isinstance(res, tuple) else res
    if df is None or len(df) == 0 or "Close" not in df.columns:
        return None
    return df


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, float("nan"))
    r = 100 - 100 / (1 + rs)
    return float(r.iloc[-1]) if pd.notna(r.iloc[-1]) else None


def chart_signals(get_prices, sym):
    """볼린저(20,2) %B·밴드폭, RSI14, 20/60/200일선 이격, 52주 위치, 거래량 배수, 3·6·12개월 수익률. 없으면 None."""
    try:
        df = _ohlc(get_prices, sym, "1y")
        if df is None:
            return None
        c = df["Close"].dropna()
        if len(c) < 60:
            return None
        out = {"price": float(c.iloc[-1]), "n": len(c)}
        m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
        up, lo = m20 + 2 * s20, m20 - 2 * s20
        width = float(up.iloc[-1] - lo.iloc[-1])
        out["pctb"] = float((c.iloc[-1] - lo.iloc[-1]) / width) if width > 0 else None
        out["bbw"] = float(width / m20.iloc[-1]) if m20.iloc[-1] else None
        bw_series = ((up - lo) / m20).dropna()
        out["bbw_rank"] = float((bw_series <= bw_series.iloc[-1]).mean()) if len(bw_series) > 20 else None
        out["rsi"] = _rsi(c)
        for n in (20, 60, 200):
            if len(c) >= n:
                out["ma%d" % n] = float(c.iloc[-1] / c.rolling(n).mean().iloc[-1] - 1)
        if len(c) >= 220:
            m200 = c.rolling(200).mean()
            out["ma200_slope"] = float(m200.iloc[-1] / m200.iloc[-20] - 1)
        hi, lo52 = float(c.max()), float(c.min())
        out["pos52"] = float((c.iloc[-1] - lo52) / (hi - lo52)) if hi > lo52 else None
        out["dd52"] = float(c.iloc[-1] / hi - 1)
        out["dd60"] = float(c.iloc[-1] / c.tail(60).max() - 1)
        for k, n in (("r3m", 63), ("r6m", 126), ("r12m", 250)):
            if len(c) > n:
                out[k] = float(c.iloc[-1] / c.iloc[-1 - n] - 1)
        if "Volume" in df.columns:
            v = df["Volume"].dropna()
            if len(v) >= 25 and float(v.tail(20).mean()) > 0:
                out["vol_x"] = float(v.tail(3).mean() / v.tail(20).mean())
        return out
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 시장 심리
@st.cache_data(ttl=3600, show_spinner=False)
def _cnn_fear_greed():
    """CNN 공포·탐욕 지수(0~100). 막히면 None. 비공식 주소라 언제든 막힐 수 있다."""
    try:
        import requests
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://edition.cnn.com/"}, timeout=8)
        if r.status_code != 200:
            return None
        fg = r.json().get("fear_and_greed", {})
        s = float(fg.get("score"))
        return {"score": s, "rating": str(fg.get("rating", "")), "date": str(fg.get("timestamp", ""))[:10]}
    except Exception:  # noqa: BLE001
        return None


def market_mood(get_prices, region):
    """시장 탐욕도 0(극단 공포)~100(극단 탐욕). 자체 계산(변동성 위치 + 지수 RSI + 지수 볼린저 위치) + (미국) CNN 지수 참고.
    -> {"greed": float|None, "parts": [문장], "label": str}"""
    parts, vals = [], []
    idx = "^KS11" if region == "KR" else "^GSPC"
    try:
        s = chart_signals(get_prices, idx)
        if s:
            if s.get("rsi") is not None:
                vals.append(s["rsi"]); parts.append("지수 RSI {:.0f}".format(s["rsi"]))
            if s.get("pctb") is not None:
                vals.append(max(0.0, min(1.0, s["pctb"])) * 100); parts.append("지수 볼린저 위치 {:.0f}%".format(s["pctb"] * 100))
            if s.get("dd52") is not None:
                vals.append(max(0.0, 100 + s["dd52"] * 100 * 3)); parts.append("52주 고점 대비 {:+.1f}%".format(s["dd52"] * 100))
    except Exception:  # noqa: BLE001
        pass
    vix_sym = "^VIX" if region == "US" else "^VKOSPI"
    try:
        df = _ohlc(get_prices, vix_sym, "1y")
        if df is not None:
            c = df["Close"].dropna()
            if len(c) > 60:
                rank = float((c <= c.iloc[-1]).mean())
                vals.append((1 - rank) * 100)
                parts.append("{} {:.1f} (1년 중 {:.0f}번째 백분위)".format("VIX" if region == "US" else "VKOSPI", float(c.iloc[-1]), rank * 100))
    except Exception:  # noqa: BLE001
        pass
    cnn = _cnn_fear_greed() if region == "US" else None
    if cnn:
        vals.append(cnn["score"])
        parts.append("CNN 공포탐욕 {:.0f} ({})".format(cnn["score"], cnn["rating"]))
    elif region == "US":
        parts.append("CNN 공포탐욕 미연결")
    if not vals:
        return {"greed": None, "parts": ["시장 심리 자료 없음"], "label": "자료 없음"}
    g = sum(vals) / len(vals)
    label = "극단 공포" if g < 25 else "공포" if g < 40 else "중립" if g < 60 else "탐욕" if g < 75 else "극단 탐욕"
    return {"greed": g, "parts": parts, "label": label}


# ---------------------------------------------------------------- 종합 점수
# 항목별 최대 가점: 가격(평단·낙폭) ±5, 차트 타이밍 ±6, 시장 심리 ±3, 달걀 국면 ±3, 기업·전망 ±6, 포트폴리오 ±3
def score_item(it, sig, mood, avg_w):
    """종목 하나의 '지금 추가 매수 매력' 점수. -> {"total", "parts": {항목: (점수, [근거])}, "gate": 막힌 이유 or None}"""
    P = {}

    # 1) 가격: 평단 대비 · 고점 대비
    pts, why = 0.0, []
    ret = it.get("ret")
    if ret is not None:
        if ret <= -0.25:
            pts += 3; why.append("평단 대비 {:+.0%} (평단을 크게 낮출 기회) +3".format(ret))
        elif ret <= -0.10:
            pts += 2; why.append("평단 대비 {:+.0%} +2".format(ret))
        elif ret <= -0.03:
            pts += 1; why.append("평단 대비 {:+.0%} +1".format(ret))
        elif ret >= 0.40:
            pts -= 2; why.append("평단 대비 {:+.0%} (많이 올라 추격 매수 부담) -2".format(ret))
        elif ret >= 0.15:
            pts -= 1; why.append("평단 대비 {:+.0%} -1".format(ret))
    dd = (sig or {}).get("dd52", it.get("dd60"))
    if dd is not None:
        if dd <= -0.30:
            pts += 2; why.append("52주 고점 대비 {:.0f}% +2".format(dd * 100))
        elif dd <= -0.15:
            pts += 1; why.append("52주 고점 대비 {:.0f}% +1".format(dd * 100))
        elif dd >= -0.03:
            pts -= 1; why.append("52주 고점 근처 -1")
    P["가격"] = (max(-5, min(5, pts)), why)

    # 2) 차트 타이밍: 볼린저·RSI·이평·거래량
    pts, why = 0.0, []
    if sig:
        b = sig.get("pctb")
        if b is not None:
            if b <= 0.0:
                pts += 2.5; why.append("볼린저 하단 이탈(%B {:.2f}) +2.5".format(b))
            elif b <= 0.2:
                pts += 1.5; why.append("볼린저 하단 근처(%B {:.2f}) +1.5".format(b))
            elif b >= 1.0:
                pts -= 2; why.append("볼린저 상단 이탈(%B {:.2f}) -2".format(b))
            elif b >= 0.8:
                pts -= 1; why.append("볼린저 상단 근처(%B {:.2f}) -1".format(b))
        r = sig.get("rsi")
        if r is not None:
            if r <= 30:
                pts += 2; why.append("RSI {:.0f} 과매도 +2".format(r))
            elif r <= 40:
                pts += 1; why.append("RSI {:.0f} 약세권 +1".format(r))
            elif r >= 75:
                pts -= 2; why.append("RSI {:.0f} 과열 -2".format(r))
            elif r >= 65:
                pts -= 1; why.append("RSI {:.0f} 높음 -1".format(r))
        m200, slope = sig.get("ma200"), sig.get("ma200_slope")
        if m200 is not None:
            if m200 < -0.05 and slope is not None and slope < -0.01:
                pts -= 1.5; why.append("200일선 아래 + 200일선 하락 중(떨어지는 칼날 주의) -1.5")
            elif m200 < -0.05:
                pts += 0.5; why.append("200일선 아래(조정 구간, 추세는 아직 꺾이지 않음) +0.5")
            elif -0.05 <= m200 <= 0.05 and (slope is None or slope >= 0):
                pts += 1; why.append("200일선 부근 지지 시험(추세 상승 유지) +1")
        vx = sig.get("vol_x")
        if vx is not None and vx >= 1.8 and (b is not None and b <= 0.25):
            pts += 0.5; why.append("하단에서 거래량 {:.1f}배(투매 가능성) +0.5".format(vx))
        bw = sig.get("bbw_rank")
        if bw is not None and bw <= 0.1:
            why.append("밴드 폭이 1년 중 최저권(변동성 응축 — 방향은 알 수 없음, 점수 없음)")
    else:
        why.append("차트 자료 없음 — 판단 보류(0점)")
    P["차트"] = (max(-6, min(6, pts)), why)

    # 3) 시장 심리
    pts, why = 0.0, []
    g = (mood or {}).get("greed")
    if g is not None:
        if g < 25:
            pts += 3; why.append("시장 심리 {:.0f} 극단 공포(남들이 팔 때) +3".format(g))
        elif g < 40:
            pts += 2; why.append("시장 심리 {:.0f} 공포 +2".format(g))
        elif g < 55:
            pts += 0.5; why.append("시장 심리 {:.0f} 중립 +0.5".format(g))
        elif g >= 75:
            pts -= 3; why.append("시장 심리 {:.0f} 극단 탐욕 -3".format(g))
        elif g >= 60:
            pts -= 1.5; why.append("시장 심리 {:.0f} 탐욕 -1.5".format(g))
    else:
        why.append("시장 심리 자료 없음(0점)")
    P["심리"] = (pts, why)

    # 4) 달걀 국면
    pts, why = 0.0, []
    top = it.get("top")
    table = {1: (3, "① 공포·투매(바닥권)"), 2: (2, "② 바닥 다지기"), 3: (1, "③ 회복 초기"), 4: (-1, "④ 상승 가속"), 5: (-3, "⑤ 과열·도취"), 6: (-1, "⑥ 상승 약화·하락 전환")}
    if top in table:
        pts, lab = table[top]
        why.append("{} {:+d}".format(lab, pts))
    else:
        why.append("국면 판단 보류(0점)")
    P["달걀 국면"] = (pts, why)

    # 5) 기업·전망 (기업 상태가 훼손이면 아래 gate에서 매수 자체를 막는다)
    pts, why = 0.0, []
    sv_val = it.get("sv_val")
    if sv_val == "견고":
        pts += 3; why.append("기업 상태 견고 +3")
    elif sv_val == "보통":
        pts += 1; why.append("기업 상태 보통 +1")
    elif sv_val == "미확인":
        pts -= 1; why.append("기업 상태 미확인 -1 (확인되면 점수가 달라질 수 있음)")
    if it.get("stale"):
        pts -= 1; why.append("기업 상태 기록이 오래됨 -1")
    if it.get("outlook") == "긍정":
        pts += 1; why.append("업황 긍정(AI·자료 인용) +1")
    elif it.get("outlook") == "부정":
        pts -= 2; why.append("업황 부정(AI·자료 인용) -2")
    tgt, price = it.get("target"), it.get("price")
    if tgt and price:
        up = tgt / price - 1
        if up >= 0.30:
            pts += 1.5; why.append("애널리스트 목표가 평균 대비 여력 {:+.0%}(외부 자료·검증 전) +1.5".format(up))
        elif up >= 0.15:
            pts += 0.5; why.append("목표가 대비 여력 {:+.0%} +0.5".format(up))
        elif up < 0:
            pts -= 1; why.append("현재가가 목표가 평균보다 높음 {:+.0%} -1".format(up))
    if sig:
        r12, r6 = sig.get("r12m"), sig.get("r6m")
        if r12 is not None and r12 > 0.2 and (sig.get("ma200") or 0) > -0.1:
            pts += 0.5; why.append("12개월 상승 추세 유지(수익률 {:+.0%}) +0.5".format(r12))
        elif r12 is not None and r12 < -0.3:
            pts -= 0.5; why.append("12개월 수익률 {:+.0%} 약한 추세 -0.5".format(r12))
    P["기업·전망"] = (max(-6, min(6, pts)), why)

    # 6) 포트폴리오 균형
    pts, why = 0.0, []
    w = it.get("weight")
    if w is not None:
        if w < avg_w * 0.6:
            pts += 2; why.append("비중 {:.0%} (평균 {:.0%}보다 많이 낮음) +2".format(w, avg_w))
        elif w < avg_w:
            pts += 1; why.append("비중 {:.0%} (평균 이하) +1".format(w))
        elif w > 0.35:
            pts -= 3; why.append("비중 {:.0%} 과대 -3".format(w))
        elif w > max(avg_w * 1.5, 0.25):
            pts -= 1.5; why.append("비중 {:.0%} 큼 -1.5".format(w))
    P["비중"] = (pts, why)

    total = sum(v[0] for v in P.values())
    gate = None
    if sv_val == "훼손":
        gate = "기업 상태 훼손 — 신규 매수 제외"
    elif it.get("outlook") == "부정" and sv_val != "견고":
        gate = "업황 부정 — 신규 매수 제외"
    elif it.get("kind") in ("sell", "stop"):
        gate = "행동 후보가 '{}'이라 신규 매수 제외".format(it.get("label", ""))
    return {"total": total, "parts": P, "gate": gate}


def grade(total):
    """점수 → 짧은 등급(상대 비교용)."""
    if total >= 10:
        return "A 적극"
    if total >= 6:
        return "B 우선"
    if total >= 3:
        return "C 소량"
    if total >= 0:
        return "D 관망"
    return "E 비선호"
