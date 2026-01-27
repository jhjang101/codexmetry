from app import create_app
from app.services.purchase_orders_service import PurchaseOrderService
from app.services.quotes_service import QuoteService
from sqlalchemy import inspect

app = create_app()

with app.app_context():
    pagination = QuoteService.get_all_with_search() # or whatever method hits the DB

    print(pagination)
    
    item = pagination.items[0]
    item_keys = []
    for column in inspect(item).mapper.column_attrs:
        item_keys.append(column.key)
    
    item_by_id = QuoteService.get_by_id(1)
    item_by_id_keys = []
    for column in inspect(item_by_id).mapper.column_attrs:
        item_by_id_keys.append(column.key)

    print(item_keys)
    print(item_by_id_keys)
    print(item_by_id.quote_number)