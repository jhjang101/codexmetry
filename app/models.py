from .extensions import db, login_manager
from flask import has_request_context
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr
from sqlalchemy import String, Integer, Boolean, DateTime, Date, Text, ForeignKey, func, event, JSON
from datetime import datetime, date

# --- 1. AUTH ---
class AuditMixin:
    """Mixin to automatically track creation and updates."""
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    
    @declared_attr
    def created_by_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey('users.id'))

    @declared_attr
    def updated_by_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey('users.id'))

    # Relationships (Singular naming)
    @declared_attr
    def creator(cls) -> Mapped["User"]:
        return relationship("User", foreign_keys=[cls.created_by_id]) # type: ignore

    @declared_attr
    def updater(cls) -> Mapped["User"]:
        return relationship("User", foreign_keys=[cls.updated_by_id]) # type: ignore
    
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(20)) # CREATE, UPDATE, ARCHIVE
    target_type: Mapped[str] = mapped_column(String(50)) # 'Invoice', 'Product', etc.
    target_id: Mapped[int] = mapped_column(Integer)
    target_label: Mapped[str | None] = mapped_column(String(255))
    
    # Stores a dict of {'field_name': [old_value, new_value]}
    changes: Mapped[dict | None] = mapped_column(JSON) 

    user: Mapped["User"] = relationship()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(100))
    phone_number: Mapped[str | None] = mapped_column(String(50))
    password_hash: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), default='user')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- 2. LOOKUP TABLES ---
class PoType(db.Model):
    __tablename__ = 'po_types'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ProductCategory(db.Model):
    __tablename__ = 'product_categories'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    # New Accounting Flag
    is_revenue: Mapped[bool] = mapped_column(Boolean, default=True, server_default='1')

class ExpenseCategory(db.Model):
    __tablename__ = 'expense_categories'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # New Reporting Field
    is_cogs: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0')

class PaymentType(db.Model):
    __tablename__ = 'payment_types'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class AdjustmentCategory(db.Model):
    __tablename__ = 'adjustment_categories'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Carrier(db.Model):
    __tablename__ = 'carriers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

# --- 3. SETTINGS ---
class SettingsMetadata(db.Model):
    __tablename__ = 'settings_metadata'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), default='Codexmetry Corp')
    address: Mapped[str | None] = mapped_column(Text)
    company_logo: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(100), default='America/Chicago')
    invoice_threshold: Mapped[int] = mapped_column(Integer, default=10000)
    doc_padding: Mapped[int] = mapped_column(Integer, default=4)

    # New Identity Fields
    company_email: Mapped[str | None] = mapped_column(String(255))
    company_phone: Mapped[str | None] = mapped_column(String(50))
    company_fax: Mapped[str | None] = mapped_column(String(50))
    payable_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)

    # New Banking Fields
    bank_name: Mapped[str | None] = mapped_column(String(100))
    bank_swift: Mapped[str | None] = mapped_column(String(50))
    bank_routing: Mapped[str | None] = mapped_column(String(50))
    bank_account: Mapped[str | None] = mapped_column(String(50))

    # New Default Terms
    default_net_days: Mapped[int] = mapped_column(Integer, default=30, server_default='30')
    default_quote_expiry_days: Mapped[int] = mapped_column(Integer, default=30, server_default='30')
    default_quote_terms: Mapped[str | None] = mapped_column(Text)
    default_invoice_terms: Mapped[str | None] = mapped_column(Text)
    default_po_terms: Mapped[str | None] = mapped_column(Text)

# --- 4. MASTER DATA ---
class Client(db.Model, AuditMixin):
    __tablename__ = 'clients'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    contacts: Mapped[list["ClientContact"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="client")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="client", foreign_keys="[PurchaseOrder.client_id]")
    po_billings: Mapped[list["PurchaseOrder"]] = relationship(back_populates="bill_to", foreign_keys="[PurchaseOrder.bill_to_id]")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="client", foreign_keys="[Invoice.client_id]")
    invoice_billings: Mapped[list["Invoice"]] = relationship(back_populates="bill_to", foreign_keys="[Invoice.bill_to_id]")
    payments: Mapped[list["Payment"]] = relationship(back_populates="client", foreign_keys="[Payment.client_id]")
    paid_from_payments: Mapped[list["Payment"]] = relationship(back_populates="paid_from", foreign_keys="[Payment.paid_from_id]")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="client")

    @property
    def primary_contact(self):
        # Standardize the 'Primary' definition: lowest ID
        if self.contacts:
            return sorted(self.contacts, key=lambda c: c.id)[0]
        return None

    @property
    def primary_contact_name(self):
        """Returns 'First Last' or '-'."""
        c = self.primary_contact
        if c:
            name = f"{c.first_name or ''} {c.last_name or ''}".strip()
            return name if name else None
        return None

    @property
    def primary_contact_email(self):
        """Returns email or '-'."""
        c = self.primary_contact
        return c.email if (c and c.email) else None
    
    @property
    def primary_contact_phone(self):
        """Returns phone or '-'."""
        c = self.primary_contact
        return c.phone_number if (c and c.phone_number) else None
    
    @property
    def full_display(self):
        """Returns 'Company Name (Contact Name)' or just 'Company Name'"""
        if self.contacts:
            contact = self.contacts[0]
            name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            return f"{self.company_name} ({name})" if name else self.company_name
        return self.company_name
    
    @property
    def has_open_pos(self) -> bool:
        """Logic: Check for POs where items are still remaining to be fulfilled."""
        # We use a generator expression for memory efficiency
        return any(po.is_active and po.status == 'open' for po in self.purchase_orders)

    @property
    def has_open_invoices(self) -> bool:
        """Logic: Check for any issued invoices that are not yet fully paid."""
        return any(inv.is_active and inv.status == 'open' for inv in self.invoices)

