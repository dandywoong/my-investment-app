"""Eggfolio 감독실 v2 — 달걀(코스톨라니) 국면 기반 포트폴리오 감독. 읽기 전용.

구조
  축 1  기업 생존력(펀더멘탈 관문)      fundamentals_check()
  축 2  대중심리·시장 국면(달걀 엔진)    evaluate() / analyze_series()
  축 3  보유 종목별 행동 조건            build_action()
  화면  시장 달걀 + 종목별 달걀 지도      render_supervision()

원칙
  - DB에 아무것도 쓰지 않는다. 주문 기능이 없다.
  - 승률·확률·예상 수익률·목표가를 만들지 않는다.
  - 국면 경계와 규칙은 검증(백테스트) 전의 '규칙 기반 후보'다. 화면에 그렇게 표시한다.
  - 자료가 없으면 '자료 없음 / 판단 보류'로 표시하고, 없는 자료를 긍정·중립으로 취급하지 않는다.
"""
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

KST = timezone(timedelta(hours=9))
PRICE_PERIOD = "1y"
MIN_ROWS_FOR_PHASE = 130   # 120일선까지 계산되려면 필요한 최소 거래일
STALE_DAYS = 5             # 가격 기준일이 이보다 오래되면 '오래됨'
TRAIL_OFFSETS = (20, 10)   # 달걀 위에 표시할 과거 위치(거래일 전)
CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}

# 임시 점검 기준(권고값이 아님). 화면의 설정 패널에서 바꿀 수 있고 저장되지 않는다.
DEFAULTS = {
    "max_stock_weight": 30.0,
    "max_category_weight": 50.0,
    "bet_total_weight": 10.0,
    "bet_loss_limit": -30.0,
    "use_weight": False,   # True이면 비중 한도 초과가 행동 라벨에도 영향을 준다(기본: 종목 단독 판단)
    "sell_frac": 20.0,     # 분할 익절 1회당 보유 수량 비율(%) - 임시 가정
}

# 시장 달걀에 쓰는 지수. 야후 파이낸스에서 읽는다.
MARKETS = [
    ("KOSPI", "^KS11", "kr"),
    ("KOSDAQ", "^KQ11", "kr"),
    ("S&P 500", "^GSPC", "us"),
    ("나스닥", "^IXIC", "us"),
    ("필라델피아 반도체", "^SOX", "us"),
]

# 달걀 국면. 번호는 순환 순서(1→2→3→4→5→6→1)다. 코스톨라니 달걀 이론에서 착안한 설계이며
# 각 국면의 경계는 검증된 기준이 아니다.
PHASES = {
    1: {"name": "공포·투매", "color": "#1E88E5",
        "mood": "공포 확대 · 투매 압력",
        "good": ["기업 논리와 재무가 유지되는지 먼저 확인", "분할 매수는 소규모 1차로 한정하고 하락 가속이 멈추는지 확인",
                 "투자 가설의 무효화 조건 재확인"],
        "avoid": ["하락 가속 중 큰 금액을 한 번에 매수", "'싸 보인다'는 이유만으로 펀더멘탈 확인 없이 매수",
                  "공포에 쫓겨 근거 없이 일괄 매도"]},
    2: {"name": "바닥 다지기·회의", "color": "#64748B",
        "mood": "회의 · 관망 · 매도 압력 둔화",
        "good": ["저점 갱신이 멈췄는지, 거래량이 줄어드는지 확인", "수급 방향 전환(외국인·기관) 확인",
                 "확인 전에는 대기하거나 소규모로만 접근"],
        "avoid": ["반등 하루이틀만 보고 비중 확대", "논리 확인 없는 물타기"]},
    3: {"name": "회복 초기", "color": "#10B981",
        "mood": "회복 기대 · 의심 속 반등",
        "good": ["20일선 회복이 유지되는지, 거래량이 동반되는지 확인", "회복 확인 뒤 비중 한도 안에서 분할 추가 검토"],
        "avoid": ["첫 반등에서 추격 매수", "무효화 조건 없이 비중 확대"]},
    4: {"name": "상승 추세·낙관 확산", "color": "#F59E0B",
        "mood": "낙관 확산 · 추세 참여 증가",
        "good": ["보유 근거(실적·논리)가 유지되는지 점검하며 보유 지속", "추가 매수는 종목·카테고리 비중 한도 안에서만"],
        "avoid": ["단기 급등 구간에서 집중 비중 확대", "근거 없는 기대 수익 상향"]},
    5: {"name": "과열·도취", "color": "#E53935",
        "mood": "도취 · 과열 · 기대의 선반영",
        "good": ["비중과 밸류에이션 점검", "분할 매도 후보 검토(전량 매도 아님)", "기업 성장·기대 수익과 함께 비교"],
        "avoid": ["과열 신호만으로 전량 매도", "'이번엔 다르다'며 비중 추가 확대"]},
    6: {"name": "상승 동력 약화·하락 전환", "color": "#8B5CF6",
        "mood": "기대 약화 · 차익 실현 · 분배",
        "good": ["20일선·60일선 이탈 여부와 거래량 확인", "비중 점검과 투자 논리 재평가", "축소 검토 조건을 미리 문서화"],
        "avoid": ["하락을 일시 조정으로 단정하고 물타기", "근거 재확인 없이 보유 지속"]},
}

ACTIONS = {
    1: {"candidate": "분할 매수 후보 탐색 (소규모 1차 → 하락 가속 멈춤 확인 후 추가)",
        "confirm": ["최근 10거래일 저점이 이전 저점을 더 낮추지 못함", "하락일 거래량이 줄어듦(투매 소진 징후)",
                    "기업 생존력 자동 점검이 '주의'가 아님", "투자 가설의 무효화 조건이 위반되지 않음"],
        "stop": ["직전 저점 아래로 내려가며 거래량 증가", "실적·재무 악화 등 기업 가치 훼손 확인", "비중 한도 도달"]},
    2: {"candidate": "확인 뒤 소규모 분할 검토 (확인 전에는 대기)",
        "confirm": ["20일선 회복과 거래량 증가가 함께 나타남", "외국인·기관 순매수 전환(한국 종목)", "저점 갱신 없이 변동성 수축 지속"],
        "stop": ["저점 이탈", "수급 재악화"]},
    3: {"candidate": "회복 확인 중 — 비중 한도 안에서 분할 추가 후보",
        "confirm": ["20일선 위 종가 유지", "상승일 거래량이 하락일보다 큼", "60일선 회복 시도"],
        "stop": ["20일선 재이탈", "회복 구간에 거래량이 따라오지 않음"]},
    4: {"candidate": "보유 유지 · 추가 매수는 비중 한도 안에서만",
        "confirm": ["보유 근거(실적·투자 논리) 유지", "종목·카테고리 비중 한도에 여유가 있음"],
        "stop": ["단기 급등(20일 수익률이 변동성 대비 과도)과 집중 비중이 겹침", "투자 가설 무효화 조건 발생"]},
    5: {"candidate": "분할 매도 후보 검토 (전량 매도 아님)",
        "confirm": ["비중이 한도를 넘었는지", "기대가 가격에 선반영되었는지(밸류에이션 점검)", "기업 성장·기대 수익과 비교"],
        "stop": ["펀더멘탈이 계속 개선되고 비중이 한도 안이면 과열 신호만으로 매도하지 않음"]},
    6: {"candidate": "비중 점검 · 논리 재평가 · 축소 검토 조건 준비",
        "confirm": ["20일선 회복 실패 여부", "60일선 이탈 여부", "고점 이후 하락일 거래량 증가 여부"],
        "stop": ["20일선·60일선을 다시 회복하고 거래량이 동반되면 재평가"]},
}


# --------------------------------------------------------------------------
# 도우미
# --------------------------------------------------------------------------
def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        x = float(v)
        if math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _fmt(v, digits=2, suffix=""):
    x = _num(v)
    return "자료 없음" if x is None else "{:,.{d}f}{s}".format(x, d=digits, s=suffix)


def _pct(v, digits=1):
    x = _num(v)
    return "자료 없음" if x is None else "{:+.{d}f}%".format(x * 100, d=digits)


def _money(v, cur):
    x = _num(v)
    return "자료 없음" if x is None else "{:,.0f} {}".format(x, cur)


def _today_kst():
    return datetime.now(KST).date()


def _parse_date(text):
    try:
        return datetime.fromisoformat(str(text)).date()
    except (TypeError, ValueError):
        return None


def _lt(a, b): return None if a is None or b is None else a < b
def _le(a, b): return None if a is None or b is None else a <= b
def _gt(a, b): return None if a is None or b is None else a > b
def _ge(a, b): return None if a is None or b is None else a >= b
def _btw(a, lo, hi): return None if a is None else (lo <= a <= hi)


def _and(*xs):
    if any(x is False for x in xs):
        return False
    if any(x is None for x in xs):
        return None
    return True


def _or(*xs):
    if any(x is True for x in xs):
        return True
    if any(x is None for x in xs):
        return None
    return False


def _read_prices(ticker, get_prices):
    try:
        res = get_prices(ticker, PRICE_PERIOD)
        df = res[0] if isinstance(res, tuple) else res
        if df is None or len(df) == 0:
            return None, "가격 자료 없음"
        return df, None
    except Exception as e:  # noqa: BLE001
        return None, "가격 조회 실패: " + str(e)[:120]


def _latest_decisions(decisions):
    out = {}
    if decisions is None or len(decisions) == 0:
        return out
    df = decisions.copy()
    if "id" in df.columns:
        df = df.sort_values("id", ascending=False)
    for _, r in df.iterrows():
        key = str(r.get("ticker", "")).strip().upper()
        if key and key not in out:
            out[key] = r
    return out


def next_phase(p):
    return p % 6 + 1


def prev_phase(p):
    return (p - 2) % 6 + 1


