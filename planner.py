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
    순위(점수) 높은 종목부터 차례로 처리한다. 남은 후보 점수 비율로 배정액을 다시 계산하고(재정규화),
    한국 주식은 정수 주 단위: 배정액이 1주보다 작아도 상위 3위 안이고 현금이 되면 1주를 먼저 확보한다.
    -> dict(rows 실행목록, board 우선순위 보드(전 종목), wait, reserved, hold_cash, used, ratio, notes, ranking)"""
    budget = max(cash * (1 - reserve_pct / 100.0), 0.0)
    left = budget                     # 아직 안 쓴 현금(대기 자금 제외)
    rows, wait, notes, board = [], [], [], {}
    mine = [i for i in items if i.get("price")]
    ak = lambda c: c.get("_k", 1.0)

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
        if i["price"] > left:
            fails.append("현금 부족(1주 약 {:,.0f}원)".format(i["price"]))
        if fails:
            board[i["name"]] = {"종목": i["name"], "점수": round(sc.get("total", 0), 1), "오늘 행동": "베팅 보류", "금액(원)": "", "수량": "", "사유": " · ".join(fails)}
        else:
            nq = i["qty"] + 1
            rows.append({"종목": i["name"], "전략": "베팅 1주 추가", "점수": round(sc.get("total", 0), 1), "금액(원)": round(i["price"]), "수량": 1.0,
                         "체결 후 평단": _avg_text(i["avg"], ak(i), i["qty"], i["price"], nq), "통화": i.get("_cur", "KRW"),
                         "근거": "조정 구간(60일 고점 대비 {}) · 기업 상태 {}".format(fmt_pct(i["dd60"]), i["sv_val"])})
            board[i["name"]] = {"종목": i["name"], "점수": round(sc.get("total", 0), 1), "오늘 행동": "✅ 베팅 1주 매수", "금액(원)": round(i["price"]), "수량": 1.0, "사유": "베팅 규칙 충족"}
            left -= i["price"]

    # 2) 후보 선정
    cands, ranked = [], []
    for i in mine:
        if i["mode"] == "베팅" or not i.get("score"):
            continue
        ranked.append(i)
    ranked.sort(key=lambda x: -x["score"]["total"])
    for i in ranked:
        sc = i["score"]
        if sc["gate"]:
            board[i["name"]] = {"종목": i["name"], "점수": round(sc["total"], 1), "오늘 행동": "⛔ 제외", "금액(원)": "", "수량": "", "사유": sc["gate"]}
        elif sc["total"] < THRESH:
            board[i["name"]] = {"종목": i["name"], "점수": round(sc["total"], 1), "오늘 행동": "⛔ 제외", "금액(원)": "", "수량": "",
                                "사유": "점수 {:.1f} < 기준 {:.0f} (지금은 살 이유가 약함)".format(sc["total"], THRESH)}
        else:
            cands.append(i)

    # 3) 오늘 투입 비율
    if cands:
        top = [c["score"]["total"] for c in cands[:3]]
        m = sum(top) / len(top)
        ratio = max(0.3, min(1.0, 0.3 + (m - THRESH) / 9.0 * 0.7))
        notes.append("상위 후보 평균 점수 {:.1f} → 남은 현금의 {:.0%}를 오늘 투입 대상으로 보고, {:.0%}는 더 좋은 기회를 위해 보유합니다.".format(m, ratio, 1 - ratio))
    else:
        ratio = 0.0
    rem_deploy = left * ratio
    reserved = 0.0

    # 4) 순위대로 처리 (남은 후보 점수 비율로 배정액을 다시 계산)
    for idx, c in enumerate(cands):
        sc = c["score"]
        rest = cands[idx:]
        wts = [max(x["score"]["total"] - 2.0, 0.1) for x in rest]
        share = wts[0] / sum(wts)
        if len(rest) >= 3:
            share = min(share, CAP_SHARE)
        alloc = rem_deploy * share
        pk = c["price"] / ak(c)
        top_why = sorted(((v[0], k) for k, v in sc["parts"].items()), reverse=True)
        why = " · ".join("{} {:+.1f}".format(k, p) for p, k in top_why if abs(p) >= 1)[:80]
        nm, rank = c["name"], idx + 1
        core = c["mode"] == "핵심 장기"
        if core and c.get("zone") and pk > c["zone"][1]:
            hold = min(alloc, left - reserved)
            reserved += hold
            rem_deploy = max(rem_deploy - hold, 0.0)
            cond = "1차 구간 {:,.0f}~{:,.0f} 진입 시 약 {:,.0f}원 투입 (현재가 대비 {:+.1f}%)".format(c["zone"][0], c["zone"][1], hold * first_pct / 100.0, (c["zone"][1] / pk - 1) * 100)
            wait.append({"종목": nm, "전략": "핵심 분할 1차(대기)", "상태": "가격 대기", "점수": round(sc["total"], 1), "이유/조건": cond, "통화": c.get("_cur", "KRW")})
            board[nm] = {"종목": nm, "점수": round(sc["total"], 1), "오늘 행동": "⏳ 가격 대기", "금액(원)": round(hold), "수량": "", "사유": cond}
            continue
        spend = alloc * (first_pct / 100.0) if core else alloc
        avail = left - reserved
        forced = False
        if c.get("_cur", "KRW") == "KRW":
            qty = float(int(spend // c["price"]))
            if qty < 1 and c["price"] <= avail and (rank <= 3 or spend >= 0.6 * c["price"]):
                qty, forced = 1.0, True
        else:
            qty = round(spend / c["price"], 4)
        amt = qty * c["price"]
        if qty <= 0 or amt > avail + 1e-6:
            need = c["price"] - avail
            reason = ("현금 부족: 1주 약 {:,.0f}원, 쓸 수 있는 현금 {:,.0f}원".format(c["price"], max(avail, 0)) + (" (약 {:,.0f}원 더 필요)".format(need) if need > 0 else ""))
            if c.get("_cur", "KRW") == "KRW" and qty <= 0 and c["price"] <= avail:
                reason = "배정액 {:,.0f}원이 1주(약 {:,.0f}원)보다 작고 상위 3위 밖이라 보류".format(spend, c["price"])
            wait.append({"종목": nm, "전략": "점수 상위(보류)", "상태": "보류", "점수": round(sc["total"], 1), "이유/조건": reason, "통화": c.get("_cur", "KRW")})
            board[nm] = {"종목": nm, "점수": round(sc["total"], 1), "오늘 행동": "⛔ 현금 부족" if "현금 부족" in reason else "⏸ 보류", "금액(원)": "", "수량": "", "사유": reason}
            continue
        left -= amt
        rem_deploy = max(rem_deploy - amt, 0.0)
        nq = c["qty"] + qty
        rows.append({"종목": nm, "전략": "핵심 분할 1차" if core else "적립 추가", "점수": round(sc["total"], 1), "금액(원)": round(amt), "수량": qty,
                     "체결 후 평단": _avg_text(c["avg"], ak(c), c["qty"], amt, nq), "통화": c.get("_cur", "KRW"),
                     "근거": ("[1주 우선 확보] " if forced else "") + why})
        board[nm] = {"종목": nm, "점수": round(sc["total"], 1), "오늘 행동": "✅ 매수 {}".format("1주" if c.get("_cur", "KRW") == "KRW" and qty == 1 else "{:g}주".format(qty)),
                     "금액(원)": round(amt), "수량": qty, "사유": ("[1주 우선 확보] " if forced else "") + why}

    # 5) 순서·정리
    order = {i["name"]: r for r, i in enumerate(sorted([x for x in mine if x["mode"] != "베팅" and x.get("score")], key=lambda x: -x["score"]["total"]), 1)}
    rows.sort(key=lambda r: -float(r["점수"]))
    for n, r in enumerate(rows, 1):
        r["행동순서"] = n
    rows = [{"행동순서": r.pop("행동순서"), **r} for r in rows]
    board_rows = []
    for name, b in sorted(board.items(), key=lambda kv: order.get(kv[0], 0)):
        board_rows.append({"종합순위": order.get(name, "-"), **b})
    used = budget - left
    return dict(budget=budget, ratio=ratio, rows=rows, board=board_rows, wait=wait, used=used, reserved=reserved,
                hold_cash=left - reserved, notes=notes, ranking=[(order[i["name"]], i) for i in ranked])
