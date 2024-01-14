import os
from dotenv import load_dotenv

from flask import Flask, request, jsonify, Response
from flask.cli import with_appcontext
from twilio.twiml.messaging_response import MessagingResponse
import logging
import traceback
from sqlalchemy import inspect
from datetime import datetime

from config import Config
from extensions import db

from models.users import User
from models.exceptions import ReplyError
from models.messages import MessageSent, MessageReceived, MessageForward, MessageConfirm
from models.messages.abstract import Message
from models.jobs import JobMc, JobEs, JobUnknown, Job

from es.manage import loop_through_files, create_index
from azure.utils import acquire_token


from constants import intents, errors, messages
from constants import FAILED, PENDING_USER_REPLY, OK, PENDING_CALLBACK

app = Flask(__name__)
app.config.from_object(Config)

# Configure the root logger
logging.basicConfig(
    filename='/var/log/app.log',  # Log file path
    filemode='a',  # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
    level=logging.INFO  # Log level
)

logging.getLogger('twilio.http_client').setLevel(logging.WARNING)

db.init_app(app)


@app.cli.command("create_new_index")
@with_appcontext
def create_new_index():
    create_index()

@app.cli.command("loop_files")
@with_appcontext
def loop_files():
    with app.app_context():
        temp_url = os.environ.get('TEMP_FOLDER_URL')
        acquire_token()
        loop_through_files(temp_url)

@app.cli.command("create_db")
@with_appcontext
def create_db():
    # Create an inspector
    inspector = inspect(db.engine)

    # List of all tables that should be created
    # Replace 'YourModel' with actual model class names
    tables = [User.__tablename__, Job.__tablename__, JobUnknown.__tablename__, JobMc.__tablename__, JobEs.__tablename__, Message.__tablename__, MessageSent.__tablename__, MessageReceived.__tablename__, MessageForward.__tablename__, MessageConfirm.__tablename__]

    # Iterate over the tables and check if they exist
    for table in tables:
        if not inspector.has_table(table):
            logging.info(f"Creating table: {table}")
            # Reflect only the specific table
            db.Model.metadata.create_all(db.engine, tables=[db.Model.metadata.tables[table]])
        else:
            logging.info(f"Table {table} already exists.")

    db.session.commit()

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

# def to_sg_number(number):
#     return 'whatsapp:+65' + str(number)


def general_workflow(user, sid, user_str, replied_details):

    # CHECK if there was a decision
    if replied_details: # user replied with Confirm/Cancel
        # TODO Just try to cancel?
        replied_msg_sid, decision = replied_details
        received_msg = Message.create_message(messages['CONFIRM'], sid, user_str, replied_msg_sid, decision)
        job = received_msg.job

    else:

        recent_job = Job.get_recent_job(user.number)

        logging.info(f"recent job {'found' if recent_job else 'not found'}")

        if recent_job and recent_job.status == PENDING_USER_REPLY:
            raise ReplyError(errors['PENDING_USER_REPLY'], job_status=None)

        # go to database to get the last user_str in the past 5 mins that is not a double user_str
        elif user.is_blocking:
            # check if the recent message hasnt been replied to yet
            if recent_job:
                logging.error("double message")
                raise ReplyError(errors['DOUBLE_MESSAGE'], job_status=None)

        # NEW JOB WILL BE CREATED
        
        intent = MessageReceived.check_for_intent(user_str)
        job = Job.create_job(intent, user.name)

        received_msg = Message.create_message(messages['RECEIVED'], job.job_no, sid, user_str)

    job.current_msg = received_msg
    job.handle_request()


@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    # logging.info("start message")
    # for key in request.values:
    #     logging.info(f"{key}: {request.values[key]}")
    # logging.info("end message")

    from_no = MessageReceived.get_number(request)
    logging.info(from_no)
    user = User.get_user(from_no)
    user_str = MessageReceived.get_message(request)
    sid = MessageReceived.get_sid(request)

    logging.info(f"{user}: {user_str}")
        
    try:
        if not user:
            raise ReplyError(errors['USER_NOT_FOUND'])
        
        replied_details = None
        
        if request.form.get('OriginalRepliedMessageSid'):
            logging.info(f"User made a decision: {request.form.get('Body')}")
            replied_msg_sid = request.form.get('OriginalRepliedMessageSid')
            decision = int(request.form.get('ButtonPayload'))
            
            replied_details = (replied_msg_sid, decision)
            logging.info(f"{replied_msg_sid}, {decision}")

        general_workflow(user, sid, user_str, replied_details) # callback to user
        return Response(status=200)
        
    except ReplyError as re: # problem

        try:

            logging.error('An error occurred: %s', str(re.err_message), exc_info=True)

            received_message = MessageReceived.query.filter_by(sid=sid).first()

            if received_message:
                job = received_message.job
                number = job.user.sg_number
            else:
                if user:
                    name = user.name
                    number = user.sg_number
                    job = Job.create_job(re.intent, name)
                else:
                    number = request.form.get("From")
                    job = JobUnknown(number)
                
                job.commit_status(re.job_status)
                received_message = Message.create_message(messages['RECEIVED'], job.job_no, sid, user_str)

            received_message.create_reply_msg(re.err_message, number)
            logging.info(traceback.format_exc())

        except Exception:
            logging.info(traceback.format_exc())

        return Response(status=200)
    
    except Exception:
        logging.info(traceback.format_exc())
        return Response(status=200)
    
    

@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming text message updates."""

    # logging.info("start callback")
    # for key in request.values:
    #     logging.info(f"{key}: {request.values[key]}")
    # logging.info("end callback")

    try:
        status = request.form.get('MessageStatus')
        sid = request.values.get('MessageSid')

        # check if this is a forwarded message, which would have its own ID
        message = Message.get_message_by_sid(sid) # TODO get the forward too? shouldnt MessageSent get forward though

        if not message:
            logging.info(f"not a message, {sid}")

        else:
            update_message_and_job_status(status, sid, message)
                        
    except Exception as e:
        logging.error(traceback.format_exc())

    return Response(status=200)

def update_message_and_job_status(status, sid, message):

    job = message.job
    
    if (message.status != PENDING_CALLBACK):
        logging.info("message was not expecting a reply")
        return Response(status=200)
    
    if status == "sent" and message.body is None:
        outgoing_body = Message.fetch_message(sid)
        logging.info(f"outgoing message: {outgoing_body}")
        message.commit_message_body(outgoing_body)

    elif status == "delivered":
        logging.info(f"message {sid} was sent successfully")

        if message.is_expecting_user_reply == True:
            job.commit_status(PENDING_USER_REPLY)
        
        message.commit_status(OK)
        job.check_for_complete()
        
        # reply message expecting user reply. just to be safe, specify the 2 types of messages
        
    
    elif status == "failed":
        # job immediately fails
        job.commit_status(FAILED)
        message.commit_status(FAILED)

        if job.type == "job_es": # TODO should probably send to myself
            message.send_msg([os.environ.get("ERROR_SID"), None], message.job)

    return job

if __name__ == "__main__":
    app.run(debug=True)