def phase_angle_deg(p):
    """달걀 위 국면 위치(도). 반시계 방향으로 ①→②→…→⑥ 순서."""
    return (210 + 60 * (p - 1)) % 360


def phase_label(p):
    return "{} {}".format(CIRCLED[p], PHASES[p]["name"])


# --------------------------------------------------------------------------
# 축 2: 국면 엔진
# --------------------------------------------------------------------------
def _slope_z(series, k, sd):
    try:
        if series is None or len(series) <= k:
            return None
        a, b = _num(series.iloc[-1]), _num(series.iloc[-1 - k])
        if a is None or b is None or b == 0:
            return None
        return (a / b - 1) / (sd * math.sqrt(k))
    except Exception:  # noqa: BLE001
        return None


def compute_features(df, ext=None):
    """가격·거래량 자료에서 심리 근거 지표를 뽑는다. 값은 변동성으로 정규화해 종목·지수를 같은 기준으로 본다."""
    f = {"n": len(df)}
    if len(df) < 60 or "Close" not in df.columns:
        return f
    close = df["Close"].astype(float)
    ret = close.pct_change()
    sd60 = _num(ret.tail(60).std(ddof=1))
    if sd60 is None or sd60 <= 0:
        return f
    sig_a = sd60 * math.sqrt(252)
    n = len(df)
    c = float(close.iloc[-1])
    f["close"] = c
    f["sig_a"] = sig_a

    def last(col):
        return _num(df[col].iloc[-1]) if col in df.columns else None

    f["ma20"], f["ma60"], f["ma120"] = last("MA20"), last("MA60"), last("MA120")
    f["atr"], f["bb_upper"], f["bb_lower"] = last("ATR14"), last("BB_Upper"), last("BB_Lower")
    hi_s = df["High"].astype(float) if "High" in df.columns else close
    lo_s = df["Low"].astype(float) if "Low" in df.columns else close
    f["high60"], f["high252"] = _num(hi_s.tail(60).max()), _num(hi_s.tail(252).max())
    f["low20"], f["low60"] = _num(lo_s.tail(20).min()), _num(lo_s.tail(60).min())
    f["rsi"], f["bb_pos"] = last("RSI14"), last("BB_Position")
    f["macd_hist"], f["vol_ratio20"] = last("MACD_Hist"), last("VolumeRatio20")
    f["ma20_slope_z"] = _slope_z(df["MA20"] if "MA20" in df.columns else None, 5, sd60)
    f["ma60_slope_z"] = _slope_z(df["MA60"] if "MA60" in df.columns else None, 10, sd60)

    for k in (5, 20, 60):
        if n > k:
            r = c / float(close.iloc[-1 - k]) - 1
            f["ret%d" % k] = r
            f["z%d" % k] = r / (sd60 * math.sqrt(k))
    hi252 = float(close.tail(252).max())
    f["dd"] = c / hi252 - 1
    f["dd_norm"] = f["dd"] / sig_a
    tail60 = close.tail(60)
    hi60 = float(tail60.max())
    f["high60_age"] = len(tail60) - 1 - int(tail60.values.argmax())
    f["dd60_norm"] = (c / hi60 - 1) / sig_a
    if f["ma20"]:
        f["dist20"] = c / f["ma20"] - 1
    if f["ma120"]:
        f["dist120"] = c / f["ma120"] - 1
        f["dist120_norm"] = f["dist120"] / sig_a

    sd10 = _num(ret.tail(10).std(ddof=1))
    if sd10 is not None:
        f["vol_expand"] = sd10 / sd60

    if "Low" in df.columns and n >= 30:
        f["low10"] = _num(df["Low"].tail(10).min())
        f["low_prior20"] = _num(df["Low"].iloc[-30:-10].min())

    if "Volume" in df.columns:
        vol = df["Volume"].astype(float)
        v20 = _num(vol.tail(20).mean())
        if v20 is not None and v20 > 0:
            f["vol5_20"] = float(vol.tail(5).mean()) / v20
            r20 = ret.tail(20)
            v_tail = vol.tail(20)
            up = float(v_tail[r20 > 0].sum())
            dn = float(v_tail[r20 < 0].sum())
            if dn > 0:
                f["updown"] = up / dn
            vma = vol.rolling(20).mean()
            climax = (ret <= -1.5 * sd60) & (vol >= 1.8 * vma)
            f["climax10"] = int(climax.tail(10).sum())

    if ext:
        f.update({k: v for k, v in ext.items() if _num(v) is not None})
    return f


def _phase_conditions():
    """국면별 근거 조건. (설명, 가중치, 선택 여부, 판정 함수). 선택 조건은 자료가 없어도 신뢰도 계산에서 감점하지 않는다."""
    P = {}
    P[1] = [
        ("종가가 60일선 아래", 1, False, lambda f: _lt(f.get("close"), f.get("ma60"))),
        ("종가가 20일선 아래", 1, False, lambda f: _lt(f.get("close"), f.get("ma20"))),
        ("20일선이 하락 중", 1, False, lambda f: _lt(f.get("ma20_slope_z"), -0.3)),
        ("20거래일 수익률이 변동성 대비 크게 음(z≤-1)", 2, False, lambda f: _le(f.get("z20"), -1.0)),
        ("52주 고점 대비 낙폭이 큼(변동성 대비 -0.6 이하)", 1, False, lambda f: _le(f.get("dd_norm"), -0.6)),
        ("하락 구간에 거래량 증가(5일 수익률<0, 거래량 20일 평균의 1.3배↑)", 1, False,
         lambda f: _and(_lt(f.get("ret5"), 0), _ge(f.get("vol_ratio20"), 1.3))),
        ("변동성 확대(최근 10일/60일 ≥ 1.3)", 1, False, lambda f: _ge(f.get("vol_expand"), 1.3)),
        ("투매성 급락일(큰 하락+거래량 급증) 관측", 1, False, lambda f: _ge(f.get("climax10"), 1)),
        ("RSI 35 이하", 1, False, lambda f: _le(f.get("rsi"), 35)),
        ("VIX가 1년 상위 20% 구간(미국 시장만)", 1, True, lambda f: _ge(f.get("vix_pct"), 0.8)),
        ("외국인·기관 5일 순매도(한국 종목만)", 1, True, lambda f: _and(_lt(f.get("f5"), 0), _lt(f.get("i5"), 0))),
    ]
    P[2] = [
        ("아직 120일선 아래이거나 낙폭이 큼", 1, False,
         lambda f: _or(_lt(f.get("close"), f.get("ma120")), _le(f.get("dd_norm"), -0.4))),
        ("최근 10일 저점이 이전 20일 저점보다 낮아지지 않음(저점 갱신 중단)", 2, False,
         lambda f: _ge(f.get("low10"), f.get("low_prior20"))),
        ("변동성 수축(최근 10일/60일 ≤ 0.9)", 1, False, lambda f: _le(f.get("vol_expand"), 0.9)),
        ("거래량 감소(최근 5일/20일 평균 ≤ 0.9)", 1, False, lambda f: _le(f.get("vol5_20"), 0.9)),
        ("20일선 ±3% 안에서 20일선이 평탄", 1, False,
         lambda f: _and(_btw(f.get("dist20"), -0.03, 0.03), _btw(f.get("ma20_slope_z"), -0.3, 0.3))),
        ("RSI 30~45", 1, False, lambda f: _btw(f.get("rsi"), 30, 45)),
        ("VIX가 상위권에서 하락 전환(미국 시장만)", 1, True,
         lambda f: _and(_ge(f.get("vix_pct"), 0.5), _lt(f.get("vix_chg10"), 0))),
        ("외국인 또는 기관 5일 순매수 전환(20일은 순매도, 한국 종목만)", 1, True,
         lambda f: _and(_or(_gt(f.get("f5"), 0), _gt(f.get("i5"), 0)),
                        _or(_lt(f.get("f20"), 0), _lt(f.get("i20"), 0)))),
    ]
    P[3] = [
        ("종가가 20일선 위", 1, False, lambda f: _gt(f.get("close"), f.get("ma20"))),
        ("20일선이 상승 전환", 1, False, lambda f: _gt(f.get("ma20_slope_z"), 0.3)),
        ("중기 추세 미확정(20일선이 60일선 아래이거나 60일선이 평탄·하락)", 1, False,
         lambda f: _or(_lt(f.get("ma20"), f.get("ma60")), _le(f.get("ma60_slope_z"), 0.3))),
        ("20거래일 수익률이 소폭 양(0<z≤1.5)", 1, False, lambda f: _and(_gt(f.get("z20"), 0), _le(f.get("z20"), 1.5))),
        ("상승일 거래량이 하락일보다 큼(≥1.1)", 1, False, lambda f: _ge(f.get("updown"), 1.1)),
        ("52주 고점 대비 아직 낙폭(변동성 대비 -0.3 이하)", 1, False, lambda f: _le(f.get("dd_norm"), -0.3)),
        ("MACD 히스토그램 양수", 1, False, lambda f: _gt(f.get("macd_hist"), 0)),
        ("외국인 또는 기관 5일 순매수(한국 종목만)", 1, True, lambda f: _or(_gt(f.get("f5"), 0), _gt(f.get("i5"), 0))),
    ]
    P[4] = [
        ("종가 > 20일선 > 60일선", 2, False,
         lambda f: _and(_gt(f.get("close"), f.get("ma20")), _gt(f.get("ma20"), f.get("ma60")))),
        ("60일선 상승", 1, False, lambda f: _gt(f.get("ma60_slope_z"), 0.3)),
        ("종가가 120일선 위", 1, False, lambda f: _gt(f.get("close"), f.get("ma120"))),
        ("60거래일 수익률이 변동성 대비 양(z>0.5)", 1, False, lambda f: _gt(f.get("z60"), 0.5)),
        ("RSI 55~70", 1, False, lambda f: _btw(f.get("rsi"), 55, 70)),
        ("52주 고점 근처(변동성 대비 -0.15 이내)", 1, False, lambda f: _ge(f.get("dd_norm"), -0.15)),
        ("상승일 거래량이 하락일보다 큼(≥1.1)", 1, False, lambda f: _ge(f.get("updown"), 1.1)),
        ("과열은 아님(20일 z<1.8, 볼린저 상단 미돌파)", 1, False,
         lambda f: _and(_lt(f.get("z20"), 1.8), _lt(f.get("bb_pos"), 1.0))),
    ]
    P[5] = [
        ("RSI 70 이상", 1, False, lambda f: _ge(f.get("rsi"), 70)),
        ("볼린저 밴드 상단 근처·돌파(위치 0.95↑)", 1, False, lambda f: _ge(f.get("bb_pos"), 0.95)),
        ("120일선 이격이 변동성 대비 큼(≥0.6)", 1, False, lambda f: _ge(f.get("dist120_norm"), 0.6)),
        ("20거래일 수익률 z ≥ 1.8", 1, False, lambda f: _ge(f.get("z20"), 1.8)),
        ("거래량 급증(20일 평균의 1.5배↑)", 1, False, lambda f: _ge(f.get("vol_ratio20"), 1.5)),
        ("5일 수익률 z ≥ 1.5(상승 가속)", 1, False, lambda f: _ge(f.get("z5"), 1.5)),
        ("52주 고점 근처(변동성 대비 -0.15 이내)", 1, False, lambda f: _ge(f.get("dd_norm"), -0.15)),
        ("VIX가 1년 하위 20% 구간(안도·낙관, 미국 시장만)", 1, True, lambda f: _le(f.get("vix_pct"), 0.2)),
    ]
    P[6] = [
        ("종가가 20일선 아래", 1, False, lambda f: _lt(f.get("close"), f.get("ma20"))),
        ("120일선 위이거나 낙폭이 중간(-0.6<낙폭≤-0.12)", 1, False,
         lambda f: _or(_gt(f.get("close"), f.get("ma120")),
                       _and(_gt(f.get("dd_norm"), -0.6), _le(f.get("dd_norm"), -0.12)))),
        ("MACD 히스토그램 음수", 1, False, lambda f: _lt(f.get("macd_hist"), 0)),
        ("60일 고점이 3거래일 이상 지났고 고점 대비 하락(-0.12 이하)", 1, False,
         lambda f: _and(_ge(f.get("high60_age"), 3), _le(f.get("dd60_norm"), -0.12))),
        ("하락일 거래량이 상승일보다 큼(상승/하락 거래량 ≤ 0.9)", 1, False, lambda f: _le(f.get("updown"), 0.9)),
        ("20일선 하락 전환, 60일선은 아직 상승·평탄", 1, False,
         lambda f: _and(_lt(f.get("ma20_slope_z"), -0.3), _ge(f.get("ma60_slope_z"), -0.3))),
        ("모멘텀 둔화(20일 z≤0, 60일 z>0)", 1, False, lambda f: _and(_le(f.get("z20"), 0), _gt(f.get("z60"), 0))),
        ("외국인 5일 순매도인데 종가는 60일선 위(한국 종목만)", 1, True,
         lambda f: _and(_lt(f.get("f5"), 0), _gt(f.get("close"), f.get("ma60")))),
    ]
    return P


