import os
import requests
import base64
from datetime import datetime
from flask import current_app, jsonify
from requests.auth import HTTPBasicAuth

class MpesaService:
    @staticmethod
    def _get_config_errors():
        required = {
            "MPESA_CONSUMER_KEY": current_app.config.get("MPESA_CONSUMER_KEY"),
            "MPESA_CONSUMER_SECRET": current_app.config.get("MPESA_CONSUMER_SECRET"),
            "MPESA_BUSINESS_SHORTCODE": current_app.config.get("MPESA_BUSINESS_SHORTCODE"),
            "MPESA_PASSKEY": current_app.config.get("MPESA_PASSKEY"),
            "MPESA_CALLBACK_URL": current_app.config.get("MPESA_CALLBACK_URL"),
        }

        errors = []
        for key, value in required.items():
            if value is None or str(value).strip() == "":
                errors.append({"key": key, "reason": "missing"})
            elif isinstance(value, str) and value.strip().lower().startswith("your_"):
                errors.append({"key": key, "reason": "placeholder"})

        return errors

    @staticmethod
    def get_base_url():
        env = current_app.config.get('MPESA_ENVIRONMENT')
        if env == 'production':
            return "https://api.safaricom.co.ke"
        return "https://sandbox.safaricom.co.ke"

    @staticmethod
    def generate_access_token():
        """Authenticates with Daraja to get the short-lived OAuth token."""
        consumer_key = current_app.config.get('MPESA_CONSUMER_KEY')
        consumer_secret = current_app.config.get('MPESA_CONSUMER_SECRET')
        api_url = f"{MpesaService.get_base_url()}/oauth/v1/generate?grant_type=client_credentials"

        try:
            if not consumer_key or not consumer_secret:
                raise ValueError("M-Pesa consumer key/secret not configured")
            response = requests.get(api_url, auth=HTTPBasicAuth(consumer_key, consumer_secret))
            response.raise_for_status()
            return response.json().get('access_token')
        except (requests.exceptions.RequestException, ValueError):
            # In production, log this error securely
            raise Exception("Failed to authenticate with Safaricom Daraja API.")

    @staticmethod
    def initiate_stk_push(phone_number: str, amount: int, account_reference: str, transaction_desc: str):
        """
        Triggers the STK Push prompt on the customer's phone.
        phone_number must be in format 2547XXXXXXXX
        """
        config_errors = MpesaService._get_config_errors()
        if config_errors:
            return jsonify({
                "error": "M-Pesa is not configured on this server.",
                "config_issues": config_errors
            }), 400

        # Format phone number to strictly 254 format if submitted as 07xx
        if phone_number.startswith('0'):
            phone_number = '254' + phone_number[1:]

        if not phone_number.isdigit() or len(phone_number) != 12 or not phone_number.startswith('2547'):
            return jsonify({
                "error": "Invalid phone_number. Use format 2547XXXXXXXX."
            }), 400

        try:
            access_token = MpesaService.generate_access_token()
        except Exception:
            return jsonify({
                "error": "Failed to authenticate with Safaricom Daraja API. Check M-Pesa credentials."
            }), 502

        api_url = f"{MpesaService.get_base_url()}/mpesa/stkpush/v1/processrequest"
        
        shortcode = str(current_app.config.get('MPESA_BUSINESS_SHORTCODE'))
        passkey = str(current_app.config.get('MPESA_PASSKEY'))
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Safaricom requires the password to be Base64(Shortcode + Passkey + Timestamp)
        data_to_encode = shortcode + passkey + timestamp
        encoded_password = base64.b64encode(data_to_encode.encode('utf-8')).decode('utf-8')

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": shortcode,
            "Password": encoded_password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone_number,
            "PartyB": shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": current_app.config.get('MPESA_CALLBACK_URL'),
            "AccountReference": account_reference[:12], # Max 12 characters
            "TransactionDesc": transaction_desc[:13]    # Max 13 characters
        }

        try:
            response = requests.post(api_url, json=payload, headers=headers)
            safaricom_data = response.json()
            
            if response.status_code == 200:
                return jsonify({
                    "message": "STK Push initiated successfully. Awaiting customer pin.",
                    "merchant_request_id": safaricom_data.get('MerchantRequestID'),
                    "checkout_request_id": safaricom_data.get('CheckoutRequestID')
                }), 200
            else:
                return jsonify({
                    "error": "Safaricom rejected the request.",
                    "details": safaricom_data
                }), response.status_code

        except requests.exceptions.RequestException as e:
            return jsonify({"error": "Failed to connect to Safaricom."}), 503