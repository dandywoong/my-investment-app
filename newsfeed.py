"""뉴스 헤드라인 수집(AI 한도와 무관). 구글 뉴스 RSS를 앱이 직접 읽어 최근 헤드라인·매체·날짜를 모은다.

왜 필요한가: Gemini의 '검색 근거' 기능은 무료 한도가 매우 작아 자주 429로 막힌다. 검색은 앱이 직접 하고,
Gemini는 모아 둔 자료를 읽고 판단만 하게 하면 한 번의 전략 생성에 AI 호출이 1~2회로 줄어 한도에 거의 걸리지 않는다.
한계: 헤드라인(제목·매체·날짜)만 읽을 수 있고 기사 본문은 못 읽는다. 결과 화면에 그 사실을 표시한다.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import streamlit as st

UA = {"User-Agent": "Mozilla/5.0 (compatible; EggfolioBot/1.0)"}
MAX_AGE_DAYS = 14

INSTITUTIONS_US = "Goldman Sachs OR Morgan Stanley OR JPMorgan OR Bank of America OR Citi OR UBS OR Wedbush"
INSTITUTIONS_KR = "삼성증권 OR 미래에셋증권 OR KB증권 OR 한국투자증권 OR NH투자증권"

KR_NAMES = {"000660.KS": "SK하이닉스", "005930.KS": "삼성전자", "009150.KS": "삼성전기", "000150.KS": "두산", "379810.KS": "KODEX 미국나스닥100",
            "0167A0.KS": "SOL AI반도체TOP2플러스"}


def _url(q, lang):
    if lang == "ko":
        return "https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko".format(quote(q))
    return "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en".format(quote(q))


@st.cache_data(ttl=1800, show_spinner=False)
def fetch(q, lang="en", n=6):
    """-> [{"title","source","date","link"}] 최신순. 실패하면 빈 목록."""
    try:
        import requests
        r = requests.get(_url(q + " when:14d", lang), headers=UA, timeout=8)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
    except Exception:  # noqa: BLE001
        return []
    out, now = [], datetime.now(timezone.utc)
    for it in root.iter("item"):
        try:
            title = (it.findtext("title") or "").strip()
            src = (it.findtext("source") or "").strip()
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            dt = parsedate_to_datetime(it.findtext("pubDate"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).days > MAX_AGE_DAYS:
                continue
            out.append({"title": re.sub(r"\s+", " ", title)[:160], "source": src, "date": dt.astimezone(timezone.utc).strftime("%Y-%m-%d"), "link": it.findtext("link") or "", "_dt": dt})
        except Exception:  # noqa: BLE001
            continue
    out.sort(key=lambda x: x["_dt"], reverse=True)
    seen, res = set(), []
    for x in out:
        k = x["title"][:40]
        if k in seen:
            continue
        seen.add(k)
        x.pop("_dt", None)
        res.append(x)
        if len(res) >= n:
            break
    return res


def _sym_query(tk, name, mkt):
    if str(tk).endswith((".KS", ".KQ")) or mkt == "한국":
        nm = KR_NAMES.get(tk) or name
        return nm + " 주가 목표주가 전망", "ko"
    base = str(tk).replace("-", ".").upper()
    if base in ("VOO",):
        return "Vanguard S&P 500 ETF VOO", "en"
    if base in ("BRK.B", "BRKB"):
        return "Berkshire Hathaway stock", "en"
    return "{} stock analyst price target".format(base), "en"


def collect(holdings):
    """시장·환율·종목 헤드라인을 병렬로 모은다. holdings: [{"ticker","name","market"}] -> dict"""
    from concurrent.futures import ThreadPoolExecutor
    jobs = [("kr_mkt", "코스피 증시 외국인 반도체", "ko", 6), ("us_mkt", "Wall Street stocks Nasdaq S&P 500 Nvidia AI", "en", 7),
            ("macro", "Federal Reserve FOMC rate inflation Treasury yield", "en", 5), ("fx", "원달러 환율 전망", "ko", 6), ("fx_en", "USD KRW won dollar outlook forecast", "en", 4),
            ("ib_us", "S&P 500 target " + INSTITUTIONS_US, "en", 5), ("ib_kr", "코스피 전망 " + INSTITUTIONS_KR, "ko", 5)]
    for h in holdings:
        q, lang = _sym_query(h["ticker"], h["name"], h.get("market"))
        jobs.append(("t:" + h["ticker"], q, lang, 6))
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda j: fetch(j[1], j[2], j[3]), jobs))
    d = {j[0]: r for j, r in zip(jobs, res)}
    total = sum(len(v) for v in d.values())
    market = {"kr": d["kr_mkt"], "us": d["us_mkt"], "macro": d["macro"], "institutions_us": d["ib_us"], "institutions_kr": d["ib_kr"]}
    fx = {"ko": d["fx"], "en": d["fx_en"]}
    tickers = [{"ticker": h["ticker"], "name": h["name"], "headlines": d.get("t:" + h["ticker"], [])} for h in holdings]
    srcs = []
    for lst in list(market.values()) + list(fx.values()) + [t["headlines"] for t in tickers]:
        for x in lst:
            srcs.append({"title": "{} {}".format(x["source"], x["date"]).strip(), "uri": x["link"], "name": x["source"]})
    return {"market": market, "fx": fx, "tickers": tickers, "total": total, "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "how": "구글 뉴스 RSS를 앱이 직접 수집한 헤드라인(제목·매체·날짜)입니다. 기사 본문은 읽지 못했습니다."}, srcs


def headlines_for(sym, name, mkt, n=8):
    """종목 1개의 헤드라인(개별 AI 분석용)."""
    q, lang = _sym_query(sym, name, mkt)
    return fetch(q, lang, n)
