"""Currency formatting and live USD/INR exchange rate lookup."""
import streamlit as st
import requests

FALLBACK_USD_INR_RATE = 87.5


@st.cache_data(ttl=3600, show_spinner=False)
def get_usd_inr_rate():
    """Returns (rate, is_live). Falls back to a static estimate if the API is unreachable."""
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
        resp.raise_for_status()
        rate = resp.json()["rates"]["INR"]
        return float(rate), True
    except Exception:
        return FALLBACK_USD_INR_RATE, False


def symbol(currency):
    return "₹" if currency == "INR" else "$"


def to_lakh_crore(value):
    """Format a rupee value using Indian Lakh/Crore notation, e.g. 1,49,000 -> '1.49 L'."""
    value = abs(value)
    if value >= 1_00_00_000:
        return f"{value / 1_00_00_000:.2f} Cr"
    if value >= 1_00_000:
        return f"{value / 1_00_000:.2f} L"
    return f"{value:,.0f}"


def format_amount(value, currency, compact=False):
    """Format a plain number as currency. `compact=True` uses Lakh/Crore for INR."""
    if currency == "INR":
        if compact:
            return f"₹{to_lakh_crore(value)}"
        return f"₹{value:,.0f}"
    return f"${value:,.2f}"
