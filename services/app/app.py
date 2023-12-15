import os
from dotenv import load_dotenv
print(f" Live in app: {os.environ.get('LIVE')}")

from flask import Flask, request, jsonify, Response
from flask.cli import with_appcontext
from twilio.twiml.messaging_response import MessagingResponse, Message as Msg
import logging

from config import Config, manager
from extensions import db
from models import User, Message, ReplyError, ForwardMessage, AzureSyncError
from models.chatbot import Chatbot
from models.job import Job, McJob
import uuid
from constants import intents, errors

from constants import CONFIRM, CANCEL, COMPLETE, USER_ERROR, DURATION_CONFLICT, DOUBLE_MESSAGE, FAILED, PENDING_USER_REPLY
from constants import REPLY_SENT, ERROR_SENT, REPLY_FAILED, ERROR_FAILED, FORWARD_SENT, FORWARD_FAILED, PENDING_REPLY_STATUS_PENDING_USER_REPLY
from constants import PENDING_REPLY_STATUS, PENDING_FORWARD_STATUS, PENDING_ERROR_REPLY_STATUS

from es.manage import search_for_document, loop_through_files, create_index
from azure_sync import acquire_token
from datetime import datetime


app = Flask(__name__)
app.config.from_object(Config)

app.logger.addHandler(logging.StreamHandler())
app.logger.setLevel(logging.INFO)

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
    db.create_all()
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



def create_confirm_mc_message(mc_message):

    mc_job = mc_message.job
    # set all the MC details
    dates_found = mc_job.generate_base(mc_message.body)
    
    if not dates_found: # check that it is an mc message
        raise ReplyError(errors['DATES_NOT_FOUND'], intent=intents['TAKE_MC'], new_message=mc_message)
        
    content_variables = Chatbot.confirm_mc_check(mc_job)
    
    if content_variables is None: # if no relations
        raise ReplyError(errors['NO_RELATIONS'], intent=intents['TAKE_MC'], new_message=mc_message)
    else:
        Chatbot.reply_template_msg(mc_message, os.environ.get("MC_CONFIRMATION_CHECK_SID"), content_variables, PENDING_REPLY_STATUS_PENDING_USER_REPLY)

def get_es_result_and_reply(es_message):

    es_job = es_message.job

    result = search_for_document(es_message.body)
    # print(f"Main result: {result}")

    content_variables = Chatbot.reply_to_query(result, es_job.user)
    Chatbot.reply_template_msg(es_message, os.environ.get("SEARCH_DOCUMENTS_SID"), content_variables)

    return

def handle_user_reply_action(decision, new_message):

    job = new_message.job

    if job.type == "mc_job":
        job.validate_mc_replied_message(decision, new_message) # checks that it is PENDING_USER_REPLY, catch any errors

def general_workflow(user, sid, user_str, replied_details):
    
    # go to database to get the last user_str in the past 5 minsthat is not a double user_str
    recent_message = Job.get_recent_message(user.number)

    print(recent_message)

    if recent_message and recent_message.reply_sid == None:
        # print(f"recent message found with status: {recent_message.status}")
        raise ReplyError(errors['DOUBLE_MESSAGE'], status=DOUBLE_MESSAGE)

    # CHECK if user reply to confirm MC
    if replied_details: # user replied with yes/no
        replied_message, decision = replied_details
        new_message = Message(replied_message.job_number, sid, user_str)
        if replied_message.job.status == FAILED:
            raise ReplyError(errors['UNKNOWN_ERROR'], new_message=new_message)
        handle_user_reply_action(decision, new_message) # this also checks if user replies no, which raises a reply error 

    # CHECK if user wants to take MC
    else:
        print("new message thread")
        if recent_message and recent_message.job.status == PENDING_USER_REPLY:
            raise ReplyError(errors['PENDING_USER_REPLY'])
        
        intent = Message.check_for_intent(user_str)
        new_message = Job.create_job(intent, sid, user_str, user.name)
        new_job = new_message.job

        if new_job.type == "mc_job":
            create_confirm_mc_message(new_message)
        else:
            try:
                #TODO
                get_es_result_and_reply(new_message)
                # print("querying documents")
                
            except Exception as e:
                # print(e)
                logging.error(f"An error occurred: {e}", exc_info=True)
                raise ReplyError(errors['ES_REPLY_ERROR'], new_message=new_message)

            
    # if mc_message.status == TEMP:
    #     mc_message.delete()

    # TODO REMOVE TEMPS


