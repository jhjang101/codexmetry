from sqlalchemy import select, func, and_, case
from ..extensions import db
from ..models import (
    Invoice, InvoiceItem, Expense, ExpenseItem, 
    Payment, Adjustment, AdjustmentCategory, 
    Product, ProductCategory, ExpenseCategory, Client
)

class ReportService:

    @classmethod
    def get_financial_package(cls, start_date, end_date):
        """Brain: Compiles a 6-table dataset for the Financial Fortress."""
        
        # 1. ACCRUAL DATA (Performance - Based on Issued Documents)
        accrual_revenue = cls._get_accrual_revenue(start_date, end_date)
        accrual_expenses = cls._get_accrual_expenses(start_date, end_date)
        
        # 2. CASH DATA (Liquidity - Based on Cash Movement)
        cash_income = db.session.execute(
            select(func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date.between(start_date, end_date))
        ).scalar() or 0
        
        cash_outgoings = cls._get_cash_outgoings(start_date, end_date)

        # 3. ADJUSTMENTS (Non-Operating)
        adjustments = cls._get_adjustments_breakdown(start_date, end_date)
        total_adj = sum(a['total'] for a in adjustments)

        # 4. CONSOLIDATED SUMMARY MATH
        # Accrual Perspective
        gross_profit_accrual = accrual_revenue - accrual_expenses['cogs_total']
        operating_profit_accrual = gross_profit_accrual - accrual_expenses['opex_total']
        net_income = operating_profit_accrual + total_adj

        # Cash Perspective
        gross_profit_cash = cash_income - cash_outgoings['cogs_paid']
        net_cash_flow = cash_income - cash_outgoings['total_paid']

        return {
            'accrual': {
                'revenue': accrual_revenue,
                'cogs': accrual_expenses['cogs_total'],
                'gross_profit': gross_profit_accrual,
                'opex': accrual_expenses['opex_total'],
                'operating_profit': operating_profit_accrual,
                'net_income': net_income
            },
            'cash': {
                'income': cash_income,
                'cogs_paid': cash_outgoings['cogs_paid'],
                'gross_profit_cash': gross_profit_cash,
                'opex_paid': cash_outgoings['opex_paid'],
                'net_cash': net_cash_flow
            },
            'adjustments': adjustments,
            'audit': {
                'invoices': cls._get_invoice_audit(start_date, end_date),
                'payments': cls._get_payment_audit(start_date, end_date),
                'expenses': cls._get_expense_audit(start_date, end_date),
                'adjustments': cls._get_adjustment_audit(start_date, end_date)
            }
        }

    # --- ACCRUAL HELPERS (Document Based) ---

    @classmethod
    def _get_accrual_revenue(cls, start, end):
        """Sums items where is_revenue is True using InvoiceItem anchor."""
        stmt = (
            select(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .select_from(InvoiceItem)
            .join(Invoice).join(Product).join(ProductCategory)
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start, end),
                ProductCategory.is_revenue == True
            )
        )
        return db.session.execute(stmt).scalar() or 0

    @classmethod
    def _get_accrual_expenses(cls, start, end):
        """Sums COGS vs OPEX using ExpenseItem anchor."""
        stmt = (
            select(
                ExpenseCategory.is_cogs,
                func.sum(ExpenseItem.quantity * ExpenseItem.unit_price)
            )
            .select_from(ExpenseItem)
            .join(Expense).join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.status != 'draft',
                Expense.expense_date.between(start, end)
            )
            .group_by(ExpenseCategory.is_cogs)
        )
        
        results = db.session.execute(stmt).all()
        data = {'cogs_total': 0, 'opex_total': 0}
        for is_cogs, total in results:
            if is_cogs: data['cogs_total'] = total
            else: data['opex_total'] = total
        return data

    # --- CASH HELPERS (Transaction Based) ---

    @classmethod
    def _get_cash_outgoings(cls, start, end):
        """Sums Completed Expenses, splitting by COGS vs OPEX flags."""
        stmt = (
            select(
                ExpenseCategory.is_cogs,
                func.sum(Expense.total_amount)
            )
            .join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.status == 'completed', # Paid
                Expense.expense_date.between(start, end)
            )
            .group_by(ExpenseCategory.is_cogs)
        )
        results = db.session.execute(stmt).all()
        data = {'cogs_paid': 0, 'opex_paid': 0, 'total_paid': 0}
        for is_cogs, total in results:
            if is_cogs: data['cogs_paid'] = total
            else: data['opex_paid'] = total
        data['total_paid'] = data['cogs_paid'] + data['opex_paid']
        return data

    # --- AUDIT TABLES (The Evidence) ---

    @classmethod
    def _get_invoice_audit(cls, start, end):
        """Chronological justification for Accrual Revenue."""
        invoices = db.session.execute(
            select(Invoice).where(
                Invoice.is_active == True, 
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start, end)
            ).order_by(Invoice.invoice_date.asc())
        ).scalars().all()

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
    def _get_payment_audit(cls, start, end):
        """Chronological justification for Cash Income."""
        return db.session.execute(
            select(Payment).options(db.joinedload(Payment.client))
            .where(Payment.is_active == True, Payment.payment_date.between(start, end))
            .order_by(Payment.payment_date.asc())
        ).scalars().all()

    @classmethod
    def _get_expense_audit(cls, start, end):
        """Chronological justification for Outgoings (Issued and Completed)."""
        expenses = db.session.execute(
            select(Expense).options(db.joinedload(Expense.category), db.joinedload(Expense.vendor))
            .where(Expense.is_active == True, Expense.status != 'draft', Expense.expense_date.between(start, end))
            .order_by(Expense.expense_date.asc())
        ).scalars().all()

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
    def _get_adjustment_audit(cls, start, end):
        return db.session.execute(
            select(Adjustment).options(db.joinedload(Adjustment.category))
            .where(Adjustment.is_active == True, Adjustment.adjustment_date.between(start, end))
            .order_by(Adjustment.adjustment_date.asc())
        ).scalars().all()

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
        return [{'category': r[0], 'total': r[1]} for r in db.session.execute(stmt).all()]