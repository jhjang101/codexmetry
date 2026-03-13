from ..extensions import db
from ..models import SettingsMetadata
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.audit_service import AuditLogService

def sync_invoice_status(invoice, original_status: str | None = None, proposed_status: str | None = None):
    """
    Determines the target status based on user intent and payment.
    1. Always honor manual user overrides.
    2. Auto-complete if fully paid.
    3. Auto-promote to 'open' if partially paid.
    Designed to be called in invoice and payment.
    Returns: {"before": str, "after": str}
    """
    if not original_status:
        original_status = 'draft'

    if not proposed_status:
        proposed_status = original_status

    if not invoice or not invoice.is_active:
        return {"before": original_status, "after": proposed_status}

    # 1. Fetch Threshold for financial checks
    settings = db.session.get(SettingsMetadata, 1)
    threshold = settings.invoice_threshold if settings else 0
    
    # 2. Evaluate Payment  (In-memory checks)
    is_fully_paid = invoice.balance <= threshold
    has_payments = any(p.is_active for p in invoice.payments)

    # RULE 1: Honor Manual User Override
    # If the status from the form differs from what was in the database,
    # the user's intent is the highest authority.
    if proposed_status and proposed_status != original_status:
        return {"before": original_status, "after": proposed_status}

    # If the user did NOT override, apply automated logic:
    
    # RULE 2: If fully paid, move to completed.
    if is_fully_paid:
        return {"before": original_status, "after": "completed"}

    # RULE 3: If not fully paid but has payments, move to open.
    if has_payments:
        return {"before": original_status, "after": "open"}

    # RULE 4: Otherwise, switch back to draft state.
    return {"before": original_status, "after": "draft"}

def sync_po_status(po_id: int):
    """
    Updates PO status based on the 3-Stage Lifecycle:
    1. 'open'      -> Real items remain to be invoiced.
    2. 'invoiced'  -> Items fully invoiced, but invoices are unpaid.
    3. 'completed' -> Items fully invoiced AND all invoices are paid.
    Explicitly called in invoice and payment. 
    Returns: {"before": str, "after": str}
    """
    # 1. Fetch the augmented PO (provides .remaining_items and .invoices)
    po = PurchaseOrderService.get_po_by_id(po_id)
    if not po or not po.is_active:
        return ""
    before = po.status
    
    # 2. Check Physical Fulfillment
    # Ignore 'Applied Deposit' system product for fulfillment logic
    real_items_left = [item for item in po.remaining_items if not item['product'].is_system] # type: ignore

    if len(real_items_left) > 0:
        new_status = 'open'
    else:
        # 3. Physical fulfillment complete -> Check Invoice Payment Status
        # Look for any active invoices that are still 'open'
        open_invoices = [invoice for invoice in po.invoices if invoice.is_active and invoice.status != 'completed']

        if open_invoices:
            new_status = 'invoiced'
        else:
            new_status = 'completed'

    # 3. Update if the status changed (commit in service layer)
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
        
    return {"before": before, "after": new_status}