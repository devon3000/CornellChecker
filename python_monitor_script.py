#!/usr/bin/env python3
"""
Cornell Visit Activities Page Monitor
Checks for changes in form submission options and sends SMS notifications
"""

import os
import hashlib
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Twilio imports (comment out if using Gmail SMS)
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

TARGET_URL = "https://www.cornell.edu/visit/plan/activities/?date=6-27-2025"
SNAPSHOT_FILE = "page_snapshot.json"
CONTENT_FILE = "page_content.html"

def fetch_page_content():
    """Fetch and parse the Cornell visit page"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        return None

def extract_form_data(html_content):
    """Extract relevant form data and activities from the page"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Look for form elements, activity listings, and registration options
    form_data = {}
    
    # Find forms
    forms = soup.find_all('form')
    for i, form in enumerate(forms):
        form_data[f'form_{i}'] = {
            'action': form.get('action', ''),
            'method': form.get('method', ''),
            'inputs': []
        }
        
        # Extract form inputs
        inputs = form.find_all(['input', 'select', 'textarea', 'button'])
        for inp in inputs:
            input_data = {
                'type': inp.get('type', inp.name if inp.name else 'unknown'),
                'name': inp.get('name', ''),
                'value': inp.get('value', ''),
                'text': inp.get_text(strip=True) if inp.get_text(strip=True) else ''
            }
            form_data[f'form_{i}']['inputs'].append(input_data)
    
    # Look for activity listings, registration buttons, availability status
    activities = []
    
    # Common selectors for activities and registration elements
    activity_selectors = [
        '.activity', '.event', '.program', '.tour',
        '[class*="activity"]', '[class*="event"]', '[class*="registration"]',
        'button[class*="register"]', 'a[class*="register"]',
        '.btn', 'button', 'a[href*="register"]'
    ]
    
    for selector in activity_selectors:
        elements = soup.select(selector)
        for elem in elements:
            text = elem.get_text(strip=True)
            if text and len(text) > 5:  # Filter out empty or very short text
                activities.append({
                    'selector': selector,
                    'text': text,
                    'href': elem.get('href', ''),
                    'class': elem.get('class', [])
                })
    
    # Look for any text indicating availability, sold out, registration status
    status_keywords = ['available', 'sold out', 'full', 'register', 'book now', 'reserve', 'waitlist']
    status_elements = []
    
    for keyword in status_keywords:
        elements = soup.find_all(text=lambda x: x and keyword.lower() in x.lower())
        for elem in elements:
            if elem.parent:
                status_elements.append({
                    'keyword': keyword,
                    'text': elem.strip(),
                    'parent_tag': elem.parent.name,
                    'parent_class': elem.parent.get('class', [])
                })
    
    return {
        'forms': form_data,
        'activities': activities,
        'status_elements': status_elements,
        'page_title': soup.title.string if soup.title else '',
        'timestamp': datetime.now().isoformat()
    }

def load_previous_snapshot():
    """Load the previous page snapshot"""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None

def save_snapshot(data):
    """Save current snapshot to file"""
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def save_content(html_content):
    """Save raw HTML content for debugging"""
    with open(CONTENT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

def calculate_content_hash(data):
    """Calculate hash of relevant content for comparison"""
    # Remove timestamp for comparison
    comparison_data = data.copy()
    comparison_data.pop('timestamp', None)
    
    content_str = json.dumps(comparison_data, sort_keys=True)
    return hashlib.md5(content_str.encode()).hexdigest()

def send_sms_twilio(message):
    """Send SMS using Twilio"""
    if not TWILIO_AVAILABLE:
        print("Twilio not available, skipping SMS")
        return False
        
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_FROM_NUMBER')
    to_number = os.getenv('TWILIO_TO_NUMBER')
    
    if not all([account_sid, auth_token, from_number, to_number]):
        print("Missing Twilio credentials")
        return False
    
    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"SMS sent successfully: {message.sid}")
        return True
    except Exception as e:
        print(f"Error sending SMS via Twilio: {e}")
        return False

def send_sms_gmail(message):
    """Send SMS using Gmail SMTP (carrier SMS gateway)"""
    gmail_user = os.getenv('GMAIL_USER')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')
    sms_email = os.getenv('SMS_EMAIL')  # e.g., 1234567890@txt.att.net
    
    if not all([gmail_user, gmail_password, sms_email]):
        print("Missing Gmail SMS credentials")
        return False
    
    try:
        msg = MIMEText(message)
        msg['Subject'] = 'Cornell Visit Update'
        msg['From'] = gmail_user
        msg['To'] = sms_email
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        
        print("SMS sent successfully via Gmail")
        return True
    except Exception as e:
        print(f"Error sending SMS via Gmail: {e}")
        return False

