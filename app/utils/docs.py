import zoneinfo
from datetime import datetime
from sqlalchemy import select, exists, func, or_
from ..extensions import db
from ..models import SettingsMetadata

def _calculate_v_digit(payload: str) -> str:
    """Helper: Sum of digits mod 10 checksum."""
    total = sum(int(digit) for digit in payload)
    return str(total % 10)

def generate_doc_number(prefix: str, model: type, column_name: str) -> str:
    """
    Brain: Generates a strictly numeric unique identifier following YYQSSSV.
    Efficiency: Starts sequence from current database count to minimize queries.
    Safety: Hard ceiling at 3x block capacity to prevent infinite loops.
    """
    # 1. Get Environment Context
    settings = db.session.get(SettingsMetadata, 1)
    tz_name = settings.timezone if settings else 'America/Chicago'
    padding = settings.doc_padding if settings else 3
    
    now_biz = datetime.now(zoneinfo.ZoneInfo(tz_name))
    year_str = now_biz.strftime('%y')
    q_base = (now_biz.month - 1) // 3 + 1
    
    # 2. Performance: Calculate the starting point (N)
    # Count existing records for this Year + (Standard Q1-4, Overflow Q5-6, or Emergency 9)
    q_std = f"{year_str}{q_base}%"
    q_ovr = f"{year_str}{q_base + 4}%"
    q_emg = f"{year_str}9%"
    
    count_stmt = select(func.count()).select_from(model).where(
        or_(
            getattr(model, column_name).like(q_std),
            getattr(model, column_name).like(q_ovr),
            getattr(model, column_name).like(q_emg)
        )
    )
    current_count = db.session.execute(count_stmt).scalar() or 0
    
    # 3. The Gap-Jumping Loop
    max_per_block = 10**padding
    safety_ceiling = max_per_block * 3 
    
    # REFINED: Start at count (e.g. 0) to ensure sequence density
    n = current_count 
    while n <= safety_ceiling:
        # Determine the active Q digit based on sequence volume
        if n < max_per_block:
            active_q = q_base
        elif n < (max_per_block * 2):
            active_q = q_base + 4
        else:
            active_q = 9
            
        # Format SSS (Sequence part)
        sss_val = n % max_per_block
        sss_str = str(sss_val).zfill(padding)
        
        # Assemble Payload and Checksum
        payload = f"{year_str}{active_q}{sss_str}"
        candidate = f"{payload}{_calculate_v_digit(payload)}"
        
        # 4. Physical Uniqueness Verification
        # Verifies if this candidate is free (handling manual entry gaps)
        check_stmt = select(exists().where(getattr(model, column_name) == candidate))
        is_taken = db.session.execute(check_stmt).scalar()
        
        if not is_taken:
            return candidate
            
        n += 1

    # 5. Safety Break
    raise RuntimeError(
        f"Critical Error: Document numbering capacity exhausted for {year_str} Q{q_base}. "
        f"Current padding of {padding} is insufficient. Update 'Doc Padding' in Settings."
    )



# def generate_doc_number(prefix: str, model: type, column_name: str) -> str:
#     """
#     Generates a document number following the format: PREFIX-YY0000.
#     Example: CDX-260001, Q-260001, EXP-260001
#     """
#     # 1. Get Settings (We need this for padding AND timezone)
#     settings = db.session.get(SettingsMetadata, 1)
    
#     # 2. Use Business Timezone to get the year (Matches layout.html)
#     tz_name = settings.timezone if settings else 'America/Chicago'
#     now_biz = datetime.now(zoneinfo.ZoneInfo(tz_name))
#     year_str = now_biz.strftime('%y')

#     # 3. Get padding
#     padding = settings.doc_padding if settings else 4

#     # 4. Count records for THIS business year
#     search_pattern = f"{prefix}-{year_str}%"
#     stmt = select(func.count()).select_from(model).where(
#         getattr(model, column_name).like(search_pattern)
#     )
#     count = db.session.execute(stmt).scalar() or 0

#     # 5. Return formatted string
#     return f"{prefix}-{year_str}{(count + 1):0{padding}d}"