class ClientContact(db.Model):
    __tablename__ = 'client_contacts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(50))


    client: Mapped["Client"] = relationship(back_populates="contacts")

class Vendor(db.Model, AuditMixin):
    __tablename__ = 'vendors'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="vendor")
    contacts: Mapped[list["VendorContact"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")

    @property
    def primary_contact(self):
        # Standardize the 'Primary' definition: lowest ID
        if self.contacts:
            return sorted(self.contacts, key=lambda c: c.id)[0]
        return None

    @property
    def primary_contact_name(self):
        """Returns 'First Last' or '-'."""
        c = self.primary_contact
        if c:
            name = f"{c.first_name or ''} {c.last_name or ''}".strip()
            return name if name else None
        return None

    @property
    def primary_contact_email(self):
        """Returns email or '-'."""
        c = self.primary_contact
        return c.email if (c and c.email) else None
    
    @property
    def primary_contact_phone(self):
        """Returns phone or '-'."""
        c = self.primary_contact
        return c.phone_number if (c and c.phone_number) else None

class VendorContact(db.Model):
    __tablename__ = 'vendor_contacts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey('vendors.id'))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(50))

    vendor: Mapped["Vendor"] = relationship(back_populates="contacts")

class Product(db.Model, AuditMixin):
    __tablename__ = 'products'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    catalog_number: Mapped[str | None] = mapped_column(String(100))
    category_id: Mapped[int | None] = mapped_column(ForeignKey('product_categories.id'))
    image_url: Mapped[str | None] = mapped_column(String(255))
    default_unit_price: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    # New Placement Field for Printable Form 
    document_placement: Mapped[str] = mapped_column(String(20), default='Lineitem', server_default='Lineitem') # lineitem, shipping, tax

    category: Mapped["ProductCategory"] = relationship()

# --- 5. REGISTRY & SALES ---
class OrderRegistry(db.Model, AuditMixin):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    quote: Mapped["Quote | None"] = relationship(back_populates="order")
    purchase_order: Mapped["PurchaseOrder | None"] = relationship(back_populates="order")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="order")
    payments: Mapped[list["Payment"]] = relationship(back_populates="order")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="order")

    @property
    def total_paid(self):
        """Sum of all active payments in this deal."""
        if 'payments' in self.__dict__:
            return sum(pay.amount for pay in self.payments if pay.is_active)
        return 0

    @property
    def total_expenses(self):
        """Sum of all active expenses in this order."""
        if 'expenses' in self.__dict__:
            return sum(exp.total_amount for exp in self.expenses if exp.is_active)
        return 0

    @property
    def remaining_to_collect(self):
        """How much has been billed but not yet paid."""
        # Total Due (Positive Invoices) - Total Paid (including prepayment)
        total_due = sum(max(0, inv.total_amount) for inv in self.invoices if inv.is_active)
        return total_due - self.total_paid
    
    @property
    def total_contextual_balance(self):
        """
        Sum of unpaid balances across all invoices. 
        Formula: (Total Billed) - (Payments already applied to Invoices)
        Shortcut: remaining_to_collect + total_prepayments
        """
        # Total Due is all positive billing
        # remaining_to_collect is (Total Due - Total Paid)
        # We add back the prepayments to show only the gap on issued invoices
        return self.remaining_to_collect + self.total_prepayments
    
    @property
    def total_invoiced_due(self):
        """Sum of all total_due values (positive billing) in this order."""
        if 'invoices' in self.__dict__:
            return sum(inv.total_due for inv in self.invoices if inv.is_active)
        return 0

    @property
    def total_prepayments(self):
        """Sum of all payments not yet linked to an invoice."""
        if 'payments' in self.__dict__:
            return sum(p.amount for p in self.payments if p.is_active and p.invoice_id is None)
        return 0

