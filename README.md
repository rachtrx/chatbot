# Leave Reporting System
Built for Grace Orchard School

## Starting the Environment in Development

1. Get [ngrok](https://dashboard.ngrok.com/get-started/setup) and use your computer as a local server
   ```sh
   ngrok http 80

2. Login to Twilio and ensure that 
   - The number is already registered as a Whatsapp number under a business
   - There is a Messaging Service. Under the integration tab, point the webhook and the callback to the ngrok URL (which is the local computer) 
   - All the Content Templates have already been implemented

3. **Build and Run Containers:** Containers are defined in the `docker-compose.yml` file, execute the following command in your terminal:

   ```sh
   docker-compose -f docker-compose.yml up --build

## Jobs

### System Jobs

The following [system jobs](./services/app/models/jobs/system/) exist
1. Acquiring MSAL Token
2. Morning Report to School Leaders
3. Syncing of Leave Records to Sharepoint
4. Syncing of Users from Sharepoint

### User Jobs

Currently, the only [user job](./services/app/models/jobs/user/) that exist is for:
1. Leave Reporting
2. Sharepoint Document Search (in progress)

#### Leave Reporting Jobs

**Application Logic**
- Uses regular expressions to determine the type of leave, dates of leave, and duration of leave

**Leave Details**
- Leave records are stored in leave_records, a table of the database, and syncs to Sharepoint via [Microsoft Graph API](https://developer.microsoft.com/en-us/graph/rest-api)

## Messages
Messages are sent and received through a Twilio number. Read Twilio's [Documentation](https://www.twilio.com/docs). It uses Programmable Messaging through a Messaging Service which allows for Content Template Builders.

### Incoming
Incoming messages are either stored as a [MessageReceived or MessageSelection](./services/app/models/messages/received.py) 
- MessageReceiveds are the initial messages
- MessageConfirms are replies to the system after the system has generated its own message

### Outgoing
Outgoing messages are either stored as a [MessageSent or MessageForward](./services/app/models/messages/sent.py)
- MessageSents are replies to the user
- MessageForwards are messages to other users about the current user

## Upcoming Features
- Possibly looking into the Sharepoint Document Search that can be implemented using ElasticSearch
- Notifications for incoming and outgoing staff

### The following are required in .env in [./services/app/](./services/app/):

**Redis**
- REDIS_URL
- FERNET_KEY

**Microsoft (MSAL) Please Read Below!**
- CLIENT_ID
- CLIENT_SECRET
- AUTHORITY
- SCOPE
- SITE_ID

**Sharepoint**
- DRIVE_ID
- FOLDER_ID
- USERS_FILE_ID
- TOKEN_PATH

**Twilio metadata**
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- MESSAGING_SERVICE_SID
- TWILIO_NO

**Twilio Content Templates (Need to be implemented already)**
- LEAVE_CONFIRMATION_CHECK_SID
- LEAVE_CONFIRMATION_CHECK_3_ISSUES_SID
- LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID
- LEAVE_CONFIRMATION_CHECK_1_ISSUE_SID
- SEND_MESSAGE_TO_HODS_SID
- SEND_MESSAGE_TO_HODS_ALL_PRESENT_SID
- FORWARD_MESSAGES_CALLBACK_SID
- LEAVE_NOTIFY_APPROVE_SID
- LEAVE_NOTIFY_CANCEL_SID
- SEND_MESSAGE_TO_LEADERS_SID
- SEND_MESSAGE_TO_LEADERS_ALL_PRESENT_SID
- SHAREPOINT_LEAVE_SYNC_NOTIFY_SID
- SELECT_LEAVE_TYPE_SID
- SEND_SYSTEM_TASKS_SID

`Note on MSAL Client Secret`: Client ID has to be changed when it expires. To create a new Client Secret, go to Microsoft Entra ID → Applications → App Registrations → Chatbot → Certificates & Secrets → New client secret. Then update the .env file and restart Docker