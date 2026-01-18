from .base_service import BaseService
from app.models import (
    SettingsMetadata, PoType, ProductCategory, 
    ExpenseCategory, PaymentType, TransactionCategory
)

class MetadataService(BaseService):
    model = SettingsMetadata

class PoTypeService(BaseService):
    model = PoType

class ProductCategoryService(BaseService):
    model = ProductCategory

class ExpenseCategoryService(BaseService):
    model = ExpenseCategory

class PaymentTypeService(BaseService):
    model = PaymentType

class TransactionCategoryService(BaseService):
    model = TransactionCategory