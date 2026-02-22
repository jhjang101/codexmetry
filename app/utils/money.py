# --- USD JINJA FILTER HELPERS ---

def format_usd(cents: int) -> str:
    """Converts integer cents to string $1,234.56"""
    if cents is None:
        return "$0.00"
    usd = cents / 100
    return f"${usd:,.2f}"

def parse_to_cents(usd_string: str) -> int:
    """Converts string 1,234.56 to integer cents"""
    if not usd_string:
        return 0
    try:
        # Remove $ and commas
        clean_str = str(usd_string).replace('$', '').replace(',', '').strip()
        dollars = float(clean_str)
        cents = int(round(dollars * 100))
        return cents
    except (ValueError, TypeError):
        raise ValueError(f"Invalid number format in one of the items.")
