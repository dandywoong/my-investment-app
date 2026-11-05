# -*- coding: utf-8 -*-
"""planner.py — 종합 점수 기반 현금 배분 (검증 전 규칙). 모든 금액은 원화 환산 기준.

흐름: ①베팅 슬롯(조정 시 1주 규칙) → ②종합 점수로 후보를 걸러 순위 → ③점수가 높을수록 오늘 투입 비율을 키우고(낮으면 현금 보유)
      ④점수에 비례해 종목별 금액 배분(한 종목 최대 40%) → ⑤핵심 장기는 1차 가격대에 들어왔을 때만 지금 실행, 아니면 대기 자금.
"""
THRESH = 3.0        # 이 점수 미만은 신규 매수 후보에서 제외
CAP_SHARE = 0.40    # 한 종목이 오늘 투입금에서 차지할 수 있는 최대 비율


def _avg_text(avg, ak, qty, amt, nq):
    if nq <= 0:
        return "-"
    return "{:,.2f} → {:,.2f}".format(avg / ak, (qty * avg + amt) / nq / ak)


def _waterfill(scores, cap):
    """점수 비례 배분. 상한을 넘는 종목은 상한으로 고정하고 나머지를 다시 나눈다."""
    n = len(scores)
    share = [0.0] * n
    free = set(range(n))
    left = 1.0
    for _ in range(n + 1):
        tot = sum(scores[i] for i in free)
        if tot <= 0 or not free:
            break
        over = [i for i in free if left * scores[i] / tot > cap + 1e-12]
        if not over:
            for i in free:
                share[i] = left * scores[i] / tot
            break
        for i in over:
            share[i] = cap
            left -= cap
            free.discard(i)
    return share