_CONDS = _phase_conditions()


def evaluate(df, ext=None):
    """한 시점의 국면 판정. 모든 국면에 대해 '근거 일치도'(충족 가중치/평가 가능 가중치)를 구한다.
    일치도는 확률이 아니다. 어느 조건이 맞고 틀렸는지를 detail에 남긴다."""
    out = {"top": None, "second": None, "margin": None, "confidence": "판단 보류", "reason": "",
           "fits": {}, "cover": {}, "detail": {}, "features": {}}
    if df is None or len(df) < MIN_ROWS_FOR_PHASE:
        out["reason"] = "가격 자료가 {}거래일 미만이라 국면을 판정하지 않습니다.".format(MIN_ROWS_FOR_PHASE)
        return out
    f = compute_features(df, ext)
    out["features"] = f
    if "close" not in f:
        out["reason"] = "가격 변동성을 계산할 수 없어 국면을 판정하지 않습니다."
        return out

    for p, conds in _CONDS.items():
        yes, no, na = [], [], []
        w_yes = w_eval = w_core = w_core_eval = 0.0
        for label, w, optional, fn in conds:
            try:
                v = fn(f)
            except Exception:  # noqa: BLE001
                v = None
            if not optional:
                w_core += w
            if v is None:
                na.append(label)
                continue
            w_eval += w
            if not optional:
                w_core_eval += w
            if v:
                w_yes += w
                yes.append(label)
            else:
                no.append(label)
        out["fits"][p] = (w_yes / w_eval) if w_eval > 0 else None
        out["cover"][p] = (w_core_eval / w_core) if w_core > 0 else 0.0
        out["detail"][p] = {"yes": yes, "no": no, "na": na}

    ranked = [p for p in PHASES if out["fits"][p] is not None and out["cover"][p] >= 0.6]
    ranked.sort(key=lambda p: out["fits"][p], reverse=True)
    if not ranked:
        out["reason"] = "근거로 쓸 수 있는 지표가 부족해 국면을 판정하지 않습니다."
        return out
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    fit = out["fits"][top]
    margin = fit - (out["fits"][second] if second else 0.0)
    out["top"], out["second"], out["margin"] = top, second, margin
    if fit < 0.45:
        out["confidence"] = "판단 보류"
        out["reason"] = "어느 국면과도 근거가 충분히 일치하지 않습니다(최고 일치도 {:.0%}).".format(fit)
        out["top"] = None
    elif margin >= 0.20 and fit >= 0.70 and out["cover"][top] >= 0.8:
        out["confidence"] = "높음"
    elif margin >= 0.10 and fit >= 0.55:
        out["confidence"] = "보통"
    else:
        out["confidence"] = "낮음"
    return out


def _angle_from_fits(fits):
    """국면별 일치도를 가중치로 달걀 위 위치(각도)를 구한다. 두 국면이 비슷하면 그 사이에 놓인다(전환 중 표현)."""
    sx = sy = 0.0
    for p, fit in fits.items():
        if fit is None:
            continue
        w = fit ** 4
        a = math.radians(phase_angle_deg(p))
        sx += w * math.cos(a)
        sy += w * math.sin(a)
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return None
    return math.atan2(sy, sx)


def analyze_series(ticker, get_prices, ext=None):
    """한 자산(지수 또는 종목)의 국면 판정과 최근 이동 경로를 계산한다."""
    df, err = _read_prices(ticker, get_prices)
    if df is None:
        return {"error": err}
    res = evaluate(df, ext)
    res["price"] = _num(df["Close"].iloc[-1]) if "Close" in df.columns else None
    try:
        asof = df.index[-1].date()
        res["asof"], res["age"] = asof, (_today_kst() - asof).days
    except AttributeError:
        res["asof"], res["age"] = None, None
    res["n_rows"] = len(df)

    # 가격 기반 과거 국면(수급 자료는 현재 시점만 있으므로 과거 비교에서는 쓰지 않는다)
    past = {}
    for k in TRAIL_OFFSETS:
        if len(df) - k >= MIN_ROWS_FOR_PHASE:
            past[k] = evaluate(df.iloc[:-k])
    res["past"] = past
    res["trail"] = [a for a in (_angle_from_fits(past[k]["fits"]) for k in TRAIL_OFFSETS if k in past)]
    res["now_angle"] = _angle_from_fits(res["fits"])
    res["direction"], res["direction_note"] = direction_label(res, past.get(10))
    return res


def direction_label(now, past10):
    top = now.get("top")
    if top is None:
        return "판단 보류", "국면이 확정되지 않아 진입 방향을 표시하지 않습니다."
    note = []
    prev = past10.get("top") if past10 else None
    if prev is None:
        label = "방향 자료 부족"
        note.append("10거래일 전 국면을 판정할 수 없습니다.")
    elif prev == top:
        label = "체류 중"
        note.append("최근 10거래일간 같은 국면(가격 기반 비교)입니다.")
    elif prev == prev_phase(top):
        label = "진입 (이전 단계 {} → 현재)".format(phase_label(prev))
    elif prev == next_phase(top):
        label = "되돌림 (이전 {} → 현재)".format(phase_label(prev))
    else:
        label = "불규칙 이동 ({} → 현재)".format(phase_label(prev))
    second, margin = now.get("second"), now.get("margin")
    if second is not None and margin is not None and margin < 0.12:
        if second == next_phase(top):
            label += " · 다음 단계({}) 전환 징후".format(phase_label(second))
        elif second == prev_phase(top):
            label += " · 이전 단계({})로 되돌아갈 가능성".format(phase_label(second))
    return label, " ".join(note)


