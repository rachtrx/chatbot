import os
import requests
from datetime import datetime
import logging
import time
from utilities import current_sg_time
from models.exceptions import AzureSyncError

from logs.config import setup_logger

def generate_header(token=None):
    
    if not token:
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