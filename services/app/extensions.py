from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from flask import has_request_context, current_app
import logging

from twilio.rest import Client
from routing.redis_client import Redis
from cryptography.fernet import Fernet
import os

db = SQLAlchemy()
twilio = Client(os.environ.get('TWILIO_ACCOUNT_SID'), os.environ.get('TWILIO_AUTH_TOKEN'))
redis_client = Redis(os.getenv("REDIS_URL"), Fernet(os.getenv("FERNET_KEY"))) # Fernet encryption key setup

ThreadSession = None

def init_thread_session(engine):
    global ThreadSession
    ThreadSession = scoped_session(sessionmaker(bind=engine))

def remove_thread_session():
    ThreadSession.remove()

def get_session():
    if has_request_context():
        logging.info("In app context")
        return current_app.extensions['sqlalchemy'].db.session
    else:
        logging.info("Not in app context")
        return ThreadSession()