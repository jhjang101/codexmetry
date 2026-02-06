from ..extensions import db
from ..models import SettingsMetadata
from ..services.invoices_service import InvoiceService

def sync_invoice_status(invoice_id: int | None):
    """
    Updates Invoice status based on balance vs. threshold.
    """
    if not invoice_id:
        return
    
    # 1. Fetch the augmented invoice (includes .balance)
    invoice = InvoiceService.get_invoice_by_id(invoice_id)
    if not invoice or not invoice.is_active:
        return

    # 2. Fetch the Threshold from settings
    settings = db.session.get(SettingsMetadata, 1)
    threshold = settings.invoice_threshold if settings else 0

    # 3. Apply logic
    # Balance is (Total - Payments). If balance <= threshold, it's completed.
    if invoice.balance <= threshold: # type: ignore
        new_status = 'completed'
    else:
        new_status = 'open'

    # 4. Update and Commit if changed
    if invoice.status != new_status:
        invoice.status = new_status
        db.session.commit()
        return True
    return False