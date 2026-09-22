from flask import current_app
import requests


def build_text_message(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


def build_main_menu_message(body: str = "Choose what you want to do") -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Menu",
                "sections": [
                    {
                        "title": "Farm Actions",
                        "rows": [
                            {"id": "log_milk", "title": "Log Milk", "description": "Record yield for a cow"},
                            {"id": "log_feed", "title": "Log Feed", "description": "Record feed usage or mixing"},
                            {"id": "view_herd", "title": "View Herd", "description": "See cows and herd status"},
                            {"id": "view_reports", "title": "Reports", "description": "Open dashboards and summaries"},
                        ],
                    }
                ],
            },
        },
    }


def build_session_buttons_message(body: str = "Select the milking session") -> dict:
    return _buttons_message(body, [
        ("shift_morning", "Morning"),
        ("shift_afternoon", "Afternoon"),
        ("shift_evening", "Evening"),
    ])


def build_confirm_buttons_message(body: str) -> dict:
    return _buttons_message(body, [
        ("confirm_yes", "Confirm"),
        ("confirm_no", "Cancel"),
    ])


def _buttons_message(body: str, id_title_pairs: list) -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": command_id, "title": title}}
                    for command_id, title in id_title_pairs
                ]
            },
        },
    }


def send_message(to: str, message: dict) -> None:
    """Sends a built message payload to a WhatsApp user via the Meta Cloud API.

    Best-effort: transport failures are logged, never raised, so a failed
    outbound send never turns an already-processed inbound webhook into a
    500 (Meta would otherwise retry and reprocess the same command).
    """
    access_token = current_app.config.get('WHATSAPP_ACCESS_TOKEN')
    phone_number_id = current_app.config.get('WHATSAPP_PHONE_NUMBER_ID')
    if not access_token or not phone_number_id or not message:
        return

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {"messaging_product": "whatsapp", "to": to, **message}
    try:
        requests.post(url, json=body, headers=headers, timeout=10)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to send WhatsApp message to {to}: {str(e)}")
