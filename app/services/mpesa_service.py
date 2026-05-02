import os
import requests
import base64
from datetime import datetime
from flask import current_app, jsonify
from requests.auth import HTTPBasicAuth
from app.repositories.customer_repo import CustomerRepository
from app.services.finance_service import FinanceService
from app.models.finance import TransactionType, TransactionCategory


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
            response = requests.get(api_url, auth=HTTPBasicAuth(
                consumer_key, consumer_secret))
            response.raise_for_status()
            return response.json().get('access_token')
        except (requests.exceptions.RequestException, ValueError):
            # In production, log this error securely
            raise Exception(
                "Failed to authenticate with Safaricom Daraja API.")

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
        encoded_password = base64.b64encode(
            data_to_encode.encode('utf-8')).decode('utf-8')

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
            "AccountReference": account_reference[:12],  # Max 12 characters
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

    @staticmethod
    def process_stk_callback(payload: dict):
        """Parses Safaricom's webhook payload and reconciles the ledger."""
        try:
            stk_callback = payload.get('Body', {}).get('stkCallback', {})
            result_code = stk_callback.get('ResultCode')
            merchant_request_id = stk_callback.get('MerchantRequestID')

            # ResultCode 0 means the transaction was successful
            if result_code == 0:
                callback_metadata = stk_callback.get(
                    'CallbackMetadata', {}).get('Item', [])

                amount = 0
                receipt_number = ""
                phone_number = ""

                # Extract the values from the metadata array
                for item in callback_metadata:
                    if item.get('Name') == 'Amount':
                        amount = float(item.get('Value', 0))
                    elif item.get('Name') == 'MpesaReceiptNumber':
                        receipt_number = item.get('Value')
                    elif item.get('Name') == 'PhoneNumber':
                        phone_number = str(item.get('Value'))

                # 1. Find the customer
                customer = CustomerRepository.get_by_phone(phone_number)
                customer_id = customer.id if customer else None

                # 2. Update the Customer's Ledger
                if customer_id:
                    CustomerRepository.credit_account(customer_id, amount)

                # 3. Record the Revenue Transaction (System Admin defaults to user_id 1 for automated entries)
                FinanceService.record_transaction(
                    t_type=TransactionType.REVENUE,
                    category=TransactionCategory.MILK_SALE,
                    amount=amount,
                    user_id=1,
                    ip_address="127.0.0.1",  # System-initiated action
                    customer_id=customer_id,
                    ref_code=receipt_number,
                    desc=f"M-Pesa payment from {phone_number}"
                    customer_id=customer_id,
                    ref_code=receipt_number,
                    desc=f"Automated M-Pesa STK Payment. ReqID: {merchant_request_id}"
                )

                # In production, you would trigger an SMS receipt to the farmer/customer here.
                return True

            else:
                # The user cancelled, had insufficient funds, or the request timed out.
                # ResultCode != 0. You can log the failure if needed.
                error_desc = stk_callback.get('ResultDesc', 'Unknown Error')
                print(f"STK Push Failed: {error_desc}")
                return False

        except Exception as e:
            print(f"Error processing M-Pesa callback: {str(e)}")
            return False
