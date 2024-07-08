from extensions import db

import os
import msal
import requests
import traceback
from datetime import datetime
import json
import logging

from models.jobs.base.utilities import current_sg_time

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage
from models.jobs.daemon.utilities import generate_header

class AcquireToken(TaskDaemon):

    name = "Token Retrieval"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.ACQUIRE_TOKEN
    }

    config = {
        'client_id': os.getenv('CLIENT_ID'),
        'client_secret': os.getenv('CLIENT_SECRET'),
        'authority': os.getenv('AUTHORITY'),
        'scope': [os.getenv('SCOPE')],
        'site_id': os.getenv('SITE_ID'),
    }

    def get_err_body(self) -> str:
        return DaemonMessage.TOKEN_NOT_ACQUIRED

    def execute(self):

        msal_instance = msal.ConfidentialClientApplication(self.config['client_id'], authority=self.config['authority'], client_credential=self.config['client_secret'])
        scope = self.config['scope']

        try:
            token = msal_instance.acquire_token_silent(scope, account=None)
            # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
            if not token:
                token = msal_instance.acquire_token_for_client(scopes=scope)

            access_token = 'Bearer ' + token['access_token']

            self.logger.info(token['access_token'])

        except Exception as e:
            self.body = DaemonMessage.SECRET_EXPIRED
            raise

        try:
            with open(os.getenv('TOKEN_PATH'), 'w') as file:
                file.write(access_token)
        
            self.update_table_urls()
            self.body = DaemonMessage.TOKEN_ACQUIRED
        except Exception as e:
            logging.error(traceback.format_exc())
            self.body = DaemonMessage.TABLE_URL_CHANGED
            raise

        return

    def update_table_urls(self): # TO PLACE IN AZURE?
        
        table_url_dict = {}

        if os.path.exists('/home/app/web/logs/table_urls.json') and os.path.getsize('/home/app/web/logs/table_urls.json') > 0:
            try:
                with open('/home/app/web/logs/table_urls.json', 'r') as file:
                    table_url_dict = json.loads(file.read())
            except json.JSONDecodeError:
                self.logger.info(traceback.format_exc())

        changed = False
        current_month = current_sg_time().month
        current_year = current_sg_time().year

        for mmyy, url in list(table_url_dict.items()):  # Use list() to avoid RuntimeError
            month_name, year = mmyy.split("-")
            month = datetime.strptime(month_name, "%B").month
            if (int(year) == current_year and current_month > month) or int(year) < current_year:
                table_url_dict.pop(mmyy)
                changed = True
            else:
                response = requests.get(url=url, headers=generate_header())
                if response.status_code != 200:
                    table_url_dict.pop(mmyy)
                    changed = True

        if changed:
            self.logger.info("File has changed")
            with open("/home/app/web/logs/table_urls.json", 'w') as file:
                file.write(json.dumps(table_url_dict, indent=4))
        

        