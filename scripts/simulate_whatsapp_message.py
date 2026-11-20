"""Send a signed fake inbound WhatsApp message to a local backend.

Lets you test reverse-OTP flows without exposing localhost to Meta:

    .venv/bin/python scripts/simulate_whatsapp_message.py 0712345678 VERIFY-482913
    .venv/bin/python scripts/simulate_whatsapp_message.py +254712345678 RESET-731904 --url http://localhost:5000

Signs the body with WHATSAPP_APP_SECRET from .env, exactly as Meta does.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.utils.phone import InvalidPhoneNumber, to_e164, to_wa_id  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sender', help='Sender phone number, any accepted format')
    parser.add_argument('text', help='Message text, e.g. VERIFY-482913')
    parser.add_argument('--url', default='http://localhost:5000', help='Backend base URL')
    args = parser.parse_args()

    load_dotenv()
    secret = os.environ.get('WHATSAPP_APP_SECRET')
    if not secret:
        sys.exit('WHATSAPP_APP_SECRET is not set in .env')
    try:
        wa_id = to_wa_id(to_e164(args.sender))
    except InvalidPhoneNumber:
        sys.exit(f'Invalid phone number: {args.sender}')

    body = json.dumps({'entry': [{'changes': [{'value': {'messages': [{
        'id': f'wamid.local-{uuid.uuid4().hex}', 'from': wa_id, 'type': 'text', 'text': {'body': args.text},
    }]}}]}]}).encode()
    signature = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    response = requests.post(
        f"{args.url.rstrip('/')}/api/whatsapp/webhook",
        data=body,
        headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': signature},
        timeout=10,
    )
    print(response.status_code, response.text)
    print('The reply is in the backend log as a [WHATSAPP_DRY_RUN] line.')


if __name__ == '__main__':
    main()
