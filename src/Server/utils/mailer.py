"""Outgoing email (password reset).

With ``SMTP_HOST`` set, mail goes out over SMTP with STARTTLS. Without it (local
development) each message is written to ``DATA_DIR/outbox/<time>-<to>.eml``, which
any mail client opens - so the reset flow works end to end with no mail account.
The reset link is never written to the server log.
"""

from __future__ import annotations

import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from config import settings
from utils.sprint import Logger

l = Logger.get_instance(True)


def outbox_dir() -> Path:
    return settings.data_dir / "outbox"


def send_mail(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if settings.smtp_host:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
        l.iprint(f"Sent '{subject}' email")
        return

    out = outbox_dir()
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = out / f"{stamp}-{re.sub(r'[^A-Za-z0-9@._-]', '_', to)}.eml"
    path.write_bytes(bytes(msg))
    l.iprint(f"SMTP not configured: '{subject}' email written to {path}")
