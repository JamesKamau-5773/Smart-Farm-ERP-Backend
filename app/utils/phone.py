import re


def normalize_phone(value: str) -> str:
    """Reduces a phone number to digits only (e.g. '+254 712 345678' -> '254712345678')

    so WhatsApp's wa_id (always digits-only) can be matched against stored
    User.phone_number values regardless of formatting.
    """
    return re.sub(r'\D', '', value or '')
