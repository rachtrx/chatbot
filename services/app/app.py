import os

import traceback
import threading

from flask import request, Response
from flask.cli import with_appcontext
from flask_apscheduler import APScheduler

import logging
from MessageLogger import LOG_LEVEL
logging.basicConfig(
    filename='/home/app/web/logs/app.log',  # Log file path
    filemode='a',  # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
    level=LOG_LEVEL  # Log level
)
logging.getLogger('twilio.http_client').setLevel(logging.WARNING)

from manage import create_app
from extensions import twilio, Session

from routing.Scheduler import job_scheduler

from models.users import User

from models.exceptions import UserNotFoundError, EnqueueMessageError

from models.messages.MessageKnown import MessageKnown
from models.messages.MessageUnknown import MessageUnknown
from models.messages.SentMessageStatus import SentMessageStatus

from models.jobs.base.Job import Job
from models.jobs.base.constants import JobType, ErrorMessage, UserState, MessageType, MESSAGING_SERVICE_SID, OutgoingMessageData
from models.jobs.base.utilities import set_user_state, check_user_state, current_sg_time

from models.jobs.daemon.constants import DaemonTaskType

from models.jobs.leave.constants import AM_HOUR, PM_HOUR

# from es.manage import loop_through_files, create_index

# logger = logging.getLogger('sqlalchemy.engine.Engine')
# # logger = logging.getLogger('redis')
# logger.setLevel(logging.INFO)

# @app.cli.command("create_new_index")
# @with_appcontext
# def create_new_index():
#     create_index()

# @app.cli.command("loop_files")
# @with_appcontext
# def loop_files():
#     with app.app_context():
#         temp_url = os.getenv('TEMP_FOLDER_URL')
#         loop_through_files(temp_url)

app = create_app()
scheduler = APScheduler()

def setup_azure():

    session = Session()

    try:
        job_no = Job.create_job(JobType.DAEMON)
        tasks_to_run = [DaemonTaskType.ACQUIRE_TOKEN, DaemonTaskType.SYNC_USERS, DaemonTaskType.SEND_PM_REPORT]
        # tasks_to_run = [DaemonTaskType.ACQUIRE_TOKEN, DaemonTaskType.SYNC_USERS, DaemonTaskType.SYNC_LEAVES]
        job_scheduler.add_to_queue(item_id=job_no, payload=tasks_to_run)
        session.commit()
        logging.info("Added daemon job")
    except Exception as e:
        session.rollback() # TODO
        raise
    finally:
        Session.remove()

def setup_es():
    # create_new_index()
    # loop_files()
    pass

from datetime import timedelta, datetime

# report_time = current_sg_time() + timedelta(minutes=1)
# logging.info(f"Reminder Time: {report_time.hour}:{report_time.minute}")

# reminder_time = current_sg_time() + timedelta(minutes=2)
# logging.info(f"Reminder Time: {reminder_time.hour}:{reminder_time.minute}")

# approval_time = current_sg_time() + timedelta(minutes=3)
# logging.info(f"Approval Time: {approval_time.hour}:{approval_time.minute}")

@scheduler.task('cron', id='health_check', minute='*/15')
def execute():
    tasks_to_run = []

    cur_datetime = current_sg_time()
    logging.info(cur_datetime)

    minute = cur_datetime.minute

    logging.info(f"{minute}, {cur_datetime.hour}")

    if minute % 15 == 0:
        tasks_to_run.append(DaemonTaskType.SYNC_LEAVES)
        tasks_to_run.append(DaemonTaskType.SYNC_USERS) # this should be more regular than acquire

    if minute % 30 == 0:
        tasks_to_run.append(DaemonTaskType.ACQUIRE_TOKEN)
    
    if cur_datetime.weekday() not in [5, 6]:
        if minute == 0 and cur_datetime.hour == AM_HOUR: # bool
            tasks_to_run.append(DaemonTaskType.SEND_AM_REPORT)
            tasks_to_run.append(DaemonTaskType.CLEAN_TASKS)

    if cur_datetime.weekday() not in [4, 5]:
        if minute == 0 and cur_datetime.hour == PM_HOUR:
            tasks_to_run.append(DaemonTaskType.SEND_PM_REPORT)

    if len(tasks_to_run) == 0:
        return

    try:
        job_no = Job.create_job(JobType.DAEMON)
        job_scheduler.add_to_queue(item_id=job_no, payload=tasks_to_run)
    except UserNotFoundError as e:
        e.execute()
    
