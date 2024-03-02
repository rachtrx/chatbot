import os
from dotenv import load_dotenv

from flask import request, Response, has_request_context
from flask.cli import with_appcontext
import logging
import traceback
from sqlalchemy import inspect, event

from extensions import db
from models.exceptions import ReplyError

from models.users import User
from models.messages.sent import MessageForward
from models.messages.received import MessageReceived
from models.messages.abstract import Message

from models.jobs.user.abstract import JobUser

from models.jobs.unknown.job_unknown import JobUnknown

from tasks import main as create_task
from sqlalchemy import create_engine
from utilities import run_new_context, init_thread_session

from es.manage import loop_through_files, create_index

from constants import intents, errors, messages, system
from constants import FAILED, PENDING_USER_REPLY, OK, PENDING_CALLBACK, PENDING

from manage import create_app

env_path = "/home/app/web/.env"
load_dotenv(dotenv_path=env_path)

# Configure the root logger
logging.basicConfig(
    filename='/var/log/app.log',  # Log file path
    filemode='a',  # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
    level=logging.INFO  # Log level
)

logging.getLogger('twilio.http_client').setLevel(logging.WARNING)

app = create_app()
engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
logging.info(app.config['SQLALCHEMY_DATABASE_URI'])
init_thread_session(engine)

@app.cli.command("setup_azure")
@with_appcontext
def setup_azure():
    create_task([system['ACQUIRE_TOKEN'], system['SYNC_USERS']])

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

@app.cli.command("create_db")
@with_appcontext
def create_db():
    # Get a list of existing tables before any creation
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    for table in existing_tables:
        logging.info(f"Table {table} already exists.")

    # Bind the event listeners to log table creation
    for table in db.Model.metadata.tables.values():
        event.listen(table, 'before_create', log_table_creation)

    # Create all tables that do not exist
    db.Model.metadata.create_all(db.engine)

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

def general_workflow(user, sid, user_str, replied_details):

    # CHECK if there was a decision
    if replied_details: # user replied with Confirm/Cancel
        # TODO Just try to cancel?
        replied_msg_sid, decision = replied_details
        received_msg = Message.create_message(messages['CONFIRM'], sid, user_str, replied_msg_sid, decision)
        job = received_msg.job

    else:

        # go to database to get the last user_str in the past 5 mins that is not a double user_str
        if user.is_blocking:
            recent_pending_job = JobUser.get_recent_pending_job(user.number)
            if recent_pending_job:
                # check if the recent message hasnt been replied to yet
                
                if recent_pending_job.status == PENDING_USER_REPLY:
                    raise ReplyError(errors['PENDING_USER_REPLY'])
                
                for msg in recent_pending_job.messages:
                    if msg.status == PENDING_CALLBACK:
                        raise ReplyError(errors['MESSAGE_STILL_PENDING'])
                    elif msg.status == PENDING:
                        raise ReplyError(errors['DOUBLE_MESSAGE'])
                    else:
                        raise ReplyError(errors['UNKNOWN_ERROR'])
                

        # NEW JOB WILL BE CREATED
        intent, options = MessageReceived.check_for_intent(user_str)
        if intent == intents['ES_SEARCH'] or intent == None:
            raise ReplyError(errors['ES_REPLY_ERROR'])
        elif intent == intents['TAKE_MC_NO_TYPE']:
            raise ReplyError(errors['MC_WRONG_SYNTAX'])

        job = JobUser.create_job(intent, user.name, options)
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
                    job = JobUser.create_job(re.intent, name)
                else:
                    number = request.form.get("From")
                    logging.info(f"unknown number: {number}")
                    job = JobUnknown(number)
                
                received_message = Message.create_message(messages['RECEIVED'], job.job_no, sid, user_str)

            job.commit_status(re.job_status)

            received_message.create_reply_msg(re.err_message)
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
        message = Message.get_message_by_sid(sid)

        if not message:
            logging.info(f"not a message, {sid}")

        else:
            job = message.job
            job.update_with_msg_callback(status, sid, message)
                        
    except Exception as e:
        logging.error(traceback.format_exc())

    return Response(status=200)

if __name__ == "__main__":
    # local development, not for gunicorn
    app.run(debug=True)