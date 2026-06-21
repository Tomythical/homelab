import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from restate import Context, Service, Workflow

# ── FastAPI app (port 8000 ─ webhooks, direct API) ──────────────────────────

app = FastAPI()

WAHA_API_URL = os.getenv("WAHA_API_URL", "http://waha.waha.svc.cluster.local:3000")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WEBHOOK_URL = os.getenv("POLL_BOT_WEBHOOK_URL", "http://poll-bot.waha.svc.cluster.local/webhook")
RESULTS_FILE = os.getenv("RESULTS_FILE", "/data/results.json")

POLL_CHAT_ID = os.getenv("POLL_CHAT_ID", "")
POLL_NAME = os.getenv("POLL_NAME", "Padel this week?")
POLL_OPTIONS = os.getenv("POLL_OPTIONS", "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday")
POLL_SELECTABLE_COUNT = int(os.getenv("POLL_SELECTABLE_COUNT", "1"))
POLL_VOTING_SECONDS = int(os.getenv("POLL_VOTING_SECONDS", "172800"))

PADEL_SLOT_IDX = int(os.getenv("PADEL_SLOT_IDX", "0"))
RESTATE_SERVER_URL = os.getenv("RESTATE_SERVER_URL", "http://restate.restate.svc.cluster.local:9071")

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
        message_id = result.get("id", {}).get("_serialized") or result.get("key", {}).get("id")

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
            or payload.get("message", {}).get("_data", {}).get("id", {}).get("_serialized")
            or payload.get("id")
        )

        vote = payload.get("vote", {}) or payload.get("voteMessage", payload)
        voter = vote.get("sender", "")

        if isinstance(vote, dict):
            selected = vote.get("selectedOptions", []) or vote.get("selectedOptionIds", [])
        else:
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


# ── Restate workflow (port 9080 ─ scheduled poll orchestration) ─────────────

workflow = Workflow("pollScheduler")

padel_service = Service("padelBooking")


def _send_poll_to_waha() -> str:
    options = [o.strip() for o in POLL_OPTIONS.split(",") if o.strip()]
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{WAHA_API_URL}/api/sendPoll",
            headers=_waha_headers(),
            json={
                "chatId": POLL_CHAT_ID,
                "poll": {
                    "name": POLL_NAME,
                    "options": options,
                    "selectableOptionsCount": POLL_SELECTABLE_COUNT,
                },
            },
        )
        resp.raise_for_status()
        result = resp.json()
        message_id = result.get("id", {}).get("_serialized") or result.get("key", {}).get("id")

        if message_id:
            with _results_lock:
                results = _load_results()
                results[message_id] = {
                    "chatId": POLL_CHAT_ID,
                    "poll": {
                        "name": POLL_NAME,
                        "options": options,
                        "selectableOptionsCount": POLL_SELECTABLE_COUNT,
                    },
                    "votes": [],
                    "sentAt": datetime.now(timezone.utc).isoformat(),
                }
                _save_results(results)

        return message_id or ""


def _get_poll_results(message_id: str) -> dict:
    with _results_lock:
        results = _load_results()
        return results.get(message_id, {})


def _determine_winner(poll_data: dict) -> dict:
    poll_options = poll_data.get("poll", {}).get("options", [])
    vote_counts: dict[str, int] = {opt: 0 for opt in poll_options}

    for vote in poll_data.get("votes", []):
        for option_idx in vote.get("options", []):
            if 0 <= option_idx < len(poll_options):
                vote_counts[poll_options[option_idx]] += 1

    if not vote_counts or all(v == 0 for v in vote_counts.values()):
        return {"winner": None, "error": "No votes received"}

    winner_day = max(vote_counts, key=vote_counts.get)

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    target_day_idx = days.index(winner_day)

    now = datetime.now(timezone.utc)
    two_weeks_out = now + timedelta(days=14)
    days_until = (target_day_idx - two_weeks_out.weekday()) % 7
    if days_until == 0:
        days_until = 7
    booking_date = two_weeks_out + timedelta(days=days_until)

    date_pattern = f"{winner_day}, {booking_date.strftime('%B')} {booking_date.day}"

    return {
        "winner": winner_day,
        "votes": vote_counts[winner_day],
        "date_pattern": date_pattern,
        "booking_date": booking_date.strftime("%Y-%m-%d"),
        "all_votes": vote_counts,
    }


@workflow.handler()
async def schedule_poll(ctx: Context, _arg: dict | None = None) -> dict:
    message_id = await ctx.run("send_poll", _send_poll_to_waha)
    print(f"Poll sent: {message_id}")

    await ctx.sleep(POLL_VOTING_SECONDS)
    print(f"Voting period ended for {message_id}")

    poll_data = await ctx.run("get_results", lambda: _get_poll_results(message_id))

    winner = await ctx.run("determine_winner", lambda: _determine_winner(poll_data))

    if winner.get("winner"):
        booking_result = await ctx.service_call(
            "padelBooking",
            "book",
            key="default",
            arg={
                "date_pattern": winner["date_pattern"],
                "slot_idx": PADEL_SLOT_IDX,
            },
        )
        winner["booking"] = booking_result

    return winner


# ── Run both servers ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from restate.endpoint import endpoint

    restate_endpoint = endpoint(workflow, padel_service)

    def _start_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=8000)

    thread = threading.Thread(target=_start_fastapi, daemon=True)
    thread.start()

    restate_endpoint.run(host="0.0.0.0", port=9080)