@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    print("start message")
    for key in request.values:
        print(f"{key}: {request.values[key]}")
    print("end message")

    replied_details = None

    if request.form.get('OriginalRepliedMessageSid'):
        print("replied message!")
        replied_msg = Message.get_reply_sid(request.form.get('OriginalRepliedMessageSid'))
        decision = int(request.form.get('ButtonPayload'))
        replied_details = (replied_msg, decision)

    from_no = Message.get_number(request)
    print(from_no)
    user = User.get_user(from_no)
    user_str = Message.get_message(request)
    sid = Message.get_sid(request)

    print(f"{user}: {user_str}")
    
    try:
        if not user:
            raise ReplyError(errors['USER_NOT_FOUND'])

        general_workflow(user, sid, user_str, replied_details) # callback to user
        return Response(status=200)
        
    except ReplyError as re: # problem

        app.logger.error('An error occurred: %s', str(re.err_message), exc_info=True)

        if re.new_message:
            new_message = re.new_message
            number = new_message.job.user.sg_number
        else:
            
            if user:
                name = user.name
                number = user.sg_number
            else:
                name = "UNKNOWN"
                number = 'whatsapp:+65' + str(from_no)

            new_message = Job.create_job(re.intent, sid, user_str, name)

        new_message.job.commit_status(re.job_status)

        Chatbot.reply_normal_msg(new_message, re.err_message, PENDING_ERROR_REPLY_STATUS, number)
        return Response(status=200)
    
    except Exception as e:
        # print(e)
        app.logger.error('An error occurred: %s', str(e), exc_info=True)
        return Response(status=200)
    

@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming calls with a simple text message."""

    print("start callback")
    for key in request.values:
        print(f"{key}: {request.values[key]}")
    print("end callback")

    status = request.form.get('MessageStatus')
    from_number = request.form.get('From')
    # Print to the terminal
    print(f"Received message from {from_number}: {status}")
    sid = request.values.get('MessageSid')
    print(f'sid: {sid}')

    # check if this is a forwarded message, which would have its own ID
    message = ForwardMessage.get_message_by_sid(sid) or Message.get_reply_sid(sid)

    if not message:
        print("not a message", sid)

    else:
        print("message!", message.body)

        if (message.status != PENDING_REPLY_STATUS and 
            message.status != PENDING_REPLY_STATUS_PENDING_USER_REPLY and 
            message.status != PENDING_FORWARD_STATUS and
            message.status != PENDING_ERROR_REPLY_STATUS):
            print("message was not expecting a reply")
            return Response(status=200)
        
        if status == "sent":
            outgoing_body = Chatbot.fetch_message(sid)
            print(f"outgoing message: {outgoing_body}")
            if message.type == "forward_message":
                if message.status == PENDING_FORWARD_STATUS:
                    message.commit_forward_message(outgoing_body)
                if message.status == PENDING_REPLY_STATUS or message.status == PENDING_ERROR_REPLY_STATUS:
                    message.commit_reply(outgoing_body)
            else:
                message.commit_reply(outgoing_body)

        elif status == "delivered":

            # error message delivered, job still failed
            if message.status == PENDING_ERROR_REPLY_STATUS:
                message.commit_status(ERROR_SENT)

            # forward message
            elif message.type == "forward_message" and message.status == PENDING_FORWARD_STATUS:
                # forward message delivered
                message.commit_forward_status(FORWARD_SENT)
                reply = message.notify_status()
                Chatbot.reply_normal_msg(message, reply)

                forwarded_msgs = message.get_other_forwards()
                if all(f_msg.forward_status == FORWARD_SENT for f_msg in forwarded_msgs):
                    pending_forward_message = message.get_pending_forward_message()
                    Chatbot.reply_normal_msg(pending_forward_message, message.acknowledge_decision())

            # reply message expecting user reply
            elif message.type == "message" and message.status == PENDING_REPLY_STATUS_PENDING_USER_REPLY:
                message.job.commit_status(PENDING_USER_REPLY)
                message.commit_status(REPLY_SENT)

            # normal reply delivered
            elif message.status == PENDING_REPLY_STATUS:
                message.commit_status(REPLY_SENT)
                all_msgs = message.job.messages
                # IF NO ERROR REPLIES # TODO what if the message is still PENDING FORWARD? we didnt reply to it. maybe can implement that
                if all(msg.status == REPLY_SENT for msg in all_msgs) and message.job.status != FAILED:
                    message.job.commit_status(COMPLETE)
        
        elif status == "failed":
            # job immediately fails
            message.job.commit_status(FAILED)

            # error message delivered, job still failed
            if message.status == PENDING_ERROR_REPLY_STATUS:
                message.commit_status(ERROR_FAILED)

            # forward message fail
            if message.type == "forward_message" and message.status == PENDING_FORWARD_STATUS:
                message.commit_forward_status(FORWARD_FAILED)
                reply = message.notify_status()
                Chatbot.reply_normal_msg(message, reply, PENDING_ERROR_REPLY_STATUS)

            # forward reply fail OR normal reply fail
            elif message.status == PENDING_REPLY_STATUS:
                message.commit_status(REPLY_FAILED)


                if message.job.type == "job": # TODO should probably send to myself
                    Chatbot.reply_template_message(message, os.environ.get("ERROR_SID"), status=FAILED)
                    

    return Response(status=200)

@app.route("/chatbot/azure_header/", methods=['GET'])
def get_azure_details():
    return manager.headers

@app.route("/chatbot/azure_create", methods=["POST"])
def get_file_id():
    data = request.get_json()
    file_id = data.get('FileId')
    print(file_id)
    response = {
        "status": "success",
        "file_id": file_id
    }
    return jsonify(response), 200

if __name__ == "__main__":
    app.run(debug=True)