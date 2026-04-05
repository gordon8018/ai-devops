"""Email notifier implementation.

Sends notifications via SMTP.
"""
from __future__ import annotations
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List

from tenacity import retry, stop_after_attempt, wait_exponential
from .base import Notifier, Alert, AlertLevel

logger = logging.getLogger(__name__)



class PasswordEncryptionError(Exception):
    """Raised when password encryption/decryption fails."""
    pass


def _load_encryption_key():
    """Load encryption key from environment or file."""
    import os
    from pathlib import Path
    key_str = os.getenv("SMTP_ENCRYPTION_KEY")
    if not key_str:
        key_file = os.getenv("SMTP_KEY_FILE")
        if key_file:
            try:
                key_path = Path(key_file)
                if key_path.exists():
                    key_str = key_path.read_text().strip()
            except Exception as e:
                logger.warning("Failed to read key file %s: %s", key_file, e)
    if key_str:
        try:
            return key_str.encode()
        except Exception as e:
            logger.error("Invalid encryption key format: %s", e)
    return None


def _decrypt_password(encrypted, key):
    """Decrypt password using Fernet symmetric encryption."""
    try:
        from cryptography.fernet import Fernet, InvalidToken
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
    except ImportError:
        raise PasswordEncryptionError("cryptography library not installed")
    except InvalidToken:
        raise PasswordEncryptionError("Invalid encrypted password or wrong key")
    except Exception as e:
        raise PasswordEncryptionError(f"Decryption failed: {e}")


def _get_password():
    """Get SMTP password from various sources with encryption support."""
    import os
    from pathlib import Path
    encrypted_pwd = os.getenv("SMTP_PASSWORD_ENC")
    if encrypted_pwd:
        key = _load_encryption_key()
        if key:
            try:
                return _decrypt_password(encrypted_pwd, key)
            except PasswordEncryptionError as e:
                logger.error("Failed to decrypt SMTP_PASSWORD_ENC: %s", e)
                return None
        else:
            logger.error("SMTP_PASSWORD_ENC set but no encryption key found")
            return None
    
    pwd_file = os.getenv("SMTP_PASSWORD_FILE")
    if pwd_file:
        try:
            pwd_path = Path(pwd_file)
            if pwd_path.exists():
                pwd_content = pwd_path.read_text().strip()
                key = _load_encryption_key()
                if key and pwd_content.startswith("gAAAA"):
                    try:
                        return _decrypt_password(pwd_content, key)
                    except PasswordEncryptionError as e:
                        logger.warning("Password file looks encrypted but decryption failed: %s", e)
                return pwd_content
        except Exception as e:
            logger.warning("Failed to read password file %s: %s", pwd_file, e)
    
    plain_pwd = os.getenv("SMTP_PASSWORD")
    if plain_pwd:
        logger.warning("Using plain-text SMTP_PASSWORD. Consider SMTP_PASSWORD ENC instead.")
        return plain_pwd
    return None

class EmailNotifier(Notifier):
    """Send notifications via Email (SMTP).
    
    Configuration via environment variables:
    - SMTP_HOST: SMTP server hostname
    - SMTP_PORT: SMTP server port (default: 587)
    - SMTP_USER: SMTP username
    - SMTP_PASSWORD: SMTP password (plain text, not recommended)
    - SMTP_PASSWORD_ENC: Encrypted SMTP password (base64, recommended)
    - SMTP_PASSWORD_FILE: Path to file containing password
    - SMTP_ENCRYPTION_KEY: Encryption key for decrypting passwords
    - SMTP_KEY_FILE: Path to file containing encryption key
    - EMAIL_FROM: From address
    - EMAIL_TO: Comma-separated recipient addresses
    - SMTP_USE_TLS: Use TLS (default: true)
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addrs: Optional[List[str]] = None,
        use_tls: Optional[bool] = None
    ):
        self._host = host or os.getenv("SMTP_HOST")
        self._port = port or int(os.getenv("SMTP_PORT", "587"))
        self._user = user or os.getenv("SMTP_USER")
        # Password: prefer constructor arg, then use secure loader
        if password is not None:
            self._password = password
        else:
            self._password = _get_password()
        self._from_addr = from_addr or os.getenv("EMAIL_FROM")
        
        if to_addrs:
            self._to_addrs = to_addrs
        else:
            to_str = os.getenv("EMAIL_TO", "")
            self._to_addrs = [addr.strip() for addr in to_str.split(",") if addr.strip()]
        
        tls_env = os.getenv("SMTP_USE_TLS", "true").lower()
        self._use_tls = use_tls if use_tls is not None else tls_env in ("true", "1", "yes")
    
    @property
    def name(self) -> str:
        return "email"
    
    @property
    def enabled(self) -> bool:
        return bool(
            self._host and
            self._user and
            self._password and
            self._from_addr and
            self._to_addrs
        )
    
    def supports_level(self, level: AlertLevel) -> bool:
        """Email only for warning and critical by default."""
        return level in (AlertLevel.WARNING, AlertLevel.CRITICAL)
    
    def _build_subject(self, alert: Alert) -> str:
        """Build email subject line."""
        level_prefix = {
            AlertLevel.INFO: "[INFO]",
            AlertLevel.WARNING: "[WARNING]",
            AlertLevel.CRITICAL: "[CRITICAL]",
        }
        prefix = level_prefix.get(alert.level, "[ALERT]")
        return f"{prefix} {alert.title}"
    
    def _build_body(self, alert: Alert) -> str:
        """Build email body."""
        lines = [
            f"Alert Level: {alert.level.value.upper()}",
            f"Title: {alert.title}",
            "",
        ]
        
        if alert.message:
            lines.append(alert.message)
            lines.append("")
        
        if alert.task_id:
            lines.append(f"Task ID: {alert.task_id}")
        
        if alert.plan_id:
            lines.append(f"Plan ID: {alert.plan_id}")
        
        if alert.metadata:
            lines.append("")
            lines.append("Additional Details:")
            for key, value in alert.metadata.items():
                lines.append(f"  {key}: {value}")
        
        lines.append("")
        lines.append("---")
        lines.append("This is an automated notification from Zoe Orchestrator")
        
        return "\n".join(lines)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, exp_base=2, min=4, max=16),
        reraise=True
    )
    def _send_email(self, alert: Alert) -> bool:
        """Internal send method with retry decorator."""
        msg = MIMEMultipart()
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg["Subject"] = self._build_subject(alert)
        
        body = self._build_body(alert)
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(self._host, self._port, timeout=30) as server:
            if self._use_tls:
                server.starttls()
            server.login(self._user, self._password)
            server.sendmail(
                self._from_addr,
                self._to_addrs,
                msg.as_string()
            )
        
        logger.info("Email notification sent: %s", alert.title)
        return True
    
    def send(self, alert: Alert) -> bool:
        """Send alert via email with retry mechanism."""
        if not self.enabled:
            logger.warning("Email not configured (missing SMTP settings)")
            return False
        
        try:
            return self._send_email(alert)
        except Exception as exc:
            logger.warning("Email notification failed after retries: %s", exc)
            return False
