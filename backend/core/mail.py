"""
Sending the two kinds of email this app needs. The body never contains anything but a one-time link.

  console  prints the message to the server log (local development only; the link is a secret)
  resend   sends through Resend's web API over HTTPS (free hosts block SMTP ports but allow HTTPS)
  off      the email features are switched off and the website hides them
"""
import logging

import httpx

from backend.core.config import settings

logger = logging.getLogger("finsight.mail")


class MailError(Exception):
    pass


def enabled() -> bool:
    return settings.mail_backend in ("console", "resend")


def send(to: str, subject: str, text: str) -> None:
    if settings.mail_backend == "console":
        logger.info("mail to=%s subject=%s\n%s", to, subject, text)
        return
    if settings.mail_backend != "resend":
        raise MailError("email is switched off")
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.mail_from, "to": [to], "subject": subject, "text": text},
            timeout=15,
        )
    except httpx.HTTPError as e:
        raise MailError("could not reach the email service") from e
    if response.status_code >= 300:
        raise MailError(f"the email service answered {response.status_code}")


def link(path: str, token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}?token={token}"
