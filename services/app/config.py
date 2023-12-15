import os
from azure_upload import SpreadsheetManager
from dotenv import load_dotenv

from twilio.rest import Client

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)
print(f" Live in app: {os.environ.get('LIVE')}")

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:

    # Database
    if not os.getenv("DATABASE_URL") is None:
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
        STATIC_FOLDER = os.path.join(os.getenv("APP_FOLDER"), "project", "static")
        UPLOADS_FOLDER = os.path.join(os.getenv("APP_FOLDER"), "project", "uploads")
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'chatbot.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

manager = SpreadsheetManager()

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)