@app.route('/chatbot/enqueue_message', methods=['POST'])
def enqueue_message():
    session = Session()
    user = message = None
    try:
        for key in request.values:
            logging.info(f"{key}: {request.values[key]}")
        logging.info("end message")

        from_no = request.form.get("From")
        logging.info(f"From no: {from_no}")
        body = request.form.get('Body')
        sid = request.form.get('MessageSid')
        
        if check_user_state(from_no, UserState.BLOCKED):
            return
        
        # set user_id
        user = User.get_user(from_no)
        if not user:
            set_user_state(from_no, UserState.BLOCKED, timeout=3600)
            incoming_msg = MessageUnknown(user_no=from_no, sid=sid, msg_type=MessageType.RECEIVED, body=body)
            session.add(incoming_msg)
            session.commit()
            raise UserNotFoundError(user_no=from_no)
        
        message = MessageKnown(
            sid=sid, 
            msg_type=MessageType.RECEIVED, 
            body=body,
            user_id=user.id
        )

        session.add(message)
        session.commit()

        replied_msg_sid = request.form.get('OriginalRepliedMessageSid', None)
        
        # SET JOB NO
        if not replied_msg_sid:
            if check_user_state(user.id, UserState.PROCESSING):
                raise EnqueueMessageError(sid=sid, user_id=user.id, incoming_body=body, body=ErrorMessage.DOUBLE_MESSAGE)
            elif check_user_state(user.id, UserState.PENDING):
                raise EnqueueMessageError(sid=sid, user_id=user.id, incoming_body=body, body=ErrorMessage.PENDING_DECISION)
            else:
                message.job_no = Job.create_job(MessageKnown.get_intent(body), primary_user_id=user.id)
                session.commit()
        else:
            try:
                message.job_no = session.query(MessageKnown).with_entities(MessageKnown.job_no).filter_by(sid=replied_msg_sid).scalar()
                session.commit()
            except AttributeError:
                raise EnqueueMessageError(sid=sid, user_id=user.id, incoming_body=body, body=ErrorMessage.UNKNOWN_ERROR)

        set_user_state(user.id, UserState.PROCESSING)
        
        logging.info(f"From No: {from_no}, Message: {request.form.get('Body')}")

        job_scheduler.add_to_queue(item_id=message.job_no, payload=message.sid)
        
    except (EnqueueMessageError, UserNotFoundError) as e: # problem
        e.execute()

    except Exception:
        if user:
            err_msg = OutgoingMessageData(
                user_id=user.id,
                msg_type=MessageType.SENT,
                job_no=message.job_no if hasattr(message, 'job_no') else None,
                content_sid=os.getenv('UNKNWON_ERROR_SID')
            )
            MessageKnown.send_msg(err_msg)
    finally:
        logging.info("Message Enqueued, ready to accept new HTTP Requests")
        Session.remove()
        return Response(status=200)

@app.route("/chatbot/message_callback", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming text message updates."""
    session = Session()

    # logging.info("start callback")
    # for key in request.values:
    #     logging.info(f"{key}: {request.values[key]}")
    # logging.info("end callback")

    try:
        status = request.form.get('MessageStatus')
        sid = request.values.get('MessageSid')

        # logging.info(f"callback received, status: {status}, sid: {sid}")
        
        # check if this is a forwarded message, which would have its own ID
        session = Session()

        sent_msg = session.query(SentMessageStatus).get(sid)

        if sent_msg:
            if sent_msg.message.body is None:
                sent_msg.update_message_body()
            sent_msg.update_message_status(status)

        # else:
            # logging.info(f"not a sent message, {sid}")
            
    except Exception as e:
        logging.error(traceback.format_exc())

    finally:
        Session.remove()
        return Response(status=200)

logging.info("Setting up Azure")
setup_azure()
scheduler.init_app(app)
scheduler.start()