def send_email_notification(subject, body):
    """Send an email notification using Gmail SMTP"""
    gmail_user = os.getenv('GMAIL_USER')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')
    email_recipient = os.getenv('EMAIL_RECIPIENT')

    # Improved diagnostics for missing credentials
    if not gmail_user:
        print("Missing GMAIL_USER environment variable.")
    if not gmail_password:
        print("Missing GMAIL_APP_PASSWORD environment variable.")
    if not email_recipient:
        print("Missing EMAIL_RECIPIENT environment variable.")

    if not all([gmail_user, gmail_password, email_recipient]):
        print("Missing Gmail email notification credentials")
        return False

    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = gmail_user
        msg['To'] = email_recipient

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()

        print("Email notification sent successfully")
        return True
    except Exception as e:
        print(f"Error sending email notification: {e}")
        return False

def send_notification(message):
    """Send notification via email"""
    print(f"Sending notification: {message}")
    subject = "Cornell Visit Activities Update"
    if send_email_notification(subject, message):
        return True
    else:
        print("Email notification failed")
        return False

def compare_snapshots(old_data, new_data):
    """Compare snapshots and return differences"""
    if not old_data:
        return ["Initial snapshot created"]
    
    old_hash = calculate_content_hash(old_data)
    new_hash = calculate_content_hash(new_data)
    
    if old_hash == new_hash:
        return None  # No changes
    
    changes = []
    
    # Compare forms
    old_forms = old_data.get('forms', {})
    new_forms = new_data.get('forms', {})
    
    if len(old_forms) != len(new_forms):
        changes.append(f"Number of forms changed: {len(old_forms)} -> {len(new_forms)}")
    
    # Compare activities
    old_activities = set(act['text'] for act in old_data.get('activities', []))
    new_activities = set(act['text'] for act in new_data.get('activities', []))
    
    added_activities = new_activities - old_activities
    removed_activities = old_activities - new_activities
    
    if added_activities:
        changes.append(f"New activities: {', '.join(list(added_activities)[:3])}")
    if removed_activities:
        changes.append(f"Removed activities: {', '.join(list(removed_activities)[:3])}")
    
    # Compare status elements
    old_status = set(elem['text'] for elem in old_data.get('status_elements', []))
    new_status = set(elem['text'] for elem in new_data.get('status_elements', []))
    
    status_changes = new_status - old_status
    if status_changes:
        changes.append(f"Status changes: {', '.join(list(status_changes)[:2])}")
    
    return changes if changes else ["Page content changed (details unclear)"]

def main():
    print(f"Monitoring {TARGET_URL} at {datetime.now()}")
    
    # Fetch current page
    html_content = fetch_page_content()
    if not html_content:
        print("Failed to fetch page content")
        return
    
    # Save raw content for debugging
    save_content(html_content)
    
    # Extract structured data
    current_data = extract_form_data(html_content)
    print(f"Extracted data: {len(current_data.get('forms', {}))} forms, {len(current_data.get('activities', []))} activities")
    
    # Load previous snapshot
    previous_data = load_previous_snapshot()
    
    # Compare snapshots
    changes = compare_snapshots(previous_data, current_data)
    
    if changes:
        change_summary = "; ".join(changes[:3])  # Limit to first 3 changes
        message = (
            f"Cornell Visit Page Changed!\n\n{change_summary}\n\n"
            f"Check: {TARGET_URL}"
        )
        
        print(f"Changes detected: {change_summary}")
        send_notification(message)
    else:
        print("No changes detected")
    
    # Save current snapshot
    save_snapshot(current_data)
    print("Snapshot updated")

if __name__ == "__main__":
    if os.getenv("TEST_EMAIL", "false").lower() == "true":
        print("TEST_EMAIL is true, sending test email...")
        success = send_email_notification(
            "Test Email from CornellChecker",
            f"This is a test email from your GitHub Actions workflow.\n\nMonitored URL: {TARGET_URL}"
        )
        if success:
            print("Test email sent successfully.")
        else:
            print("Test email failed to send.")
        print("Exiting after test email.")
    else:
        main()