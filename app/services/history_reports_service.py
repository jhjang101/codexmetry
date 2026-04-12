from sqlalchemy import select, func, desc, asc, and_, case, extract
from dateutil.relativedelta import relativedelta
from datetime import date
from ..extensions import db
from ..models import (
    Invoice, InvoiceItem, Expense, ExpenseItem, 
    Payment, PaymentType, Adjustment, AdjustmentCategory, 
    Product, ProductCategory, ExpenseCategory, Client, Vendor
)

class HistoryReportService:

    @classmethod
    def get_historical_summary(cls, years=5):
        """
        Brain: Generates a 60-month gapless financial timeline for PostgreSQL.
        Uses 'extract' for cross-DB compatibility and supports YoY grouping.
        """
        # 1. Setup Time Window
        end_date = date.today().replace(day=1) + relativedelta(months=1) - relativedelta(days=1)
        start_date = (end_date + relativedelta(days=1)) - relativedelta(years=years)
        
        # 2. Initialize the Timeline (The Master Dictionary)
        # Key format: "YYYY-MM" for easy sorting and lookup
        timeline = {}
        curr = start_date.replace(day=1)
        while curr <= end_date:
            key = curr.strftime('%Y-%m')
            timeline[key] = {
                'year': curr.year,
                'month': curr.month,
                'month_label': curr.strftime('%b %Y'),
                'accrual': {'revenue': 0, 'cogs': 0, 'opex': 0, 'total_adj': 0},
                'cash': {'payments': 0, 'cogs_paid': 0, 'opex_paid': 0, 'manual_adj': 0}
            }
            curr += relativedelta(months=1)

        # 3. Aggregate Data via SQL (Postgres Compatible Extract)
        
        # --- BUCKET A: Accrual Revenue ---
        y_ext = extract('year', Invoice.invoice_date)
        m_ext = extract('month', Invoice.invoice_date)
        
        rev_stmt = (
            select(y_ext, m_ext, func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .select_from(InvoiceItem).join(Invoice).join(Product).join(ProductCategory)
            .where(Invoice.is_active == True, Invoice.status != 'draft', 
                Invoice.invoice_date.between(start_date, end_date), ProductCategory.is_revenue == True)
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(rev_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['accrual']['revenue'] = total or 0

        # --- BUCKET B: Accrual Expenses ---
        y_ext = extract('year', Expense.expense_date)
        m_ext = extract('month', Expense.expense_date)
        
        exp_acc_stmt = (
            select(y_ext, m_ext, ExpenseCategory.is_cogs, func.sum(ExpenseItem.quantity * ExpenseItem.unit_price))
            .select_from(ExpenseItem).join(Expense).join(ExpenseCategory)
            .where(Expense.is_active == True, Expense.status != 'draft', 
                Expense.expense_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, ExpenseCategory.is_cogs)
        )
        for y, m, is_cogs, total in db.session.execute(exp_acc_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                label = 'cogs' if is_cogs else 'opex'
                timeline[key]['accrual'][label] = total or 0

        # --- BUCKET C: Cash Payments Received ---
        y_ext = extract('year', Payment.payment_date)
        m_ext = extract('month', Payment.payment_date)
        
        cash_in_stmt = (
            select(y_ext, m_ext, func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(cash_in_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['cash']['payments'] = total or 0

        # --- BUCKET D: Cash Paid Expenses (Completed Expenses) ---
        y_ext = extract('year', Expense.expense_date)
        m_ext = extract('month', Expense.expense_date)

        cash_out_stmt = (
            select(y_ext, m_ext, ExpenseCategory.is_cogs, func.sum(Expense.total_amount))
            .join(ExpenseCategory).where(Expense.is_active == True, Expense.status == 'completed',
                                        Expense.expense_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, ExpenseCategory.is_cogs)
        )
        for y, m, is_cogs, total in db.session.execute(cash_out_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                label = 'cogs_paid' if is_cogs else 'opex_paid'
                timeline[key]['cash'][label] = total or 0

        # --- BUCKET E & F: Adjustments (Accrual vs Cash) ---
        y_ext = extract('year', Adjustment.adjustment_date)
        m_ext = extract('month', Adjustment.adjustment_date)
        
        adj_stmt = (
            select(y_ext, m_ext, Adjustment.is_system, func.sum(Adjustment.amount))
            .where(Adjustment.is_active == True, Adjustment.adjustment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, Adjustment.is_system)
        )
        for y, m, is_system, total in db.session.execute(adj_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                # Every adjustment counts for Accrual
                timeline[key]['accrual']['total_adj'] += (total or 0)
                # Only non-system adjustments count for Cash
                if not is_system:
                    timeline[key]['cash']['manual_adj'] = total or 0

        # 4. Final Processing (Derived Math)
        results = []
        for k in sorted(timeline.keys(), reverse=True):
            m = timeline[k]
            # Accrual Perspctive
            m['accrual']['gross_profit'] = m['accrual']['revenue'] - m['accrual']['cogs']
            m['accrual']['operating_profit'] = m['accrual']['gross_profit'] - m['accrual']['opex']
            m['accrual']['net_income'] = m['accrual']['operating_profit'] + m['accrual']['total_adj']
            
            # Cash Perspective
            m['cash']['gross_margin'] = m['cash']['payments'] - m['cash']['cogs_paid']
            m['cash']['operating_cash'] = m['cash']['gross_margin'] - m['cash']['opex_paid']
            m['cash']['net_cash'] = m['cash']['operating_cash'] + m['cash']['manual_adj']
            
            results.append(m)

        return results
    
    @classmethod
    def get_chart_data(cls, history, perspective='accrual', mode='monthly'):
        """
        Brain: Transforms 60-month history into Monthly, Quarterly, Yearly, 
        or Seasonal Overlay aggregates.
        """
        # 1. Perspective Configuration
        if perspective == 'accrual':
            kpi_keys = ['revenue', 'cogs', 'gross_profit', 'opex', 'operating_profit', 'total_adj', 'net_income']
            sub_key = 'accrual'
            focus_kpi = 'net_income'
            primary_color = '#3b82f6' # Blue spectrum
        else:
            kpi_keys = ['payments', 'cogs_paid', 'gross_margin', 'opex_paid', 'operating_cash', 'manual_adj', 'net_cash']
            sub_key = 'cash'
            focus_kpi = 'net_cash'
            primary_color = '#10b981' # Green spectrum

         # ---------------------------------------------------------
        # MODE A: OVERLAY VIEWS (Seasonal Performance & Growth)
        # ---------------------------------------------------------
        if mode in ['yearly_comparison', 'seasonal_cumulative']:
            this_year = date.today().year
            target_years = [this_year, this_year - 1, this_year - 2]
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            datasets = []
            
            overlay_styles = [
                {'label': f"{this_year}", 'color': primary_color, 'width': 3, 'dash': []},
                {'label': f"{this_year - 1}", 'color': primary_color + '88', 'width': 2, 'dash': []},
                {'label': f"{this_year - 2}", 'color': '#94a3b8', 'width': 1, 'dash': [5, 5]}
            ]

            for i, year in enumerate(target_years):
                year_data = [None] * 12
                running_total = 0
                
                # Filter and sort months for this specific year
                year_months = sorted([m for m in history if m['year'] == year], key=lambda x: x['month'])
                
                for m in year_months:
                    val = m[sub_key].get(focus_kpi, 0) / 100
                    
                    if mode == 'seasonal_cumulative':
                        running_total += val
                        year_data[m['month'] - 1] = running_total
                    else:
                        year_data[m['month'] - 1] = val

                style = overlay_styles[i]
                datasets.append({
                    'label': f"{style['label']} {'(YTD Growth)' if mode == 'seasonal_cumulative' else '(Monthly)'}",
                    'data': year_data,
                    'borderColor': style['color'],
                    'borderWidth': style['width'],
                    'borderDash': style['dash'],
                    'tension': 0.1 if mode == 'seasonal_cumulative' else 0.3,
                    'pointRadius': 3,
                    'fill': i == 0 
                })
            
            return {'labels': labels, 'datasets': datasets}

        # ---------------------------------------------------------
        # MODE B: LINEAR AGGREGATION (Chronological MoM, QoQ, YoY)
        # ---------------------------------------------------------
        raw_data = sorted(history, key=lambda x: f"{x['year']}-{x['month']:02d}")
        aggregated = {}

        for m in raw_data:
            if mode == 'yearly':
                group_key = str(m['year'])
            elif mode == 'quarterly':
                q = (m['month'] - 1) // 3 + 1
                group_key = f"{m['year']} Q{q}"
            else: # monthly
                group_key = m['month_label']

            if group_key not in aggregated:
                aggregated[group_key] = {k: 0 for k in kpi_keys}
            
            for k in kpi_keys:
                aggregated[group_key][k] += (m[sub_key].get(k, 0) / 100)

        labels = list(aggregated.keys())
        if mode == 'monthly': labels = labels[-24:] # Filter to last 2 years for MoM clarity

        datasets = []
        style_map = {
            'revenue': {'color': '#3b82f6', 'width': 3, 'dash': []},
            'payments': {'color': '#10b981', 'width': 3, 'dash': []},
            'net_income': {'color': '#0f172a', 'width': 3, 'dash': []},
            'net_cash': {'color': '#064e3b', 'width': 3, 'dash': []},
            'cogs': {'color': '#ef4444', 'width': 1, 'dash': [5, 5]},
            'cogs_paid': {'color': '#ef4444', 'width': 1, 'dash': [5, 5]},
            'opex': {'color': '#f59e0b', 'width': 1, 'dash': [2, 2]},
            'opex_paid': {'color': '#f59e0b', 'width': 1, 'dash': [2, 2]},
        }

        for k in kpi_keys:
            style = style_map.get(k, {'color': '#94a3b8', 'width': 1, 'dash': [5, 5]})
            datasets.append({
                'label': k.replace('_', ' ').capitalize(),
                'data': [aggregated[l][k] for l in labels],
                'borderColor': style['color'],
                'borderWidth': style['width'],
                'borderDash': style['dash'],
                'tension': 0.3,
                'pointRadius': 2 if len(labels) < 20 else 0
            })

        return {'labels': labels, 'datasets': datasets}