def plan_smart(items, cash, first_pct=50, reserve_pct=0, bet_cap_pct=10.0, fmt_pct=lambda x: "-"):
    """items: 원화 환산된 종목 목록(_k=환율계수, _cur=원통화, zone=원통화 1차 매수구간, score=signals.score_item 결과).
    -> dict(budget, deploy, ratio, rows, wait, hold_cash, reserved, notes, ranking)"""
    budget = max(cash * (1 - reserve_pct / 100.0), 0.0)
    remaining = budget
    rows, wait, notes = [], [], []
    mine = [i for i in items if i.get("price")]

    # 1) 베팅 슬롯
    for i in [x for x in mine if x["mode"] == "베팅"]:
        fails = []
        sc = i.get("score") or {}
        if i["sv_val"] == "훼손":
            fails.append("기업 상태 훼손")
        if i["sv_val"] == "미확인":
            fails.append("기업 상태 미기록")
        if i.get("outlook") == "부정":
            fails.append("업황 부정")
        if i.get("dd60") is None or i["dd60"] > -0.10:
            fails.append("조정 조건 미충족(60일 고점 대비 -10% 이하일 때만, 현재 {})".format(fmt_pct(i.get("dd60"))))
        if i.get("weight") is not None and i["weight"] * 100 >= bet_cap_pct:
            fails.append("베팅 비중 한도 {:.0f}% 도달".format(bet_cap_pct))
        if i["price"] > remaining:
            fails.append("현금 부족(1주 약 {:,.0f}원)".format(i["price"]))
        if fails:
            wait.append({"종목": i["name"], "전략": "베팅 1주 추가", "상태": "보류", "점수": round(sc.get("total", 0), 1), "이유/조건": " · ".join(fails)})
        else:
            nq = i["qty"] + 1
            rows.append({"순위": "-", "종목": i["name"], "전략": "베팅 1주 추가", "점수": round(sc.get("total", 0), 1), "금액(원)": round(i["price"]), "수량": 1.0,
                         "체결 후 평단": _avg_text(i["avg"], i.get("_k", 1.0), i["qty"], i["price"], nq), "통화": i.get("_cur", "KRW"),
                         "근거": "조정 구간(60일 고점 대비 {}) · 기업 상태 {}".format(fmt_pct(i["dd60"]), i["sv_val"])})
            remaining -= i["price"]

    # 2) 후보 선정 (베팅 제외)
    cands, excluded = [], []
    for i in mine:
        if i["mode"] == "베팅":
            continue
        sc = i.get("score")
        if not sc:
            excluded.append((i["name"], "점수 계산 불가"))
        elif sc["gate"]:
            excluded.append((i["name"], sc["gate"]))
        elif sc["total"] < THRESH:
            excluded.append((i["name"], "점수 {:.1f} < 기준 {:.0f} (지금은 살 이유가 약함)".format(sc["total"], THRESH)))
        else:
            cands.append(i)
    cands.sort(key=lambda x: -x["score"]["total"])
    ranking = []
    for r, i in enumerate(sorted([x for x in mine if x["mode"] != "베팅" and x.get("score")], key=lambda x: -x["score"]["total"]), 1):
        ranking.append((r, i))

    # 3) 오늘 투입 비율: 상위 후보 점수가 높을수록 크게, 낮으면 현금 보유
    if cands:
        top = [c["score"]["total"] for c in cands[:3]]
        m = sum(top) / len(top)
        ratio = max(0.3, min(1.0, 0.3 + (m - THRESH) / 9.0 * 0.7))
    else:
        m, ratio = 0.0, 0.0
    deploy = remaining * ratio
    hold_cash = remaining - deploy
    if cands:
        notes.append("상위 후보 평균 점수 {:.1f} → 남은 현금의 {:.0%}를 오늘 투입, {:.0%}는 더 좋은 기회를 위해 보유합니다.".format(m, ratio, 1 - ratio))

    # 4) 점수 비례 배분 (한 종목 최대 40%)
    shares = _waterfill([max(c["score"]["total"] - 2.0, 0.1) for c in cands], CAP_SHARE if len(cands) >= 3 else (0.6 if len(cands) == 2 else 1.0)) if cands else []
    reserved, used = 0.0, 0.0
    for rank, (c, sh) in enumerate(zip(cands, shares), 1):
        alloc = deploy * sh
        sc = c["score"]
        top_why = sorted(((v[0], k) for k, v in sc["parts"].items()), reverse=True)
        why = " · ".join("{} {:+.1f}".format(k, p) for p, k in top_why if abs(p) >= 1)[:90]
        pk = c["price"] / c.get("_k", 1.0)
        # 핵심 장기: 1차 가격대 확인
        if c["mode"] == "핵심 장기" and c.get("zone") and pk > c["zone"][1]:
            reserved += alloc
            wait.append({"종목": c["name"], "전략": "핵심 분할 1차(대기)", "상태": "가격 대기", "점수": round(sc["total"], 1),
                         "이유/조건": "1차 구간 {:,.0f}~{:,.0f} 진입 시 {:,.0f}원 투입 (현재가 대비 {:+.1f}%)".format(
                             c["zone"][0], c["zone"][1], alloc * first_pct / 100.0, (c["zone"][1] / pk - 1) * 100),
                         "통화": c.get("_cur", "KRW"), "_reserve": alloc})
            continue
        spend = alloc * (first_pct / 100.0) if c["mode"] == "핵심 장기" else alloc
        if c.get("_cur", "KRW") == "KRW":
            qty = float(int(spend // c["price"]))
            if qty < 1 and remaining - used >= c["price"] and alloc >= c["price"] * 0.5:
                qty = 1.0
            amt = qty * c["price"]
        else:
            qty = round(spend / c["price"], 4)
            amt = qty * c["price"]
        if qty <= 0 or amt > remaining - used + 1e-6:
            wait.append({"종목": c["name"], "전략": "점수 상위(현금 부족)", "상태": "보류", "점수": round(sc["total"], 1),
                         "이유/조건": "배정액 {:,.0f}원으로는 1주(약 {:,.0f}원)를 살 수 없음".format(alloc, c["price"])})
            continue
        used += amt
        if c["mode"] == "핵심 장기" and alloc - amt > c["price"] * 0.5:
            reserved += alloc - amt
            wait.append({"종목": c["name"], "전략": "핵심 추가 분할(대기)", "상태": "추가 하락/기간 대기", "점수": round(sc["total"], 1),
                         "이유/조건": "2차 분할용 {:,.0f}원 대기 (더 내려오거나 며칠 지켜본 뒤)".format(alloc - amt), "통화": c.get("_cur", "KRW"), "_reserve": alloc - amt})
        nq = c["qty"] + qty
        rows.append({"순위": rank, "종목": c["name"], "전략": "핵심 분할 1차" if c["mode"] == "핵심 장기" else "적립 추가", "점수": round(sc["total"], 1),
                     "금액(원)": round(amt), "수량": qty, "체결 후 평단": _avg_text(c["avg"], c.get("_k", 1.0), c["qty"], amt, nq),
                     "통화": c.get("_cur", "KRW"), "근거": why})
    unspent = max(deploy - used - reserved, 0.0)
    for n_, why in excluded:
        wait.append({"종목": n_, "전략": "신규 매수 제외", "상태": "제외", "점수": "", "이유/조건": why})
    return dict(budget=budget, deploy=deploy, ratio=ratio, rows=rows, wait=wait, used=used + (budget - remaining),
                reserved=reserved, hold_cash=hold_cash + unspent, notes=notes, ranking=ranking)
