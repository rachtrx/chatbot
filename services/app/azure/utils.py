import msal
import os
from dotenv import load_dotenv
import requests
from datetime import datetime
import logging
import time
from utilities import current_sg_time

from logs.config import setup_logger

env_path = "/home/app/web/.env"
load_dotenv(dotenv_path=env_path)

logger = setup_logger('az.utils')

config = {
    'client_id': os.environ.get('CLIENT_ID'),
    'client_secret': os.environ.get('CLIENT_SECRET'),
    'authority': os.environ.get('AUTHORITY'),
    'scope': [os.environ.get('SCOPE')],
    'site_id': os.environ.get('SITE_ID'),
}

# create an MSAL instance providing the client_id, authority and client_credential params
msal_instance = msal.ConfidentialClientApplication(config['client_id'], authority=config['authority'], client_credential=config['client_secret'])

class AzureSyncError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


def acquire_token(scope=config['scope']):
    # First, try to lookup an access token in cache
    token_result = msal_instance.acquire_token_silent(scope, account=None)
    # print("retrieving token")

    # If the token is available in cache, save it to a variable
    if token_result:
        print('Access token was loaded from cache')

    # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
    if not token_result:
        token_result = msal_instance.acquire_token_for_client(scopes=scope)
        # print(token_result)
        access_token = 'Bearer ' + token_result['access_token']

        print(f"Live env: {os.environ.get('LIVE')}")

        if os.environ.get('LIVE') == '1':
            # write the token to the file if on live, otherwise just use the token printed for postman
            print(f"Token path: {os.environ.get('TOKEN_PATH')}")
            with open(os.environ.get('TOKEN_PATH'), 'w') as file:
                file.write(access_token)

    return

def generate_header():
    with open(os.environ.get('TOKEN_PATH'), 'r') as file:
        token = file.read().strip()

    headers = {
        'Authorization': token,
        'Content-Type': 'application/json'
    }

    return headers

def loop_mc_files(url=os.environ.get('MC_FOLDER_URL')):

    header = generate_header()

    drive_url = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/"

    print(url)
    response = requests.get(url=url, headers=header)

    # response.raise_for_status()
    if not 200 <= response.status_code < 300:
        print("something went wrong when getting files")
        print(response.text)
        return
    
    for value in response.json()['value']:
        if value['name'].endswith(".xlsx"):
            year = value['name'].split('.')[0]
            year_int = int(year)
            current_year = current_sg_time().year
            if not year_int < current_year:
                new_url = drive_url + value['id'] + '/workbook/worksheets'
                logging.info(f"getting worksheets: {new_url}")
                sheets_resp = requests.get(url=new_url, headers=header)
                if not 200 <= sheets_resp.status_code < 300:
                    print("something went wrong when getting sheets")
                    return
                months = []
                for obj in sheets_resp.json()['value']:
                    month = obj['name']
                    month_int = datetime.strptime(month, "%B").month
                    if not month_int < current_sg_time().month:
                        months.append(f"{obj['name']}-{year}")
                return months
        else:
            continue

    return months

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

if __name__ == "__main__":
    acquire_token()