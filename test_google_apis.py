import os
from utils.api_integrations import create_calendar_event
from dotenv import load_dotenv
load_dotenv()

print("--- Testing Google Calendar API ---")
# Using tomorrow's date for test
from datetime import datetime, timedelta
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
res_cal = create_calendar_event("Complete Alpha UI Design", tomorrow)
print(res_cal)
