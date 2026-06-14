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


def fmt_response(raw: float) -> dict:
    """Every money field in API response has display and raw."""
    return {
        "display": fmt_display(raw),
        "raw": abs(raw),
        "inr": fmt_inr(raw)
    }
