from math import ceil

class ManualPagination:
    """
    Helper to mimic Flask-SQLAlchemy Pagination for manual queries.
    """
    def __init__(self, items, page, per_page, total, sort_by=None, direction=None):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.sort_by = sort_by
        self.direction = direction

    @property
    def pages(self):
        if self.per_page == 0 or self.total is None:
            return 0
        return ceil(self.total / self.per_page)

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1

    @property
    def next_num(self):
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num