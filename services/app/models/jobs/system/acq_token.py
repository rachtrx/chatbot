from extensions import db
from .abstract import JobSystem
from logs.config import setup_logger
import os
import msal
from constants import OK, FAILED

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

    def main(self):
        try:
            self.token = self.msal_instance.acquire_token_silent(self.scope, account=None)
            # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
            if not self.token:
                self.token = self.msal_instance.acquire_token_for_client(scopes=self.scope)
        except Exception as e:
            self.task_status = FAILED
            return "Failed to acquire Access Token. Likely due to Client Secret Expiration. To create a new Client Secret, go to Microsoft Entra ID → Applications → App Registrations → Chatbot → Certificates & Secrets → New client secret. Then send it to me with the syntax"

        access_token = 'Bearer ' + self.token['access_token']

        print(f"Live env: {os.environ.get('LIVE')}")

        if os.environ.get('LIVE') == '1':
            # write the token to the file if on live, otherwise just use the token printed for postman
            print(f"Token path: {os.environ.get('TOKEN_PATH')}")
            with open(os.environ.get('TOKEN_PATH'), 'w') as file:
                file.write(access_token)

        return "Successfully retrieved Access Token"