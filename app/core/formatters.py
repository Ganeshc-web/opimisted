def fmt_display(value: float) -> float:
    """Round to 2dp for API response display only."""
    return round(abs(value), 2)


def fmt_inr(value: float) -> str:
    """Format as Indian currency string."""
    v = abs(value)
    if v >= 1e7:
        return f"₹{v/1e7:.2f} Cr"
    elif v >= 1e5:
        return f"₹{v/1e5:.2f} L"
    return f"₹{v:,.0f}"


def fmt_inr_report(value: float) -> str:
    """Indian lakh/crore grouping with full digits for Word report placeholders."""
    v = int(round(abs(value)))
    s = str(v)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups = []
    while rest:
        groups.append(rest[-2:])
        rest = rest[:-2]
    groups.reverse()
    return "₹" + ",".join(groups + [last3])


def fmt_inr_report_blank(value: float | None) -> str:
    """Like fmt_inr_report, but leave the placeholder empty when value is missing or zero."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if amount == 0:
        return ""
    return fmt_inr_report(amount)


def fmt_response(raw: float) -> dict:
    """Every money field in API response has display and raw."""
    return {
        "display": fmt_display(raw),
        "raw": abs(raw),
        "inr": fmt_inr(raw)
    }
