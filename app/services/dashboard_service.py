from datetime import datetime, date
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, or_, and_
from ..extensions import db
from ..models import (
    PurchaseOrder, Invoice, Payment, Expense, AuditLog, 
    SettingsMetadata, OrderRegistry, Client, Vendor
)
from .purchase_orders_service import PurchaseOrderService
from .invoices_service import InvoiceService

class DashboardService:

    @classmethod
    def get_dashboard_data(cls):
        """Brain: Orchestrates the full state of the business for the Dashboard."""
        # 1. Date Context (Timezone Aware)
        settings = db.session.get(SettingsMetadata, 1)
        tz_name = settings.timezone if settings else 'America/Chicago'
        now = datetime.now(ZoneInfo(tz_name))
        
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # 2. Fetch KPIs
        kpis = {
            'backlog': cls._get_total_backlog(),
            'ar': cls._get_total_ar(),
            'mtd_cash': cls._get_net_cash(start_of_month, now),
            'ytd_cash': cls._get_net_cash(start_of_year, now)
        }

        # 3. Fetch Operational Tables (Limited to 15 rows)
        return {
            'kpis': kpis,
            'pos': cls._get_dashboard_pos(),
            'invoices': cls._get_dashboard_invoices(),
            'expenses': cls._get_recent_expenses(limit=10),
            'activity': cls._get_recent_activity(limit=10)
        }

    # --- PRIVATE HELPERS: KPI MATH ---

    @classmethod
    def _get_total_backlog(cls):
        """Calculates total unbilled revenue from all open POs."""
        # We call the existing search logic but for all open items
        pagination = PurchaseOrderService.get_all_with_search(page=1, per_page=1000)
        return sum(po.to_be_invoiced for po in pagination.items if po.status == 'open')

    @classmethod
    def _get_total_ar(cls):
        """Calculates total unpaid balance from all draft and open invoices."""
        pagination = InvoiceService.get_all_with_search(page=1, per_page=1000)
        return sum(inv.balance for inv in pagination.items if inv.status in ['draft', 'open'])

    @classmethod
    def _get_net_cash(cls, start_date, end_date):
        """Calculates Net Cash Flow: (Payments Received) - (Expenses Paid)."""
        pay_sum = db.session.execute(
            select(func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date >= start_date.date())
        ).scalar() or 0

        exp_sum = db.session.execute(
            select(func.sum(Expense.total_amount))
            .where(Expense.is_active == True, Expense.expense_date >= start_date.date())
        ).scalar() or 0

        return pay_sum - exp_sum

    # --- PRIVATE HELPERS: TABLE FETCHING ---

    @classmethod
    def _get_dashboard_pos(cls):
        """All 'open' POs + Last 5 'completed' POs. Max 15."""
        open_pos = PurchaseOrderService.get_all_with_search(page=1, per_page=15).items
        # Filter for open
        display = [po for po in open_pos if po.status == 'open']
        # If we have space, get invoiced
        if len(display) < 15:
            invoiced = db.session.execute(
                select(PurchaseOrder).where(PurchaseOrder.status == 'invoiced', PurchaseOrder.is_active == True)
                .order_by(PurchaseOrder.po_date.desc())
            ).scalars().all()
            display.extend(invoiced)
        # If we still have space, get completed
        if len(display) < 15:
            completed = db.session.execute(
                select(PurchaseOrder).where(PurchaseOrder.status == 'completed', PurchaseOrder.is_active == True)
                .order_by(PurchaseOrder.po_date.desc())
            ).scalars().all()
            display.extend(completed)

        return display[:15]

    @classmethod
    def _get_dashboard_invoices(cls):
        """All 'draft/open' Invoices + Last 5 'completed'. Max 15."""
        active_invs = InvoiceService.get_all_with_search(page=1, per_page=15).items
        display = [inv for inv in active_invs if inv.status in ['draft', 'open']]
        if len(display) < 15:
            completed = db.session.execute(
                select(Invoice).where(Invoice.status == 'completed', Invoice.is_active == True)
                .order_by(Invoice.invoice_date.desc()).limit(5)
            ).scalars().all()
            display.extend(completed)
        return display[:15]

    @classmethod
    def _get_recent_expenses(cls, limit=10):
        return db.session.execute(
            select(Expense).options(db.joinedload(Expense.vendor))
            .where(Expense.is_active == True)
            .order_by(Expense.expense_date.desc()).limit(limit)
        ).scalars().all()

    @classmethod
    def _get_recent_activity(cls, limit=10):
        return db.session.execute(
            select(AuditLog).options(db.joinedload(AuditLog.user))
            .order_by(AuditLog.timestamp.desc()).limit(limit)
        ).scalars().all()