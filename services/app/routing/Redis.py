from extensions import redis_client
import json
import os
from cryptography.fernet import Fernet

FERNET_KEY_STR = os.getenv("FERNET_KEY") if int(os.getenv('LIVE')) else os.getenv('FERNET_KEY_DEV') # Fernet encryption key setup
FERNET_KEY = Fernet(FERNET_KEY_STR)

class RedisQueue:

    def __init__(self, name, namespace="queue"):
        self.key = f"{namespace}:{name}"

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
        self.key = f"{namespace}:{name}"

    def update(self, value):
        redis_client.set(self.key, value)
    
    def set(self, value, ex=60):
        """Set or delete a value in Redis based on its content."""
        if value is None:
            redis_client.delete(self.key)
        else:
            if isinstance(value, dict):
                value = json.dumps(value)
            encrypted_value = FERNET_KEY.encrypt(value.encode())
            redis_client.set(self.key, encrypted_value, ex=ex)

    def get(self):
        """Get and decrypt a value from Redis."""
        value = redis_client.get(self.key)
        if not value:
            return None
        try:
            decrypted_value = FERNET_KEY.decrypt(value).decode()
            return json.loads(decrypted_value)
        except json.JSONDecodeError:
            return decrypted_value
        