# --------------------------------------------------------------------------
# 축 1: 기업 생존력(펀더멘탈) 관문
# --------------------------------------------------------------------------
def fundamentals_check(ticker, get_fundamentals):
    """부호 기반 자동 점검만 한다(임의 임계값 없음). 생존력을 확정하는 점검이 아니다."""
    try:
        info = get_fundamentals(ticker)
    except Exception as e:  # noqa: BLE001
        return {"gate": "자료 없음", "rows": [], "refs": [], "note": "재무 조회 실패: " + str(e)[:100]}
    if not info:
        return {"gate": "자료 없음", "rows": [], "refs": [], "note": "재무 자료가 제공되지 않았습니다."}
    qt = str(info.get("quoteType", "") or "").upper()
    if qt in ("ETF", "INDEX", "MUTUALFUND"):
        return {"gate": "해당 없음", "rows": [], "refs": [],
                "note": "ETF·지수에는 개별 기업 생존력 지표를 적용하지 않습니다. 구성 종목·보수·추종 지수 점검은 미연결입니다."}
    rows = []
    for label, key in (("영업현금흐름", "operatingCashflow"), ("순이익률", "profitMargins"),
                       ("매출 성장률", "revenueGrowth")):
        v = _num(info.get(key))
        if v is None:
            rows.append((label, "자료 없음", "자료 없음"))
        else:
            rows.append((label, "{:,.2f}".format(v), "양호" if v > 0 else "주의"))
    refs = []
    for label, key in (("부채비율(D/E)", "debtToEquity"), ("PER(TTM)", "trailingPE"), ("선행 PER", "forwardPE")):
        refs.append((label, _fmt(info.get(key), 2)))
    verdicts = [r[2] for r in rows if r[2] in ("양호", "주의")]
    if len(verdicts) < 2:
        gate = "자료 부족"
    elif "주의" in verdicts:
        gate = "주의"
    else:
        gate = "양호"
    return {"gate": gate, "rows": rows, "refs": refs,
            "note": "부호만 보는 자동 점검입니다. 부채 수준·경쟁 구도·산업 지위는 반영되지 않았습니다."}


# --------------------------------------------------------------------------
# 축 3: 보유 종목별 행동 조건
# --------------------------------------------------------------------------
def bet_checks(is_bet, facts, cfg):
    """베팅 슬롯 조건: 생존 가능성·한도·최대 손실·무효화 조건이 미리 정해져 있어야 한다."""
    if not is_bet:
        return None
    pnl = facts.get("pnl_pct")
    items = [
        ("투자 가설이 판단 기록에 있음", True if facts["has_thesis"] else False),
        ("무효화 조건이 판단 기록에 있음", True if facts["has_invalidation"] else False),
        ("기업 생존력 자동 점검이 '양호'", True if facts["gate"] == "양호" else (False if facts["gate"] == "주의" else None)),
        ("베팅 슬롯 합계 비중이 한도({:.0f}%) 이내".format(cfg["bet_total_weight"]),
         None if facts.get("slot_weight") is None else facts["slot_weight"] <= cfg["bet_total_weight"]),
        ("평단 대비 손익률이 최대 손실 한도({:+.0f}%)보다 위".format(cfg["bet_loss_limit"]),
         None if pnl is None else pnl > cfg["bet_loss_limit"]),
    ]
    return items


def _px(v, cur):
    x = _num(v)
    if x is None:
        return "자료 없음"
    return "{:,.0f}".format(x) if cur == "KRW" else "{:,.2f}".format(x)


def build_action(facts, cfg):
    """종목 단독 판단: 국면 + 내 평단 대비 위치 + 기업 점검 + 가격 구조로 행동 후보를 정한다.
    포트폴리오 비중은 기본적으로 행동 라벨에 반영하지 않고 '집중도 참고'로만 보여 준다(설정으로 반영 가능)."""
    phase, f = facts["phase"], facts.get("f") or {}
    pnl, price = facts.get("pnl_pct"), facts.get("price")
    w, cw = facts.get("weight"), facts.get("cat_weight")
    over = (w is not None and w > cfg["max_stock_weight"]) or (cw is not None and cw > cfg["max_category_weight"])
    conc = []
    if w is not None and w > cfg["max_stock_weight"]:
        conc.append("종목 비중 {:.1f}%가 임시 한도 {:.0f}%를 넘습니다.".format(w, cfg["max_stock_weight"]))
    if cw is not None and cw > cfg["max_category_weight"]:
        conc.append("카테고리 비중 {:.1f}%가 임시 한도 {:.0f}%를 넘습니다.".format(cw, cfg["max_category_weight"]))

    cautions, why, blockers = [], [], []
    if conc:
        cautions.append("집중도 참고(행동 라벨에는 " + ("반영됨" if cfg.get("use_weight") else "반영하지 않음") + "): " + " ".join(conc))
    if not facts["has_thesis"]:
        cautions.append("판단 기록 없음 — 가설·무효화 조건을 '📝 판단 기록' 탭에 남기면 연결됩니다.")
    elif not facts["has_invalidation"]:
        cautions.append("최근 판단 기록에 무효화 조건이 비어 있습니다.")
    if facts["gate"] in ("자료 부족", "자료 없음"):
        cautions.append("기업 생존력 자동 점검 자료가 부족합니다(판정에 반영하지 못함).")

    if phase is None or not facts["price_ok"]:
        label = "판단 보류"
        why.append("국면 판정 또는 가격 자료가 부족하거나 오래되어 행동 후보를 제시하지 않습니다.")
    elif facts["gate"] == "주의":
        label = "기업 가설 재검증"
        why.append("기업 생존력 자동 점검에서 주의 항목(적자·현금흐름 음수·매출 감소 등)이 있습니다. 가격 국면보다 먼저 확인하세요.")
    elif cfg.get("use_weight") and over:
        label = "비중 축소 검토"
        why.extend(conc)
    elif phase == 5:
        if pnl is not None and pnl > 0:
            label = "분할 익절 검토"
            why.append("과열 국면이고 평단 대비 {:+.1f}% 수익 구간입니다. 일부 수익 실현을 검토할 수 있습니다(전량 매도 아님).".format(pnl))
        else:
            label = "보유 유지"
            why.append("과열 국면이지만 평단 이하라 익절 대상이 아닙니다. 평단 회복 여부와 기업 논리를 점검하며 보유합니다.")
    elif phase == 6:
        if pnl is not None and pnl > 0:
            label = "분할 익절 검토"
            why.append("상승 동력 약화·하락 전환 징후이고 평단 대비 {:+.1f}% 수익 구간입니다. 수익 일부 보전을 검토할 수 있습니다.".format(pnl))
        else:
            label = "기업 가설 재검증"
            why.append("하락 전환 징후이고 평단 이하입니다. 매수 근거(투자 가설)가 아직 유효한지 먼저 확인하세요.")
    elif phase == 4:
        ma20 = f.get("ma20")
        if price is not None and ma20 and price <= ma20 * 1.01:
            label = "추가매수 검토"
            why.append("상승 추세 중 가격이 20일선 근처로 눌려 있습니다(눌림목). 가격대 표의 매수 후보 구간을 참고하세요.")
        else:
            label = "보유 유지"
            why.append("상승 추세 국면이며 가격이 20일선보다 위에 있어 추격 매수 근거는 약합니다. 보유를 유지합니다.")
    else:  # 1·2·3: 하락~회복 초기
        if facts.get("confidence") == "낮음":
            blockers.append("국면 판정 신뢰도가 낮습니다(두 국면의 근거가 비슷).")
        if phase == 1:
            lo10, lp = f.get("low10"), f.get("low_prior20")
            if lo10 is not None and lp is not None and lo10 < lp:
                blockers.append("최근 10거래일에 저점을 갱신했습니다(하락 가속) — 갱신이 멈출 때까지 대기.")
        bc = facts.get("bet_checks")
        if bc is not None and not all(ok is True for _, ok in bc):
            blockers.append("베팅 슬롯 조건이 모두 충족되지 않았습니다.")
        if blockers:
            label = "추가매수 보류"
            why.extend(blockers)
        else:
            label = "추가매수 검토"
            why.append("{} 국면이고 하락 가속·신뢰도 부족 신호가 없습니다. 소규모 분할로만 접근할 후보입니다.".format(phase_label(phase)))

    headlines = {
        "추가매수 검토": "추가매수 검토 — 아래 가격대에서 소규모 분할로 접근할 후보(예측·권유 아님)",
        "추가매수 보류": "추가매수 보류 — 아래 조건이 해소될 때까지 기다립니다",
        "보유 유지": "보유 유지",
        "분할 익절 검토": "분할 익절 검토 — 아래 가격대에서 일부만 수익 실현할 후보(전량 매도 아님)",
        "비중 축소 검토": "비중 축소 검토(집중도 반영 설정이 켜져 있음)",
        "기업 가설 재검증": "기업 가설 재검증 — 보유·추가 근거를 먼저 확인",
        "판단 보류": "판단 보류",
    }
    confirm = ACTIONS[phase]["confirm"] if phase else []
    stop = ACTIONS[phase]["stop"] if phase else []

    numbers = []
    total, value = facts.get("total"), facts.get("value")
    L = cfg["max_stock_weight"] / 100.0
    if conc and total and value is not None and price and L < 1 and w is not None and w > cfg["max_stock_weight"]:
        excess = (value - L * total) / (1 - L)
        numbers.append("(집중도 참고) 임시 한도 비중으로 되돌리려면 약 {:,.0f} {} (약 {:,.2f}주) 규모입니다. 가정 계산이며 매도 지시가 아닙니다.".format(
            excess, facts["currency"], excess / price))
    return {"label": label, "headline": headlines[label], "why": why, "blockers": blockers, "cautions": cautions,
            "confirm": confirm, "stop": stop, "numbers": numbers}


def _merge_levels(cands, reverse, atr, limit=3):
    """가까운 구조 가격(지지·저항)을 모으고, ATR의 0.8배 안에 겹치는 것은 하나로 합친다."""
    cands = [(n, v) for n, v in cands if v is not None]
    cands.sort(key=lambda x: x[1], reverse=reverse)
    out = []
    for n, v in cands:
        if out and abs(out[-1][1] - v) < 0.8 * atr:
            out[-1] = (out[-1][0] + "·" + n, out[-1][1])
        else:
            out.append((n, v))
        if len(out) >= limit:
            break
    return out


