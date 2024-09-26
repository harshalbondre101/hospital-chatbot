from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
import datetime
from datetime import timezone
import os
import yaml

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def load_config(file_path):
    with open(file_path, "r") as f:
        config = yaml.safe_load(f)
    return config

config = load_config("global_config.yaml")

TOKEN_FILE_PATH = config['google_calendar_config']['token_file_path']
CLIENT_SECRET_FILE_PATH = config['google_calendar_config']['client_secret_file_path']
CALENDAR_ID = config['google_calendar_config']['calendar_id']
EVENT_DURATION = datetime.timedelta(hours=config['google_calendar_config']['event_duration_hours'])
GENERATE_SCHEDULE_DAYS = config['google_calendar_config']['generate_schedule_days']
TIME_SLOTS_START = config['google_calendar_config']['time_slots_start']
TIME_SLOTS_END = config['google_calendar_config']['time_slots_end']
DEFAULT_TIMEZONE_OFFSET = config['google_calendar_config']['default_timezone_offset']

# Define scopes for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_service_and_credentials():
    """
    Function to authenticate and get Google Calendar service and credentials
    """
    creds = None
    # Load credentials from token.json if available
    if os.path.exists(TOKEN_FILE_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE_PATH, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE_PATH,
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_FILE_PATH, "w") as token:
            token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    return service, creds

OFFSET_TO_TIMEZONE = {
    "+00:00": "Etc/UTC",
    "-11:00": "Pacific/Niue",
    "-10:00": "Pacific/Rarotonga",
    "-09:30": "Pacific/Marquesas",
    "-09:00": "Pacific/Gambier",
    "-08:00": "America/Anchorage",
    "-07:00": "America/Dawson_Creek",
    "-06:00": "America/Bahia_Banderas",
    "-05:00": "America/Cancun",
    "-04:00": "America/Barbados",
    "-03:00": "America/Argentina/Buenos_Aires",
    "-02:30": "America/St_Johns",
    "-02:00": "Atlantic/South_Georgia",
    "-01:00": "Atlantic/Cape_Verde",
    "+01:00": "Africa/Algiers",
    "+02:00": "Africa/Johannesburg",
    "+03:00": "Asia/Baghdad",
    "+03:30": "Asia/Tehran",
    "+04:00": "Asia/Dubai",
    "+04:30": "Asia/Kabul",
    "+05:00": "Asia/Karachi",
    "+05:30": "Asia/Kolkata",
    "+05:45": "Asia/Kathmandu",
    "+06:00": "Asia/Dhaka",
    "+06:30": "Asia/Yangon",
    "+07:00": "Asia/Bangkok",
    "+08:00": "Asia/Shanghai",
    "+08:45": "Australia/Eucla",
    "+09:00": "Asia/Tokyo",
    "+09:30": "Australia/Adelaide",
    "+10:00": "Australia/Brisbane",
    "+10:30": "Australia/Lord_Howe",
    "+11:00": "Asia/Magadan",
    "+12:00": "Pacific/Auckland",
    "+12:45": "Pacific/Chatham",
    "+13:00": "Pacific/Tongatapu",
    "+14:00": "Pacific/Kiritimati"
}



def settimezone(offset):
    service, creds = get_service_and_credentials()
    try:
        # Validate the offset format
        if offset not in OFFSET_TO_TIMEZONE:
            raise ValueError(f"Offset {offset} not recognized")

        # Get the primary calendar
        calendar = service.calendars().get(calendarId=CALENDAR_ID).execute()
        current_timezone = calendar['timeZone']
        print(f"Current calendar timezone: {current_timezone}")

        new_timezone = OFFSET_TO_TIMEZONE[offset]

        # Check if the timezone needs to be updated
        if current_timezone == new_timezone:
            print(f"Timezone is already set to {new_timezone}, no update needed.")
            return

        # Change the timezone of the primary calendar
        calendar['timeZone'] = new_timezone
        updated_calendar = service.calendars().update(calendarId=CALENDAR_ID, body=calendar).execute()

        print(f"Updated calendar timezone: {updated_calendar['timeZone']}")
    except Exception as e:
        print(f"An error occurred: {e}")


