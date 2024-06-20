import shortuuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.types import Enum as SQLEnum
from sqlalchemy.orm import declared_attr

from extensions import db

from routing.RedisQueue import RedisCache

from models.jobs.base.constants import JOBS_PREFIX, ErrorMessage, Status
from models.jobs.base.utilities import current_sg_time

from models.messages.ForwardCallback import ForwardCallback

from models.exceptions import ReplyError

from MessageLogger import setup_logger

# from sqlalchemy.ext.declarative import AbstractConcreteBase

class Task(db.Model):

    __abstract__ = True

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')
    
    @declared_attr
    def created_at(cls):
        return db.Column(db.DateTime(timezone=True), nullable=False)
    
    @declared_attr
    def status(cls):
        return db.Column(SQLEnum(Status), nullable=True)

    def __init__(self, job_no, payload=None, user_id=None):
        self.id = shortuuid.ShortUUID().random(length=8)
        self.job_no = job_no # JOB_NO IS IMPLEMENTED IN THE CHILD CLASS
        self.user_id = user_id
        self.status = Status.PENDING
        self.background_tasks = []
        self.cache = RedisCache(f"{JOBS_PREFIX}:{self.job_no}")
        self.payload = payload
        self.created_at = current_sg_time()

    @property
    def cache(self):
        if not getattr(self, '_cache', None):
            self.cache = RedisCache(f"{JOBS_PREFIX}:{self.job_no}")
        return self._cache

    @cache.setter
    def cache(self, value):
        self._cache = value

    @property
    def background_tasks(self):
        if not getattr(self, '_background_tasks', None):
            self._background_tasks = []
        return self._background_tasks

    @background_tasks.setter
    def background_tasks(self, value):
        self._background_tasks = value

    def restore_cache(self, data):
        pass

    def update_cache(self):
        pass

    def run(self):
        data = self.cache.get()
        if data:
            self.restore_cache(data)

        try:
            self.execute() # FINAL STATE
            self.update_cache()
            self.status = Status.COMPLETED
            self.run_background_tasks()
        except Exception as e:
            self.status = Status.FAILED
            raise

    def execute(self):
        raise NotImplementedError("Please define an execute method for the task to update the history")

    def run_background_tasks(self):
        if len(self.background_tasks) == 0:
            return
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            for func, args in self.background_tasks:
                executor.submit(func, *args)

    def forwards_callback(self, successful_aliases, forward_callback: ForwardCallback):
        '''names of successful forwards'''

        if len(successful_aliases) == 0:
            raise ReplyError(
                ErrorMessage.NO_SUCCESSFUL_FORWARDS, 
                forward_callback.user_id,
                forward_callback.job_no, 
            )
        
        if not forward_callback:
            return

        self.background_tasks.append(
            (forward_callback.update_on_forwards, {
                'use_name_alias': True,
                'wait_time': 5
            }) # TODO check if job_no and seq_no can be accessed by the callback itself?
        )

    def get_callback_context(self):
        return "your request"