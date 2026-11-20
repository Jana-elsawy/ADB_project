from collections import OrderedDict


class ReplacementPolicy:
    def __init__(self):
        self.order = OrderedDict()

    def record_access(self, page_id):
        raise NotImplementedError

    def remove(self, page_id):
        self.order.pop(page_id, None)

    def evict(self, candidates):
        for page_id in self.order:
            if page_id in candidates:
                return page_id
        return None


class LRUPolicy(ReplacementPolicy):
    """Least recently used: move a page to the newest position on every access."""

    def record_access(self, page_id):
        self.order.pop(page_id, None)
        self.order[page_id] = None


class FIFOPolicy(ReplacementPolicy):
    """First in, first out: only the first load establishes the order."""

    def record_access(self, page_id):
        if page_id not in self.order:
            self.order[page_id] = None


def make_policy(policy):
    if isinstance(policy, str):
        name = policy.lower()
        if name == "lru":
            return LRUPolicy()
        if name == "fifo":
            return FIFOPolicy()
        raise ValueError("policy must be 'lru' or 'fifo'")
    return policy
