import shortuuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import declared_attr

from extensions import db, Session

from routing.Redis import RedisCache

from models.jobs.base.constants import JOBS_PREFIX, ErrorMessage, Status, OutgoingMessageData
from models.jobs.base.utilities import current_sg_time

from models.messages.ForwardCallback import ForwardCallback

from models.exceptions import ReplyError

from MessageLogger import setup_logger

# from sqlalchemy.ext.declarative import AbstractConcreteBase

class Task(db.Model):

    __abstract__ = True

    @declared_attr
    def id(cls):
        return db.Column(db.String(32), primary_key=True, nullable=False)

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')
    logger.propagate = False
    
    @declared_attr
    def created_at(cls):
        return db.Column(db.DateTime(timezone=True), nullable=False)
    
    @declared_attr
    def status(cls):
        return db.Column(db.String(10), nullable=True)
    
    @declared_attr
    def user_id(cls):
        return db.Column(db.ForeignKey("users.id"), nullable=True)

    def __init__(self, job_no, payload=None, user_id=None):
        self.id = shortuuid.ShortUUID().random(length=8)
        self.job_no = job_no # JOB_NO IS IMPLEMENTED IN THE CHILD CLASS
        self.user_id = user_id
        self.status = Status.PENDING
        self.background_tasks = []
        self.cache = RedisCache(f"{JOBS_PREFIX}:{self.job_no}")
        self.payload = payload
        self.created_at = current_sg_time()
        session = Session()
        session.add(self)
        session.commit()

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
        if hasattr(self, 'type'):
            self.logger.info(f"Task type: {self.type}; Data in cache: {self.cache.get()}")
    
        self.restore_cache(self.cache.get())

        session = Session()
        try:
            self.execute() # FINAL STATE
            self.cache.set(self.update_cache())
            self.status = Status.COMPLETED
            session.commit()
            self.logger.info("Running background tasks")
            self.run_background_tasks()
        except Exception as e:
            self.status = Status.FAILED
            session.commit()
            raise

    def execute(self):
        raise NotImplementedError("Please define an execute method for the task to update the history")

    def run_background_tasks(self):
        if len(self.background_tasks) == 0:
            return
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            for func, kwargs in self.background_tasks:
                executor.submit(func, **kwargs)

    def forwards_callback(self, forward_callback: ForwardCallback):
        '''names of successful forwards'''
        
        if not forward_callback:
            return
        
        self.logger.info("Adding to background tasks")

        self.background_tasks.append(
            (forward_callback.update_on_forwards, {
                'use_name_alias': True,
                'wait_time': 10
            }) # TODO check if job_no and seq_no can be accessed by the callback itself?
        )