def send_confirmation_email(name, email, eventTime_datetime):
    try:
        smtp_server = 'smtp.hostinger.com'
        port = 587  # or 465 for SSL
        sender_email = 'info@dataintelligence.cloud'
        password = 'Data786Intelligence.'
        receiver_email = email

        message = MIMEMultipart("alternative")
        message["Subject"] = "Appointment Confirmation"
        message["From"] = sender_email
        message["To"] = receiver_email

        eventTime_formatted_display = eventTime_datetime.strftime('%Y-%m-%d %I:%M %p')

        text = f"Hi {name}, your appointment has been scheduled for {eventTime_formatted_display}."
        html = f"<p>Hi {name},<br>Your appointment has been scheduled for {eventTime_formatted_display}.</p>"

        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")

        message.attach(part1)
        message.attach(part2)

        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, message.as_string())

        return True
    except Exception as e:
        print(f"Failed to send confirmation email: {str(e)}")
        return False


def create_appointment(name, email, date, time, timezone_offset=DEFAULT_TIMEZONE_OFFSET, calendar_id=CALENDAR_ID):
    """
    Function to create an event in Google Calendar
    """
    try:
        service, _ = get_service_and_credentials()
        if service is None:
            return None

        # Convert date and time to datetime object
        event_start = datetime.datetime.strptime(date + " " + time, "%Y-%m-%d %H:%M")
        # Convert event time to UTC
        event_start_utc = event_start - datetime.timedelta(hours=int(timezone_offset[:3]), minutes=int(timezone_offset[4:]))
        event_end_utc = event_start_utc + EVENT_DURATION

        event = {
            'summary': name,
            'description': f"Name: {name}\nEmail: {email}\n Date: {date}\n Time: {time}",
            'start': {
                'dateTime': event_start_utc.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': event_end_utc.isoformat(),
                'timeZone': 'UTC',
            },
        }

        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        email_sent = send_confirmation_email(name, email, event_start)
        if email_sent is True:
            email_sent = True
        else:
            email_sent = False

        return f"Appointment created successfully and email sent: {email_sent}"
    except Exception as e:
        print("Error occurred while creating event:", str(e))
        return "Error creating event"



def delete_appointment(email, calendar_id=CALENDAR_ID):
    """
    Function to delete events associated with the given email
    """
    try:
        service, _ = get_service_and_credentials()
        if service is None:
            return None

        events_result = service.events().list(calendarId=calendar_id, q=email).execute()
        events = events_result.get('items', [])

        if not events:
            return 'No events found for the given email.'
        else:
            for event in events:
                service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
                return f"Event '{event['summary']}' deleted."
    except Exception as e:
        print("Error occurred while deleting event:", str(e))
        return "Could not delete event"

def update_appointment(name, email, date, time, timezone_offset=DEFAULT_TIMEZONE_OFFSET, calendar_id=CALENDAR_ID):
    """
    Function to update events associated with the given email and name with new details of date and time.
    """
    try:
        delete_appointment(email, calendar_id=CALENDAR_ID)
        create_appointment(name, email, date, time)
        return "Appointment updated successfully"
    except Exception as e:
        print("Error occurred while updating event:", str(e))
        return "Error updating event"

