from extensions import redis_client
import json

class RedisQueue:
    def __init__(self, name, namespace='queue'):
        self.db = redis_client
        self.key = f"{namespace}:{name}"

    def put(self, item):
        self.db.rpush(self.key, json.dumps(item))

    def get(self, block=True, timeout=None):
        item = self.db.blpop(self.key, timeout=timeout) if block else self.db.lpop(self.key)
        return json.loads(item[1]) if item else None

    def is_empty(self):
        return self.db.llen(self.key) == 0