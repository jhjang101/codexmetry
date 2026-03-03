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
    Updates PO status based on the 3-Stage Lifecycle:
    1. 'open'      -> Real items remain to be invoiced.
    2. 'invoiced'  -> Items fully invoiced, but invoices are unpaid.
    3. 'completed' -> Items fully invoiced AND all invoices are paid.
    """
    if not po_id:
        return False

    # 1. Fetch the augmented PO (provides .remaining_items and .invoices)
    po = PurchaseOrderService.get_po_by_id(po_id)
    if not po or not po.is_active:
        return False
    
    # 2. Check Physical Fulfillment
    # Ignore 'Applied Deposit' system product for fulfillment logic
    real_items_left = [item for item in po.remaining_items if not item['product'].is_system] # type: ignore

    if len(real_items_left) > 0:
        new_status = 'open'
    else:
        # 3. Physical fulfillment complete -> Check Invoice Payment Status
        # Look for any active invoices that are still 'open'
        open_invoices = [invoice for invoice in po.invoices if invoice.is_active and invoice.status == 'open']

        if open_invoices:
            new_status = 'invoiced'
        else:
            new_status = 'completed'

    # 3. Update and Commit if the status changed
    if po.status != new_status:
        po.status = new_status
        db.session.commit()
        return True
        
    return False