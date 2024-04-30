from datetime import datetime, timedelta, date
from extensions import db, get_session
from constants import errors, LeaveType, LeaveIssue, leave_keywords, SelectionType, Decision, Intent, JobStatus
from dateutil.relativedelta import relativedelta
import os
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, join_with_commas_and, get_latest_date_past_9am, combine_with_key_increment
from overrides import overrides

from logs.config import setup_logger

from models.users import User
from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUser
from models.leave_records import LeaveRecord
import re
import traceback
from .utils_leave import dates
from sqlalchemy import Enum as SQLEnum

class JobAuthorise(JobUser):
    __tablename__ = "job_authorise"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    forwards_status = db.Column(db.Integer, default=None, nullable=True)
    local_db_updated = db.Column(db.Boolean(), nullable=False)
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_leave"
    }
