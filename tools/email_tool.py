import smtplib
from email.message import EmailMessage
import sys
import os
from pathlib import Path

# Add project root to path so database can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database

def send_email_agentic(recipient_email: str, subject: str, body: str) -> str:
    """
    Sends an email using the SMTP app password stored in the database.
    """
    password = database.get_state("EMAIL_PASSWORD")
    sender = database.get_state("SENDER_EMAIL", "pythonlusty@gmail.com")
    
    if not password:
        return "Failed: Email password is not configured in settings."
        
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = recipient_email
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return f"Successfully sent email to {recipient_email}."
    except Exception as e:
        return f"Failed to send email. Error: {e}"
