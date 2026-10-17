"""Deterministic solver for the DSO 429 hourly quiz.

Each question type is a regex plus a formula. The formula produces a target
value, and the option closest to it wins. Questions no pattern recognises
return None so the caller can fall back to an LLM or flag them.
"""

import re
from datetime import date, timedelta

NUM = r"\$?(-?[\d,]+(?:\.\d+)?)"
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def num(s):
    return float(s.replace(",", "").replace("$", "").replace("%", "").strip())


def parse_option_number(opt):
    m = re.search(r"-?[\d,]*\.?\d+", opt.replace("$", ""))
    return num(m.group(0)) if m else None


def parse_date(s):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", s)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))


def decimals(opt):
    m = re.search(r"\.(\d+)", opt)
    return len(m.group(1)) if m else 0


def closest(target, options):
    """Index of the option that equals target at that option's displayed precision.

    Falls back to the nearest option within 0.5% when none matches exactly, and
    to None when nothing is close, so a misparsed question is flagged, not guessed.
    """
    exact = [i for i, opt in enumerate(options)
             if parse_option_number(opt) is not None
             and abs(parse_option_number(opt) - target) <= 0.5 * 10 ** -decimals(opt) + 1e-9]
    if len(exact) == 1:
        return exact[0]
    best, best_err = None, float("inf")
    for i, opt in enumerate(options):
        v = parse_option_number(opt)
        if v is None:
            continue
        err = abs(v - target) / max(abs(target), 1e-9)
        if err < best_err:
            best, best_err = i, err
    return best if best_err < 0.005 else None


def solve_value(q):
    """Return ('num', value) or ('date', date) for a recognised question, else None."""
    t = " ".join(q.split())
    tl = t.lower()

    # Discount: "An item listed at $X is discounted by P%. What is the sale price?"
    m = re.search(rf"listed at {NUM} is discounted by {NUM}%", t)
    if m and "sale price" in tl:
        return "num", num(m.group(1)) * (1 - num(m.group(2)) / 100)

    # Revenue: "sells N units at $P each. What is total revenue?"
    m = re.search(rf"sells {NUM} units at {NUM} each", t)
    if m and "revenue" in tl:
        return "num", num(m.group(1)) * num(m.group(2))

    # FX: "$X is converted to euros at R euros per US dollar"
    m = re.search(rf"{NUM} is converted to (\w+) at {NUM} (\w+) per (?:US )?dollar", t)
    if m:
        return "num", num(m.group(1)) * num(m.group(3))
    m = re.search(rf"{NUM} is converted to dollars at {NUM} \w+ per (?:US )?dollar", t)
    if m:
        return "num", num(m.group(1)) / num(m.group(2))

    # Weighted average order value across two regions.
    m = re.search(rf"had {NUM} orders averaging {NUM}.*?had {NUM} orders averaging {NUM}", t)
    if m:
        n1, a1, n2, a2 = (num(g) for g in m.groups())
        return "num", (n1 * a1 + n2 * a2) / (n1 + n2)

    # Gross margin %.
    m = re.search(rf"{NUM} in revenue against {NUM} in cost of goods sold", t)
    if m and "gross margin" in tl:
        rev, cogs = num(m.group(1)), num(m.group(2))
        return "num", (rev - cogs) / rev * 100

    # Compound interest, annual.
    m = re.search(rf"investment of {NUM} grows at {NUM}% compounded annually.*?after {NUM} years?", t)
    if m:
        p, r, n = (num(g) for g in m.groups())
        return "num", p * (1 + r / 100) ** n

    # Break-even units.
    m = re.search(rf"Fixed costs are {NUM}.*?sells for {NUM} with a variable cost of {NUM}", t)
    if m:
        f, price, vc = (num(g) for g in m.groups())
        return "num", round(f / (price - vc))

    # Probability of drawing a category: "holds 25 billing tickets, 6 technical tickets and 10 account tickets ... a billing ticket"
    m = re.search(r"holds (.*?)\. If one is drawn.*?probability it is an? (\w+)", t)
    if m:
        counts = {k.lower(): num(v) for v, k in re.findall(r"(\d[\d,]*) (\w+)", m.group(1))}
        want = m.group(2).lower()
        if want in counts:
            return "num", counts[want] / sum(counts.values()) * 100

    # Percentage change.
    m = re.search(rf"moved from {NUM} to {NUM}", t)
    if m and "percentage change" in tl:
        a, b = num(m.group(1)), num(m.group(2))
        return "num", (b - a) / a * 100

    # Ratio split.
    m = re.search(rf"{NUM} .*? is split between two \w+ in the ratio (\d+):(\d+)\. What does the (first|second)", t)
    if m:
        total, x, y = num(m.group(1)), num(m.group(2)), num(m.group(3))
        share = x if m.group(4) == "first" else y
        return "num", total * share / (x + y)

    # Next value in a sequence (arithmetic or geometric).
    m = re.search(r"series runs ([\d,.\s-]+?)\. If the pattern continues", t)
    if m:
        seq = [num(s) for s in re.findall(r"-?\d+(?:\.\d+)?", m.group(1).replace(",", " "))]
        if len(seq) >= 3:
            diffs = {round(b - a, 9) for a, b in zip(seq, seq[1:])}
            if len(diffs) == 1:
                return "num", seq[-1] + diffs.pop()
            if all(a != 0 for a in seq[:-1]):
                ratios = {round(b / a, 9) for a, b in zip(seq, seq[1:])}
                if len(ratios) == 1:
                    return "num", seq[-1] * ratios.pop()

    # Settlement date: "signed on D Month YYYY has a N-day settlement period"
    m = re.search(r"signed on (\d{1,2} [A-Za-z]+ \d{4}) has an? (\d+)-day", t)
    if m:
        start = parse_date(m.group(1))
        if start:
            return "date", start + timedelta(days=int(m.group(2)))

    return None


def solve(question, options):
    """Return 'A'-'D', or None if the question is not recognised or no option fits."""
    res = solve_value(question)
    if res is None:
        return None
    kind, val = res
    if kind == "date":
        for i, opt in enumerate(options):
            if parse_date(opt) == val:
                return "ABCD"[i]
        return None
    i = closest(val, options)
    return "ABCD"[i] if i is not None else None
