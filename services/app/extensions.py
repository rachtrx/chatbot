from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy import create_engine
from flask import has_request_context, current_app
import logging

from twilio.rest import Client

import redis
from cryptography.fernet import Fernet
import os

db = SQLAlchemy()
twilio = Client(os.environ.get('TWILIO_ACCOUNT_SID'), os.environ.get('TWILIO_AUTH_TOKEN'))
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))
fernet_key = Fernet(os.getenv("FERNET_KEY")) # Fernet encryption key setup

ThreadSession = None

engine = create_engine(os.environ.get('DATABASE_URL'))
Session = scoped_session(sessionmaker(bind=engine))
