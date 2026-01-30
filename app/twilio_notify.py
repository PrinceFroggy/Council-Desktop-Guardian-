import os
from typing import Optional

def twilio_send_sms(text: str, to_number: str) -> bool:
    sid = os.getenv("TWILIO_ACCOUNT_SID","")
    token = os.getenv("TWILIO_AUTH_TOKEN","")
    from_ = os.getenv("TWILIO_FROM","")
    if not (sid and token and from_ and to_number):
        return False
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(from_=from_, to=to_number, body=text)
        return True
    except Exception:
        return False
