import requests
from datetime import datetime
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import ForeignKey
from logs.config import setup_logger
from utilities import get_relations_name_and_no_list
import json
import time

class Metric(db.Model):

    logger = setup_logger('models.metrics')

    __tablename__ = "metrics"
    
    user = db.Column(db.String(80), primary_key=True, nullable=False)
    number = db.Column(db.Integer(), unique=True, nullable=False)
    dept = db.Column(db.String(50), nullable=True)
    last_local_db_update = db.Column(db.DateTime(timezone=True), nullable=True)
    last_azure_db_update = db.Column(db.DateTime(timezone=True), nullable=True)

    def check_azure_sync_status(self, api_url):

        try:
            response = requests.get(api_url)
            status = "Available" if response.status_code == 200 else "Unavailable"
            response_time = response.elapsed.total_seconds()
        except requests.RequestException:
            status = "Unavailable"
            response_time = None
        
        last_checked = datetime.now()
        self.update_api_status(api_name=api_url, status=status, response_time=response_time, last_checked=last_checked)

    def update_azure_status():
        pass