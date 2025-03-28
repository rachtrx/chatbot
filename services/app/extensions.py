from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import scoped_session, sessionmaker
from flask import has_request_context, current_app
import logging

db = SQLAlchemy()

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