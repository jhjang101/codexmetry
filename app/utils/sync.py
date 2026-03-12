from ..extensions import db
from ..models import SettingsMetadata
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.audit_service import AuditLogService

def sync_invoice_status(invoice, old_status: str):
    """
    Brain: Enforces status rules on a Invoice object.
    Promotes 'draft' to 'open/completed' if payment.
    """
    if not invoice or not invoice.is_active:
        return False
    
    # 1. Fetch the Threshold from settings
    settings = db.session.get(SettingsMetadata, 1)
    threshold = settings.invoice_threshold if settings else 0

    # 2. Determine the target status based on financial reality
    if invoice.balance <= threshold:
        target_status = 'completed'
    else:
        # If not fully paid, it's either 'open' or it stays 'draft'
        # Rule: If it was already 'open' or 'completed', it must stay 'open'.
        # Rule: If it's a 'draft' and this sync was triggered (by payment or print), 
        # it is promoted to 'open'.
        target_status = 'open' if old_status != 'draft' else 'draft'
        
        # Override: If it's a draft but has a linked payment, promote it
        if old_status == 'draft' and any(p.is_active for p in invoice.payments):
            target_status = 'open'
    
    # 3. Apply Change
    if invoice.status != target_status:
        invoice.status = target_status

    # 4. Final Audit Check: Did the status change from the BEGINNING of the request?
    if invoice.status != old_status:
        AuditLogService.record(
            target_id=invoice.id,
            target_type='Invoice',
            action='UPDATE',
            old_data={'status': old_status},
            new_data={'status': invoice.status}
        )
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
        # 1. Capture old status for the forensic record
        old_status = po.status
        # 2. Apply change
        po.status = new_status
        # 3. Record Audit
        # We use 'UPDATE' but the changes dict makes it clear it was a status flip
        AuditLogService.record(
            target_id=po.id,
            target_type='PurchaseOrder',
            action='UPDATE',
            old_data={'status': old_status},
            new_data={'status': new_status}
        )

        db.session.commit()
        return True
        
    return False