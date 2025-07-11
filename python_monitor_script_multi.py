#!/usr/bin/env python3
"""
Multi-Page Monitor
Checks for changes in form submission options across multiple pages and sends SMS notifications
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

def get_target_urls():
    """Get target URLs from environment variables or configuration"""
    # Option 1: Single URL from environment (backward compatible)
    single_url = os.getenv("TARGET_URL")
    if single_url:
        return [{"name": "default", "url": single_url}]
    
    # Option 2: Multiple URLs from environment variables
    urls = []
    i = 1
    while True:
        url = os.getenv(f"TARGET_URL_{i}")
        name = os.getenv(f"TARGET_NAME_{i}", f"page_{i}")
        if not url:
            break
        urls.append({"name": name, "url": url})
        i += 1
    
    # Option 3: URLs from JSON configuration file
    if not urls and os.path.exists("urls_config.json"):
        try:
            with open("urls_config.json", "r") as f:
                config = json.load(f)
                urls = config.get("urls", [])
        except (json.JSONDecodeError, IOError):
            pass
    
    return urls

def get_snapshot_filename(page_name):
    """Generate snapshot filename for a specific page"""
    return f"page_snapshot_{page_name}.json"

def get_content_filename(page_name):
    """Generate content filename for a specific page"""
    return f"page_content_{page_name}.html"

def fetch_page_content(url):
    """Fetch and parse a web page"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching page {url}: {e}")
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
        elements = soup.find_all(string=lambda x: x and keyword.lower() in x.lower())
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

def load_previous_snapshot(page_name):
    """Load the previous page snapshot for a specific page"""
    snapshot_file = get_snapshot_filename(page_name)
    if os.path.exists(snapshot_file):
        try:
            with open(snapshot_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None

def save_snapshot(data, page_name):
    """Save current snapshot to file for a specific page"""
    snapshot_file = get_snapshot_filename(page_name)
    with open(snapshot_file, 'w') as f:
        json.dump(data, f, indent=2)

def save_content(html_content, page_name):
    """Save raw HTML content for debugging for a specific page"""
    content_file = get_content_filename(page_name)
    with open(content_file, 'w', encoding='utf-8') as f:
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
        msg['Subject'] = 'Page Monitor Update'
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
    """Send email notification"""
    gmail_user = os.getenv('GMAIL_USER')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')
    email_recipient = os.getenv('EMAIL_RECIPIENT')
    
    if not all([gmail_user, gmail_password, email_recipient]):
        print("Missing email credentials")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = email_recipient
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        
        print("Email sent successfully")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def send_notification(message):
    """Send notification via available methods"""
    # Try SMS first, then email
    sms_sent = send_sms_twilio(message) or send_sms_gmail(message)
    
    if not sms_sent:
        send_email_notification("Page Monitor Alert", message)

def compare_snapshots(old_data, new_data, page_name):
    """Compare old and new snapshots and detect changes"""
    if not old_data:
        print(f"No previous snapshot found for {page_name}, creating baseline")
        return False
    
    old_hash = calculate_content_hash(old_data)
    new_hash = calculate_content_hash(new_data)
    
    if old_hash != new_hash:
        print(f"Change detected for {page_name}!")
        
        # Generate detailed change report
        changes = []
        
        # Compare forms
        old_forms = old_data.get('forms', {})
        new_forms = new_data.get('forms', {})
        
        if old_forms != new_forms:
            changes.append(f"Form changes detected for {page_name}")
        
        # Compare activities
        old_activities = old_data.get('activities', [])
        new_activities = new_data.get('activities', [])
        
        if old_activities != new_activities:
            changes.append(f"Activity changes detected for {page_name}")
        
        # Compare status elements
        old_status = old_data.get('status_elements', [])
        new_status = new_data.get('status_elements', [])
        
        if old_status != new_status:
            changes.append(f"Status changes detected for {page_name}")
        
        if changes:
            # Check if the only change is "details unclear"
            if len(changes) == 1 and "details unclear" in changes[0]:
                print(f"Minor change detected for {page_name} (details unclear) - suppressing notification")
                print(f"Page hash changed but no specific changes identified")
                return False
            else:
                message = f"🚨 PAGE CHANGE ALERT for {page_name}!\n\n" + "\n".join(changes)
                message += f"\n\nURL: {new_data.get('url', 'N/A')}"
                message += f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                
                send_notification(message)
                return True
    
    return False

def monitor_page(page_config):
    """Monitor a single page"""
    page_name = page_config['name']
    url = page_config['url']
    
    print(f"Monitoring {page_name}: {url}")
    
    # Fetch current page content
    html_content = fetch_page_content(url)
    if not html_content:
        print(f"Failed to fetch content for {page_name}")
        return False
    
    # Save raw content for debugging
    save_content(html_content, page_name)
    
    # Extract and analyze form data
    current_data = extract_form_data(html_content)
    current_data['url'] = url  # Add URL to data for reference
    
    # Load previous snapshot
    previous_data = load_previous_snapshot(page_name)
    
    # Compare and detect changes
    changes_detected = compare_snapshots(previous_data, current_data, page_name)
    
    # Save current snapshot
    save_snapshot(current_data, page_name)
    
    if changes_detected:
        print(f"Changes detected and notification sent for {page_name}")
    else:
        print(f"No changes detected for {page_name}")
    
    return True

def main():
    """Main function to monitor all configured pages"""
    print(f"Starting multi-page monitor at {datetime.now()}")
    
    # Get target URLs
    target_urls = get_target_urls()
    
    if not target_urls:
        print("No target URLs configured. Please set TARGET_URL or TARGET_URL_1, TARGET_URL_2, etc.")
        return
    
    print(f"Found {len(target_urls)} pages to monitor")
    
    # Check if this is a test email run
    test_email = os.getenv('TEST_EMAIL', 'false').lower() == 'true'
    if test_email:
        print("Sending test email...")
        send_notification("🧪 This is a test notification from the multi-page monitor")
        return
    
    # Monitor each page
    success_count = 0
    for page_config in target_urls:
        try:
            if monitor_page(page_config):
                success_count += 1
        except Exception as e:
            print(f"Error monitoring {page_config['name']}: {e}")
    
    print(f"Monitoring complete. Successfully monitored {success_count}/{len(target_urls)} pages")

if __name__ == "__main__":
    main() 