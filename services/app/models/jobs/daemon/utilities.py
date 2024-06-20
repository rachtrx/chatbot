import os
import time

from models.exceptions import AzureSyncError

def generate_header(token=None):
    
    if not token:
        with open(os.environ.get('TOKEN_PATH'), 'r') as file:
            token = file.read().strip()

    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }

    return headers

def delay_decorator(message, seconds = 1, retries = 5):
    def outer_wrapper(func):
        def inner_wrapper(*args, **kwargs):
            count = 0
            while (count < retries):
                response = func(*args, **kwargs)
                # logging.info(f"{response.status_code}, {response.text}")
                if 200 <= response.status_code < 300:
                    return response
                else:
                    time.sleep(seconds)
                count += 1
            raise AzureSyncError(f"{message}. {response.text}")
            
        return inner_wrapper
    return outer_wrapper