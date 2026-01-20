import zoneinfo
from datetime import datetime
from sqlalchemy import select, func
from ..extensions import db
from ..models import SettingsMetadata

def generate_doc_number(prefix: str, model: type, column_name: str) -> str:
    """
    Generates a document number following the format: PREFIX-YY0000.
    Example: CDX-260001, Q-260001, EXP-260001
    """
    # 1. Get Settings (We need this for padding AND timezone)
    settings = db.session.get(SettingsMetadata, 1)
    
    # 2. Use Business Timezone to get the year (Matches layout.html)
    tz_name = settings.timezone if settings else 'America/Chicago'
    now_biz = datetime.now(zoneinfo.ZoneInfo(tz_name))
    year_str = now_biz.strftime('%y')

    # 3. Get padding
    padding = settings.doc_padding if settings else 4

    # 4. Count records for THIS business year
    search_pattern = f"{prefix}-{year_str}%"
    stmt = select(func.count()).select_from(model).where(
        getattr(model, column_name).like(search_pattern)
    )
    count = db.session.execute(stmt).scalar() or 0

    # 5. Return formatted string
    return f"{prefix}-{year_str}{(count + 1):0{padding}d}"
