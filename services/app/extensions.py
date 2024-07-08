from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy import create_engine
from flask import has_request_context, current_app
import logging

from twilio.rest import Client

import redis
import os

db = SQLAlchemy()
twilio = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))

engine = create_engine(os.getenv('DATABASE_URL'))
Session = scoped_session(sessionmaker(bind=engine))
