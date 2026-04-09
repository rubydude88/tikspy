import time


class TTLCache:
    def __init__(self, ttl: int = 600, max_size: int = 30):
        self._store: dict = {}
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key: str):
        if key not in self._store:
            return None
        data, timestamp = self._store[key]
        if time.time() - timestamp > self._ttl:
            del self._store[key]
            return None
        return data

    def set(self, key: str, value):
        if len(self._store) >= self._max_size:
            oldest_key = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest_key]
        self._store[key] = (value, time.time())

    def make_key(self, *args) -> str:
        return ":".join(str(a) for a in args)
