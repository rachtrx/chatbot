from extensions import redis_client
import json

class RedisQueue:
    def __init__(self, name, namespace='queue', **redis_kwargs):
        self.db = redis_client
        self.key = f"{namespace}:{name}"

    def qsize(self):
        return self.db.llen(self.key)

    def put(self, item):
        self.db.rpush(self.key, json.dumps(item))

    def get(self, block=True, timeout=None):
        if block:
            item = self.db.blpop(self.key, timeout=timeout)
        else:
            item = self.db.lpop(self.key)
        
        if item:
            return json.loads(item[1])
        return None