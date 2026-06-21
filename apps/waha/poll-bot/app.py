import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI()

WAHA_API_URL = os.getenv("WAHA_API_URL", "http://waha.waha.svc.cluster.local:3000")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WEBHOOK_URL = os.getenv(
    "POLL_BOT_WEBHOOK_URL", "http://poll-bot.waha.svc.cluster.local/webhook"
)
RESULTS_FILE = os.getenv("RESULTS_FILE", "/data/results.json")

_results_lock = threading.Lock()


def _load_results() -> dict:
    try:
        with open(RESULTS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_results(results: dict) -> None:
    Path(RESULTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


def _waha_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if WAHA_API_KEY:
        headers["X-Api-Key"] = WAHA_API_KEY
    return headers


class PollOption(BaseModel):
    name: str
    options: list[str]
    selectableOptionsCount: int = 1


class PollRequest(BaseModel):
    chatId: str
    poll: PollOption


class PollVoteItem(BaseModel):
    voter: str
    options: list[int]
    timestamp: str | None = None


class WebhookEvent(BaseModel):
    event: str
    session: str
    payload: dict


@app.on_event("startup")
def startup() -> None:
    _configure_webhooks()


def _configure_webhooks() -> None:
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{WAHA_API_URL}/api/sessions",
                headers=_waha_headers(),
            )
            resp.raise_for_status()
            sessions = resp.json()

            for session in sessions:
                session_name = session.get("name", "")
                if not session_name:
                    continue

                try:
                    client.post(
                        f"{WAHA_API_URL}/api/sessions/{session_name}",
                        headers=_waha_headers(),
                        json={
                            "name": session_name,
                            "config": {
                                "webhook": {"url": WEBHOOK_URL, "events": ["poll.vote"]}
                            },
                        },
                    )
                    print(f"Webhook configured for session: {session_name}")
                except httpx.HTTPError as e:
                    print(f"Failed to configure webhook for {session_name}: {e}")
    except httpx.HTTPError as e:
        print(f"Failed to list WAHA sessions: {e}")


def _get_chat_id_prefix(chat_id: str) -> str:
    return chat_id[: chat_id.index("@")] if "@" in chat_id else chat_id


@app.post("/poll")
def send_poll(req: PollRequest) -> dict:
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{WAHA_API_URL}/api/sendPoll",
            headers=_waha_headers(),
            json={
                "chatId": req.chatId,
                "poll": req.poll.model_dump(),
            },
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        result = resp.json()
        message_id = result.get("id", {}).get("_serialized") or result.get(
            "key", {}
        ).get("id")

        if message_id:
            with _results_lock:
                results = _load_results()
                results[message_id] = {
                    "chatId": req.chatId,
                    "poll": req.poll.model_dump(),
                    "votes": [],
                    "sentAt": datetime.now(timezone.utc).isoformat(),
                }
                _save_results(results)

        return {
            "status": "sent",
            "messageId": message_id,
            "waResponse": result,
        }


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    data = await request.json()

    events = data if isinstance(data, list) else [data]

    for event in events:
        event_type = event.get("event", "")
        if event_type != "poll.vote":
            continue

        payload = event.get("payload", {})
        message_id = (
            payload.get("msgId", {}).get("_serialized")
            or payload.get("message", {})
            .get("_data", {})
            .get("id", {})
            .get("_serialized")
            or payload.get("id")
        )

        vote = payload.get("vote", {}) or payload.get("voteMessage", payload)
        voter = vote.get("sender", "")

        if isinstance(vote, dict):
            selected = vote.get("selectedOptions", []) or vote.get(
                "selectedOptionIds", []
            )
        else:
            selected = []
            continue

        if not message_id or not voter:
            continue

        with _results_lock:
            results = _load_results()
            if message_id in results:
                vote_entry = {
                    "voter": voter,
                    "options": selected,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                results[message_id]["votes"].append(vote_entry)
                _save_results(results)

    return {"status": "received"}


@app.get("/results/{message_id}")
def get_results(message_id: str) -> dict:
    with _results_lock:
        results = _load_results()
        if message_id not in results:
            raise HTTPException(status_code=404, detail="Poll not found")
        return {message_id: results[message_id]}


@app.get("/results")
def list_polls() -> dict:
    with _results_lock:
        return _load_results()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

