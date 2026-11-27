import contextlib
import fcntl
import hashlib
import hmac
import http.client
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import SplitResult, urlsplit

QUEUE_LIFETIME = 24 * 60 * 60
DEDUPE_LIFETIME = 7 * QUEUE_LIFETIME
MAX_WEBHOOK_AGE = 15 * 60
MAX_MESSAGE_AGE = 5 * 60
MAX_REQUEST_BYTES = 1024 * 1024
PART_HEADER = "X-WhatsApp-Forwarder-Part"
NEXT_PART_HEADER = "X-WhatsApp-Forwarder-Next-Part"
TOKEN_HEADER = "X-WhatsApp-Forwarder-Token"

PRIVATE_JID = re.compile(r"[0-9]+@(?:c\.us|lid)")
GROUP_JID = re.compile(r"[0-9]+(?:-[0-9]+)?@g\.us")
PRIVATE_CONTENT = {
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
}
CONTENT_WRAPPERS = ("documentWithCaptionMessage", "associatedChildMessage", "lottieStickerMessage")
ATTACHMENTS = {
    "imageMessage": "Photo",
    "videoMessage": "Video",
    "audioMessage": "Audio",
    "ptvMessage": "Video message",
    "documentMessage": "Document",
    "stickerMessage": "Sticker",
    "contactMessage": "Contact",
    "contactsArrayMessage": "Contacts",
    "locationMessage": "Location",
    "liveLocationMessage": "Live location",
    "pollCreationMessage": "Poll",
    "pollCreationMessageV2": "Poll",
    "pollCreationMessageV3": "Poll",
}


def fields(value):
    return value if isinstance(value, dict) else {}


def label(value):
    return " ".join(value.split())[:128] if isinstance(value, str) else ""


def private_jid(value):
    if not isinstance(value, str):
        return ""
    value = value.replace("@s.whatsapp.net", "@c.us")
    return value if PRIVATE_JID.fullmatch(value) else ""


@dataclass(frozen=True)
class Config:
    hmac_key: bytes
    session: str
    private_chats: dict[str, str]
    group_chats: dict[str, str]
    destination: SplitResult
    token: str

    @classmethod
    def from_env(cls):
        secret = os.getenv("WAHA_FORWARDER_HMAC_KEY", "")
        raw_config = os.getenv("WAHA_FORWARDER_CONFIG", "")
        if not secret and not raw_config:
            return None
        if len(secret) < 32:
            raise ValueError("WAHA_FORWARDER_HMAC_KEY must be at least 32 characters")

        try:
            config = fields(json.loads(raw_config))
        except ValueError:
            raise ValueError("WAHA_FORWARDER_CONFIG must be a JSON object") from None

        session = config.get("session")
        if not isinstance(session, str) or not session.strip():
            raise ValueError("session is required")
        url = config.get("webhookUrl", "")
        if not isinstance(url, str) or any(not 33 <= ord(char) <= 126 for char in url):
            raise ValueError("invalid webhookUrl")
        try:
            destination = urlsplit(url)
            port = destination.port
        except ValueError:
            raise ValueError("invalid webhookUrl") from None
        if (
            not destination.hostname
            or destination.username is not None
            or destination.fragment
            or port == 0
            or not (
                destination.scheme == "https"
                or (destination.scheme == "http" and destination.hostname.endswith(".svc.cluster.local"))
            )
        ):
            raise ValueError("webhookUrl must use HTTPS or internal Kubernetes service HTTP")

        token = config.get("webhookToken", "")
        if not isinstance(token, str) or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError("webhookToken must be printable ASCII without whitespace")

        def chats(name, pattern):
            values = config.get(name, {})
            if not isinstance(values, dict) or any(
                not pattern.fullmatch(jid) or not isinstance(display_name, str)
                for jid, display_name in values.items()
            ):
                raise ValueError(f"{name} must map WhatsApp chat IDs to display names")
            return {jid: label(display_name) for jid, display_name in values.items()}

        return cls(
            secret.encode(),
            session,
            chats("privateChats", PRIVATE_JID),
            chats("groupChats", GROUP_JID),
            destination,
            token,
        )


