import os
from dotenv import load_dotenv

from twilio.rest import Client
import logging

env_path = f"/etc/environment"
load_dotenv(dotenv_path=env_path)

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = 10
    SQLALCHEMY_MAX_OVERFLOW = 20
    REDIS_URL = os.getenv("REDIS_URL")
    FERNET_KEY = os.getenv("FERNET_KEY")

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
twilio_client = Client(account_sid, auth_token)