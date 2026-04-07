from datetime import datetime, date
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, or_, and_
from ..extensions import db
from ..models import (
    PurchaseOrder, Invoice, Payment, Expense, AuditLog, 
    SettingsMetadata, OrderRegistry, Client, Vendor, Adjustment
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
            'to_be_invoiced': cls._get_total_to_be_invoiced(),
            'balance': cls._get_total_balance(),
            'mtd': cls._get_cash_summary(start_of_month, now),
            'ytd': cls._get_cash_summary(start_of_year, now)
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
    def _get_total_to_be_invoiced(cls):
        """Calculates total unbilled revenue from all open POs."""
        # We call the existing search logic but for all open items
        pagination = PurchaseOrderService.get_all_with_search(page=1, per_page=1000)
        return sum(po.to_be_invoiced for po in pagination.items if po.status == 'open')

    @classmethod
    def _get_total_balance(cls):
        """Calculates total unpaid balance from all draft and open invoices."""
        pagination = InvoiceService.get_all_with_search(page=1, per_page=1000)
        return sum(inv.balance for inv in pagination.items if inv.status in ['open'])

    @classmethod
    def _get_cash_summary(cls, start_date, end_date):
        """Calculates Received, Paid, and Net for a given period."""
        # 1. Payments Received (Income)
        payments = db.session.execute(
            select(func.sum(Payment.amount))
            .where(
                Payment.is_active == True, 
                Payment.payment_date.between(start_date.date(), end_date.date())
            )
        ).scalar() or 0

        # 2. Expenses Spent (Completed only)
        expenses = db.session.execute(
            select(func.sum(Expense.total_amount))
            .where(
                Expense.is_active == True, 
                Expense.status == 'completed',
                Expense.expense_date.between(start_date.date(), end_date.date())
            )
        ).scalar() or 0
        
        # 3. Manual Adjustments (Non-system only)
        adjustments = db.session.execute(
            select(func.sum(Adjustment.amount))
            .where(
                Adjustment.is_active == True, 
                Adjustment.is_system == False,
                Adjustment.adjustment_date.between(start_date.date(), end_date.date())
            )
        ).scalar() or 0

        return {
            'payments': payments,
            'expenses': expenses,
            'adjustments': adjustments,
            'net': payments - expenses + adjustments
        }

    # --- PRIVATE HELPERS: TABLE FETCHING ---

    @classmethod
    def _get_dashboard_pos(cls):
        """Fetches exactly 15 POs, priority-sorted by Status (Open -> Invoiced -> Completed)."""
        # We use sort='status' and dir='desc' because 'O' > 'I' > 'C'
        pagination = PurchaseOrderService.get_all_with_search(
            page=1, 
            per_page=15, 
            sort_by='status', 
            direction='desc'
        )
        return pagination.items

    @classmethod
    def _get_dashboard_invoices(cls):
        """Fetches exactly 15 Invoices. priority-sorted by Status (Open -> Draft -> Completed)."""
        # active_invs = InvoiceService.get_all_with_search(page=1, per_page=1000).items
        # display = [inv for inv in active_invs if inv.status in ['draft', 'open']]
        # if len(display) < 15:
        #     completed = [inv for inv in active_invs if inv.status == 'completed']
        #     display.extend(completed[:15])
        # return display[:15]
        pagination = InvoiceService.get_all_with_search(
            page=1, 
            per_page=15, 
            sort_by='status', 
            direction='desc'
        )
        return pagination.items


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