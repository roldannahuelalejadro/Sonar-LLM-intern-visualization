from collections import deque


class History:
    def __init__(self, budget_bytes):
        self._items = deque()
        self.used_bytes = 0
        self.evicted = 0
        self.resize(budget_bytes)

    def __len__(self):
        return len(self._items)

    def append(self, sample):
        if sample.accounted_bytes > self.budget_bytes:
            self.evicted += 1
            return False
        self._items.append(sample)
        self.used_bytes += sample.accounted_bytes
        self._evict()
        return True

    def resize(self, budget_bytes):
        if type(budget_bytes) is not int or budget_bytes < 4096:
            raise ValueError("Historial: presupuesto minimo 4096 bytes")
        self.budget_bytes = budget_bytes
        self._evict()

    def _evict(self):
        while self.used_bytes > self.budget_bytes:
            self.used_bytes -= self._items.popleft().accounted_bytes
            self.evicted += 1

    def samples(self, probe_id=None):
        return [s for s in self._items if probe_id is None or s.probe_id == probe_id]

