from .extensions import db, login_manager
from flask import has_request_context
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr
from sqlalchemy import String, Integer, Boolean, DateTime, Date, Text, ForeignKey, func, event
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

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
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

class ExpenseCategory(db.Model):
    __tablename__ = 'expense_categories'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class PaymentType(db.Model):
    __tablename__ = 'payment_types'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class TransactionCategory(db.Model):
    __tablename__ = 'transaction_categories'
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
            return name if name else "-"
        return "-"

    @property
    def primary_contact_email(self):
        """Returns email or '-'."""
        c = self.primary_contact
        return c.email if (c and c.email) else "-"
    
    @property
    def full_display(self):
        """Returns 'Company Name (Contact Name)' or just 'Company Name'"""
        if self.contacts:
            contact = self.contacts[0]
            name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            return f"{self.company_name} ({name})" if name else self.company_name
        return self.company_name

class ClientContact(db.Model):
    __tablename__ = 'client_contacts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id'))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))

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

class VendorContact(db.Model):
    __tablename__ = 'vendor_contacts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey('vendors.id'))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))

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
        """Formula: po_total - sum(invoice_total_due) - sum(prepayments)"""
        if self.order and 'invoices' in self.order.__dict__ and 'payments' in self.order.__dict__:
            # Sum only positive billed amounts
            billed = sum(inv.total_due for inv in self.order.invoices 
                        if inv.po_id == self.id and inv.is_active)
            # Sum payments applied to PO but not yet to an invoice
            prepaid = sum(p.amount for p in self.order.payments 
                        if p.po_id == self.id and p.invoice_id is None and p.is_active)
            return self.total_amount - billed - prepaid
        return self.total_amount

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
    tracking_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default='open')
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    order: Mapped["OrderRegistry"] = relationship(back_populates="invoices")
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="invoice")
    client: Mapped["Client"] = relationship(back_populates="invoices", foreign_keys=[client_id])
    bill_to: Mapped["Client"] = relationship(back_populates="invoice_billings", foreign_keys=[bill_to_id])
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

class Transaction(db.Model, AuditMixin):
    __tablename__ = 'transactions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_number: Mapped[str] = mapped_column(String(100), nullable=False) # Not unique
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    category_id: Mapped[int | None] = mapped_column(ForeignKey('transaction_categories.id'))
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped["TransactionCategory"] = relationship()
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Transaction.id==Attachment.entity_id, Attachment.entity_type=='Transaction')",
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
                Transaction, Attachment]

for model in AUDIT_MODELS:
    event.listen(model, 'before_insert', set_audit_fields)
    event.listen(model, 'before_update', set_audit_fields)