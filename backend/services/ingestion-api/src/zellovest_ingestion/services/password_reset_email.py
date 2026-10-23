"""SMTP delivery for local-auth password reset links."""

import smtplib
import ssl
from email.message import EmailMessage

from zellovest_ingestion.config import IngestionAPISettings


def send_password_reset_email(settings: IngestionAPISettings, recipient: str, link: str) -> None:
    """Send a password reset link over authenticated TLS SMTP."""
    message = EmailMessage()
    message["Subject"] = "Reset your Zellovest password"
    message["From"] = settings.email_from
    message["To"] = recipient
    message.set_content(
        "We received a request to reset your Zellovest password.\n\n"
        f"Use this link within 30 minutes: {link}\n\n"
        "If you did not request this, you can ignore this email."
    )
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if settings.email_smtp_username:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password)
        smtp.send_message(message)
