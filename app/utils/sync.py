from ..extensions import db
from ..models import SettingsMetadata
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.audit_service import AuditLogService

def sync_invoice_status(invoice, old_status: str):
    """
    Enforces status transitions based on user intent and financial reality.
    1. Always honor manual user overrides.
    2. Auto-complete if fully paid.
    3. Auto-promote to 'open' if partially paid.
    4. Auto-promote to 'open' if printed.
    """
    if not invoice or not invoice.is_active:
        return False
    
    # 1. Fetch the Threshold from settings
    settings = db.session.get(SettingsMetadata, 1)
    threshold = settings.invoice_threshold if settings else 0

    is_fully_paid = invoice.balance <= threshold
    has_payments = any(p.is_active for p in invoice.payments)

    # RULE 1: If old_status != current status, the user manually overrode it.
    # We honor that choice and do not perform auto-logic.
    if old_status != invoice.status:
        new_status = invoice.status
    else:
        # User did NOT override, apply automated rules:
        
        # RULE 2: If fully paid, move to completed.
        if is_fully_paid:
            new_status = 'completed'
        
        # RULE 3: If not fully paid but has payments, move to open.
        elif has_payments:
            new_status = 'open'

        # RULE 4: Otherwise, maintain the current state (stays draft or stays open).
        else:
            new_status = old_status
        
    # Apply Change
    if invoice.status != new_status:
        invoice.status = new_status

    # Final Audit Check: Did the status change from the BEGINNING of the request?
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
        open_invoices = [invoice for invoice in po.invoices if invoice.is_active and invoice.status != 'completed']

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