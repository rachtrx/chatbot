import os

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