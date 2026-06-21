import os
import random
import re
import time

from restate import Context, Service

URL = "https://padelmates.se/club/instantpadelatcanadawater"

PADEL_USERNAME = os.getenv("PADEL_USERNAME", "tomatheickal@hotmail.com")
PADEL_PASSWORD = os.getenv("PADEL_PASSWORD", "")


def _delay(min_s=0.5, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))


def _book_court(date_pattern: str, slot_idx: int = 0) -> dict:
    from playwright.sync_api import sync_playwright

    if not PADEL_PASSWORD:
        return {"status": "error", "detail": "PADEL_PASSWORD not set"}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            slow_mo=80,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            timezone_id="Europe/London",
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
        """)

        try:
            # step 1: open club page
            page.goto(URL)
            _delay()

            # step 2: pick date
            _delay()
            page.get_by_role("button", name="Today").click()
            page.get_by_role("option", name=re.compile(date_pattern)).click()

            # step 3: pick slot by index
            _delay()
            slots = page.locator(
                "#root > div > div.mt-\\[80px\\] > div > div > div.px-4.md\\:px-2.lg\\:px-4.xl\\:px-7.mx-auto.flex.w-full.max-w-\\[1412px\\].justify-center.items-center > div > div.w-full.md\\:w-\\[calc\\(70\\%-4px\\)\\].lg\\:w-\\[calc\\(60\\%-8px\\)\\].xl\\:max-w-\\[850px\\].xl\\:w-\\[850px\\].md\\:mr-auto.flex.flex-col.gap-10.mt-8.md\\:mt-0 > div.md\\:block.hidden > div.md\\:block.hidden.mb-10.px-2.md\\:px-0 > div > div.overflow-hidden > div > div:nth-child(4) > div:nth-child(13) > div:nth-child(2) > div"
            )
            slot = slots.nth(slot_idx)
            slot.hover()
            slot.click()

            # step 4: pick 1h 30m session
            _delay()
            page.get_by_role("button", name=re.compile(r"1h 30m.*\u00a3")).click()

            # step 5: book
            _delay()
            page.get_by_role("button", name=re.compile(r"Book \u00a3")).click()

            # step 6: sign in
            _delay()
            page.get_by_role("textbox", name="Email address").fill(PADEL_USERNAME)
            page.get_by_role("textbox", name="Password").fill(PADEL_PASSWORD)
            _delay()
            page.get_by_role("button", name="Sign in", exact=True).click()

            # step 7: payment flow
            _delay()
            page.get_by_role("button", name="Continue to payment").click()
            _delay()
            page.get_by_role("button", name="Confirm extras").click()
            _delay()
            page.get_by_role("button", name="Pay now").click()
            time.sleep(10)

            return {"status": "booked", "date_pattern": date_pattern, "slot_idx": slot_idx}
        except Exception:
            return {"status": "error", "detail": "Booking failed — check Restate invocation for details"}
        finally:
            context.close()
            browser.close()


service = Service("padelBooking")


@service.handler()
async def book(ctx: Context, arg: dict) -> dict:
    date_pattern = arg["date_pattern"]
    slot_idx = arg.get("slot_idx", 0)

    result = await ctx.run(
        "book_court",
        lambda: _book_court(date_pattern, slot_idx),
    )

    return result


if __name__ == "__main__":
    from restate.endpoint import endpoint

    endpoint(service).run(host="0.0.0.0", port=9080)