def get_events_in_range(start_date, end_date):
    """Retrieves events within the specified date range."""
    try:
        service, _ = get_service_and_credentials()
        if not service:
            return None

        # Define the timeMin and timeMax parameters to filter events within the specified date range
        time_min = datetime.datetime.combine(start_date, datetime.time.min).isoformat() + "Z"
        time_max = datetime.datetime.combine(end_date, datetime.time.max).isoformat() + "Z"

        events_result = (
            service.events()
            .list(
                calendarId=CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        return events

    except HttpError as error:
        print(f"An error occurred: {error}")


def generate_schedule():
    start_date = datetime.date.today()

    end_date = start_date + datetime.timedelta(days=GENERATE_SCHEDULE_DAYS)
    """Generates a schedule table for the specified date range."""
    schedule = []

    # Define time slots from TIME_SLOTS_START to TIME_SLOTS_END for each day in the range
    current_date = start_date
    while current_date <= end_date:
        for hour in range(TIME_SLOTS_START, TIME_SLOTS_END):  
            time_slot = {
                "date": current_date.strftime("%Y-%m-%d"),
                "time": f"{hour:02}:00 - {hour+1:02}:00",
                "availability": "Available",
            }
            schedule.append(time_slot)
        current_date += datetime.timedelta(days=1)

    # Retrieve events and update schedule based on event timings
    events = get_events_in_range(start_date, end_date)
    if events:
        for event in events:
            start_time = datetime.datetime.fromisoformat(event["start"].get("dateTime", ""))
            end_time = datetime.datetime.fromisoformat(event["end"].get("dateTime", ""))
            event_date = start_time.date()
            event_hour = start_time.hour

            # Find the corresponding time slot and mark it as not available
            for slot in schedule:
                slot_date = datetime.datetime.strptime(slot["date"], "%Y-%m-%d").date()
                slot_hour = int(slot["time"][:2])
                if slot_date == event_date and slot_hour == event_hour:
                    slot["availability"] = "Not available"
                    break

    return schedule


def get_events_by_user_email(user_email):
    """
    Retrieves details of events where the summary contains the specified user email.
    Args:
        user_email (str): The email address to search for within event summaries.
    Returns:
        list: A list of dictionaries containing details of events where the summary contains the user email.
    """
    try:
        service, _ = get_service_and_credentials()
        if not service:
            return None
        


        # Define the current time in UTC
        now = datetime.datetime.now(timezone.utc).isoformat()

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            orderBy="startTime",
            singleEvents=True,
            timeMin=now  # Retrieve events after the current time
        ).execute()

        events = events_result.get("items", [])
        
        # Filter events where summary contains user email and extract necessary details
        user_events = []
        for event in events:
            if user_email in event.get("description", ""):
                # Extract name, email, date, and time
                start_time = event['start'].get('dateTime', event['start'].get('date'))
                end_time = event['end'].get('dateTime', event['end'].get('date'))
                user_event = {
                    'name': event['description'],
                    'email': user_email,
                    'start_time': start_time,
                    'end_time': end_time
                }
                user_events.append(user_event)
        
        return user_events

    except RefreshError as error:
        # Handle token refresh errors here
        print(f"Token refresh error: {error}")
        return None
    except Exception as error:
        # Handle other exceptions here
        print(f"An error occurred: {error}")
        return None
    

def get_list_of_available_slots_on_date(date_str, offset=DEFAULT_TIMEZONE_OFFSET):
    """
    Retrieves events on the specified date.
    Args:
        date_str (str): The date for which events need to be retrieved in the format "YYYY-MM-DD".
    Returns:
        list: A list of dictionaries containing details of events on the specified date.
        string: Timezone
    """
    start_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

    end_date = start_date + datetime.timedelta(days=0)
    """Generates a schedule table for the specified date range."""
    schedule = []

    # Define time slots from TIME_SLOTS_START to TIME_SLOTS_END for each day in the range
    current_date = start_date
    while current_date <= end_date:
        for hour in range(TIME_SLOTS_START, TIME_SLOTS_END):  
            time_slot = {
                "date": current_date.strftime("%Y-%m-%d"),
                "time": f"{hour:02}:00 - {hour+1:02}:00",
                "availability": "Available",
            }
            schedule.append(time_slot)
        current_date += datetime.timedelta(days=1)

    # Retrieve events and update schedule based on event timings
    events = get_events_in_range(start_date, end_date)
    if events:
        for event in events:
            start_time = datetime.datetime.fromisoformat(event["start"].get("dateTime", ""))
            end_time = datetime.datetime.fromisoformat(event["end"].get("dateTime", ""))
            event_date = start_time.date()
            event_hour = start_time.hour

            # Find the corresponding time slot and mark it as not available
            for slot in schedule:
                slot_date = datetime.datetime.strptime(slot["date"], "%Y-%m-%d").date()
                slot_hour = int(slot["time"][:2])
                if slot_date == event_date and slot_hour == event_hour:
                    slot["availability"] = "Not available"
                    break


    service, creds = get_service_and_credentials()
    try:
        # Validate the offset format
        if offset not in OFFSET_TO_TIMEZONE:
            raise ValueError(f"Offset {offset} not recognized")

        # Get the primary calendar
        calendar = service.calendars().get(calendarId=CALENDAR_ID).execute()
        current_timezone = calendar['timeZone']

        return schedule, current_timezone
    except Exception as e:
        print(f"Error: {e}")
        return schedule, None

    