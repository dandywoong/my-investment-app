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
    "※ 아래는 내가 지금까지 세운 기본 선호입니다. 오늘의 검색 결과·데이터가 강하게 반대하면 데이터를 우선해 예외를 제안해도 됩니다(예외는 명시).\n"
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
 "research_summary": "오늘 검색·데이터에서 가장 중요했던 발견 3~5줄(출처명 포함)",
 "policy_deviations": ["내 정책과 다르게 제안한 부분과 이유(없으면 빈 배열)"],
 "priorities": [{"rank": 1, "name": "종목명", "ticker": "티커", "action": "매수|보류|홀드|정리검토", "amount_krw": 0, "weight_hint": "목표 비중 방향(예: 늘림/유지/줄임)", "reason": "근거", "evidence": "오늘 검색·데이터에서 찾은 이 종목의 근거(출처명·날짜)", "counter": "반대 근거"}],
 "avg_down_review": [{"name": "손실 종목", "verdict": "유리|조건부|불리", "reason": "근거", "conditions": "물타기가 성립하려면 필요한 조건", "recovery_pct_note": "평단까지 필요한 상승률·과거 도달 빈도·목표가 여력을 인용한 한 줄"}],
 "fx_view": {"lean": "환전 유리|중립|환전 불리|판단 불가", "confidence": "낮음|보통|높음", "level_note": "원/달러 판단 근거(research.fx 헤드라인·fx_rule에서 확인된 것만, 정확한 예측은 불가)", "institution_views": [{"name": "기관·매체", "view": "의견", "date": "날짜"}]},
 "questions_to_user": ["내게 확인하고 싶은 것"],
 "confidence": "낮음|보통|높음",
 "unknowns": ["확인하지 못한 것"]
}"""


SOURCES = {
    "글로벌 투자은행·리서치": ["Goldman Sachs", "Morgan Stanley", "JPMorgan", "Bank of America", "Citi", "UBS", "Bernstein", "Wedbush", "Mizuho"],
    "국내 증권사·컨센서스": ["삼성증권", "미래에셋증권", "KB증권", "한국투자증권", "NH투자증권", "FnGuide 컨센서스", "네이버 증권 목표주가"],
    "시장 데이터·앱": ["Investing.com (애널리스트 목표가·기술적 지표·경제 캘린더)", "Yahoo Finance", "TipRanks", "Finviz", "MarketWatch", "Seeking Alpha", "CNN Fear & Greed"],
    "뉴스·기관 발표": ["Reuters", "Bloomberg", "CNBC", "Wall Street Journal", "Financial Times", "연합인포맥스", "한국경제", "매일경제", "Federal Reserve(FOMC)"],
    "인물·기업 발언": ["Jensen Huang(엔비디아)", "Warren Buffett·버크셔 주주서한", "Howard Marks 메모", "Jerome Powell", "각 기업 실적발표·IR 자료"],
}
SOURCE_DOMAINS = {"investing.com": "Investing.com", "yahoo.com": "Yahoo Finance", "tipranks.com": "TipRanks", "finviz.com": "Finviz", "marketwatch.com": "MarketWatch",
                  "seekingalpha.com": "Seeking Alpha", "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "cnbc.com": "CNBC", "wsj.com": "WSJ", "ft.com": "Financial Times",
                  "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "naver.com": "네이버 증권", "fnguide.com": "FnGuide", "yna.co.kr": "연합뉴스", "einfomax.co.kr": "연합인포맥스",
                  "federalreserve.gov": "Federal Reserve", "cnn.com": "CNN", "goldmansachs.com": "Goldman Sachs", "morganstanley.com": "Morgan Stanley", "jpmorgan.com": "JPMorgan"}
RESEARCH_TTL_HOURS = 8


def _source_text():
    return "\n".join("- {}: {}".format(k, ", ".join(v)) for k, v in SOURCES.items())


def _retry_delay(r):
    """429 응답에 들어 있는 재시도 권장 시간(초). 없으면 None."""
    try:
        for d in r.json().get("error", {}).get("details", []):
            if isinstance(d, dict) and d.get("retryDelay"):
                return float(str(d["retryDelay"]).rstrip("s"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _grounded(prompt):
    """검색 근거(구글 검색)를 켠 호출. -> (dict|None, 출처목록, 오류, 한도초과 여부)
    429(분당·일일 한도)는 권장 대기시간이 짧으면(45초 이하) 한 번만 기다렸다 재시도하고, 그래도 안 되면 다음 모델로 넘어간다."""
    import time
    key = ai_agent.get_api_key()
    if not key:
        return None, [], "GEMINI_API_KEY 가 설정되지 않았습니다.", False
    try:
        models = ai_agent.pick_models(key)
    except Exception as e:  # noqa: BLE001
        return None, [], "모델 목록 조회 실패: " + str(e)[:100], False
    last, quota, slept = "사용 가능한 모델 없음", False, False
    for m in models:
        for attempt in (0, 1):
            try:
                r = ai_agent._call(key, m, prompt, True)
            except Exception as e:  # noqa: BLE001
                last = "연결 오류: " + str(e)[:80]
                break
            if r.status_code == 429:
                quota = True
                last = "429 " + ai_agent._err_text(r)
                dl = _retry_delay(r)
                if attempt == 0 and not slept and dl is not None and dl <= 45:
                    slept = True  # 한 호출에서 기다리는 것은 최대 한 번(앱이 오래 멈추지 않도록)
                    time.sleep(dl + 1)
                    continue
                break
            if r.status_code >= 400:
                last = "{} {}".format(r.status_code, ai_agent._err_text(r))
                break
            try:
                cand = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"])
                res = ai_agent._extract_json(text)
            except Exception as e:  # noqa: BLE001
                last = "응답 해석 실패: " + str(e)[:80]
                break
            chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
            srcs = [{"title": (c.get("web") or {}).get("title", ""), "uri": (c.get("web") or {}).get("uri", "")} for c in chunks]
            return res, srcs, None, False
    return None, [], last, quota


def _research_prompt(scope, rows):
    today = date.today().isoformat()
    base = ("오늘은 {}입니다. 당신은 리서치 담당입니다. 반드시 웹 검색을 실제로 수행해 최근 7일 이내의 최신 정보를 우선 조사하세요. 기억에 의존하지 말고, 찾지 못한 것은 '찾지 못함'이라고 쓰세요. "
            "아래 출처를 우선적으로 확인하세요(검색어에 기관·매체 이름을 넣어 찾으세요).\n{}\n"
            "내 투자 정책은 고려하지 말고 순수하게 조사만 하세요. 승률·확률·수익 보장 표현 금지. 각 항목에 날짜와 출처 이름을 적으세요.\n").format(today, _source_text())
    if scope == "market":
        return base + ('조사 대상: 오늘·어제 한국과 미국 증시 상황(지수, 변동성, 반도체·AI 업종 흐름, 금리·연준, 주요 이슈 인물 발언, 공포탐욕 지수).\n'
                       '또한 원/달러 환율을 조사하세요: 오늘 환율 수준, 최근 1~3개월 흐름, 달러지수(DXY), 한·미 금리 전망, 외국인 자금·달러 수급, 증권사·기관(예: 국내 증권사 환율 전망, 글로벌 IB 원/달러 전망)의 최근 의견. 환율은 정확히 예측할 수 없으므로 전망은 근거·출처와 함께 "참고 의견"으로만 쓰세요.\n'
                       '출력 JSON: {"market": {"summary": "...", "drivers": ["..."], "sentiment": "...", "key_events_ahead": ["..."]}, "fx": {"level_note": "...", "drivers": ["..."], "institution_views": [{"name": "...", "view": "...", "date": "..."}], "lean": "환전 유리|중립|환전 불리|판단 불가", "confidence": "낮음|보통|높음"}, "not_found": ["..."]}')
    return base + ("조사 대상 종목(오늘·최근 5일 주가 움직임 자료 포함):\n" + json.dumps(rows, ensure_ascii=False) +
                   '\n종목마다: 최근 주가가 움직인 이유(뉴스·인물 발언·실적·규제·수급), 월가·국내 증권사의 최근 목표주가·투자의견 변화, Investing.com 등의 애널리스트 의견/기술적 지표 요약, 강세 논거와 약세 논거, 향후 주요 일정을 조사하세요. '
                   'ETF는 구성 종목·자금 흐름·운용 이슈를 조사하세요.\n출력 JSON: {"tickers": [{"ticker": "...", "name": "...", "move_reason": "...", "analyst_view": "...", "price_targets": "...", "bull": "...", "bear": "...", "next_events": "...", '
                   '"sources": [{"name": "...", "date": "..."}]}], "not_found": ["..."]}')


def research(get_conn, packet, force=False):
    """뉴스 헤드라인은 앱이 직접 수집한다(AI 한도와 무관). secrets에 GEMINI_SEARCH=1 이 있으면 구글 검색 근거 조사를 먼저 시도하고, 실패하면 헤드라인으로 대신한다.
    -> (결과 dict, 출처목록, 경고목록)"""
    warns = []
    if force:
        try:
            import newsfeed
            newsfeed.fetch.clear()
        except Exception:  # noqa: BLE001
            pass
    try:
        flag = str(st.secrets.get("GEMINI_SEARCH", "")).strip() in ("1", "true", "True")
    except Exception:  # noqa: BLE001
        flag = False
    if flag:
        res, srcs, w = research_grounded(get_conn, packet, force)
        if res.get("market") or res.get("tickers"):
            return res, srcs, w
        warns += w
    try:
        import newsfeed
        hold = [{"ticker": h["ticker"], "name": h["name"], "market": h["market"]} for h in packet["holdings"]]
        res, srcs = newsfeed.collect(hold)
    except Exception as e:  # noqa: BLE001
        return {"market": None, "fx": None, "tickers": [], "not_found": []}, [], warns + ["뉴스 헤드라인 수집 실패: " + str(e)[:100]]
    if res["total"] == 0:
        warns.append("뉴스 헤드라인을 하나도 가져오지 못했습니다(네트워크 제한일 수 있음). 이 경우 앱 자료만으로 판단하며 확신도를 낮게 표시합니다.")
        return {"market": None, "fx": None, "tickers": [], "not_found": []}, [], warns
    res["market"]["_note"] = res["how"]
    return res, srcs, warns


def research_grounded(get_conn, packet, force=False):
    """시장 1회 + 종목 묶음(4개씩) 검색 조사. 6시간 안의 결과는 재사용한다. -> (결과 dict, 출처목록, 경고목록)"""
    scope_key = ",".join(sorted(h["ticker"] for h in packet["holdings"]))
    if not force:
        try:
            df = ai_agent._run(get_conn, "SELECT created_at, scope, content FROM research_log ORDER BY id DESC LIMIT 1", fetch=True)
            if df is not None and len(df):
                r = df.iloc[0]
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(r["created_at"]))).total_seconds() / 3600
                if age < RESEARCH_TTL_HOURS and r["scope"] == scope_key:
                    out = json.loads(r["content"])
                    return out["res"], out["sources"], ["{}시간 안의 검색 조사 결과를 재사용했습니다(새로 검색하려면 '검색 새로 하기'를 체크하세요).".format(RESEARCH_TTL_HOURS)]
        except Exception:  # noqa: BLE001
            pass
    import time
    rows = [{"ticker": h["ticker"], "name": h["name"], "market": h["market"], "move_1d_pct": h.get("move_1d_pct"), "move_5d_pct": h.get("move_5d_pct")} for h in packet["holdings"]]
    # 무료 한도를 아끼기 위해 검색 호출은 '시장+환율 1회, 종목 전체 1~2회'로 줄이고 한 번에 하나씩(직렬) 실행한다.
    size = 8 if len(rows) <= 16 else 10
    batches = [rows[i:i + size] for i in range(0, len(rows), size)]
    jobs = [("market", [])] + [("tickers", b) for b in batches]
    warns, all_src, res = [], [], {"market": None, "fx": None, "tickers": [], "not_found": []}
    quota_hit = False
    for n_, (kind, b) in enumerate(jobs):
        if quota_hit:
            break
        if n_:
            time.sleep(4)
        r_, srcs, err, q_ = _grounded(_research_prompt(kind, b))
        if err or not r_:
            if q_:
                quota_hit = True
            else:
                warns.append("검색 조사 실패({}): {}".format("시장·환율" if kind == "market" else ", ".join(x["ticker"] for x in b), err))
            continue
        all_src += srcs
        if kind == "market":
            res["market"] = r_.get("market")
            res["fx"] = r_.get("fx")
        else:
            res["tickers"] += r_.get("tickers") or []
        res["not_found"] += r_.get("not_found") or []
    if quota_hit:
        warns.insert(0, "Gemini 무료 검색 한도(분당 또는 하루)에 걸려 실시간 검색을 건너뛰었습니다. 이 경우 Yahoo 시세·컨센서스와 앱 계산 자료만으로 전략을 만들며 확신도를 낮게 표시합니다. 몇 분 뒤 '검색 새로 하기'로 다시 시도하거나, 내일 다시 시도해 보세요. (한 번 성공한 검색 결과는 6시간 동안 재사용되어 한도를 아낍니다.)")
    if res["market"] or res["tickers"]:
        try:
            ai_agent._run(get_conn, "INSERT INTO research_log (created_at,scope,content) VALUES (%s,%s,%s)", (_now(), scope_key, json.dumps({"res": res, "sources": all_src}, ensure_ascii=False)))
        except Exception:  # noqa: BLE001
            pass
    return res, all_src, warns


def coverage(sources):
    """실제로 참조된 지정 출처(도메인 기준)."""
    hit = set()
    for s_ in sources:
        blob = (str(s_.get("title", "")) + " " + str(s_.get("uri", ""))).lower()
        for dom, nm in SOURCE_DOMAINS.items():
            if dom in blob or nm.lower() in blob:
                hit.add(nm)
    return sorted(hit)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(get_conn):
    for sql in (
        "CREATE TABLE IF NOT EXISTS strategy_log (id SERIAL PRIMARY KEY, created_at TEXT, status TEXT, deposit BIGINT, content TEXT)",
        "CREATE TABLE IF NOT EXISTS cash_events (id SERIAL PRIMARY KEY, event_date TEXT, amount_krw BIGINT, memo TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS research_log (id SERIAL PRIMARY KEY, created_at TEXT, scope TEXT, content TEXT)",
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


def _move(get_prices, tk):
    """최근 1일·5일 등락률(%). 자료가 없으면 (None, None)."""
    if not get_prices:
        return None, None
    try:
        df, _ = get_prices(tk, "1mo")
        c = df["Close"].dropna()
        if len(c) < 6:
            return None, None
        return round((c.iloc[-1] / c.iloc[-2] - 1) * 100, 2), round((c.iloc[-1] / c.iloc[-6] - 1) * 100, 2)
    except Exception:  # noqa: BLE001
        return None, None


def build_packet(items, risk, stress, fx, cfg, deposit, memo, cash_map, policy_text, prev_strategy, get_prices=None):
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
        a["move_1d_pct"], a["move_5d_pct"] = _move(get_prices, i["tk"])
        if i.get("ret") is not None and i["ret"] < 0:
            try:
                sym_ = i["tk"] if str(i["tk"]).endswith((".KS", ".KQ")) else str(i["tk"]).replace(".", "-")
                need_ = (i["avg"] / i["price"] - 1) if i.get("price") else 0
                r = recovery.assess(i, recovery.consensus(sym_), i.get("target"), recovery.hist_rate(sym_, round(need_, 3)))
            except Exception:  # noqa: BLE001
                r = None
            if r:
                a["recovery_check"] = {"need_rise_to_avg_pct": round(r["평단까지 필요한 상승"] * 100, 1), "consensus_mean_target": r["목표가(평균)"],
                                       "upside_to_target_pct": None if r["여력"] is None else round(r["여력"] * 100, 1), "verdict": r["판정"], "source": r["출처"],
                                       "past_frequency_reached_avg_within_12m_pct": None if r.get("과거빈도12m") is None else round(r["과거빈도12m"], 1),
                                       "past_frequency_reached_avg_within_6m_pct": None if r.get("과거빈도6m") is None else round(r["과거빈도6m"], 1)}
            a["average_down_simulation"] = _avg_down(i, [1, 2, 3] if i["cur"] == "KRW" else [])
        rows.append(a)
    pk = {
        "today": date.today().isoformat(),
        "fx_krw_per_usd": round(fx, 1) if fx else None,
        "portfolio_total_krw": round(total),
        "index_moves_pct": {nm: dict(zip(("1d", "5d"), _move(get_prices, sym))) for nm, sym in (("KOSPI", "^KS11"), ("S&P500", "^GSPC"), ("NASDAQ", "^IXIC"), ("SOX(반도체)", "^SOX"), ("VIX", "^VIX"))},
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
    try:  # 코스톨라니 심리·가치 괴리·환전/예수금 자료
        import kostolany
        if get_prices is not None:
            kostolany.cached_analysis(items, get_prices, fx)
        if st.session_state.get("_kost_compact"):
            pk["sentiment_and_value_gap"] = st.session_state["_kost_compact"]
        if st.session_state.get("_fx_packet"):
            pk["cash_accounts_and_fx"] = st.session_state["_fx_packet"]
    except Exception:  # noqa: BLE001
        pass
    return pk


def _prompt(packet, task, extra=""):
    return (
        "당신은 장기 투자자를 돕는 펀드매니저 보조입니다. 아래 JSON 자료는 앱이 계산한 사실이며, 모든 수치 계산(평단·손익률·합계)은 이미 끝나 있으니 새로 계산하지 말고 주어진 값만 인용하세요.\n"
        "원칙: (1) 승률·확률·수익 보장 표현 금지. (2) 모든 판단에 반대 근거를 함께 적는다. (3) 평단가는 참고일 뿐 매수·매도 근거가 아니다. 가격이 내렸다는 것만으로 싸다고 하지 않는다. "
        "(4) 산업 성장성, 기업의 이익 포착 능력, 주가 매력을 구분한다. (5) 시장 스트레스가 높다는 것은 기업이 나빠졌다는 뜻이 아니다. 급락을 바닥이라고 단정하지 않고 나눠 투입한다. "
        "(6) 자료가 없는 것은 '자료 없음'이라 쓰고 추측으로 채우지 않는다. (7) user_policy_text는 사용자의 기본 선호일 뿐 결론을 대신하지 않는다. 증거(research의 검색 결과, 종목별 등락·점수·회복 점검)가 정책과 충돌하면 증거를 우선하고, 벗어난 부분은 policy_deviations에 이유와 함께 적는다. "
        "(7-1) 입금액을 코어 두 종목에 일괄 배분하는 식의 단순 결론 금지. 보유 종목 전부를 priorities에 넣고, 종목마다 오늘 매수 매력을 비교해 금액을 나눈다. 오늘 크게 하락·급등한 종목은 research의 move_reason을 근거로 일시적 요인인지 구조적 요인인지 판단하고, evidence에 출처 이름과 날짜를 적는다. "
        "research가 비어 있거나 실패하면 '실시간 검색 미반영'이라고 headline과 unknowns에 명시하고 확신도를 낮춘다. "
        "(8) 금액은 원화 정수. allocation의 kr_krw+us_krw+cash_krw는 new_deposit.amount_krw와 정확히 같아야 한다(입금이 0이면 모두 0). "
        "(7-2) 판단은 다섯 단계로 하세요: ①사용자 정책 확인(임의 변경 금지) ②기업 투자 논리(실적·현금흐름·경쟁력, 주가 하락만으로 훼손 판단 금지) ③현재 가격·시장심리(sentiment_and_value_gap의 코스톨라니 5단계, 주가 vs 기업가치 괴리 유형) "
        "④전체 포트폴리오 위험(국내+미국 합산, VOO 안에도 엔비디아·구글 등 AI·빅테크가 들어 있어 VOO 보유가 개별 AI 노출을 완전히 분산하지 않음) ⑤신규 자금 최종 배분(종목별 매수/보유/대기/제외, 투자하지 않고 남기는 현금 허용). "
        "소신파/부화뇌동파는 직접 관찰할 수 없는 추정임을 지키고, 심리 신호 하나로 매매를 결론짓지 마세요. 과매수·과매도는 매매 명령이 아니라 판단 입력값입니다. 기업이 훌륭하다는 평가와 지금 가격에 사기 좋다는 평가는 구분하세요. "
        "(7-3) 코어(VOO·버크셔)를 가장 높은 비중으로 두는 것은 사용자의 기본 선호이지만, 코어끼리·코어와 개별 종목 사이의 금액은 정해진 비율이 아니라 오늘의 가격 매력·심리 단계(sentiment_and_value_gap)·뉴스·시장 흐름을 보고 직접 판단하세요. "
        "AI 노출(risk.ai_exposure_pct)은 고려 요소 중 하나일 뿐 개별 AI 종목을 무조건 배제하는 근거가 아닙니다. 심리 1~2단계이면서 이익 전망이 유지되는 종목(rule_final이 '매수 검토')은 분할 매수 후보로 진지하게 검토하고, 사지 않는다면 그 이유를 구체적으로 쓰세요. "
        "앱 규칙 판단(rule_final)과 다르게 결론 내리면 이유를 쓰고, 매수 후보로 검토한 모든 종목에 대해 '왜 이 금액인가/왜 0원인가'를 비교해서 쓰세요. 점수(score_total)가 낮은 종목에 큰 금액을 주면 reason에 이유를 쓰세요. "
        "좋은 매수 가격이 보이지 않으면 현금(cash_krw)을 남기는 것도 하나의 결정입니다. 각 판단에 근거의 기준일·출처·실제 데이터인지 추정인지·판단이 바뀌는 조건을 포함하세요. "
        "좋은 매수 가격이 보이지 않으면 현금(cash_krw)을 남기는 것도 하나의 결정입니다. 각 판단에 근거의 기준일·출처·실제 데이터인지 추정인지·판단이 바뀌는 조건을 포함하세요. "
        "(7-4) 환전과 매수는 별개: cash_accounts_and_fx에 달러 예수금이 있으면 환전 없이 그 달러로 매수할 수 있다는 점을 고려하고, 환율 조사 의견은 참고로만 쓰세요. "
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


def enforce_limits(pri, warns):
    """금액을 바꾸지 않고 알리기만 한다. 코어 비율·종목 상한을 앱이 강제하지 않는다(AI가 시장 흐름을 보고 판단)."""
    buys = [p for p in pri if p.get("market") == "미국" and p.get("action") == "매수" and p.get("amount_krw", 0) > 0]
    tot = sum(p["amount_krw"] for p in buys)
    if not tot:
        return
    core = ("VOO", "BRK-B", "BRK.B", "BRKB")
    for p in buys:
        if str(p.get("ticker", "")).upper() not in core and p["amount_krw"] / tot > 0.6:
            warns.append("참고: '{}' 한 종목에 미국 매수액의 {:.0f}%가 배정됐습니다(앱은 비율을 강제하지 않고 알리기만 합니다).".format(p.get("name"), p["amount_krw"] / tot * 100))
    if len(buys) == 1:
        warns.append("참고: 오늘 매수가 '{}' 한 종목뿐입니다. 아래 종목별 근거(왜 0원인지)와 '앱 규칙 판단'을 비교해 보세요.".format(buys[0].get("name")))


def postprocess(strategy, items, fx):
    """보유 종목 누락 보완, 시장별 금액 상한, 달러 환산, 근거 누락 표시."""
    warns = []
    by_name = {i["name"]: i for i in items}
    by_tk = {i["tk"]: i for i in items}
    pri = strategy.get("priorities") or []
    seen = set()
    for p in pri:
        it = by_tk.get(p.get("ticker")) or by_name.get(p.get("name"))
        p["_item"] = it["tk"] if it else None
        if it:
            seen.add(it["tk"])
            p["market"] = it["mkt"]
        try:
            p["amount_krw"] = max(0, int(float(p.get("amount_krw") or 0)))
        except Exception:  # noqa: BLE001
            p["amount_krw"] = 0
        if p.get("action") == "매수" and not str(p.get("evidence", "")).strip():
            warns.append("'{}' 매수 제안에 검색·데이터 근거(evidence)가 없습니다. 근거 없는 제안으로 보세요.".format(p.get("name")))
    for it in items:
        if it["tk"] not in seen:
            pri.append({"rank": 99, "name": it["name"], "ticker": it["tk"], "action": "AI 미언급", "amount_krw": 0, "weight_hint": "-", "reason": "AI가 이 종목을 다루지 않았습니다.", "evidence": "", "counter": "", "_item": it["tk"], "market": it["mkt"]})
    enforce_limits(pri, warns)
    try:  # 점수·배분 일관성과 AI 집중 점검(앱이 다시 확인)
        by_item = {i["tk"]: i for i in items}
        tot_dep = sum(p["amount_krw"] for p in pri if p.get("action") == "매수") or 0
        for p in pri:
            it_ = by_item.get(p.get("_item"))
            sc_ = None if not it_ or not it_.get("score") else it_["score"]["total"]
            if p.get("action") == "매수" and p["amount_krw"] > 0 and sc_ is not None and sc_ < 3 and not any(k in str(p.get("reason", "")) for k in ("정책", "코어", "예외")):
                warns.append("'{}'은(는) 앱 점수 {:.1f}점으로 낮은데 {:,}원이 배정됐고 reason에 정책·코어 예외 설명이 없습니다. 일관성을 직접 확인하세요.".format(p.get("name"), sc_, p["amount_krw"]))
        tech = {"NVDA", "PLTR", "GOOGL", "TSLA", "IONQ", "AMD", "MSFT", "META", "AVGO"}
        tsum = sum(p["amount_krw"] for p in pri if p.get("action") == "매수" and str(p.get("ticker", "")).upper() in tech)
        if tot_dep and tsum / tot_dep > 0.4:
            warns.append("개별 AI·기술주에 오늘 매수액의 {:.0f}%가 배정됐습니다. VOO에도 같은 종목이 들어 있어 실질 AI 노출이 더 큽니다.".format(tsum / tot_dep * 100))
    except Exception:  # noqa: BLE001
        pass
    al = strategy.get("allocation") or {}
    for mk, key in (("한국", "kr_krw"), ("미국", "us_krw")):
        tot = sum(p["amount_krw"] for p in pri if p.get("market") == mk and p.get("action") == "매수")
        cap = int(al.get(key, 0) or 0)
        if tot > cap:
            warns.append("{} 종목별 금액 합계({:,}원)가 {} 배분({:,}원)을 넘어 비율대로 줄였습니다.".format(mk, tot, mk, cap))
            for p in pri:
                if p.get("market") == mk and p.get("action") == "매수":
                    p["amount_krw"] = int(p["amount_krw"] * cap / tot) if tot else 0
    for p in pri:
        p["amount_usd"] = round(p["amount_krw"] / fx, 2) if (fx and p.get("market") == "미국") else None
    al["us_usd"] = round(int(al.get("us_krw", 0) or 0) / fx, 2) if fx else None
    al["fx"] = round(fx, 1) if fx else None
    strategy["allocation"], strategy["priorities"] = al, sorted(pri, key=lambda p: (p.get("rank") or 99))
    return strategy, warns


def _fill_missing(packet, res, items):
    """AI가 빠뜨린 보유 종목을 한 번 더 물어 채운다(금액은 이미 정한 배분을 건드리지 않도록 0원)."""
    miss = [p for p in res.get("priorities") or [] if p.get("action") == "AI 미언급"]
    if not miss:
        return []
    names = [p.get("name") for p in miss]
    keep = {"today": packet.get("today"), "holdings": [h for h in packet["holdings"] if h["name"] in names], "research": {"tickers": [t for t in (packet.get("research") or {}).get("tickers", []) if t.get("name") in names]},
            "sentiment_and_value_gap": packet.get("sentiment_and_value_gap"), "already_decided_allocation": res.get("allocation"), "policy": packet.get("user_policy_text")}
    pr = ("당신은 펀드매니저 보조입니다. 오늘 배분은 이미 정해졌습니다(already_decided_allocation). 아래 종목에 대해서만 오늘의 판단을 JSON으로 쓰세요. 금액은 배정하지 않습니다(0원). "
          "action은 매수후보|보류|홀드|정리검토 중 하나, reason과 evidence(헤드라인 근거와 날짜·매체, 없으면 '자료 없음'), counter(반대 근거)를 쓰세요. 승률·확률 표현 금지, 헤드라인에 없는 사실은 추측 금지.\n"
          '출력: {"priorities": [{"name": "", "ticker": "", "action": "", "reason": "", "evidence": "", "counter": ""}]}\n자료:\n' + json.dumps(keep, ensure_ascii=False)[:30000])
    out, err = _gemini(pr)
    if err or not isinstance(out, dict):
        return ["일부 종목({})은 AI가 다루지 못했습니다: {}".format(", ".join(names), err or "응답 형식 오류")]
    by = {(p.get("ticker") or "", p.get("name") or ""): p for p in out.get("priorities") or []}
    got = 0
    for p in miss:
        q = next((v for k, v in by.items() if k[0] == p.get("ticker") or k[1] == p.get("name")), None)
        if q:
            p["action"] = q.get("action") or "보류"
            p["reason"], p["evidence"], p["counter"] = q.get("reason", ""), q.get("evidence", ""), q.get("counter", "")
            p["amount_krw"] = 0
            got += 1
    return [] if got == len(miss) else ["{}개 종목은 끝내 판단을 받지 못했습니다.".format(len(miss) - got)]


def make_strategy(get_conn, packet, items, deposit, fx, force_research=False):
    try:
        ai_ = float((packet.get("risk") or {}).get("ai_exposure_pct") or 0) / 100.0
        band_ = float(packet.get("ai_exposure_comfort_band_pct") or 45) / 100.0
        share_ = max(0.30, min(0.85, 0.40 + 1.6 * (ai_ - band_)))
        st.session_state["_limits"] = None  # 비율을 강제하지 않는다(AI가 판단). 집중도는 경고로만 알린다.
    except Exception:  # noqa: BLE001
        st.session_state["_limits"] = None
    res_r, srcs, rwarns = research(get_conn, packet, force_research)
    packet["research"] = res_r
    packet["research_status"] = ("정상: 뉴스 헤드라인 {}건 반영(앱이 직접 수집, 본문은 못 읽음)".format(res_r.get("total", "")) if res_r.get("total") else "정상") if (res_r.get("market") or res_r.get("tickers")) else "실패: 뉴스 자료 없음"
    task = ("이번에 배분할 가용 자금 {:,}원(= CMA에서 쓸 수 있는 원화 + 이미 보유한 달러의 원화 환산, packet.cash_pool 참고)을 포함해 현재 포트폴리오의 큰 전략·세부 전략·배분·우선순위를 새로 짜세요. "
            "국장 매수(kr_krw)는 CMA 원화(cash_pool.cma_available_krw) 범위 안에서만, 미국 매수(us_krw)는 보유 달러를 먼저 쓰고 부족분만 환전합니다. 환율 등급(cash_accounts_and_fx.fx_rule_level)이 낮음·매우 낮음이면 환전이 필요한 미국 매수는 줄이거나 미루고, 이미 가진 달러 범위에서 먼저 매수를 검토하세요. "
            "research의 뉴스 헤드라인(앱이 수집, 본문은 못 읽음)과 종목별 등락·점수·회복 점검·심리 단계를 근거로 '보유 종목 전부'를 priorities에 넣어 종목마다 판단하세요(하나라도 빠뜨리지 마세요. 사지 않는 종목도 보류·홀드와 이유를 쓰세요). "
            "헤드라인에 없는 사실은 추측하지 말고 unknowns에 적으세요. 환율은 fx_view에 헤드라인에서 확인된 범위로만 판단하고 정확한 예측은 불가함을 전제하세요. "
            "손실 종목마다 물타기가 유리한지 불리한지도 avg_down_review에 검토하세요.").format(deposit)
    res, err = _gemini(_prompt(packet, task, "반드시 아래 JSON 스키마만 출력하세요.\n" + SCHEMA))
    if err:
        return None, err, rwarns
    res, warns = validate(res, deposit, items)
    res, w2 = postprocess(res, items, fx)
    w2 += _fill_missing(packet, res, items)
    res["_deposit"] = int(deposit)
    res["_pool"] = packet.get("cash_pool")
    res["_coverage"] = coverage(srcs)
    res["_research_ok"] = bool(res_r.get("market") or res_r.get("tickers"))
    afx = res.get("fx_view")
    if not (isinstance(afx, dict) and afx.get("lean")):
        afx = res_r.get("fx") if isinstance(res_r.get("fx"), dict) and res_r["fx"].get("lean") else None
    res["_ai_fx"] = afx
    res["_headlines_total"] = res_r.get("total")
    res["_research_src"] = [{"title": x.get("title", ""), "uri": x.get("uri", "")} for x in srcs][:30]
    ai_agent._run(get_conn, "INSERT INTO strategy_log (created_at,status,deposit,content) VALUES (%s,%s,%s,%s)",
                  (_now(), "draft", int(deposit), json.dumps(res, ensure_ascii=False)))
    return res, None, rwarns + warns + w2


def load_latest(get_conn):
    try:
        df = ai_agent._run(get_conn, "SELECT id, created_at, status, deposit, content FROM strategy_log ORDER BY id DESC LIMIT 1", fetch=True)
        if df is not None and len(df):
            r = df.iloc[0]
            return int(r["id"]), str(r["status"]), json.loads(r["content"]), str(r["created_at"])
    except Exception:  # noqa: BLE001
        pass
    return None, None, None, None


def chat_reply(get_conn, packet, strategy, history, msg, items, fx=None):
    hist = "\n".join("{}: {}".format("나" if h["role"] == "user" else "펀드매니저", h["text"]) for h in history[-8:])
    extra = ("지금 확정 전 전략(JSON):\n" + json.dumps(strategy, ensure_ascii=False)[:20000] + "\n\n지금까지 대화:\n" + hist + "\n\n사용자 의견: " + msg +
             "\n\n사용자의 의견이 타당하면 반영하고, 근거가 약하면 이유를 들어 정중히 반대하세요. 정책과 충돌하면 그 점을 말하세요. 아래 JSON으로만 답하세요.\n"
             '{"reply": "사용자에게 하는 답(간결하게)", "revised_strategy": null 또는 위 전략 스키마 전체(전략을 바꿔야 할 때만)}\n전략 스키마:\n' + SCHEMA)
    pr = _prompt(packet, "사용자와 전략에 대해 대화하세요. 사용자가 최신 이슈를 묻거나 판단에 새 사실이 필요하면 웹 검색으로 확인하고 출처 이름과 날짜를 답에 적으세요.", extra)
    res, srcs, err, _q = _grounded(pr)
    note = ""
    if err or not res:
        res, err = _gemini(pr)
        note = "\n\n(실시간 검색을 하지 못해 기존 자료로만 답했습니다.)"
    if err:
        return None, err, []
    warns = []
    rs = res.get("revised_strategy")
    if isinstance(rs, dict) and rs.get("master"):
        rs, warns = validate(rs, int(strategy.get("_deposit", 0) or 0), items)
        rs, w2_ = postprocess(rs, items, fx)
        warns += w2_
        rs["_deposit"] = strategy.get("_deposit", 0)
        rs["_coverage"], rs["_research_ok"] = strategy.get("_coverage", []), strategy.get("_research_ok", False)
        ai_agent._run(get_conn, "INSERT INTO strategy_log (created_at,status,deposit,content) VALUES (%s,%s,%s,%s)",
                      (_now(), "draft", int(rs["_deposit"] or 0), json.dumps(rs, ensure_ascii=False)))
    else:
        rs = None
    return {"reply": str(res.get("reply", "")) + note, "revised": rs}, None, warns


# ------------------------------------------------------------------ 실행 계획
def execution_rows(strategy, items, fx):
    """AI 우선순위를 수량으로 환산한다. 한국 주식은 정수 주, 미국 주식은 소수점. 금액은 환율로 달러 환산."""
    by_tk = {i["tk"]: i for i in items}
    rows = []
    for p in strategy.get("priorities") or []:
        it = by_tk.get(p.get("_item"))
        amt = int(p.get("amount_krw") or 0)
        row = {"순위": p.get("rank") if p.get("rank") != 99 else None, "종목": p.get("name"), "행동": p.get("action"), "금액(원)": amt if amt else None,
               "금액(USD)": None, "수량": None, "현재가": None, "체결 후 평단": None, "규칙 점수": None, "비중 방향": p.get("weight_hint"),
               "앱 규칙 판단(심리)": ((st.session_state.get("_kost_compact") or {}).get(p.get("_item")) or {}).get("rule_final"), "근거": (str(p.get("reason") or "") + ("  [앱 보정: {}]".format(p["_adj"]) if p.get("_adj") else "")), "오늘의 증거(출처)": p.get("evidence"), "반대 근거": p.get("counter")}
        if it:
            row["규칙 점수"] = None if not it.get("score") else round(it["score"]["total"], 1)
            px = it.get("price")
            if px:
                row["현재가"] = ("${:,.2f}".format(px) + " (≈{:,.0f}원)".format(px * fx)) if it["cur"] == "USD" and fx else "{:,.0f}원".format(px)
            if px and amt and p.get("action") == "매수":
                if it["cur"] == "USD" and fx:
                    usd = amt / fx
                    q = usd / px
                    row["금액(USD)"] = round(usd, 2)
                    row["수량"] = "{:.4f}주".format(q)
                    row["체결 후 평단"] = "${:,.2f}".format((it["qty"] * it["avg"] + q * px) / (it["qty"] + q))
                else:
                    q = int(amt // px)
                    row["수량"] = "{}주".format(q) if q else "1주 금액 부족"
                    if q:
                        row["금액(원)"] = int(q * px)
                        row["체결 후 평단"] = "{:,.0f}원".format((it["qty"] * it["avg"] + q * px) / (it["qty"] + q))
        rows.append(row)
    return rows


def plan_for_banner(strategy, items, fx):
    """맨 위 '오늘 투입 안내'용 요약(확정된 AI 전략)."""
    rows = [r for r in execution_rows(strategy, items, fx) if r["행동"] == "매수" and r["금액(원)"]]
    lines = []
    for n, r in enumerate(rows, 1):
        txt = "{:,}원".format(r["금액(원)"]) + (" (${:,.2f}, {})".format(r["금액(USD)"], r["수량"]) if r["금액(USD)"] else " ({})".format(r["수량"]))
        lines.append({"행동순서": n, "종목": r["종목"], "전략": "AI 제안", "금액(원)": r["금액(원)"], "표시": txt})
    al = strategy.get("allocation") or {}
    used = sum(r["금액(원)"] for r in rows)
    dep = int(strategy.get("_deposit", 0) or 0)
    return {"rows": lines, "used": used, "reserved": 0, "hold_cash": max(0, dep - used), "board": [], "notes": []}


# ------------------------------------------------------------------ 화면
def _log_chat(get_conn, role, text):
    ai_agent._run(get_conn, "INSERT INTO chat_log (created_at,role,text) VALUES (%s,%s,%s)", (_now(), role, text[:4000]))


def _load_chat(get_conn, n=30):
    try:
        df = ai_agent._run(get_conn, "SELECT role, text FROM chat_log ORDER BY id DESC LIMIT {}".format(int(n)), fetch=True)
        return [{"role": r["role"], "text": r["text"]} for _, r in df.iloc[::-1].iterrows()]
    except Exception:  # noqa: BLE001
        return []


def render_panel(get_conn, items, risk, stress, fx, cfg, cash_map, save_cfg, load_cfg, hub, get_prices=None):
    import plotly.graph_objects as go
    import ledger
    ensure_tables(get_conn)
    try:  # 달러·원화 예수금과 환율 판단을 AI 자료에 포함
        import fx as fxmod
        fxmod.ensure_tables(get_conn)
        _l = load_latest(get_conn)
        st.session_state["_fx_packet"] = fxmod.packet_part(get_conn, fxmod.fx_view(), (_l[2] or {}).get("_ai_fx") if _l and _l[2] else None)
    except Exception:  # noqa: BLE001
        pass
    c = load_cfg(get_conn)
    policy = c.get("policy_text") or DEFAULT_POLICY
    cfg_pk = {"goal": hub.get("goal"), "invested": hub.get("invested"), "band": st.session_state.get("_ai_band"), "freeze": hub.get("freeze"), "core": hub.get("core")}
    st.markdown("### AI 투자 에이전트")
    st.caption("입금액을 넣으면 ① 지정 기관·매체·인물을 웹 검색으로 먼저 조사하고 ② 보유 종목별 등락·점수·회복 점검 자료와 합쳐 ③ 큰 전략, 국장·미국·현금 배분, 종목별 우선순위와 수량을 짭니다. "
               "최종 결정과 주문은 내가 합니다. AI에 보내는 내용: 종목명·비중·수량·평단·평가금액·현금·입금액·정책 메모(계좌번호·로그인·이름은 보내지 않음). 무료 API 입력은 구글 서비스 개선에 쓰일 수 있습니다.")
    with st.expander("내 투자 정책 메모 (기본 선호 — 데이터가 강하게 반대하면 AI가 예외를 제안할 수 있음)", expanded=False):
        with st.form("policy_text_form"):
            txt = st.text_area("정책", value=policy, height=220, key="policy_text_area")
            if st.form_submit_button("정책 저장"):
                save_cfg(get_conn, "policy_text", txt)
                st.rerun()
    with st.expander("검색 조사 대상으로 지정한 기관·매체·인물"):
        for k_, v_ in SOURCES.items():
            st.markdown("**{}** — {}".format(k_, ", ".join(v_)))
        st.caption("AI가 검색 때 이 이름들을 우선 찾도록 지시하지만, 검색 엔진이 실제로 어떤 사이트를 보여 줄지는 보장할 수 없습니다. 결과 화면에 실제로 참조된 지정 출처를 표시합니다.")
    sid, status, strat, created = load_latest(get_conn)
    import fx as fxmod
    fxmod.ensure_tables(get_conn)
    cma0, usd0, dep_cum, fx_cum, buy_cum = fxmod.balances(get_conn)
    reserve0 = int(float(c.get("fx_reserve", 0) or 0))
    spread0 = float(c.get("fx_spread", 0.25) or 0.25)
    st.markdown("##### 내 돈 현황 — 원화 예수금 · 달러 예수금 · 투자 가능 금액")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CMA 원화 예수금", "{:,.0f}원".format(cma0))
    m2.metric("달러 예수금", "${:,.2f}".format(usd0), "{:,.0f}원 환산".format(usd0 * fx) if fx else None)
    m3.metric("비상금·부채 제외 후 투자 가능 원화", "{:,.0f}원".format(max(0.0, cma0 - reserve0)))
    m4.metric("이번에 배분할 수 있는 총액", "{:,.0f}원".format(max(0.0, cma0 - reserve0) + usd0 * (fx or 0)))
    st.caption("누적 입금 {:,.0f}원 · 누적 환전 {:,.0f}원 · 누적 미국 매수 ${:,.2f}. 이 잔액은 '실제로 한 일'을 기록해야만 바뀝니다(아래 계획 화면과 '환전·달러 예수금' 탭에서 기록). "
               "처음이라면 지금 CMA 잔액과 달러 잔액을 '환전·달러 예수금' 탭의 '잔액 바로잡기'로 한 번 맞춰 두세요.".format(dep_cum, fx_cum, buy_cum))
    with st.form("deposit_form"):
        d1, d2, d3 = st.columns([1, 1, 2])
        ev_date = d1.date_input("입금 날짜", value=date.today(), key="dep_date")
        amt = d2.number_input("CMA에 새로 입금한 돈 (원, 없으면 0)", min_value=0, value=0, step=100000, key="dep_amt")
        memo = d3.text_input("메모 (선택)", key="dep_memo")
        r1, r2 = st.columns(2)
        reserve_in = r1.number_input("CMA 중 투자에 쓰지 않을 돈 (비상금·부채 상환 예정액)", min_value=0, value=reserve0, step=100000, key="dep_reserve")
        spread_in = r2.number_input("증권사 환전 스프레드 (우대 반영, %)", min_value=0.0, max_value=3.0, value=spread0, step=0.05, key="dep_spread")
        force = st.checkbox("뉴스를 새로 모으기 (끄면 30분 안에 모은 헤드라인을 재사용)", value=False, key="dep_force")
        b1, b2 = st.columns(2)
        go_new = b1.form_submit_button("입금 기록하고 오늘 운용 계획 받기")
        go_chk = b2.form_submit_button("입금 없이 오늘 운용 계획 받기")
    if go_new or go_chk:
        try:
            save_cfg(get_conn, "fx_reserve", str(int(reserve_in)))
            save_cfg(get_conn, "fx_spread", str(float(spread_in)))
        except Exception:  # noqa: BLE001
            pass
        new_dep = int(amt) if go_new else 0
        if new_dep > 0:
            try:
                ai_agent._run(get_conn, "INSERT INTO fx_events (created_at,event_date,kind,krw_delta,usd_delta,rate,memo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                              (_now(), ev_date.isoformat(), "deposit", new_dep, 0, None, memo))
                ai_agent._run(get_conn, "INSERT INTO cash_events (event_date,amount_krw,memo,created_at) VALUES (%s,%s,%s,%s)", (ev_date.isoformat(), new_dep, memo, _now()))
            except Exception as e:  # noqa: BLE001
                st.error("입금 기록 실패: " + str(e)[:100])
        cma1, usd1 = fxmod.balances(get_conn)[:2]
        cma_av = max(0.0, cma1 - reserve_in)
        pool = int(cma_av + usd1 * (fx or 0))
        pool_info = {"cma_krw": round(cma1), "cma_available_krw": round(cma_av), "reserve_excluded_krw": int(reserve_in), "usd_cash_usd": round(usd1, 2), "usd_cash_krw": round(usd1 * (fx or 0)),
                     "new_deposit_today_krw": new_dep, "fx_spread_pct": float(spread_in), "total_pool_krw": pool}
        packet = build_packet(items, risk, stress, fx, cfg_pk, pool, memo, cash_map, policy, strat, get_prices)
        packet["cash_pool"] = pool_info
        packet["new_deposit"]["note"] = "amount_krw는 이번에 배분할 전체 가용 자금(CMA 사용 가능 원화 + 보유 달러의 원화 환산)이며, 오늘 새로 들어온 돈은 new_deposit_today_krw입니다."
        with st.spinner("뉴스를 모으고 전략을 짜는 중... (30초~1분)"):
            res, err, warns = make_strategy(get_conn, packet, items, pool, fx, force_research=force)
        if err:
            st.error("전략을 만들지 못했습니다: " + err)
        else:
            st.session_state["_strat_warn"] = warns
            st.rerun()
    sid, status, strat, created = load_latest(get_conn)
    if not strat:
        st.info("아직 전략이 없습니다. 위에서 '입금 없이 전략만 다시 점검'을 눌러도 현재 포트폴리오 기준의 전략을 받을 수 있습니다.")
        return None
    for w in st.session_state.get("_strat_warn", []):
        st.warning(w)
    mstr = strat.get("master") or {}
    al = strat.get("allocation") or {}
    dep = int(strat.get("_deposit", 0) or 0)
    st.markdown("#### {}".format(strat.get("headline", "")))
    cov = strat.get("_coverage") or []
    st.caption("상태: {} · 작성 {} UTC · 신뢰도 {} · AI 초안이며 검증 전입니다".format("확정" if status == "confirmed" else "초안(확정 전)", created[:16].replace("T", " "), strat.get("confidence", "-")))
    if strat.get("_research_ok"):
        n_h = strat.get("_headlines_total")
        st.caption("뉴스 반영: 예{} · 참조된 지정 기관·매체 {}곳 — {} · 헤드라인(제목·매체·날짜)만 읽었고 기사 본문은 읽지 못했습니다.".format(
            " · 헤드라인 {}건".format(n_h) if n_h else "", len(cov), ", ".join(cov) if cov else "지정 기관이 직접 확인되지 않음"))
    else:
        st.error("뉴스 자료를 가져오지 못했습니다. 이 전략은 앱 자료(시세·점수·컨센서스)에만 근거하므로 참고만 하세요.")
    if strat.get("research_summary"):
        st.markdown("**오늘의 핵심 발견** — " + str(strat["research_summary"]))
    for d_ in strat.get("policy_deviations") or []:
        st.warning("정책과 다른 제안: " + str(d_))
    col1, col2 = st.columns([3, 2])
    with col1:
        st.write(mstr.get("summary", ""))
        for k, lab in (("phase_goal", "지금 단계 목표"), ("kr_policy", "국장"), ("us_policy", "미국"), ("core_policy", "코어(VOO·버크셔)"), ("tech_policy", "기술주"), ("cash_policy", "현금")):
            if mstr.get(k):
                st.markdown("**{}** — {}".format(lab, mstr[k]))
    with col2:
        if dep > 0:
            fig = go.Figure(go.Pie(labels=["국장", "미국", "현금 보유"], values=[al.get("kr_krw", 0), al.get("us_krw", 0), al.get("cash_krw", 0)], hole=0.55,
                                   textinfo="label+percent", sort=False, marker=dict(colors=["#14213D", "#0F766E", "#B8B4A8"])))
            fig.update_layout(height=230, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                              annotations=[dict(text="{:,}원".format(dep), x=0.5, y=0.5, showarrow=False, font=dict(size=14))])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            usd_txt = " (${:,.2f}, 환율 {:,.0f}원)".format(al["us_usd"], al["fx"]) if al.get("us_usd") is not None else ""
            st.caption("국장 {:,}원 · 미국 {:,}원{} · 현금 {:,}원 — {}".format(al.get("kr_krw", 0), al.get("us_krw", 0), usd_txt, al.get("cash_krw", 0), al.get("reason", "")))
        else:
            st.caption("배분할 수 있는 돈이 없어(CMA·달러 예수금이 0원) 이번 전략은 점검만 합니다. 위 '내 돈 현황'에 잔액을 먼저 맞춰 주세요.")
    try:
        import fx as fxmod2
        pool_ = strat.get("_pool") or {}
        if dep > 0 and fx:
            gap_ = max(0.0, float(cfg_pk.get("goal") or 0) - float(cfg_pk.get("invested") or 0))
            pl_ = fxmod2.plan(al, fx, float(pool_.get("cma_available_krw", 0)), float(pool_.get("usd_cash_usd", 0)), float(pool_.get("fx_spread_pct", 0.25)),
                              fxmod2.fx_view(), strat.get("_ai_fx"), gap_)
            fxmod2.render_plan(get_conn, pl_, dep, "p%s" % sid)
            afx_ = strat.get("_ai_fx")
            if afx_:
                st.caption("AI 환율 의견(참고, 정확한 예측 불가): {} · 신뢰도 {} — {}".format(afx_.get("lean", "-"), afx_.get("confidence", "-"), afx_.get("level_note", "")))
    except Exception as e:  # noqa: BLE001
        st.caption("자금 계획을 표시하지 못했습니다: " + str(e)[:100])
    ex = execution_rows(strat, items, fx)
    if ex:
        st.markdown("**실행 계획 — 우선순위 · 금액 · 수량**")
        st.dataframe(pd.DataFrame(ex), use_container_width=True, hide_index=True,
                     column_config={"금액(원)": st.column_config.NumberColumn("금액(원)", format="%d"), "금액(USD)": st.column_config.NumberColumn("금액(USD)", format="$%.2f")})
        st.caption("미국 종목은 오늘 환율로 달러 환산했고 소수점 수량으로 계산했습니다. 한국 종목은 정수 주 단위라 남는 금액은 현금으로 둡니다. '규칙 점수'는 앱의 기존 점수 규칙으로, AI 판단과 비교하는 참고값입니다.")
    ad = strat.get("avg_down_review") or []
    if ad:
        st.markdown("**손실 종목 물타기 검토**")
        st.dataframe(pd.DataFrame([{"종목": a.get("name"), "판정": a.get("verdict"), "회복 가능성 수치": a.get("recovery_pct_note"), "근거": a.get("reason"), "성립 조건": a.get("conditions")} for a in ad]),
                     use_container_width=True, hide_index=True)
        st.caption("평단을 낮추는 것 자체는 근거가 되지 못합니다. 조건이 충족될 때만 참고하세요.")
    with st.expander("세부 규칙 · 위험 · 질문 · 검색 출처 목록"):
        for r in strat.get("detail_rules") or []:
            st.markdown("**{}** — {}".format(r.get("topic"), r.get("rule")))
        for r in mstr.get("risk_notes") or []:
            st.caption("위험: " + str(r))
        for q in strat.get("questions_to_user") or []:
            st.caption("질문: " + str(q))
        for u in strat.get("unknowns") or []:
            st.caption("확인 못함: " + str(u))
        for x in (strat.get("_research_src") or [])[:20]:
            st.caption("출처: {} {}".format(x.get("title", ""), x.get("uri", "")[:90]))
    if status != "confirmed" and dep > 0:
        if st.button("이 계획을 확정하고 기록하기", key="strat_confirm", type="primary"):
            try:
                for key_, val_ in (("KR_KRW", al.get("kr_krw", 0)), ("US_KRW", al.get("us_krw", 0))):
                    ai_agent._run(get_conn, "INSERT INTO cash_balance (currency,amount,updated_at) VALUES (%s,%s,%s) ON CONFLICT (currency) DO UPDATE SET amount=EXCLUDED.amount, updated_at=EXCLUDED.updated_at",
                                  (key_, float(val_), _now()))
                save_cfg(get_conn, "kr_freeze", "1" if not al.get("kr_krw") else "0")
                ai_agent._run(get_conn, "UPDATE strategy_log SET status='confirmed' WHERE id=%s", (sid,))
                ledger.log_recs(get_conn, sid, strat, items, fx)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error("반영하지 못했습니다: " + str(e)[:120])
    elif status == "confirmed" and dep > 0:
        st.success("확정되었습니다. 이 제안은 기록되어 아래 '기록·백테스트'에서 시간이 지난 뒤의 성과를 점검합니다. 실제 매수는 내가 증권사 앱에서 하고, 체결 후 미국주 수량·평단을 고쳐 주세요.")
    # ---- 채팅 ----
    st.markdown("#### 펀드매니저와 의견 나누기")
    hist = _load_chat(get_conn)
    for h in hist[-10:]:
        with st.chat_message("user" if h["role"] == "user" else "assistant"):
            st.write(h["text"])
    msg = st.chat_input("의견을 적어 주세요 (예: 오늘 엔비디아가 빠진 이유가 일시적인지 찾아보고 비중을 다시 짜줘)", key="mgr_chat")
    if msg:
        packet = build_packet(items, risk, stress, fx, cfg_pk, dep, "", cash_map, policy, None, get_prices)
        _log_chat(get_conn, "user", msg)
        with st.spinner("펀드매니저가 확인하고 답을 정리하는 중..."):
            out, err, warns = chat_reply(get_conn, packet, strat, hist, msg, items, fx)
        if err:
            st.error("답을 받지 못했습니다: " + err)
        else:
            text = out["reply"] + ("\n\n(전략이 수정되어 새 초안으로 저장했습니다. 위에서 확인 후 확정하세요.)" if out["revised"] else "")
            _log_chat(get_conn, "assistant", text)
            st.session_state["_strat_warn"] = warns
            st.rerun()
    return strat if status == "confirmed" else None