def content_for_forwarding(payload):
    raw = fields(payload.get("_data"))
    if fields(raw.get("key")).get("isViewOnce") is True:
        return None

    # Inspect only the current message, never its quoted message or media URL.
    content = fields(raw.get("message"))
    while True:
        if not content or PRIVATE_CONTENT.intersection(content):
            return None
        if any(
            fields(fields(item).get("contextInfo")).get("expiration") not in (None, 0, "0")
            or fields(item).get("viewOnce") is True
            for item in content.values()
        ):
            return None
        if {"protocolMessage", "groupStatusMessage", "groupStatusMessageV2"}.intersection(content):
            return None
        wrapper = next((name for name in CONTENT_WRAPPERS if name in content), None)
        if wrapper is None:
            break
        content = fields(fields(content[wrapper]).get("message"))

    body = payload.get("body")
    body = body if isinstance(body, str) else ""
    attachment = next((kind for key, kind in ATTACHMENTS.items() if key in content), None)
    if fields(content.get("audioMessage")).get("ptt") is True:
        attachment = "Voice message"
    if attachment is None and payload.get("hasMedia") is True:
        attachment = "Attachment"
    if not body.strip() and not attachment:
        return None
    return body, attachment


def forwardable_message(event, config, now):
    if (
        event.get("event") != "message"
        or event.get("session") != config.session
        or event.get("engine") != "NOWEB"
    ):
        return None
    payload = fields(event.get("payload"))
    if payload.get("fromMe") is not False:
        return None

    event_time = event.get("timestamp")
    sent_time = payload.get("timestamp")
    if type(event_time) not in (float, int) or type(sent_time) not in (float, int):
        return None
    event_time /= 1000
    if not (
        -60 <= now - event_time <= MAX_WEBHOOK_AGE
        and -60 <= event_time - sent_time <= MAX_MESSAGE_AGE
    ):
        return None

    chat = payload.get("from")
    message_id = payload.get("id")
    if not isinstance(chat, str) or not isinstance(message_id, str) or not message_id:
        return None
    raw = fields(payload.get("_data"))
    key = fields(raw.get("key"))
    push_name = label(raw.get("pushName"))
    if GROUP_JID.fullmatch(chat):
        if chat not in config.group_chats:
            return None
        participant = private_jid(payload.get("participant"))
        alternate = private_jid(key.get("participantAlt"))
        sender = config.private_chats.get(participant) or config.private_chats.get(alternate)
        sender = sender or push_name or participant or "Unknown sender"
        group = config.group_chats[chat] or chat
    else:
        chat = private_jid(chat)
        if not chat:
            return None
        alternate = private_jid(key.get("remoteJidAlt"))
        allowed_id = chat if chat in config.private_chats else alternate
        if allowed_id not in config.private_chats:
            return None
        sender = config.private_chats[allowed_id] or push_name or allowed_id
        group = None

    content = content_for_forwarding(payload)
    if content is None:
        return None
    body, attachment = content
    delivery_id = hashlib.sha256(json.dumps([config.session, message_id]).encode()).hexdigest()
    return {
        "id": delivery_id,
        "timestamp": int(sent_time),
        "sender": sender,
        "group": group,
        "text": body,
        "attachment": attachment,
    }


