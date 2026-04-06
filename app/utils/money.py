# --- USD JINJA FILTER HELPERS ---

def format_usd(cents: int) -> str:
    """Converts integer cents to string $1,234.56"""
    if cents is None:
        return "$0.00"
    usd = cents / 100
    return f"${usd:,.2f}"

def parse_to_cents(usd_string: str) -> int:
    """
    Converts string 1,234.56 to integer cents
    handling negatives and parentheses.
    """
    if not usd_string:
        return 0
    try:
        # 1. Clean the string
        clean_str = str(usd_string).replace('$', '').replace(',', '').strip()

        # 2. Handle Accounting Parentheses: (100.00) -> -100.00
        if clean_str.startswith('('):
            clean_str = '-' + clean_str[1:-1]

        # 3. GUARD: Incomplete Entry Check (Crucial for HTMX triggers)
        # If the user has only typed the negative sign or start of parenthesis, 
        # return 0 so the calculation doesn't crash while they type.
        if clean_str in ["-", "(", "()", "($", "-$"]:
            return 0

        # 4. Convert to cents
        dollars = float(clean_str)
        cents = int(round(dollars * 100))
        return cents
    
    except (ValueError, TypeError):
        raise ValueError(f"Invalid number format: {usd_string}")
