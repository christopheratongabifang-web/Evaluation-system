import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def main():
    sid = os.environ.get('TWILIO_ACCOUNT_SID')
    token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_num = os.environ.get('TWILIO_FROM_NUMBER')
    to = os.environ.get('TWILIO_TEST_TO')  # optional override recipient

    if not sid or not token or not from_num:
        print('Missing TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN or TWILIO_FROM_NUMBER in environment')
        return 2

    try:
        from twilio.rest import Client
    except Exception as e:
        print('twilio package not installed:', e)
        return 3

    client = Client(sid, token)

    if not to:
        to = input('Enter recipient phone number (E.164) to test: ').strip()

    print('Sending test message...')
    try:
        msg = client.messages.create(body='RUBRIC test SMS - ignore', from_=from_num, to=to)
        print('Message queued:', msg.sid, 'status:', getattr(msg, 'status', 'unknown'))
    except Exception as e:
        print('Twilio send error:')
        print(e)

    print('\nListing recent messages to this recipient (last 10):')
    try:
        msgs = client.messages.list(to=to, limit=10)
        for m in msgs:
            print(m.sid, m.status, m.error_code, m.error_message, m.date_created)
    except Exception as e:
        print('Could not list messages:', e)

if __name__ == '__main__':
    sys.exit(main())