class Quote(db.Model, AuditMixin):
    __tablename__ = 'quotes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    quote_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    quote_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    expiration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default='draft') # draft, sent, accepted, expired
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id')) # Linked after conversion
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    order: Mapped["OrderRegistry"] = relationship(back_populates="quote")
    purchase_order: Mapped["PurchaseOrder | None"] = relationship(back_populates="quote")
    client: Mapped["Client"] = relationship(back_populates="quotes")
    items: Mapped[list["QuoteItem"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Quote.id==Attachment.entity_id, Attachment.entity_type=='Quote')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True, # Safety: manage files via the AttachmentService, not this list
        order_by="Attachment.uploaded_at.asc()"
    )

class PurchaseOrder(db.Model, AuditMixin):
    __tablename__ = 'purchase_orders'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), nullable=False)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey('quotes.id'))
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    bill_to_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    po_number: Mapped[str | None] = mapped_column(String(100))
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    po_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    po_type_id: Mapped[int | None] = mapped_column(ForeignKey('po_types.id'))
    status: Mapped[str] = mapped_column(String(20), default='open')
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    order: Mapped["OrderRegistry"] = relationship(back_populates="purchase_order")
    quote: Mapped["Quote | None"] = relationship(back_populates="purchase_order")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="purchase_order")
    payments: Mapped[list["Payment"]] = relationship(back_populates="purchase_order")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="purchase_order")
    client: Mapped["Client"] = relationship(back_populates="purchase_orders", foreign_keys=[client_id])
    bill_to: Mapped["Client"] = relationship(back_populates="po_billings", foreign_keys=[bill_to_id])
    items: Mapped[list["PoItem"]] = relationship(back_populates="po", cascade="all, delete-orphan")
    po_type: Mapped["PoType"] = relationship()
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(PurchaseOrder.id==Attachment.entity_id, Attachment.entity_type=='PurchaseOrder')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True,
        order_by="Attachment.uploaded_at.asc()"
    )

    @property
    def invoiced_total(self):
        """Sum of non-system invoices (total due) linked to this PO."""
        if self.order and 'invoices' in self.order.__dict__:
            return sum(inv.total_amount for inv in self.order.invoices 
                    if inv.po_id == self.id and inv.is_active)
        return 0

    @property
    def balance_tobe_invoiced(self):
        """
        Logic: (Total PO Commitment - Real Goods Billed) - max(0, Unapplied Credit Pool)
        This matches the precise backlog math used in the Service and List View.
        """
        # 1. Total PO Commitment
        commitment = sum(item.quantity * item.agreed_unit_price for item in self.items)

        # 2. Total Fulfilled PO Items (Goods only)
        # We only count invoice items that exist in the PO's product list
        po_product_ids = {item.product_id for item in self.items}
        fulfilled = 0
        applied_deposits = 0
        negative_carryover = 0

        for inv in self.invoices:
            if not inv.is_active:
                continue
            
            # Track negative grand totals for carry-over
            if inv.total_amount < 0:
                negative_carryover += inv.total_amount

            for item in inv.items:
                if item.product_id in po_product_ids:
                    fulfilled += (item.quantity * item.billed_unit_price)
                
                # Track 'Applied Deposit' system items
                if item.product.is_system:
                    applied_deposits += (item.quantity * item.billed_unit_price)

        # 3. Prepayments (Cash in at PO level)
        prepayments = sum(p.amount for p in self.payments if p.is_active and p.invoice_id is None)

        # 4. Math
        remaining_fulfillment = commitment - fulfilled
        
        # Applied deposits and Negative carryover are negative in DB, so we add them
        raw_credit_pool = prepayments + applied_deposits - negative_carryover
        clamped_credit = max(0, raw_credit_pool)

        return remaining_fulfillment - clamped_credit

class Invoice(db.Model, AuditMixin):
    __tablename__ = 'invoices'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), nullable=False)
    po_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    bill_to_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    invoice_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    carrier_id: Mapped[int | None] = mapped_column(ForeignKey('carriers.id'))
    ship_date: Mapped[date | None] = mapped_column(Date)
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default='draft')
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    order: Mapped["OrderRegistry"] = relationship(back_populates="invoices")
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="invoice")
    client: Mapped["Client"] = relationship(back_populates="invoices", foreign_keys=[client_id])
    bill_to: Mapped["Client"] = relationship(back_populates="invoice_billings", foreign_keys=[bill_to_id])
    carrier: Mapped["Carrier"] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Invoice.id==Attachment.entity_id, Attachment.entity_type=='Invoice')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True,
        order_by="Attachment.uploaded_at.asc()"
    )

    @property
    def total_due(self):
        """The actual billable amount (clamped to 0 for credits)."""
        return max(0, self.total_amount)

    @property
    def contextual_balance(self):
        """Calculates balance using payments already in the parent order's memory."""
        # Logic: Look at parent order's payments to find matches for THIS invoice
        if self.order and 'payments' in self.order.__dict__:
            applied_payments = sum(p.amount for p in self.order.payments 
                                if p.invoice_id == self.id and p.is_active)
            return self.total_due - applied_payments
        return self.total_due

