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

def loop_leave_files(url=os.environ.get('LEAVE_FOLDER_URL'), latest_date=None):

    header = generate_header()

    drive_url = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/"

    logging.info(url)
    response = requests.get(url=url, headers=header)

    # response.raise_for_status()
    if not 200 <= response.status_code < 300:
        logging.info("something went wrong when getting files")
        logging.info(response.text)
        raise AzureSyncError("Connection to Azure failed")
    
    months = []

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
                    logging.info("something went wrong when getting sheets")
                    return
                for obj in sheets_resp.json()['value']:
                    month = obj['name']
                    month_int = int(datetime.strptime(month, "%B").month)
                    if not latest_date:
                        latest_date = current_sg_time()
                    if not month_int < latest_date.month:
                        months.append([month_int, year_int])
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