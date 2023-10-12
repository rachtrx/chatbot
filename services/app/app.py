from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import os
from twilio.rest import Client
from config import Config
from extensions import db
from models import User, Message, McDetails, DurationMismatchError, ReplyError
from dotenv import load_dotenv

from constants import PENDING_USER_REPLY, SUCCESS, DURATION_CONFLICT

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

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

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)


def general_workflow(request):

    message = Message.get_message(request)
    user = User.get_user(Message.get_number(request))

    if not user:
        return False

    # CHECK if user reply to confirm MC
    if Message.check_response(str(message)): # user replied with yes/no
        mc_message = McDetails.get_recent_message(user.number, PENDING_USER_REPLY) # goes to database to get old number
        if mc_message:
            if os.environ.get('LIVE') == "1":
                mc_message.send_message(client)
                mc_message.commit_message(SUCCESS)
                return False # nothing to reply, maybe acknowledgement TODO
            else:
                mc_message.commit_message(SUCCESS)
                reply = mc_message.send_message()
        else:
            raise ReplyError("I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?")
            
            
    # CHECK if user wants to take MC
    else:
        mc_intent = Message.check_for_intent(message)
        if mc_intent:
            mc_message = McDetails(user.number, message) # initialise

            try:
                dates_found = mc_message.generate_base()
            except DurationMismatchError as de:
                mc_message.commit_message(DURATION_CONFLICT)
                return de.message

            if not dates_found: # check that it is an mc message
                raise ReplyError("The chatbot is still in development, we could not determine your intent, really sorry!")
                
            reply = mc_message.generate_reply()
            if reply is None: # if no relations
                raise ReplyError("Really sorry, there doesn't seem to anyone to inform about your MC. Please contact the school HR")
            else:    
                mc_message.commit_message(PENDING_USER_REPLY) # save to database TODO probably only after callback
            
    # return reply for both cases
    return reply

            # TODO REMOVE TEMPS
                


@app.route("/chatbot/sms/test/", methods=['GET', 'POST'])
def sms_reply_test():
    """Respond to incoming calls with a simple text message."""

    try:
        response = general_workflow(request) # callback to user
        if not response: # message forwarded successfully
            return True
        
    except ReplyError as re: # problem
        response = re.message

    return response

@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    try:
        response = general_workflow(request) # callback to user
        if not response: # message forwarded successfully
            return True
        
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
    print(status)

    return True
    
    # TODO get the number and inform success

if __name__ == "__main__":
    app.run(debug=True)