class Payment(db.Model, AuditMixin):
    __tablename__ = 'payments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), nullable=False)
    po_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey('invoices.id'))
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    paid_from_id: Mapped[int] = mapped_column(ForeignKey('clients.id'), nullable=False)
    payment_type_id: Mapped[int | None] = mapped_column(ForeignKey('payment_types.id'))
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    order: Mapped["OrderRegistry"] = relationship(back_populates="payments")
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="payments")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="payments")
    client: Mapped["Client"] = relationship(back_populates="payments", foreign_keys=[client_id])
    paid_from: Mapped["Client"] = relationship(back_populates="paid_from_payments", foreign_keys=[paid_from_id])
    payment_type: Mapped["PaymentType"] = relationship()
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Payment.id==Attachment.entity_id, Attachment.entity_type=='Payment')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True,
        order_by="Attachment.uploaded_at.asc()"
    )

class Expense(db.Model, AuditMixin):
    __tablename__ = 'expenses'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    vendor_id: Mapped[int] = mapped_column(ForeignKey('vendors.id'), nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey('clients.id'))
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id'))
    po_id: Mapped[int | None] = mapped_column(ForeignKey('purchase_orders.id'))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey('invoices.id'))
    category_id: Mapped[int | None] = mapped_column(ForeignKey('expense_categories.id'))
    description: Mapped[str] = mapped_column(String(255), nullable=False) # The short summary
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    expense_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    status: Mapped[str] = mapped_column(String(20), default='open') # New: draft, open, completed
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    vendor: Mapped["Vendor"] = relationship(back_populates="expenses")
    client: Mapped["Client | None"] = relationship(back_populates="expenses")
    order: Mapped["OrderRegistry"] = relationship(back_populates="expenses")
    purchase_order: Mapped["PurchaseOrder | None"] = relationship(back_populates="expenses")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="expenses")
    category: Mapped["ExpenseCategory"] = relationship()
    items: Mapped[list["ExpenseItem"]] = relationship(back_populates="expense", cascade="all, delete-orphan")
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Expense.id==Attachment.entity_id, Attachment.entity_type=='Expense')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True,
        order_by="Attachment.uploaded_at.asc()"
    )

class Adjustment(db.Model, AuditMixin):
    __tablename__ = 'adjustments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    adjustment_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    category_id: Mapped[int | None] = mapped_column(ForeignKey('adjustment_categories.id'))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped["AdjustmentCategory"] = relationship()
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Adjustment.id==Attachment.entity_id, Attachment.entity_type=='Adjustment')",
        foreign_keys="[Attachment.entity_id]",
        viewonly=True,
        order_by="Attachment.uploaded_at.asc()"
    )


# --- 6. LINE ITEMS ---
class QuoteItem(db.Model):
    __tablename__ = 'quote_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey('quotes.id'), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    quoted_unit_price: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    quote: Mapped["Quote"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

class PoItem(db.Model):
    __tablename__ = 'po_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    agreed_unit_price: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey('invoices.id'), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    billed_unit_price: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped["Invoice"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class ExpenseItem(db.Model):
    __tablename__ = 'expense_items'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey('expenses.id'), nullable=False)
    catalog_number: Mapped[str | None] = mapped_column(String(100))
    item: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    expense: Mapped["Expense"] = relationship(back_populates="items")

# --- 7. UTILITIES ---
class Attachment(db.Model, AuditMixin):
    __tablename__ = 'attachments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False) 
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

# --- 8. AUDIT EVENT LISTENERS ---

def set_audit_fields(mapper, connection, target):
    """Automatically set user IDs from the Flask-Login context."""
    # If we are running run.py (no request context), skip auditing
    if not has_request_context():
        return
    # current_user.get_id() returns None if not authenticated or outside request context
    user_id = current_user.get_id()
    if user_id:
        if not target.created_by_id:
            target.created_by_id = int(user_id)
        target.updated_by_id = int(user_id)

# We list all models that should use this logic
AUDIT_MODELS = [Client, Vendor, Product, 
                OrderRegistry, Quote, PurchaseOrder, 
                Invoice, Payment, Expense, 
                Adjustment, Attachment]

for model in AUDIT_MODELS:
    event.listen(model, 'before_insert', set_audit_fields)
    event.listen(model, 'before_update', set_audit_fields)