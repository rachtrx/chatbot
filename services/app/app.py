from flask import Flask, request, jsonify, Response
from twilio.twiml.messaging_response import MessagingResponse
import os
from twilio.rest import Client
from config import Config
from extensions import db
from models import User, Message, McDetails, DatesMismatchError, ReplyError, ForwardDetails, AzureSyncError
from dotenv import load_dotenv
import uuid
from constants import intents, PENDING_USER_REPLY, SUCCESS, DURATION_CONFLICT, TEMP, FAILED, PENDING_CALLBACK
from azure_upload import SpreadsheetManager

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)
print(f" Live in app: {os.environ.get('LIVE')}")
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)
manager = SpreadsheetManager()

@app.cli.command("create_db")
def create_db():
    with app.app_context():
        db.create_all()
        db.session.commit()


@app.cli.command("remove_db")
def remove_db():
    with app.app_context():
        db.drop_all()
        db.session.commit()

@app.cli.command("seed_db")
def seed_db():
    with app.app_context():
        user = User("Rachmiel", "12345678", "rach@rach")
        db.session.add(user)
        db.session.commit()

def general_workflow(request):

    message = Message.get_message(request)
    print(message)
    user = User.get_user(Message.get_number(request))
    if os.environ.get('LIVE') == "1":
        id = Message.get_id(request)
    else:
        id = uuid.uuid4().hex

    print(user)

    if not user:
        raise ReplyError("I'm sorry, your contact has not been added to our database. Please check with HR")

    # CHECK if user reply to confirm MC
    if Message.check_yes_no(str(message)): # user replied with yes/no
        recent_message = Message.get_recent_message(user.number) # goes to database to get old number
        if recent_message:
            print("recent message found")
            if recent_message.intent == intents["TAKE_MC"] and 300 <= recent_message.status < 400:
                # recent_message is a mc_details objects
                if os.environ.get('LIVE') == "1":
                    #send message
                    forward_messages = recent_message.send_message(client)
                    for forward_message in forward_messages:
                        forward_message.commit_message(PENDING_CALLBACK)
                    # upload to azure
                    try:
                        print(True)
                        manager.upload_data(recent_message)
                        return None # nothing to reply, maybe acknowledgement TODO
                    except AzureSyncError as e:
                        print(e.message)
                        raise ReplyError("I'm sorry, something went wrong with the code, please check with ICT")
                else: # local
                    recent_message.commit_message(SUCCESS)
                    reply = recent_message.send_message()
                    print("reply created")
            elif 200 <= recent_message.status < 300:
                raise ReplyError("Previous message has already been sent successfully")
            else:
                raise ReplyError("Something went wrong, please send the message again")
        else:
            raise ReplyError("I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?")
            
            
    # CHECK if user wants to take MC
    else:
        print("new message thread")
        mc_intent = Message.check_for_intent(message)
        if mc_intent:
            mc_message = McDetails(id, user.number, message) # initialise

            try:
                dates_found = mc_message.generate_base()
            except DatesMismatchError as de:
                mc_message.commit_message(DURATION_CONFLICT)
                return de.message

            if not dates_found: # check that it is an mc message
                raise ReplyError("The chatbot is still in development, we regret that we could not determine your period of MC, could you specify the dates/duration again?")
                
            reply = mc_message.generate_reply(client)
            if reply is None: # if no relations
                raise ReplyError("Really sorry, there doesn't seem to be anyone to inform about your MC. Please contact the school HR")
            else:    
                mc_message.commit_message(PENDING_USER_REPLY) # save to database TODO probably only after callback
                return reply
        else:
            raise ReplyError("The chatbot is still in development, we regret that we could not determine your intent. If you need additional help, please reach out to our new helpline 87178103.")
            
    # if mc_message.status == TEMP:
    #     mc_message.delete()

    # return reply for both cases
    # if os.environ.get('LIVE') != "1":
        # return reply

            # TODO REMOVE TEMPS
                


@app.route("/chatbot/sms/test/", methods=['GET', 'POST'])
def sms_reply_test():
    """Respond to incoming calls with a simple text message."""

    try:
        response = general_workflow(request) # callback to user
        if not response: # message forwarded successfully
            return Response(status=200)
        
    except ReplyError as re: # problem
        response = re.message

    return response

@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    try:
        response = general_workflow(request) # callback to user
        if not response: # message forwarded successfully
            return Response(status=200)
        
    except ReplyError as re: # problem
        response = re.message

    # Start our TwiML response
    resp = MessagingResponse()

    # Add a message
    resp.message(response)

    print(str(resp))

    return str(resp)

@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming calls with a simple text message."""

    status = request.form.get('MessageStatus')
    from_number = request.form.get('From')
    # Print to the terminal
    print(f"Received message from {from_number}: {status}")
    sid = request.values.get('MessageSid')
    print(f'sid: {sid}')

    message = Message.get_message_by_id(sid)

    if not message:
        print("not a message", sid)
        return Response(status=200)
    else:
        print("message!", message.body)
        
    if status == "delivered":
        message.commit_message(SUCCESS) # forward msg is successful
        message.notify_status(SUCCESS, client)
        ref_id = message.ref_id
        forwarded_msges = ForwardDetails.get_all_forwards(ref_id)
        all_success = True
        for forwarded_msg in forwarded_msges:
            if forwarded_msg.status != SUCCESS:
                all_success = False
                break
        if all_success:
            ref_msg = Message.get_message_by_id(ref_id)
            ref_msg.commit_message(SUCCESS)
            ref_msg.notify_complete(client)
            
    elif status == "failed":
        message.commit_message(FAILED)
        message.notify_status(FAILED, client)


    from_number = request.form.get('From')
    # Print to the terminal
    print(f"Received message from {from_number}: {status}")

    return '', 200
    
    # TODO get the number and inform success

if __name__ == "__main__":
    app.run(debug=True)