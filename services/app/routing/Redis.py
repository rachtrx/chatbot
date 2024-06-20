from extensions import redis_client
import json

class RedisQueue:
    def __init__(self, name, namespace="queue"):
        self.db = redis_client
        self.key = f"{namespace}:{name}"

    def push(self, item):
        self.db.lpush(self.key, json.dumps(item))

    def enqueue(self, item):
        self.db.rpush(self.key, json.dumps(item))

    def get(self, block=True, timeout=None):
        if block:
            item = self.db.blpop(self.key, timeout=timeout)
            value = item[1] if item else None
        else:
            value = self.db.lpop(self.key)
        return json.loads(value) if value else None

    def is_empty(self):
        return self.db.llen(self.key) == 0
    
class RedisCache:
    def __init__(self, name, namespace="cache"):
        self.db = redis_client
        self.key = f"{namespace}:{name}"

    def update(self, value):
        self.db.set(self.key, value)
    
    def get(self):
        return self.db.get(self.key)
    
    def set(self, value, ex=120):
        if value is None:  # or any other condition indicating a delete operation
            self.db.delete(self.key)
        else:
            self.db.set(self.key, value, ex=ex)