class DeliveryQueue:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS delivery (
                    id TEXT PRIMARY KEY NOT NULL,
                    body BLOB,
                    queued_at INTEGER NOT NULL,
                    next_attempt INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    part INTEGER NOT NULL DEFAULT 1
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS delivery_due
                ON delivery(next_attempt) WHERE body IS NOT NULL
            """)

    @contextlib.contextmanager
    def connect(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA secure_delete = ON")
            db.row_factory = sqlite3.Row
            yield db

    def put(self, message, now):
        body = json.dumps(message, separators=(",", ":")).encode()
        with self.connect() as db:
            db.execute("""
                INSERT INTO delivery (id, body, queued_at, next_attempt)
                VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
            """, (message["id"], body, now, now))

    def next_due(self, now):
        with self.connect() as db:
            return db.execute("""
                SELECT id, body, attempts, part FROM delivery
                WHERE body IS NOT NULL AND next_attempt <= ? AND queued_at > ?
                ORDER BY rowid LIMIT 1
            """, (now, now - QUEUE_LIFETIME)).fetchone()

    def expire(self, now):
        with self.connect() as db:
            expired = db.execute("""
                UPDATE delivery SET body = NULL
                WHERE body IS NOT NULL AND queued_at <= ?
            """, (now - QUEUE_LIFETIME,)).rowcount
            db.execute("DELETE FROM delivery WHERE queued_at <= ?", (now - DEDUPE_LIFETIME,))
        if expired:
            logging.warning("Expired %d undelivered WhatsApp message(s)", expired)

    def advance(self, delivery_id, next_part):
        with self.connect() as db:
            if next_part:
                db.execute(
                    "UPDATE delivery SET part = ?, attempts = 0 WHERE id = ?",
                    (next_part, delivery_id),
                )
            else:
                db.execute("UPDATE delivery SET body = NULL WHERE id = ?", (delivery_id,))

    def retry(self, delivery, now):
        delay = min(5 * 2 ** min(delivery["attempts"], 6), 300)
        with self.connect() as db:
            db.execute("""
                UPDATE delivery SET next_attempt = ?, attempts = attempts + 1 WHERE id = ?
            """, (now + delay, delivery["id"]))


class DeliveryError(Exception):
    pass


def post_delivery(config, delivery):
    url = config.destination
    connection_type = (
        http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    )
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": delivery["id"],
        PART_HEADER: str(delivery["part"]),
    }
    if config.token:
        headers[TOKEN_HEADER] = config.token

    with contextlib.closing(connection_type(url.hostname, url.port, timeout=15)) as connection:
        path = url.path or "/"
        if url.query:
            path += "?" + url.query
        connection.request("POST", path, body=delivery["body"], headers=headers)
        with connection.getresponse() as response:
            if not 200 <= response.status < 300:
                raise DeliveryError(f"HTTP {response.status}")
            next_part = response.getheader(NEXT_PART_HEADER)
            if next_part is None or next_part == "0":
                return None
            if next_part != str(delivery["part"] + 1):
                raise DeliveryError("invalid next-part acknowledgment")
            return delivery["part"] + 1


def deliver(queue, config):
    next_cleanup = 0
    while True:
        now = int(time.time())
        try:
            if now >= next_cleanup:
                queue.expire(now)
                next_cleanup = now + 60
            delivery = queue.next_due(now) if config else None
            if delivery:
                try:
                    next_part = post_delivery(config, delivery)
                except (DeliveryError, OSError, http.client.HTTPException) as error:
                    reason = str(error) if isinstance(error, DeliveryError) else type(error).__name__
                    logging.warning("Webhook delivery failed (%s); will retry", reason)
                    queue.retry(delivery, int(time.time()))
                else:
                    queue.advance(delivery["id"], next_part)
        except sqlite3.Error:
            logging.error("Delivery queue database operation failed")
        # One worker sends at most one part per second to the Telegram conversation.
        time.sleep(1.1)


class WebhookHandler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, *args):
        pass

    def reply(self, status):
        self.send_response(status)
        self.end_headers()

    def do_GET(self):
        if self.path != "/health":
            self.reply(404)
        else:
            self.reply(204 if self.server.delivery_worker.is_alive() else 503)

    def do_POST(self):
        if self.path != "/webhook":
            self.reply(404)
            return
        config = self.server.forwarder_config
        if config is None:
            self.reply(503)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            self.reply(413 if length > MAX_REQUEST_BYTES else 400)
            return
        signature = self.headers.get("X-Webhook-Hmac", "")
        if not re.fullmatch(r"[0-9a-f]{128}", signature):
            self.reply(403)
            return
        body = self.rfile.read(length)
        expected = hmac.new(config.hmac_key, body, "sha512").hexdigest()
        if not hmac.compare_digest(signature, expected):
            self.reply(403)
            return

        try:
            event = fields(json.loads(body))
            now = int(time.time())
            message = forwardable_message(event, config, now)
        except (ValueError, OverflowError, RecursionError):
            self.reply(400)
            return
        if message is not None:
            try:
                self.server.delivery_queue.put(message, now)
            except sqlite3.Error:
                logging.error("Could not enqueue WhatsApp message")
                self.reply(503)
                return
        self.reply(204)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        config = Config.from_env()
    except ValueError as error:
        sys.exit(str(error))
    with open("/data/worker.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue = DeliveryQueue("/data/queue.sqlite3")
        with ThreadingHTTPServer(("", 8080), WebhookHandler) as server:
            server.forwarder_config = config
            server.delivery_queue = queue
            server.delivery_worker = threading.Thread(target=deliver, args=(queue, config), daemon=True)
            server.delivery_worker.start()
            logging.info("WAHA forwarder %s", "ready" if config else "disabled until configured")
            server.serve_forever()


if __name__ == "__main__":
    main()
