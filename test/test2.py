quantities = [1,2,3]
unit_prices = [10,20,30]

items = [{'qty': q, 'price': p} for q, p in zip(quantities, unit_prices)]
print(items)