def price_ladders(f, price, qty, avg, budget, sell_frac, cur):
    """가격 구조(이동평균·저점·고점·볼린저)와 변동성(ATR)으로 분할 후보 구간을 만든다.
    목표가·예상 수익이 아니며 검증 전 규칙이다. 금액·수량·평단은 단순 산수(수수료·세금 제외)."""
    if price is None or not f:
        return None
    atr = _num(f.get("atr"))
    if atr is None and f.get("sig_a"):
        atr = price * f["sig_a"] / math.sqrt(252)
    if atr is None or atr <= 0:
        return None
    half = 0.5 * atr

    # ---- 매수 후보(현재가 이하의 지지 구조) ----
    pool = [(n, v) for n, v in [("20일선", f.get("ma20")), ("60일선", f.get("ma60")), ("120일선", f.get("ma120")),
                                ("20일 저점", f.get("low20")), ("60일 저점", f.get("low60")), ("볼린저 하단", f.get("bb_lower"))]
            if v is not None and v <= price + 0.3 * atr]
    sup = _merge_levels(pool, True, atr, 3)
    while len(sup) < 3:
        base = sup[-1][1] if sup else price
        sup.append(("변동성 기준(−1.5×ATR)", base - 1.5 * atr))
    buys, cum_cost, cum_qty = [], qty * avg, qty
    for i, (name, v) in enumerate(sup, 1):
        lo, hi = max(v - half, 0.0), min(v + half, price)
        mid = (lo + hi) / 2 if hi >= lo else v
        row = {"차수": "{}차".format(i), "구간": "{} ~ {}".format(_px(lo, cur), _px(hi, cur)), "기준": name,
               "현재가 대비": "{:+.1f}%".format((mid / price - 1) * 100),
               "상태": "현재가가 구간 안" if lo <= price <= hi else "대기(가격이 내려오면)"}
        if budget and budget > 0 and mid > 0:
            amt = budget / 3.0
            q = amt / mid
            cum_cost += amt
            cum_qty += q
            row["금액"] = _px(amt, cur)
            row["수량"] = "{:,.2f}".format(q)
            row["체결 후 평단"] = _px(cum_cost / cum_qty, cur)
        buys.append(row)
    review_below = max(sup[-1][1] - half, 0.0)

    # ---- 익절 후보(평단 위 수익 구간에서만) ----
    sells, sell_note = [], None
    if avg and price > avg:
        res_ = _merge_levels([(n, v) for n, v in [("볼린저 상단", f.get("bb_upper")), ("60일 고점", f.get("high60")),
                                                  ("52주 고점", f.get("high252"))] if v is not None and v >= price - 0.3 * atr],
                             False, atr, 3)
        k = 1
        while len(res_) < 3:
            base = res_[-1][1] if res_ else price
            res_.append(("변동성 기준(+{}×ATR)".format(1.5 if res_ else 1.0), base + (1.5 if res_ else 1.0) * atr))
            k += 1
        for i, (name, v) in enumerate(res_, 1):
            lo, hi = max(v - half, price), v + half
            mid = (lo + hi) / 2
            q = qty * sell_frac / 100.0
            sells.append({"차수": "{}차".format(i), "구간": "{} ~ {}".format(_px(lo, cur), _px(hi, cur)), "기준": name,
                          "현재가 대비": "{:+.1f}%".format((mid / price - 1) * 100),
                          "수량(보유의 {:.0f}%)".format(sell_frac): "{:,.2f}".format(q),
                          "평단 대비 구간 수익(세전)": "{:+.1f}%".format((mid / avg - 1) * 100)})
    else:
        sell_note = "평단({}) 이하라 익절 구간을 제시하지 않습니다. 평단 회복이 첫 기준입니다.".format(_px(avg, cur))
    return {"atr": atr, "buys": buys, "sells": sells, "sell_note": sell_note, "review_below": review_below}


def reason_lines(it, cfg):
    """'왜 이런 판단인가'를 가격·추세·수급·기업·집중도 근거로 풀어 쓴다."""
    res, fa, fund = it["res"], it["facts"], it["fund"]
    out = []
    top = res.get("top") if not res.get("error") else None
    if top is None:
        out.append("국면: 판단 보류 — {}".format(res.get("error") or res.get("reason") or "근거 부족"))
    else:
        out.append("국면: {} · 신뢰도 {} · 진입 방향 {}".format(phase_label(top), res["confidence"], res["direction"]))
        d = res["detail"][top]
        if d["yes"]:
            out.append("가격·추세·거래량 근거(일치): " + " / ".join(d["yes"][:3]))
        if d["no"]:
            out.append("일치하지 않은 근거: " + " / ".join(d["no"][:2]))
        if d["na"]:
            out.append("자료 없어 평가하지 못한 근거 {}개".format(len(d["na"])))
    f = res.get("features") or {}
    if "f5" in f:
        out.append("수급(한국 종목, 일별 집계): 외국인 5일 {}주 · 기관 5일 {}주 — 기준일 확인 필요".format(
            _fmt(f.get("f5"), 0), _fmt(f.get("i5"), 0)))
    else:
        out.append("수급: 자료 없음/미연결 (미국 종목이거나 조회 실패) — 판정에 반영되지 않음")
    out.append("기업 기초체력: 자동 점검 '{}' — {}".format(fund["gate"], fund["note"]))
    if fa["weight"] is not None:
        out.append("집중도(참고용, 행동 라벨 기본 미반영): 종목 비중 {:.1f}%(임시 한도 {:.0f}%) · 카테고리 '{}' {:.1f}%(임시 한도 {:.0f}%)".format(
            fa["weight"], cfg["max_stock_weight"], it["category"], fa["cat_weight"] or 0.0, cfg["max_category_weight"]))
    if it["pnl_pct"] is not None:
        out.append("내 포지션: {}주 · 평단 {:,.2f} · 현재가 {} · 평가손익률 {:+.1f}%".format(
            _fmt(it["qty"], 4).rstrip("0").rstrip("."), it["avg"], _fmt(it["price"], 2), it["pnl_pct"]))
    return out


# --------------------------------------------------------------------------
# 달걀 그림
# --------------------------------------------------------------------------
def _egg_xy(theta, scale=1.0):
    return (scale * 0.92 * math.cos(theta) * (1 - 0.16 * math.sin(theta)), scale * 1.05 * math.sin(theta))


def egg_figure(res, title):
    fig = go.Figure()
    th = [i * 2 * math.pi / 120 for i in range(121)]
    fig.add_trace(go.Scatter(
        x=[_egg_xy(t)[0] for t in th], y=[_egg_xy(t)[1] for t in th], mode="lines",
        fill="toself", fillcolor="rgba(148,163,184,0.10)", line=dict(color="#94A3B8", width=2),
        hoverinfo="skip", showlegend=False))
    top = res.get("top")
    fits = res.get("fits", {})
    if top:
        a0 = phase_angle_deg(top)
        arc = [math.radians(a0 - 30 + i * 60 / 20) for i in range(21)]
        fig.add_trace(go.Scatter(
            x=[_egg_xy(t)[0] for t in arc], y=[_egg_xy(t)[1] for t in arc], mode="lines",
            line=dict(color=PHASES[top]["color"], width=9), hoverinfo="skip", showlegend=False))
    for p, ph in PHASES.items():
        t = math.radians(phase_angle_deg(p))
        x, y = _egg_xy(t)
        fit = fits.get(p)
        hover = "{}<br>근거 일치도 {}".format(phase_label(p), "자료 없음" if fit is None else "{:.0%}".format(fit))
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers",
            marker=dict(size=22 if p == top else 12, color=ph["color"], line=dict(color="#FFFFFF", width=2)),
            hovertemplate=hover + "<extra></extra>", showlegend=False))
        label = phase_label(p)
        fig.add_annotation(x=x * 1.34, y=y * 1.22, text=("<b>" + label + "</b>") if p == top else label,
                           showarrow=False, font=dict(size=12, color=ph["color"]))

    pts = [a for a in res.get("trail", []) if a is not None]
    now_a = res.get("now_angle")
    if now_a is not None:
        pts = pts + [now_a]
        xy = [_egg_xy(a, 0.80) for a in pts]
        if len(xy) >= 2:
            fig.add_trace(go.Scatter(
                x=[p[0] for p in xy], y=[p[1] for p in xy], mode="lines+markers",
                line=dict(color="#475569", width=2, dash="dot"),
                marker=dict(size=7, color="#FFFFFF", line=dict(color="#475569", width=2)),
                hoverinfo="skip", showlegend=False))
            fig.add_annotation(x=xy[-1][0], y=xy[-1][1], ax=xy[-2][0], ay=xy[-2][1], xref="x", yref="y",
                               axref="x", ayref="y", text="", showarrow=True, arrowhead=3, arrowsize=1.2,
                               arrowwidth=2, arrowcolor="#475569")
        cx, cy = xy[-1]
        fig.add_trace(go.Scatter(
            x=[cx], y=[cy], mode="markers+text", text=["현재"], textposition="bottom center",
            marker=dict(size=17, symbol="star", color="#111827", line=dict(color="#FFFFFF", width=2)),
            hovertemplate="현재 위치(근거 일치도 가중 평균 · 시각화)<extra></extra>", showlegend=False))
    center = "<b>{}</b><br>{}".format(title, phase_label(top) if top else "판단 보류")
    fig.add_annotation(x=0, y=0, text=center, showarrow=False, font=dict(size=13, color="#334155"))
    fig.update_layout(
        height=380, margin=dict(l=0, r=0, t=6, b=0), showlegend=False, template="plotly_white",
        xaxis=dict(visible=False, range=[-1.85, 1.85], fixedrange=True),
        yaxis=dict(visible=False, range=[-1.6, 1.6], fixedrange=True, scaleanchor="x", scaleratio=1))
    return fig


