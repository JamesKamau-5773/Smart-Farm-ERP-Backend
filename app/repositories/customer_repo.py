from app.models.finance import Customer
from app import db
from sqlalchemy.exc import SQLAlchemyError

class CustomerRepository:
    @staticmethod
    def get_by_phone(phone_number: str) -> Customer:
        """Fetches a customer using the standard 2547XXXXXXXX format."""
        return Customer.query.filter_by(phone_number=phone_number).first()

    @staticmethod
    def credit_account(customer_id: int, amount: float) -> Customer:
        """Reduces the customer's outstanding balance."""
        try:
            customer = Customer.query.get(customer_id)
            if customer:
                # Assuming account_balance tracks what they owe. 
                # A payment reduces this balance.
                customer.account_balance -= amount
                db.session.commit()
            return customer
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Database error while crediting customer account.")