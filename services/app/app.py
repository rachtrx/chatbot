from dotenv import load_dotenv
env_path = f"/etc/environment"
load_dotenv(dotenv_path=env_path)

import os
from datetime import datetime

from flask import Flask, request, Response
from flask.cli import with_appcontext
import logging
import traceback
from sqlalchemy import inspect, event

from manage import create_app
from extensions import db, redis_client, twilio

from models.users import User
from models.messages.received import MessageReceived
from models.messages.abstract import Message

from tasks import main as create_task

from es.manage import loop_through_files, create_index

from constants import SystemOperation, SelectionType, JobStatus

import os
from sqlalchemy import create_engine
from extensions import init_thread_session

import jsonify
import json
import time

from routing.MessageHandler import MessageHandler
from routing.JobScheduler import JobScheduler
from routing.RedisQueue import RedisQueue

import threading
from dataclasses import dataclass
from typing import Optional

from utilities import log_level

# logger = logging.getLogger('sqlalchemy.engine.Engine')
# # logger = logging.getLogger('redis')
# logger.setLevel(logging.INFO)
# file_handler = logging.FileHandler('/var/log/sqlalchemy_engine.log')
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)

app = create_app()

@app.cli.command("setup_azure")
@with_appcontext
def setup_azure():
    create_task([SystemOperation.ACQUIRE_TOKEN, SystemOperation.SYNC_USERS, SystemOperation.SYNC_LEAVE_RECORDS])
    # create_task([system['ACQUIRE_TOKEN'], system['SYNC_USERS']])

@app.cli.command("create_new_index")
@with_appcontext
def create_new_index():
    create_index()

@app.cli.command("loop_files")
@with_appcontext
def loop_files():
    with app.app_context():
        temp_url = os.environ.get('TEMP_FOLDER_URL')
        loop_through_files(temp_url)

def log_table_creation(target, connection, **kw):
    logging.info(f"Creating table: {target.name}")

@app.cli.command("remove_db")
@with_appcontext
def remove_db():
    db.drop_all()
    db.session.commit()

@app.cli.command("seed_db")
@with_appcontext
def seed_db():
    user = User("Rachmiel", "12345678", "rach@rach")
    db.session.add(user)
    db.session.commit()

@dataclass
class NewMessageData:
    from_no: str
    user_str: str
    sid: str
    replied_msg_sid: Optional[str] = None
    selection: Optional[int] = None
    
@app.route('/enqueue_message', methods=['POST'])
def enqueue_message():
    try:
        from_no = request.form.get("From")
        logging.info(f"FROMNO: {from_no}")
        user_str = MessageReceived.get_message(request)
        sid = MessageReceived.get_sid(request)

        replied_msg_sid = request.form.get('OriginalRepliedMessageSid', None)
        selection = None
        if request.form.get('ButtonPayload', None):
            selection = int(request.form['ButtonPayload'])
        elif request.form.get('ListId', None):
            selection = int(request.form['ListId'])
        message = NewMessageData(user_str, sid, replied_msg_sid, selection)

        logging.info(f"User made a selection: {request.form.get('Body')}")

        user_id = redis_client.hash_identifier(str(from_no))

        # Check for timeout
        if check_user_processing_state(user_id):
            return jsonify({"status": "User is currently processing another request. Please wait."}), 429

        response = message_handler.handle_message(message)
        if response["status"] == "User is currently processing another request. Please wait.":
            return jsonify(response), 429  # HTTP 429 Too Many Requests
        return jsonify(response), 202
    
    except Exception:
        logging.error(traceback.format_exc())
        twilio.messages.create(
            to=from_no,
            from_=os.environ.get('TWILIO_NO'),
            body="Really sorry, you caught error that we did find during development, please let us know!"
        )

@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming text message updates."""

    logging.info("start callback")
    for key in request.values:
        logging.info(f"{key}: {request.values[key]}")
    logging.info("end callback")

    try:
        status = request.form.get('MessageStatus')
        sid = request.values.get('MessageSid')

        logging.info(f"callback received, status: {status}, sid: {sid}")
        
        # check if this is a forwarded message, which would have its own ID
        message = Message.get_message_by_sid(sid)

        if not message:
            logging.info(f"not a message, {sid}")

        else:
            job = message.job
            logging.info(f"callback received, status: {status}, sid: {sid}, message: {message}, Job found: {job}")
            message_pending_selection = job.update_with_msg_callback(status, sid, message) # pending callback
            if message_pending_selection:
                if message_pending_selection.selection_type == SelectionType.AUTHORIZED_DECISION:
                    status = JobStatus.PENDING_AUTHORISED_DECISION
                else:
                    status = JobStatus.PENDING_DECISION
                job.commit_status(job, status)
                to_no = request.form.get("To")
                user_id = redis_client.hash_identifier(str(to_no))
                redis_client.start_next_job(user_id)
            else:
                redis_client.check_for_complete(job)
            
    except Exception as e:
        logging.error(traceback.format_exc())

    return Response(status=200)


def start_redis_listener():

    def listen():
        with app.app_context():  # Ensure Redis listener has access to Flask app context
            redis_client.subscriber.listen()

    listener_thread = threading.Thread(target=listen, daemon=True)
    listener_thread.start()

if __name__ == "__main__":
    # local development, not for gunicorn
    # Configure the root logger
    
    with app.app_context():
        redis_client.start_redis_listener()
    app.run(debug=True)

# RedisQueue helper functions
def set_user_processing_state(user_id, timeout=30):
    redis_client.setex(f"user:{user_id}:processing", timeout, "true")

def check_user_processing_state(user_id):
    return redis_client.exists(f"user:{user_id}:processing")

def clear_user_processing_state(user_id):
    redis_client.delete(f"user:{user_id}:processing")

# Initialize JobScheduler and MessageHandler
job_scheduler = JobScheduler()
message_handler = MessageHandler(job_scheduler)

# Start the message listener in a separate thread
def message_listener(redis_queue, message_handler):
    while True:
        try:
            message = redis_queue.get(block=True, timeout=10)
            if message:
                message_handler.handle_message(message)
        except json.JSONDecodeError as e:
            print(f"Error decoding message: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")
        time.sleep(0.1)  # Sleep briefly to avoid tight loop in case of continuous errors

def start_listener():
    redis_queue = RedisQueue(name='tasks')
    listener_thread = threading.Thread(target=message_listener, args=(redis_queue, message_handler))
    listener_thread.daemon = True
    listener_thread.start()

if __name__ == '__main__':
    logging.basicConfig(
        filename='/var/log/app.log',  # Log file path
        filemode='a',  # Append mode
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
        level=log_level  # Log level
    )
    logging.getLogger('twilio.http_client').setLevel(logging.WARNING)
    start_listener()
    app.run(debug=True)