# --------------------------------------------------------------------------
# 화면 조각
# --------------------------------------------------------------------------
def _evidence_rows(f, ext_present):
    def rr(label, value, note=""):
        return [label, value, note]
    rows = [
        rr("종가 대비 20·60·120일선", "{} / {} / {}".format(
            _pct(f.get("close") / f["ma20"] - 1 if f.get("ma20") else None),
            _pct(f.get("close") / f["ma60"] - 1 if f.get("ma60") else None),
            _pct(f.get("close") / f["ma120"] - 1 if f.get("ma120") else None)), "가격 위치"),
        rr("5·20·60거래일 수익률", "{} / {} / {}".format(_pct(f.get("ret5")), _pct(f.get("ret20")), _pct(f.get("ret60"))),
           "변동성 대비 z: 20일 {} · 60일 {}".format(_fmt(f.get("z20"), 2), _fmt(f.get("z60"), 2))),
        rr("52주 고점 대비 낙폭", _pct(f.get("dd")), "변동성 대비 {}".format(_fmt(f.get("dd_norm"), 2))),
        rr("RSI(14)", _fmt(f.get("rsi"), 1), "참고 지표(단독 판단 금지)"),
        rr("거래량 / 20일 평균", _fmt(f.get("vol_ratio20"), 2, "배"), "최근 5일/20일 {}".format(_fmt(f.get("vol5_20"), 2, "배"))),
        rr("상승일 ÷ 하락일 거래량(20일)", _fmt(f.get("updown"), 2), "1보다 크면 상승일 거래량 우위"),
        rr("변동성 비율(최근 10일/60일)", _fmt(f.get("vol_expand"), 2), "1보다 크면 변동성 확대"),
        rr("투매성 급락일(최근 10일)", _fmt(f.get("climax10"), 0, "회"), "큰 하락+거래량 급증"),
    ]
    if "vix_pct" in ext_present:
        rows.append(rr("VIX 1년 내 백분위", _pct(f.get("vix_pct"), 0), "높을수록 공포 쪽(미국 시장 참고)"))
    if "f5" in ext_present:
        rows.append(rr("외국인 5일·20일 순매수(주)", "{} / {}".format(_fmt(f.get("f5"), 0), _fmt(f.get("f20"), 0)),
                       "공급자 기준일 확인 필요 · 일별 집계"))
        rows.append(rr("기관 5일·20일 순매수(주)", "{} / {}".format(_fmt(f.get("i5"), 0), _fmt(f.get("i20"), 0)), ""))
    return pd.DataFrame(rows, columns=["항목", "현재 값", "비고"])


def _render_condition_detail(res):
    top = res.get("top")
    if top is None:
        return
    d = res["detail"][top]
    st.markdown("**{} 와(과) 일치한 근거 ✔ / 일치하지 않은 근거 ✖ / 자료 없음 –**".format(phase_label(top)))
    for t in d["yes"]:
        st.write("✔ " + t)
    for t in d["no"]:
        st.write("✖ " + t)
    for t in d["na"]:
        st.write("– " + t + " (자료 없음)")


def _render_egg_panel(res, title, key, ext_present=()):
    if res.get("error"):
        st.warning("{}: {}".format(title, res["error"]))
        return
    left, right = st.columns([1, 1])
    with left:
        st.plotly_chart(egg_figure(res, title), use_container_width=True, key="egg_" + key,
                        config={"displayModeBar": False})
        st.caption("★ 현재 위치는 6개 국면의 근거 일치도를 가중 평균한 시각화이며, 두 국면 사이에 놓이면 전환 중이라는 뜻입니다. "
                   "점선은 20·10거래일 전 위치(가격 기반)입니다.")
    with right:
        top = res.get("top")
        if top is None:
            st.markdown("### 판단 보류")
            st.write(res.get("reason") or "근거가 부족합니다.")
        else:
            st.markdown("### {}".format(phase_label(top)))
            if res["confidence"] == "낮음" and res.get("second") is not None:
                st.info("전환·혼합 구간: 1위 {}와 2위 {}의 근거가 비슷합니다. 국면을 확정하지 않습니다.".format(
                    phase_label(top), phase_label(res["second"])))
            st.write("**심리 상태(가격·거래량으로 추정, 직접 측정 아님)** · " + PHASES[top]["mood"])
            st.write("**진입 방향** · " + res["direction"])
            st.write("**판정 신뢰도** · {} (최고 일치도 {:.0%} · 2위와 차이 {:.0%}p)".format(
                res["confidence"], res["fits"][top], (res["margin"] or 0) * 100))
            if res.get("second") is not None:
                st.caption("2위 후보: {} (일치도 {:.0%})".format(phase_label(res["second"]), res["fits"][res["second"]]))
            st.markdown("**현재 단계에서 유리한 행동**")
            for t in PHASES[top]["good"]:
                st.write("- " + t)
            st.markdown("**피해야 할 행동**")
            for t in PHASES[top]["avoid"]:
                st.write("- " + t)
        st.caption("가격 기준일 {} · 이 판정은 검증 전 규칙 기반 후보이며 확률·승률이 아닙니다.".format(res.get("asof") or "자료 없음"))
    with st.expander("판정 근거 상세 · {}".format(title)):
        if res.get("features"):
            st.dataframe(_evidence_rows(res["features"], ext_present), use_container_width=True, hide_index=True)
        _render_condition_detail(res)


# --------------------------------------------------------------------------
# 데이터 모으기
# --------------------------------------------------------------------------
def _vix_context(get_prices):
    df, err = _read_prices("^VIX", get_prices)
    if df is None or "Close" not in df.columns or len(df) < 30:
        return {}, err or "VIX 자료 부족"
    c = df["Close"].astype(float).dropna()
    last = float(c.iloc[-1])
    pct = float((c <= last).mean())
    chg = (last / float(c.iloc[-11]) - 1) if len(c) > 11 else None
    ext = {"vix_pct": pct}
    if chg is not None:
        ext["vix_chg10"] = chg
    return ext, None


def _flow_ext(ticker, flows):
    t = ticker.strip().upper()
    if flows is None or not t.endswith((".KS", ".KQ")):
        return {}
    code = t.rsplit(".", 1)[0]
    m = flows.loc[flows["ticker"] == code]
    if m.empty:
        return {}
    row = m.iloc[0]
    out = {}
    for key, col in (("f5", "f_5d_sh"), ("f20", "f_20d_sh"), ("i5", "i_5d_sh"), ("i20", "i_20d_sh")):
        v = _num(pd.to_numeric(row.get(col), errors="coerce"))
        if v is not None:
            out[key] = v
    return out


def _market_name_for(ticker, category):
    t = ticker.strip().upper()
    if t.endswith(".KS"):
        return "KOSPI"
    if t.endswith(".KQ"):
        return "KOSDAQ"
    if category == "반도체·하드웨어":
        return "필라델피아 반도체"
    return "S&P 500"


def _settings_panel(holdings):
    with st.expander("⚙️ 점검 기준 · 베팅 슬롯 설정 (이 화면에서만 적용, 저장되지 않음)", expanded=False):
        st.caption("숫자는 권고값이 아니라 임시 기준입니다. 본인의 원칙에 맞게 바꾸세요. 새로고침하면 기본값으로 돌아갑니다.")
        c1, c2 = st.columns(2)
        with c1:
            max_stock = st.number_input("한 종목 최대 비중(%)", min_value=1.0, max_value=100.0,
                                        value=DEFAULTS["max_stock_weight"], step=5.0, key="sv_max_stock")
        with c2:
            max_cat = st.number_input("한 카테고리 최대 비중(%)", min_value=1.0, max_value=100.0,
                                      value=DEFAULTS["max_category_weight"], step=5.0, key="sv_max_cat")
        c5, c6 = st.columns(2)
        with c5:
            use_weight = st.checkbox("비중 한도 초과를 행동 라벨에도 반영 (기본: 꺼짐 = 종목 단독 판단)", value=DEFAULTS["use_weight"], key="sv_use_weight")
        with c6:
            sell_frac = st.number_input("분할 익절 1회당 보유 수량 비율(%)", min_value=1.0, max_value=100.0,
                                        value=DEFAULTS["sell_frac"], step=5.0, key="sv_sell_frac")
        st.markdown("**베팅 슬롯** — 생존 가능성이 불확실해도 감수하려는 고위험 종목(최대 2개). 한도와 최대 손실을 미리 정해야 합니다.")
        options = [str(t) for t in holdings["ticker"]]
        names = {str(r["ticker"]): "{} ({})".format(r["name"], r["ticker"]) for _, r in holdings.iterrows()}
        bets = st.multiselect("베팅 슬롯 종목", options, format_func=lambda t: names.get(t, t), key="sv_bets")
        if len(bets) > 2:
            st.warning("베팅 슬롯은 최대 2종목입니다. 앞의 2종목만 적용합니다.")
            bets = bets[:2]
        c3, c4 = st.columns(2)
        with c3:
            bet_total = st.number_input("베팅 슬롯 합계 최대 비중(%)", min_value=1.0, max_value=100.0,
                                        value=DEFAULTS["bet_total_weight"], step=1.0, key="sv_bet_total")
        with c4:
            bet_loss = st.number_input("베팅 종목 최대 손실 한도(평단 대비 %)", min_value=-100.0, max_value=-1.0,
                                       value=DEFAULTS["bet_loss_limit"], step=5.0, key="sv_bet_loss")
    return {"max_stock_weight": float(max_stock), "max_category_weight": float(max_cat),
            "bet_total_weight": float(bet_total), "bet_loss_limit": float(bet_loss), "bets": [str(b) for b in bets],
            "use_weight": bool(use_weight), "sell_frac": float(sell_frac)}


