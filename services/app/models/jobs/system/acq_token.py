from extensions import db
from .abstract import JobSystem
from logs.config import setup_logger
import os
import msal
from constants import OK, SERVER_ERROR
from azure.utils import generate_header
import requests
import traceback
from utilities import current_sg_time
from datetime import datetime
import json
import logging

class JobAcqToken(JobSystem):

    logger = setup_logger('az.acq_token')

    __tablename__ = 'job_acq_token'
    job_no = db.Column(db.ForeignKey("job_system.job_no"), primary_key=True)

    __mapper_args__ = {
        "polymorphic_identity": "job_acq_token"
    }

    config = {
        'client_id': os.environ.get('CLIENT_ID'),
        'client_secret': os.environ.get('CLIENT_SECRET'),
        'authority': os.environ.get('AUTHORITY'),
        'scope': [os.environ.get('SCOPE')],
        'site_id': os.environ.get('SITE_ID'),
    }

    def __init__(self):
        super().__init__() # admin name is default
        # create an MSAL instance providing the client_id, authority and client_credential params
        self.msal_instance = msal.ConfidentialClientApplication(self.config['client_id'], authority=self.config['authority'], client_credential=self.config['client_secret'])
        self.scope = self.config['scope']

    def update_table_urls(self):
        
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

    def main(self):
        try:
            self.token = self.msal_instance.acquire_token_silent(self.scope, account=None)
            # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
            if not self.token:
                self.token = self.msal_instance.acquire_token_for_client(scopes=self.scope)

        except Exception as e:
            self.error = True
            self.reply = "Failed to retrieve token. Likely due to Client Secret Expiration. To create a new Client Secret, go to Microsoft Entra ID → Applications → App Registrations → Chatbot → Certificates & Secrets → New client secret. Then send it to me with the syntax"
            raise

        access_token = 'Bearer ' + self.token['access_token']

        logging.info(f"Live env: {os.environ.get('LIVE')}")

        if os.environ.get('LIVE') == '1':
            logging.info(f"Token path: {os.environ.get('TOKEN_PATH')}")
            with open(os.environ.get('TOKEN_PATH'), 'w') as file:
                file.write(access_token)

        logging.info("Access token retrieved.")

        try:
            self.update_table_urls()
            self.reply = "Access token retrieved."
        except Exception as e:
            logging.error(traceback.format_exc())
            self.reply = "Access token retrieved. Also, there might have been an issue with the Azure table URLs."

        return self.reply
        

        