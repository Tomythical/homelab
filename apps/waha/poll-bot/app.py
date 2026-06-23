import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import restate
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

WAHA_API_URL = os.getenv("WAHA_API_URL", "http://waha.waha.svc.cluster.local:3000")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
WEBHOOK_URL = os.getenv(
    "POLL_BOT_WEBHOOK_URL", "http://poll-bot.waha.svc.cluster.local/webhook"
)
RESULTS_FILE = os.getenv("RESULTS_FILE", "/data/results.json")

POLL_CHAT_ID = os.getenv("POLL_CHAT_ID", "")
POLL_NAME = os.getenv("POLL_NAME", "Padel this week?")
POLL_OPTIONS = os.getenv(
    "POLL_OPTIONS", "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
)
POLL_SELECTABLE_COUNT = int(os.getenv("POLL_SELECTABLE_COUNT", "1"))
POLL_VOTING_SECONDS = int(os.getenv("POLL_VOTING_SECONDS", "172800"))

PADEL_SLOT_IDX = int(os.getenv("PADEL_SLOT_IDX", "0"))

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
                    existing = session.get("config", {})
                    existing["webhooks"] = [{"url": WEBHOOK_URL, "events": ["poll.vote"]}]
                    client.put(
                        f"{WAHA_API_URL}/api/sessions/{session_name}",
                        headers=_waha_headers(),
                        json={
                            "name": session_name,
                            "config": existing,
                        },
                    )
                    print(f"Webhook configured for session: {session_name}")
                except httpx.HTTPError as e:
                    print(f"Failed to configure webhook for {session_name}: {e}")
    except httpx.HTTPError as e:
        print(f"Failed to list WAHA sessions: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _configure_webhooks()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/poll")
def send_poll(req: PollRequest) -> dict:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{WAHA_API_URL}/api/sendPoll",
                headers=_waha_headers(),
                json={
                    "session": WAHA_SESSION,
                    "chatId": req.chatId,
                    "poll": req.poll.model_dump(),
                },
            )
            body = resp.text
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=body)

            result = resp.json()
            mid = result.get("id") or result.get("key", {})
            message_id = mid.get("_serialized") if isinstance(mid, dict) else str(mid) if mid else None

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            continue

        if not message_id or not voter:
            continue

        with _results_lock:
            results = _load_results()
            if message_id in results:
                results[message_id]["votes"] = [
                    v for v in results[message_id]["votes"]
                    if v["voter"] != voter
                ]
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


@app.get("/sessions")
def list_sessions() -> dict:
    """Debug: list WAHA sessions to verify session name"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{WAHA_API_URL}/api/sessions",
                headers=_waha_headers(),
            )
            resp.raise_for_status()
            return {"sessions": resp.json()}
    except Exception as e:
        return {"error": str(e)}


@app.post("/test/book")
def test_book(data: dict) -> dict:
    """Debug: trigger padelBooking with a date_pattern and slot_idx"""
    date_pattern = data.get("date_pattern", "Thursday, July 10")
    slot_idx = data.get("slot_idx", PADEL_SLOT_IDX)
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "http://padel-booking.waha.svc.cluster.local:9080/book",
                json={"date_pattern": date_pattern, "slot_idx": slot_idx},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ── Restate workflow (mounted on /restate/v1) ──────────────────────────────

workflow = restate.Workflow("pollScheduler")


def _send_poll_to_waha() -> str:
    options = [o.strip() for o in POLL_OPTIONS.split(",") if o.strip()]
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{WAHA_API_URL}/api/sendPoll",
            headers=_waha_headers(),
            json={
                "session": WAHA_SESSION,
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
        message_id = result.get("id", {}).get("_serialized") or result.get(
            "key", {}
        ).get("id")

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

    days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
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


@workflow.main()
async def schedule_poll(ctx: restate.WorkflowContext) -> dict:
    message_id = await ctx.run_typed("send_poll", _send_poll_to_waha)
    print(f"Poll sent: {message_id}")

    await ctx.sleep(delta=timedelta(seconds=POLL_VOTING_SECONDS))
    print(f"Voting period ended for {message_id}")

    poll_data = await ctx.run_typed(
        "get_results", lambda: _get_poll_results(message_id)
    )

    winner = await ctx.run_typed(
        "determine_winner", lambda: _determine_winner(poll_data)
    )

    if winner.get("winner"):
        booking_arg = json.dumps(
            {
                "date_pattern": winner["date_pattern"],
                "slot_idx": PADEL_SLOT_IDX,
            }
        ).encode("utf-8")

        booking_bytes = await ctx.generic_call(
            "padelBooking",
            "book",
            key="default",
            arg=booking_arg,
        )
        winner["booking"] = json.loads(booking_bytes)

    return winner


# ── Mount Restate on FastAPI ────────────────────────────────────────────────

restate_app = restate.app(services=[workflow])
app.mount("/restate/v1", restate_app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9080)

