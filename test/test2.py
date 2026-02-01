product_ids = ['1', '2', '3']
quantities = ['2', '3', '3']
unit_prices = ['100', '200', '300']
    
items = []
for product_id, qty, price in zip(product_ids, quantities, unit_prices):
    if product_id:
        items.append({
            'product_id': int(product_id),
            'quantity': int(qty) if qty else 1,
            'unit_price': int(price)
        })

print(items)



value = '   '
if value is None or (isinstance(value, str) and not value.strip()):
    print(value.strip())

a = None
print(a.strip())