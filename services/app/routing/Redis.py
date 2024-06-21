from extensions import redis_client, fernet_key
import json

class RedisQueue:

    def __init__(self, name, namespace="queue"):
        self.key = f"{namespace}:{name}"

    def push(self, item):
        redis_client.lpush(self.key, json.dumps(item))

    def enqueue(self, item):
        redis_client.rpush(self.key, json.dumps(item))

    def get(self, block=True, timeout=None):
        if block:
            item = redis_client.blpop(self.key, timeout=timeout)
            value = item[1] if item else None
        else:
            value = redis_client.lpop(self.key)
        return json.loads(value) if value else None

    def is_empty(self):
        return redis_client.llen(self.key) == 0
    
class RedisCache:
    def __init__(self, name, namespace="cache"):
        redis_client = redis_client
        self.key = f"{namespace}:{name}"

    def update(self, value):
        redis_client.set(self.key, value)
    
    def set(self, value, ex=120):
        """Set or delete a value in Redis based on its content."""
        if value is None:
            redis_client.delete(self.key)
        else:
            encrypted_value = fernet_key.encrypt(value.encode())
            redis_client.set(self.key, encrypted_value, ex=ex)

    def get(self):
        """Get and decrypt a value from Redis."""
        value = redis_client.get(self.key)
        if value:
            decrypted_value = fernet_key.decrypt(value).decode()
            return decrypted_value
        return None