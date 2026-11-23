"""The M-Pesa STK callback is not routed until callbacks are verified (Phase 0B)."""
from app import db
from app.models.finance import Customer, Transaction
from tests.base import BaseTestCase

SUCCESSFUL_STK_CALLBACK = {
    'Body': {
        'stkCallback': {
            'MerchantRequestID': 'merchant-1',
            'CheckoutRequestID': 'checkout-1',
            'ResultCode': 0,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {
                'Item': [
                    {'Name': 'Amount', 'Value': 500},
                    {'Name': 'MpesaReceiptNumber', 'Value': 'FORGED0001'},
                    {'Name': 'PhoneNumber', 'Value': 254700000001},
                ],
            },
        },
    },
}


class MpesaCallbackDisabledTestCase(BaseTestCase):

    def test_callback_paths_return_404_and_record_nothing(self):
        db.session.add(Customer(tenant_id=self.tenant.id, name='Kiosk', phone_number='254700000001'))
        db.session.commit()

        for path in ('/mpesa/callback', '/api/finance/mpesa/callback', '/api/mpesa/callback'):
            response = self.client.post(path, json=SUCCESSFUL_STK_CALLBACK)
            self.assertEqual(response.status_code, 404, path)

        self.assertEqual(Transaction.query.count(), 0)

    def test_no_route_reaches_the_callback_handler(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
        self.assertFalse([endpoint for endpoint in endpoints if 'mpesa' in endpoint.lower()])