# --------------------------------------------------------------------------
# 메인 화면
# --------------------------------------------------------------------------
def render_supervision(holdings, get_prices, classify, load_decisions, get_fundamentals, load_flows):
    st.markdown("##### PORTFOLIO SUPERVISOR")
    st.subheader("🥚 나의 포트폴리오 달걀 지도")
    st.caption("시장 국면과 보유 종목별 국면을 따로 판정해 함께 봅니다. 읽기 전용이며 주문·저장 기능이 없습니다. "
               "국면 규칙은 백테스트 전의 '규칙 기반 후보'이고, 승률·확률·목표가는 계산하지 않습니다.")

    if holdings is None or len(holdings) == 0:
        st.info("등록된 보유 종목이 없습니다. '💼 내 포트폴리오' 탭에서 보유 종목을 먼저 등록하세요.")
        return

    cfg = _settings_panel(holdings)

    try:
        decisions = load_decisions()
    except Exception as e:  # noqa: BLE001
        decisions = None
        st.warning("판단 기록을 읽지 못했습니다(기록 연결 없이 계속합니다): " + str(e)[:100])
    latest = _latest_decisions(decisions)

    flows, flow_err = None, None
    try:
        flows, flow_err = load_flows()
    except Exception as e:  # noqa: BLE001
        flow_err = str(e)[:100]

    with st.spinner("시장과 보유 종목의 국면을 계산하는 중... (처음 한 번은 수십 초 걸릴 수 있습니다)"):
        vix_ext, vix_err = _vix_context(get_prices)
        market_res = {}
        for name, tk, region in MARKETS:
            ext = vix_ext if region == "us" else {}
            r = analyze_series(tk, get_prices, ext)
            r["region"], r["ticker"] = region, tk
            market_res[name] = r

        items = []
        for _, h in holdings.iterrows():
            raw = str(h["ticker"])
            name = str(h.get("name", raw))
            cur = str(h.get("currency", "KRW"))
            qty = _num(h.get("quantity")) or 0.0
            avg = _num(h.get("avg_cost")) or 0.0
            cat = classify(name, raw)
            is_kr = raw.strip().upper().endswith((".KS", ".KQ"))
            ext = _flow_ext(raw, flows) if is_kr else dict(vix_ext)
            try:
                res = analyze_series(raw, get_prices, ext)
            except Exception as e:  # noqa: BLE001
                res = {"error": "분석 오류: " + str(e)[:120]}
            res["ext_keys"] = tuple(ext.keys())
            price = res.get("price")
            value = price * qty if price is not None else None
            pnl_pct = (price / avg - 1) * 100 if (price is not None and avg > 0) else None
            items.append({
                "ticker": raw, "key": raw.strip().upper(), "name": name, "currency": cur, "qty": qty, "avg": avg,
                "account": str(h.get("account", "")), "category": cat, "res": res, "price": price, "value": value,
                "pnl_pct": pnl_pct, "market": _market_name_for(raw, cat),
                "fund": fundamentals_check(raw, get_fundamentals),
            })

    # 통화별 비중
    for it in items:
        it["weight"] = it["cat_weight"] = None
    for cur in sorted({it["currency"] for it in items}):
        grp = [it for it in items if it["currency"] == cur and it["value"] is not None and it["value"] > 0]
        total = sum(it["value"] for it in grp)
        cat_tot = {}
        for it in grp:
            cat_tot[it["category"]] = cat_tot.get(it["category"], 0.0) + it["value"]
        bet_value = sum(it["value"] for it in grp if it["ticker"] in cfg["bets"])
        grp_ids = {id(g) for g in grp}
        for it in items:
            if it["currency"] != cur:
                continue
            it["total"] = total if total > 0 else None
            it["slot_weight"] = (bet_value / total * 100) if total > 0 else None
            if id(it) in grp_ids and total > 0:
                it["weight"] = it["value"] / total * 100
                it["cat_weight"] = cat_tot[it["category"]] / total * 100

    # ------------------------------------------------------------------ 시장 달걀
    st.markdown("### 1. 시장 달걀")
    st.caption("코스피·미국 시장·반도체 업종처럼 자금 흐름과 대중심리의 큰 방향입니다. 보유 종목과 별개로 판정합니다.")
    names = [m[0] for m in MARKETS]
    pick = st.selectbox("시장 선택", names, key="sv_market_pick")
    _render_egg_panel(market_res[pick], pick, "mkt_" + pick, tuple(k for k in ("vix_pct",) if market_res[pick].get("region") == "us" and vix_ext))
    rows = []
    for n in names:
        r = market_res[n]
        if r.get("error"):
            rows.append([n, "자료 없음", "-", "-", r["error"]])
        else:
            rows.append([n, phase_label(r["top"]) if r.get("top") else "판단 보류", r["direction"], r["confidence"],
                         str(r.get("asof") or "자료 없음")])
    st.dataframe(pd.DataFrame(rows, columns=["시장", "현재 국면", "진입 방향", "신뢰도", "가격 기준일/비고"]),
                 use_container_width=True, hide_index=True)
    if vix_ext:
        st.caption("VIX 백분위 {:.0%} (1년 내 · 미국 시장 근거에만 사용). 한국 변동성 지수(VKOSPI)는 미연결입니다.".format(vix_ext["vix_pct"]))
    else:
        st.caption("VIX·한국 변동성 지수는 미연결/조회 실패입니다. 변동성 지표 근거 없이 가격·거래량만으로 판정합니다.")

    # ------------------------------------------------------------------ 종목별 달걀
    st.markdown("### 2. 보유 종목별 달걀")
    st.caption("각 종목은 시장과 독립적으로 판정합니다. 시장 국면과 다르면 '시장과 다름'으로 표시합니다.")

    summary = []
    for it in items:
        res = it["res"]
        facts = {
            "phase": res.get("top") if not res.get("error") else None,
            "price_ok": it["price"] is not None and (res.get("age") is None or res.get("age") <= STALE_DAYS),
            "gate": it["fund"]["gate"], "weight": it["weight"], "cat_weight": it["cat_weight"],
            "total": it.get("total"), "value": it["value"], "price": it["price"], "currency": it["currency"],
            "pnl_pct": it["pnl_pct"], "slot_weight": it.get("slot_weight"),
            "f": res.get("features") or {}, "confidence": res.get("confidence"),
        }
        rec = latest.get(it["key"])
        facts["has_thesis"] = bool(rec is not None and str(rec.get("thesis", "") or "").strip())
        facts["has_invalidation"] = bool(rec is not None and str(rec.get("invalidation", "") or "").strip())
        facts["bet_checks"] = bet_checks(it["ticker"] in cfg["bets"], facts, cfg)
        it["facts"], it["rec"] = facts, rec
        it["action"] = build_action(facts, cfg)
        try:
            it["lad"] = price_ladders(facts["f"], it["price"], it["qty"], it["avg"], 0.0, cfg["sell_frac"], it["currency"])
        except Exception:  # noqa: BLE001
            it["lad"] = None
        nxt = "-"
        lab = it["action"]["label"]
        if it["lad"]:
            if lab in ("추가매수 검토", "추가매수 보류") and it["lad"]["buys"]:
                nxt = "1차 매수 후보 " + it["lad"]["buys"][0]["구간"]
            elif lab == "분할 익절 검토" and it["lad"]["sells"]:
                nxt = "1차 익절 후보 " + it["lad"]["sells"][0]["구간"]
        it["next_zone"] = nxt
        mres = market_res.get(it["market"], {})
        it["market_phase"] = mres.get("top") if not mres.get("error") else None
        summary.append({
            "종목": it["name"] + (" ★베팅" if it["ticker"] in cfg["bets"] else ""),
            "수량": it["qty"], "평단": it["avg"],
            "현재 국면": phase_label(facts["phase"]) if facts["phase"] else "판단 보류",
            "진입 방향": res.get("direction", "-") if not res.get("error") else "자료 없음",
            "행동": it["action"]["label"],
            "다음 가격대": it["next_zone"],
            "신뢰도": res.get("confidence", "-") if not res.get("error") else "-",
            "소속 시장 · 국면": "{} · {}".format(it["market"], phase_label(it["market_phase"]) if it["market_phase"] else "판단 보류"),
            "기업 점검": it["fund"]["gate"],
            "비중(%, 참고)": it["weight"],
        })
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True,
                 column_config={"수량": st.column_config.NumberColumn("수량", format="%.4f"),
                                "평단": st.column_config.NumberColumn("평단", format="%.2f"),
                                "비중(%, 참고)": st.column_config.NumberColumn("비중(%, 참고)", format="%.1f")})

    # 통화별 국면 분포
    dist_rows = []
    for cur in sorted({it["currency"] for it in items}):
        tot = sum(it["value"] for it in items if it["currency"] == cur and it["value"])
        if not tot:
            continue
        acc = {}
        for it in items:
            if it["currency"] == cur and it["value"]:
                key = phase_label(it["facts"]["phase"]) if it["facts"]["phase"] else "판단 보류"
                acc[key] = acc.get(key, 0.0) + it["value"]
        for k, v in sorted(acc.items(), key=lambda kv: -kv[1]):
            dist_rows.append([cur, k, round(v / tot * 100, 1)])
    if dist_rows:
        st.markdown("**평가금액 기준 국면 분포(통화별)**")
        st.dataframe(pd.DataFrame(dist_rows, columns=["통화", "국면", "비중(%)"]), use_container_width=True, hide_index=True)

    for it in items:
        res, fa, act = it["res"], it["facts"], it["action"]
        st.markdown("---")
        st.markdown("**{}** · {}주 · 평단가 {:,.0f}{}".format(it["name"], _fmt(it["qty"], 4).rstrip("0").rstrip("."),
                                                             it["avg"], " " + it["currency"]))
        st.markdown("**행동: {}**".format(act["label"]))
        st.caption("{} · 현재 국면 {} · {}".format(
            it["ticker"], phase_label(fa["phase"]) if fa["phase"] else "판단 보류", act["headline"]))
        with st.expander("개별 국면 분석 ▸ {}".format(it["name"])):
            st.markdown("#### 왜 이런 판단인가")
            for line in reason_lines(it, cfg):
                st.write("- " + line)
            _render_egg_panel(res, it["name"], "stk_" + it["key"], res.get("ext_keys", ()))
            if (not res.get("error")) and it["market_phase"] is not None and fa["phase"] is not None:
                if it["market_phase"] != fa["phase"]:
                    st.info("시장({}: {})과 이 종목({})의 국면이 다릅니다. 종목은 시장과 독립적으로 판정했습니다.".format(
                        it["market"], phase_label(it["market_phase"]), phase_label(fa["phase"])))
                else:
                    st.caption("시장({})과 같은 국면으로 판정되었습니다.".format(it["market"]))

            st.markdown("#### 내 포지션 기준 행동 (이 종목만 봤을 때)")
            pnl_text = "자료 없음" if it["pnl_pct"] is None else "{:+.1f}%".format(it["pnl_pct"])
            st.write("- 보유 {}주 · 평단 {} · 현재가 {} · 평단 대비 {}".format(
                _fmt(it["qty"], 4).rstrip("0").rstrip("."), _px(it["avg"], it["currency"]), _px(it["price"], it["currency"]), pnl_text))
            st.write("**{}**".format(act["headline"]))
            for t in act["why"]:
                st.write("- 이유: " + t)
            if act["cautions"]:
                st.markdown("**⚠️ 참고·주의 (행동 라벨을 바꾸지 않는 항목 포함)**")
                for t in act["cautions"]:
                    st.write("- " + t)
            for t in act["numbers"]:
                st.write("- " + t)

            lad = it.get("lad")
            if lad:
                st.markdown("#### 분할 가격대 (후보 구간 · 예측·목표가 아님)")
                st.caption("가격 구조(이동평균·저점·고점·볼린저)와 변동성(ATR14 {})으로 계산한 규칙 기반 후보이며 백테스트 전입니다. "
                           "구간 폭은 기준 가격 ±0.5×ATR입니다.".format(_px(lad["atr"], it["currency"])))
                budget = st.number_input("추가로 넣을 계획 금액 ({}) — 입력하면 차수별 금액·수량·체결 후 평단을 계산합니다(저장 안 됨)".format(it["currency"]),
                                         min_value=0.0, value=0.0, step=100000.0 if it["currency"] == "KRW" else 100.0,
                                         key="sv_budget_" + it["key"])
                try:
                    lad2 = price_ladders(fa["f"], it["price"], it["qty"], it["avg"], float(budget), cfg["sell_frac"], it["currency"])
                except Exception:  # noqa: BLE001
                    lad2 = lad
                lad2 = lad2 or lad
                st.markdown("**분할 매수 후보** (균등 3분할 가정 · 현재 행동: {})".format(act["label"]))
                st.dataframe(pd.DataFrame(lad2["buys"]), use_container_width=True, hide_index=True)
                st.caption("종가가 {} 아래로 마감하면 분할을 멈추고 투자 논리를 재검토하는 기준으로 볼 수 있습니다(손절 주문이 아님).".format(
                    _px(lad2["review_below"], it["currency"])))
                if act["label"] not in ("추가매수 검토",):
                    st.caption("현재 행동이 '추가매수 검토'가 아니므로 위 매수 구간은 참고용입니다.")
                st.markdown("**분할 익절 후보**")
                if lad2["sells"]:
                    st.dataframe(pd.DataFrame(lad2["sells"]), use_container_width=True, hide_index=True)
                    if act["label"] != "분할 익절 검토":
                        st.caption("현재 행동이 '분할 익절 검토'가 아니므로 위 구간은 참고용입니다. 세금·수수료는 반영하지 않았습니다.")
                else:
                    st.write(lad2["sell_note"] or "자료 없음")
            else:
                st.info("가격 구조 자료가 부족해 분할 가격대를 계산하지 못했습니다(판단 보류).")

            if act["confirm"]:
                st.markdown("**확인할 조건**")
                for t in act["confirm"]:
                    st.write("- " + t)
            if act["stop"]:
                st.markdown("**중단·재검토 조건**")
                for t in act["stop"]:
                    st.write("- " + t)

            if fa["bet_checks"] is not None:
                st.markdown("#### ★ 베팅 슬롯 점검")
                for label, ok in fa["bet_checks"]:
                    st.write("{} {}".format("✔" if ok is True else ("✖" if ok is False else "–"), label + ("" if ok is not None else " (자료 없음/확인 불가)")))
                if it["value"] is not None and it.get("total"):
                    st.caption("전액 손실을 가정하면 같은 통화 평가금액의 {:.1f}%({:,.0f} {})가 사라집니다. 가정 계산입니다.".format(
                        it["value"] / it["total"] * 100, it["value"], it["currency"]))

            st.markdown("#### 기업 생존력 점검(축 1)")
            fund = it["fund"]
            st.write("자동 점검 결과: **{}**".format(fund["gate"]))
            if fund["rows"]:
                st.dataframe(pd.DataFrame(fund["rows"], columns=["항목", "값", "판정"]), use_container_width=True, hide_index=True)
            if fund["refs"]:
                st.caption("참고값(판정 없음): " + " · ".join("{} {}".format(a, b) for a, b in fund["refs"]))
            st.caption(fund["note"])

            st.markdown("#### 최근 판단 기록")
            rec = it["rec"]
            if rec is None:
                st.write("기록 없음 — '📝 판단 기록' 탭에 가설·반대 근거·무효화 조건을 남기면 여기에 연결됩니다.")
            else:
                d = _parse_date(rec.get("created_at"))
                st.write("- 기록일 {} · 기간 {} · 판단 {}".format(d or "자료 없음", rec.get("horizon", ""), rec.get("decision", "")))
                for label, col in (("핵심 가설", "thesis"), ("지지 근거", "evidence_for"), ("반대 근거", "evidence_against"),
                                   ("주요 위험", "risks"), ("무효화 조건", "invalidation")):
                    text = str(rec.get(col, "") or "").strip()
                    st.write("- {}: {}".format(label, text[:300] if text else "미기록"))

    # ------------------------------------------------------------------ 연결 상태
    st.markdown("### 3. 데이터 연결 상태")
    st.dataframe(pd.DataFrame([
        ["가격·거래량(일봉)", "연결(야후 파이낸스, 비공식)", "지연·누락 가능 · 모든 국면 판정의 기본 근거"],
        ["변동성(VIX)", "연결됨" if vix_ext else "조회 실패/미연결", "미국 시장·종목 근거에만 사용"],
        ["외국인·기관 수급", "연결됨(한국 종목, 제공자 일별 집계)" if flows is not None else "미연결: {}".format(flow_err or "자료 없음"),
         "기준일 별도 검증 필요 · 미국 종목은 미연결"],
        ["시장 참여도·업종 확산", "미연결", "소수 종목만 오르는지 판정하지 못함"],
        ["투자심리·파생 지표(풋콜, VKOSPI 등)", "미연결", "자료 없음"],
        ["뉴스·실적에 대한 가격 반응", "미연결", "자료 없음 — 심리 전환의 중요한 단서이나 아직 판정에 반영되지 않음"],
        ["기업 재무", "부분 연결(야후 info, 부호 점검만)", "공시·IR 기반 검증은 미연결"],
    ], columns=["영역", "상태", "비고"]), use_container_width=True, hide_index=True)
    st.caption("판정은 연결된 자료만으로 계산한 것입니다. 미연결 영역이 많을수록 신뢰도가 낮아지며, 없는 자료를 긍정·중립으로 가정하지 않습니다. "
               "모든 규칙은 과거 데이터 검증 전입니다.")


