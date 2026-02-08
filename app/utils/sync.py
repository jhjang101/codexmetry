from ..extensions import db
from ..models import SettingsMetadata
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService

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

def sync_po_status(po_id: int | None):
    """
    Updates PO status based on whether all items are fully invoiced.
    Uses PurchaseOrderService.get_po_by_id to leverage existing aggregation.
    """
    if not po_id:
        return False

    # 1. Fetch the augmented PO (this already calculates .remaining_items)
    po = PurchaseOrderService.get_po_by_id(po_id)
    if not po or not po.is_active:
        return False

    # 2. Apply logic: If the list of items needing invoicing is empty, it's done.
    # We use len(po.remaining_items) == 0 as our "Fulfillment" check.
    new_status = 'completed' if len(po.remaining_items) == 0 else 'open' # type: ignore

    # 3. Update and Commit if the status changed
    if po.status != new_status:
        po.status = new_status
        db.session.commit()
        return True
        
    return False