from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import os
from twilio.rest import Client

from regex_pattern_extraction import check_for_intent, check_response
from database_conn import get_cfm_mc_details, add_message, get_user_info

from config import Config
from extensions import db
from models import User, McDetails
from dotenv import load_dotenv

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

    message, from_number = get_message_details(request)

    if check_response(str(message)):
        cfm_mc_details = get_cfm_mc_details(from_number) # goes to database to get old number
        if cfm_mc_details:
            send_message(cfm_mc_details)
            return False

    print(message)
    mc_details = check_for_intent(message)
    if mc_details and get_user_info(from_number): # check that user exists and it is an mc message
        user, r, h = get_user_info(from_number)
        print("retrieved user details!")
        draft_mc_details = add_message(mc_details, user)
        return generate_reply(draft_mc_details, user, r, h)
    else:
        return "Sorry I did not get what you mean, or you have exceeded the 10 min timeout. Please let me know how many days of leave you are planning to take"

def send_message(cfm_mc_details):
    '''This function sets up the details of the forward to HOD and reporting officer message'''

    user, r, h, mc = cfm_mc_details
    print(cfm_mc_details)

    to_numbers = [(r.name, r.number), (h.name, h.number)]

    # Define the message parameters
    for to_name, number in to_numbers:
        
        to_number = str(number)  # Original number
        from_number = '+18155730824'  # Your Twilio number
        body = f'Hi {to_name}! This is to inform you that {user.name} will be taking {mc.duration} days MC from {mc.start_date} to {mc.end_date}'

        # Send the message
        message = client.messages.create(
            to='+65' + to_number,
            from_=from_number,
            body=body
        )

    print(message.sid)
    return True

def get_message_details(request):

    print(request.form)

    user_str = request.form.get("Body")
    from_number = int(request.form.get("From")[-8:])

    print(from_number)
    print(f"Received {user_str}")

    return (user_str, from_number)


def generate_reply(draft_mc_details, user, r, h):
    '''This function gets a mc_details object and returns a confirmation message'''

    statement = f"Hi {user.name}, Kindly confirm that you are on MC for {draft_mc_details.duration} days from {draft_mc_details.start_date} to {draft_mc_details.end_date}. I will help you to inform "

    if not (r or h):
        statement = "Really sorry, there doesn't seem to anyone to inform about your MC. Please contact the school HR"

    elif r and h:
        statement += f"{r.name} ({r.number}) and {h.name} ({h.number})"

    elif r:
        statement += f"{r.name} ({r.number})"

    else:
        statement += f"{h.name} ({h.number})"

    statement += " (Yes/No)"

    return statement


@app.route("/chatbot/sms/test/", methods=['GET', 'POST'])
def sms_reply_test():
    """Respond to incoming calls with a simple text message."""

    response = general_workflow(request)

    return response

@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    response = general_workflow(request)

    if response:
        # Start our TwiML response
        resp = MessagingResponse()

        # Add a message
        resp.message(response)

        print(str(resp))

        return str(resp)
    else:
        return "Message was a confirmation, now waiting for callback"


@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming calls with a simple text message."""

    status = request.form.get('MessageStatus')
    print(status)

    return True
    
    # TODO get the number and inform success

if __name__ == "__main__":
    app.run(debug=True)