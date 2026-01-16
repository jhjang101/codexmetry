from .extensions import db, login_manager
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. AUTH ---
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='user') # admin, user
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 2. LOOKUP TABLES ---
class PoType(db.Model):
    __tablename__ = 'po_types'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class ProductCategory(db.Model):
    __tablename__ = 'product_categories'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class ExpenseCategory(db.Model):
    __tablename__ = 'expense_categories'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class PaymentType(db.Model):
    __tablename__ = 'payment_types'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class TransactionCategory(db.Model):
    __tablename__ = 'transaction_categories'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

# --- 3. SETTINGS ---
class SettingsMetadata(db.Model):
    __tablename__ = 'settings_metadata'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), default='Codexmetry Corp')
    address = db.Column(db.Text)
    company_logo = db.Column(db.String(255))
    timezone = db.Column(db.String(100), default='America/Chicago')
    invoice_threshold = db.Column(db.Integer, default=10000)
    doc_padding = db.Column(db.Integer, default=4)

# --- 4. MASTER DATA ---
class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    contacts = db.relationship('ClientContact', backref='client', cascade="all, delete-orphan")

class ClientContact(db.Model):
    __tablename__ = 'client_contacts'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(255))

class Vendor(db.Model):
    __tablename__ = 'vendors'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(255))
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    contacts = db.relationship('VendorContact', backref='vendor', cascade="all, delete-orphan")

class VendorContact(db.Model):
    __tablename__ = 'vendor_contacts'
    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(255))

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    catalog_number = db.Column(db.String(100))
    category_id = db.Column(db.Integer, db.ForeignKey('product_categories.id'))
    image_url = db.Column(db.String(255))
    default_unit_price = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

# --- 5. REGISTRY & SALES ---
class OrderRegistry(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False) # CDX-YY0000
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    is_active = db.Column(db.Boolean, default=True)

class Quote(db.Model):
    __tablename__ = 'quotes'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    quote_number = db.Column(db.String(100), nullable=False) # Manual or Q-YY0000
    total_amount = db.Column(db.Integer, default=0)
    quote_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    expiration_date = db.Column(db.Date) # Added per PRD
    status = db.Column(db.String(20), default='draft') # draft, sent, accepted, expired
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id')) # Optional: Linked after conversion
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    items = db.relationship('QuoteItem', backref='quote', cascade="all, delete-orphan")

class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    bill_to_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    po_number = db.Column(db.String(100)) # Client reference
    total_amount = db.Column(db.Integer, default=0)
    po_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    po_type_id = db.Column(db.Integer, db.ForeignKey('po_types.id'))
    status = db.Column(db.String(20), default='open')
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    items = db.relationship('PoItem', backref='po', cascade="all, delete-orphan")

class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    bill_to_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    invoice_number = db.Column(db.String(100), nullable=False) # Manual or INV-YY0000
    total_amount = db.Column(db.Integer, default=0)
    invoice_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    tracking_number = db.Column(db.String(100))
    status = db.Column(db.String(20), default='open')
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    items = db.relationship('InvoiceItem', backref='invoice', cascade="all, delete-orphan")

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    paid_from_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    payment_type_id = db.Column(db.Integer, db.ForeignKey('payment_types.id'))
    amount = db.Column(db.Integer, nullable=False)
    payment_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    expense_number = db.Column(db.String(20), unique=True, nullable=False) # EXP-YY0000
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_categories.id'))
    total_amount = db.Column(db.Integer, default=0)
    expense_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    items = db.relationship('ExpenseItem', backref='expense', cascade="all, delete-orphan")

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(20), unique=True, nullable=False) # TRX-YY0000
    description = db.Column(db.String(255))
    amount = db.Column(db.Integer, nullable=False) # Positive for gain, Negative for loss
    transaction_date = db.Column(db.Date, server_default=db.func.current_timestamp())
    category_id = db.Column(db.Integer, db.ForeignKey('transaction_categories.id'))
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

# --- 6. LINE ITEMS ---
class QuoteItem(db.Model):
    __tablename__ = 'quote_items'
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quotes.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    quoted_unit_price = db.Column(db.Integer, default=0)

class PoItem(db.Model):
    __tablename__ = 'po_items'
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    agreed_unit_price = db.Column(db.Integer, default=0)

class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    billed_unit_price = db.Column(db.Integer, default=0)

class ExpenseItem(db.Model):
    __tablename__ = 'expense_items'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    item = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Integer, default=0)

# --- 7. UTILITIES ---
class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False) # 'Quote', 'PO', etc.
    entity_id = db.Column(db.Integer, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())