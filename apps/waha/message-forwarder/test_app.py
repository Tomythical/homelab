import contextlib
import copy
import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app import (
    QUEUE_LIFETIME,
    Config,
    DeliveryQueue,
    WebhookHandler,
    forwardable_message,
)


class ForwarderTest(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())
        self.config = Config(
            b"test-signing-key",
            "default",
            {"15555550100@c.us": "Maya"},
            {"12345@g.us": "Family"},
            urlsplit("https://example.test/webhook"),
            "",
        )
        self.event = {
            "event": "message",
            "engine": "NOWEB",
            "session": "default",
            "timestamp": self.now * 1000,
            "payload": {
                "id": "false_15555550101@lid_message",
                "timestamp": self.now,
                "fromMe": False,
                "from": "15555550101@lid",
                "body": "Hello",
                "_data": {
                    "key": {"remoteJidAlt": "15555550100@s.whatsapp.net"},
                    "message": {"conversation": "Hello"},
                },
            },
        }

    def test_direct_chat_alias_does_not_authorize_groups(self):
        direct = forwardable_message(self.event, self.config, self.now)
        self.assertEqual(direct["sender"], "Maya")
        self.assertIsNone(direct["group"])

        payload = self.event["payload"]
        payload["from"] = "99999@g.us"
        payload["participant"] = "15555550100@c.us"
        self.assertIsNone(forwardable_message(self.event, self.config, self.now))
        payload["from"] = "12345@g.us"
        group = forwardable_message(self.event, self.config, self.now)
        self.assertEqual((group["group"], group["sender"]), ("Family", "Maya"))
        payload["participant"] = "15555550199@lid"
        payload["_data"]["pushName"] = "Sam"
        self.assertEqual(forwardable_message(self.event, self.config, self.now)["sender"], "Sam")

    def test_temporary_content_filtered_without_inspecting_quote(self):
        payload = self.event["payload"]
        payload["body"] = "Caption"
        payload["_data"]["message"] = {
            "documentWithCaptionMessage": {
                "message": {
                    "documentMessage": {
                        "contextInfo": {"quotedMessage": {"ephemeralMessage": {}}},
                    },
                },
            },
        }
        forward = forwardable_message(self.event, self.config, self.now)
        self.assertEqual((forward["attachment"], forward["text"]), ("Document", "Caption"))
        document = payload["_data"]["message"]["documentWithCaptionMessage"]["message"]
        document["documentMessage"]["contextInfo"]["expiration"] = 86400
        self.assertIsNone(forwardable_message(self.event, self.config, self.now))
        document["documentMessage"]["contextInfo"]["expiration"] = 0
        payload["_data"]["key"]["isViewOnce"] = True
        self.assertIsNone(forwardable_message(self.event, self.config, self.now))

    def test_authenticated_ingress_and_queue_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            queue = DeliveryQueue(path)
            with ThreadingHTTPServer(("127.0.0.1", 0), WebhookHandler) as server:
                server.forwarder_config = self.config
                server.delivery_queue = queue
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with contextlib.closing(http.client.HTTPConnection(*server.server_address)) as connection:
                        self.assertEqual(self.post(connection, self.event, "0" * 128), 403)
                        self.assertIsNone(queue.next_due(self.now))

                        for changes in ({"fromMe": True}, {"timestamp": self.now - 600}):
                            ignored = copy.deepcopy(self.event)
                            ignored["payload"].update(changes)
                            self.assertEqual(self.post(connection, ignored), 204)
                        self.assertIsNone(queue.next_due(self.now))

                        self.assertEqual(self.post(connection, self.event), 204)
                        self.assertEqual(self.post(connection, self.event), 204)
                finally:
                    server.shutdown()
                    thread.join()

            due_time = int(time.time())
            queue = DeliveryQueue(path)
            queued = queue.next_due(due_time)
            self.assertEqual(json.loads(queued["body"])["text"], "Hello")
            queue.advance(queued["id"], 2)
            queue.retry(queue.next_due(due_time), due_time)

            queue = DeliveryQueue(path)
            self.assertIsNone(queue.next_due(due_time))
            self.assertEqual(queue.next_due(due_time + 5)["part"], 2)
            queue.advance(queued["id"], None)
            self.assertIsNone(queue.next_due(due_time + 5))
            queue.put(json.loads(queued["body"]), due_time + 5)
            self.assertIsNone(queue.next_due(due_time + 5))

            message = {**json.loads(queued["body"]), "id": "another"}
            queue.put(message, due_time)
            with self.assertLogs(level="WARNING"):
                queue.expire(due_time + QUEUE_LIFETIME)
            with queue.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(body) FROM delivery").fetchone()[0], 0)

    def post(self, connection, event, signature=None):
        body = json.dumps(event).encode()
        signature = signature or hmac.new(self.config.hmac_key, body, hashlib.sha512).hexdigest()
        connection.request("POST", "/webhook", body, {"X-Webhook-Hmac": signature})
        with connection.getresponse() as response:
            response.read()
            return response.status