def render_single_asset(ticker, name, get_prices, get_fundamentals, load_flows):
    """종목 분석 탭용: 보유 여부와 상관없이 선택한 종목 하나의 달걀 국면과 기업 자동 점검을 보여 준다. 읽기 전용."""
    st.markdown("##### 선택 종목의 달걀 국면")
    st.caption("보유하지 않은 종목도 볼 수 있습니다. 보유 종목의 행동 후보와 분할 가격대는 '🎯 감독실'에서 확인하세요. "
               "규칙은 검증 전 후보이며 확률·승률이 아닙니다.")
    t = str(ticker).strip().upper()
    is_kr = t.endswith((".KS", ".KQ"))
    flows = None
    if is_kr:
        try:
            flows, _ = load_flows()
        except Exception:  # noqa: BLE001
            flows = None
    vix_ext = {}
    if not is_kr:
        try:
            vix_ext, _ = _vix_context(get_prices)
        except Exception:  # noqa: BLE001
            vix_ext = {}
    ext = _flow_ext(t, flows) if is_kr else dict(vix_ext)
    with st.spinner("{} 국면을 계산하는 중...".format(t)):
        try:
            res = analyze_series(t, get_prices, ext)
        except Exception as e:  # noqa: BLE001
            res = {"error": "분석 오류: " + str(e)[:120]}
    res["ext_keys"] = tuple(ext.keys())
    _render_egg_panel(res, name or t, "single_" + t, res["ext_keys"])

    st.markdown("#### 기업 생존력 자동 점검")
    try:
        fund = fundamentals_check(t, get_fundamentals)
    except Exception as e:  # noqa: BLE001
        fund = {"gate": "자료 없음", "rows": [], "refs": [], "note": "점검 오류: " + str(e)[:100]}
    st.write("자동 점검 결과: **{}**".format(fund["gate"]))
    if fund["rows"]:
        st.dataframe(pd.DataFrame(fund["rows"], columns=["항목", "값", "판정"]), use_container_width=True, hide_index=True)
    if fund["refs"]:
        st.caption("참고값(판정 없음): " + " · ".join("{} {}".format(a, b) for a, b in fund["refs"]))
    st.caption(fund["note"])
