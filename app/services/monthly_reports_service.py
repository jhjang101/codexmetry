from sqlalchemy import select, func, desc, asc, and_, case, extract
from dateutil.relativedelta import relativedelta
from datetime import date
from ..extensions import db
from ..models import (
    Invoice, InvoiceItem, Expense, ExpenseItem, 
    Payment, PaymentType, Adjustment, AdjustmentCategory, 
    Product, ProductCategory, ExpenseCategory, Client, Vendor
)

class MonthlyReportService:

    @classmethod
    def get_financial_package(cls, start_date, end_date):
        """Brain: Compiles a 6-table dataset for the Financial Fortress."""
        
        # 1. ACCRUAL DATA (Performance - Based on Issued Documents)
        accrual_revenue = cls._get_revenue_summary(start_date, end_date)
        accrual_expenses = cls._get_expense_summary(start_date, end_date, mode='accrual')
        accrual_adjustments = cls._get_adjustment_summary(start_date, end_date, mode='accrual')
        
        # 2. CASH DATA (Liquidity - Based on Cash Movement)
        cash_payments = cls._get_payment_summary(start_date, end_date)
        cash_expenses = cls._get_expense_summary(start_date, end_date, mode='cash')
        cash_adjustments = cls._get_adjustment_summary(start_date, end_date, mode='cash')
        
        # 3. SUMMARY MATH
        # Accrual Perspective
        accrual_gross_profit = accrual_revenue['total'] - accrual_expenses['cogs']['total']
        accrual_operating_profit = accrual_gross_profit - accrual_expenses['opex']['total']
        accrual_net_income = accrual_operating_profit + accrual_adjustments['total']

        # Cash Perspective
        cash_gross_profit = cash_payments['total'] - cash_expenses['cogs']['total']
        cash_operating_profit = cash_gross_profit - cash_expenses['opex']['total']
        cash_net_cash = cash_operating_profit + cash_adjustments['total']

        return {
            'accrual': {
                'revenue': accrual_revenue,
                'cogs': accrual_expenses['cogs'],
                'gross_profit': accrual_gross_profit,
                'opex': accrual_expenses['opex'],
                'operating_profit': accrual_operating_profit,
                'adjustments': accrual_adjustments,
                'net_income': accrual_net_income
            },
            'cash': {
                'payments': cash_payments,
                'cogs': cash_expenses['cogs'],
                'gross_profit': cash_gross_profit,
                'opex': cash_expenses['opex'],
                'operating_profit': cash_operating_profit,
                'adjustments': cash_adjustments,
                'net_cash': cash_net_cash
            },
            'audit': {
                'invoices': cls._get_invoice_audit(start_date, end_date),
                'payments': cls._get_payment_audit(start_date, end_date),
                'expenses': cls._get_expense_audit(start_date, end_date),
                'adjustments': cls._get_adjustment_audit(start_date, end_date)
            }
        }

    # --- HELPERS (Document Based) ---

    @classmethod
    def _get_revenue_summary(cls, start, end):
        """
        Sums items grouped by category where is_revenue is True 
        from open and completed Invoices.
        """
        stmt = (
            select(
                ProductCategory.type, 
                func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price)
            )
            .select_from(InvoiceItem)
            .join(Invoice).join(Product).join(ProductCategory)
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start, end),
                ProductCategory.is_revenue == True
            )
            .group_by(ProductCategory.type)
        )
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}
    
    @classmethod
    def _get_payment_summary(cls, start, end):
        """
        Groups actual cash received by Payment Type
        from Payments.
        """
        stmt = (
            select(
                PaymentType.type, 
                func.sum(Payment.amount)
            )
            .join(PaymentType)
            .where(
                Payment.is_active == True, 
                Payment.payment_date.between(start, end)
            )
            .group_by(PaymentType.type)
        )
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}

    @classmethod
    def _get_expense_summary(cls, start, end, mode='accrual'):
        """Groups Expenses by category, separated into COGS and OPEX."""
        stmt = (
            select(
                ExpenseCategory.type, 
                ExpenseCategory.is_cogs, 
                func.sum(Expense.total_amount)
            )
            .join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.expense_date.between(start, end)
            )
        )

        # Apply status filters based on accounting perspective
        if mode == 'accrual':
            # Accrual basis looks at all open/completed expenses
            stmt = stmt.where(Expense.status != 'draft')
        else:
            # Cash basis looks only at completed espenses
            stmt = stmt.where(Expense.status == 'completed')
        
        # Group by category and separated into COGS and OPEX
        stmt = stmt.group_by(ExpenseCategory.type, ExpenseCategory.is_cogs)

        results = db.session.execute(stmt).all()
        
        cogs_breakdown = [{'category': r[0], 'amount': r[2] or 0} for r in results if r[1]]
        cogs_total = sum(item['amount'] for item in cogs_breakdown)
        
        opex_breakdown = [{'category': r[0], 'amount': r[2] or 0} for r in results if not r[1]]
        opex_total = sum(item['amount'] for item in opex_breakdown)

        expenses = {
            'cogs': {'total': cogs_total, 'breakdown': cogs_breakdown},
            'opex': {'total': opex_total, 'breakdown': opex_breakdown}
        }
        return expenses
    
    @classmethod
    def _get_adjustment_summary(cls, start, end, mode='accrual'):
        """
        Groups Adjustments by category,
        Accrual mode includes all active
        Cash mode excludes system write-offs.
        """
        stmt = (
            select(
                AdjustmentCategory.type, 
                func.sum(Adjustment.amount)
            )
            .join(AdjustmentCategory)
            .where(
                Adjustment.is_active == True,
                Adjustment.adjustment_date.between(start, end)
            )
        )
        # If cash mode, only include manual entries
        if mode == 'cash':
            stmt = stmt.where(Adjustment.is_system == False)

        # Group by category
        stmt = stmt.group_by(AdjustmentCategory.type)
            
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}
    
    # --- SORTING HELPER ---

    @classmethod
    def _apply_audit_sorting(cls, stmt, sort_by, direction, whitelist, default_col):
        """
        Brain: Local sorting logic for report tables.
        Defaults to ASC (Oldest first) for accounting ledger style.
        """
        # Standardize Direction: Default to ASC for ledgers
        sort_dir = desc if direction == 'desc' else asc
        target_col = whitelist.get(sort_by)

        if target_col is not None:
            # Primary: User Selection | Secondary: Default (Date)
            return stmt.order_by(sort_dir(target_col), asc(default_col))
        
        # Fallback: Chronological Ledger Order
        return stmt.order_by(asc(default_col))

    # --- AUDIT TABLES (The Evidence) ---

    @classmethod
    def _get_invoice_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Accrual Revenue."""
        # Whitelist for Invoices
        MAP = {
            'date': Invoice.invoice_date,
            'number': Invoice.invoice_number,
            'amount': Invoice.total_amount,
            'client': Client.company_name
        }

        stmt = select(Invoice).join(Client, Invoice.client_id == Client.id).where(
            Invoice.is_active == True, 
            Invoice.status != 'draft',
            Invoice.invoice_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Invoice.invoice_date)

        invoices = db.session.execute(stmt).scalars().all()

        audit_rows = []
        for inv in invoices:
            rev = sum(i.quantity * i.billed_unit_price for i in inv.items if i.product.category.is_revenue)
            audit_rows.append({
                'obj': inv,
                'revenue_portion': rev,
                'non_revenue_portion': inv.total_amount - rev
            })
        return audit_rows

    @classmethod
    def _get_payment_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Cash Income."""
        MAP = {
            'date': Payment.payment_date,
            'number': Payment.payment_number,
            'amount': Payment.amount,
            'client': Client.company_name
        }

        stmt = select(Payment).join(Client, Payment.client_id == Client.id).where(
            Payment.is_active == True,
            Payment.payment_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Payment.payment_date)
        return db.session.execute(stmt.options(db.joinedload(Payment.client))).scalars().all()

    @classmethod
    def _get_expense_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Outgoings (Issued and Completed)."""
        MAP = {
            'date': Expense.expense_date,
            'number': Expense.expense_number,
            'amount': Expense.total_amount,
            'vendor': Vendor.company_name,
            'category': ExpenseCategory.type
        }

        stmt = select(Expense).join(Vendor, Expense.vendor_id == Vendor.id).outerjoin(ExpenseCategory).where(
            Expense.is_active == True,
            Expense.status != 'draft',
            Expense.expense_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Expense.expense_date)
        expenses = db.session.execute(stmt.options(db.joinedload(Expense.category), db.joinedload(Expense.vendor))).scalars().all()

        audit_rows = []
        for exp in expenses:
            is_cogs = exp.category.is_cogs if exp.category else False
            audit_rows.append({
                'obj': exp,
                'cogs_portion': exp.total_amount if is_cogs else 0,
                'opex_portion': exp.total_amount if not is_cogs else 0
            })
        return audit_rows

    @classmethod
    def _get_adjustment_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Adjustments with dynamic sorting."""
        MAP = {
            'date': Adjustment.adjustment_date,
            'number': Adjustment.adjustment_number,
            'amount': Adjustment.amount,
            'category': AdjustmentCategory.type
        }

        stmt = select(Adjustment).join(AdjustmentCategory).where(
            Adjustment.is_active == True,
            Adjustment.adjustment_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Adjustment.adjustment_date)
        return db.session.execute(stmt.options(db.joinedload(Adjustment.category))).scalars().all()

    @classmethod
    def _get_adjustments_breakdown(cls, start, end):
        """Sums adjustments by category for the P&L statement."""
        stmt = (
            select(AdjustmentCategory.type, func.sum(Adjustment.amount))
            .join(Adjustment).where(
                Adjustment.is_active == True,
                Adjustment.adjustment_date.between(start, end)
            )
            .group_by(AdjustmentCategory.type)
        )
