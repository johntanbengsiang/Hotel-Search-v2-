"""
Google Hotels Price Scraper
Architecture:
  - /api/test-direct  : tests batchexecute API with known token (no browser needed)
  - /api/test-proxy   : tests if a proxy env var reaches google.com/travel
  - /api/scrape       : main endpoint
"""

import asyncio, json, re, requests, nest_asyncio
from datetime import datetime, date, timedelta
from calendar import monthrange
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote
import os

nest_asyncio.apply()

app = Flask(__name__)
CORS(app)
app.static_folder = "."
app.static_url_path = ""

@app.route("/")
def index():
    return app.send_static_file("index.html")
@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")

@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js")
# ─── helpers ────────────────────────────────────────────────────────────────

def months_in_range(start: date, end: date):
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12: m, y = 1, y + 1
    return months

def month_window(year, month):
    return [year, month, 1], [year, month, monthrange(year, month)[1]]

def parse_prices(text):
    results = {}
    m = re.search(r'\["wrb\.fr","yY52ce","(.+?)",null,null,null', text, re.DOTALL)
    if not m:
        return results
    try:
        parsed = json.loads(json.loads('"' + m.group(1) + '"'))
        for entry in parsed[1]:
            try:
                # entry[8]: [[check_in_y, check_in_m, check_in_d],
                #             [check_out_y, check_out_m, check_out_d],
                #             nights, ...]
                ci     = entry[8][0]   # check-in date [y, m, d]
                nights = entry[8][2]   # number of nights in this window

                # entry[44]: [base_price, tax_amount, fees, tax_inclusive_total]
                # entry[1][4]: rounded base rate (excl. tax) — what we were using before
                # Google's calendar shows tax-inclusive prices, so use entry[44][3]
                price_with_tax = entry[44][3]   # exact float, tax-inclusive
                price = round(price_with_tax)

                date_key = f"{ci[0]}-{ci[1]:02d}-{ci[2]:02d}"
                # Prefer 1-night entries if API ever returns mixed windows
                if date_key not in results or nights == 1:
                    results[date_key] = price
            except:
                pass
    except:
        pass
    return results

# Currency → Google locale mapping
GL_TIMEZONE = {
    "sg": "-480", "th": "-420", "id": "-420", "my": "-480", "vn": "-420",
    "ph": "-480", "jp": "-540", "hk": "-480", "tw": "-480", "kr": "-540",
    "cn": "-480", "gb": "0",   "fr": "-60",  "de": "-60",  "it": "-60",
    "es": "-60",  "nl": "-60",  "ch": "-60",  "pt": "0",   "gr": "-120",
    "us": "300",  "ca": "300",  "mx": "360",  "br": "180", "ae": "-240",
    "qa": "-180", "sa": "-180", "in": "-330", "mv": "-300","au": "-600",
    "nz": "-720", "za": "-120", "ma": "0",
}
GL_COUNTRY_CODE = {
    "sg":"SG","th":"TH","id":"ID","my":"MY","vn":"VN","ph":"PH","jp":"JP",
    "hk":"HK","tw":"TW","kr":"KR","cn":"CN","gb":"GB","fr":"FR","de":"DE",
    "it":"IT","es":"ES","nl":"NL","ch":"CH","pt":"PT","gr":"GR","us":"US",
    "ca":"CA","mx":"MX","br":"BR","ae":"AE","qa":"QA","sa":"SA","in":"IN",
    "mv":"MV","au":"AU","nz":"NZ","za":"ZA","ma":"MA",
}

def batchexecute(token, year, month, cookies=None, f_sid=None, bl=None, currency="SGD", gl="sg", guests=2):
    start, end = month_window(year, month)
    freq = json.dumps([[["yY52ce",
        json.dumps([None, [start, end, 1], None, token, currency]),
        None, "generic"]]])
    tz  = GL_TIMEZONE.get(gl, "0")
    cc  = GL_COUNTRY_CODE.get(gl, "SG")
    params = {"rpcids":"yY52ce","source-path":"/travel/search",
              "hl":"en","gl":gl,"soc-app":"162",
              "soc-platform":"1","soc-device":"1","rt":"c"}
    if f_sid: params["f.sid"] = f_sid
    if bl:    params["bl"]    = bl
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.google.com/travel/search",
        "x-same-domain": "1",
        "x-goog-ext-259736195-jspb": f'["en-US","{cc}","{currency}",{guests},null,[{tz}],null,null,7,[]]',
        "x-goog-ext-190139975-jspb": f'["{cc}","ZZ","ZwswOw=="]',
    }
    r = requests.post(
        "https://www.google.com/_/TravelFrontendUi/data/batchexecute",
        params=params, data={"f.req": freq},
        headers=headers, cookies=cookies or {}, timeout=20)
    return r.status_code, r.text

# ─── diagnostic endpoints ────────────────────────────────────────────────────

@app.route("/api/test-direct")
def test_direct():
    """
    Tests whether batchexecute works WITHOUT any browser session.
    Uses Marina Bay Sands (well-known stable token).
    Run this first to see if we even need Playwright.
    """
    TOKEN = "ChcIq5qZt_n_____ARoJL20vMDc3Nm14EAE"
    results = {}

    # Test 1: completely bare (no cookies, no session params)
    status1, body1 = batchexecute(TOKEN, 2026, 8)
    prices1 = parse_prices(body1)
    results["test1_no_session"] = {
        "status": status1,
        "body_len": len(body1),
        "has_data": bool(prices1),
        "prices_found": len(prices1),
        "sample": dict(list(prices1.items())[:3]),
        "first_200": body1[:200],
    }

    # Test 2: With full goog extension headers
    start, end = month_window(2026, 8)
    freq = json.dumps([[["yY52ce",
        json.dumps([None, [start, end, 1], None, TOKEN, "SGD"]),
        None, "generic"]]])
    r2 = requests.post(
        "https://www.google.com/_/TravelFrontendUi/data/batchexecute",
        params={"rpcids":"yY52ce","source-path":"/travel/search","hl":"en",
                "gl":"sg","soc-app":"162","soc-platform":"1","soc-device":"1","rt":"c"},
        data={"f.req": freq},
        headers={
            "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer":"https://www.google.com/travel/search",
            "x-same-domain":"1",
            "x-goog-ext-259736195-jspb":'["en-US","SG","USD",1,null,[-480],null,null,7,[]]',
            "x-goog-ext-190139975-jspb":'["SG","ZZ","ZwswOw=="]',
            "Accept":"*/*", "Accept-Language":"en-US,en;q=0.9",
            "Origin":"https://www.google.com",
        },
        timeout=20
    )
    prices2 = parse_prices(r2.text)
    results["test2_full_headers"] = {
        "status": r2.status_code,
        "body_len": len(r2.text),
        "has_data": bool(prices2),
        "prices_found": len(prices2),
        "sample": dict(list(prices2.items())[:3]),
        "first_200": r2.text[:200],
    }

    # Report server IP for debugging
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=5).json()["ip"]
    except:
        ip = "unknown"

    results["server_ip"] = ip
    results["conclusion"] = (
        "batchexecute works without browser!" 
        if (prices1 or prices2) 
        else "batchexecute requires browser session or different IP"
    )
    return jsonify(results)


@app.route("/api/test-proxy")
def test_proxy():
    """
    Tests if PROXY_URL env var routes around Google's datacenter IP block.
    Set PROXY_URL=http://user:pass@host:port in Render env vars.
    """
    proxy_url = os.environ.get("PROXY_URL")
    if not proxy_url:
        return jsonify({
            "error": "PROXY_URL env var not set",
            "how_to": "Add PROXY_URL=http://user:pass@host:port in Render environment variables",
            "free_options": [
                "webshare.io - 10 free residential proxies",
                "proxyscrape.com - free shared proxies (less reliable)",
            ]
        })

    proxies = {"http": proxy_url, "https": proxy_url}
    results = {}

    # Test 1: Can we reach google.com/travel through proxy?
    try:
        r = requests.get(
            "https://www.google.com/travel/search?q=Marina+Bay+Sands+Singapore&hl=en&gl=sg",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                     "Accept-Language": "en-US,en;q=0.9"},
            proxies=proxies, timeout=20
        )
        tokens = re.findall(r"/travel/hotels/entity/([A-Za-z0-9_=-]{20,})", r.text)
        results["proxy_travel_page"] = {
            "status": r.status_code,
            "body_len": len(r.text),
            "tokens_found": tokens[:3],
            "has_entity_links": bool(tokens),
            "note": "If status=200 and tokens found, proxy works for token extraction",
        }
    except Exception as e:
        results["proxy_travel_page"] = {"error": str(e)}

    # Test 2: Proxy IP
    try:
        ip_r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
        results["proxy_ip"] = ip_r.json().get("ip")
    except Exception as e:
        results["proxy_ip"] = f"error: {e}"

    return jsonify(results)


@app.route("/api/test-playwright")
def test_playwright():
    """
    Tests Playwright with optional PROXY_URL.
    Measures timing and whether token is found.
    """
    proxy_url = os.environ.get("PROXY_URL")

    async def run():
        from playwright.async_api import async_playwright
        import time

        log = []
        result = {"token": None, "f_sid": None, "cookies": 0, "timing": {}}

        async with async_playwright() as p:
            t0 = time.time()
            launch_kwargs = dict(
                headless=True,
                args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                      "--single-process","--no-zygote",
                      "--disable-blink-features=AutomationControlled",
                      "--disable-background-networking","--no-first-run"],
            )
            if proxy_url:
                launch_kwargs["proxy"] = {"server": proxy_url}
                log.append(f"Using proxy: {proxy_url[:30]}...")
            else:
                log.append("No proxy - direct connection")

            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4}", 
                              lambda r: r.abort())

            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            def on_request(req):
                if "batchexecute" in req.url:
                    sid_m = re.search(r"f\.sid=(-?\d+)", req.url)
                    bl_m  = re.search(r"bl=([^&]+)", req.url)
                    if sid_m: result["f_sid"] = sid_m.group(1)
                    if bl_m:  result["bl"]    = bl_m.group(1)

            page.on("request", on_request)
            result["timing"]["browser_launch"] = round(time.time() - t0, 2)

            try:
                await page.goto(
                    "https://www.google.com/travel/search?q=Marina+Bay+Sands+Singapore&hl=en&gl=sg",
                    wait_until="commit", timeout=30000
                )
                result["timing"]["commit"] = round(time.time() - t0, 2)
                log.append(f"commit at {result['timing']['commit']}s")

                for i in range(20):
                    await asyncio.sleep(1)
                    html = await page.content()
                    tokens = re.findall(r"/travel/hotels/entity/([A-Za-z0-9_=-]{20,})", html)
                    log.append(f"t={i+1}s html_len={len(html)} tokens={len(tokens)}")
                    if tokens:
                        result["token"] = tokens[0]
                        result["timing"]["token_found"] = round(time.time() - t0, 2)
                        break
                    if i == 0 and len(html) < 500:
                        log.append(f"Suspicious short page: {html[:200]}")
            except Exception as e:
                log.append(f"Error: {e}")
                result["timing"]["error"] = round(time.time() - t0, 2)

            cookies = await context.cookies()
            result["cookies"] = len(cookies)
            result["timing"]["total"] = round(time.time() - t0, 2)
            await browser.close()

        return result, log

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result, log = loop.run_until_complete(run())
    finally:
        loop.close()

    return jsonify({"result": result, "log": log})


# ─── main scrape ─────────────────────────────────────────────────────────────

async def get_session(hotel_name, debug, gl="sg", currency="SGD", guests=2):
    from playwright.async_api import async_playwright
    import time

    proxy_url = os.environ.get("PROXY_URL")
    session = {"token": None, "cookies": {}, "f_sid": None, "bl": None}

    async with async_playwright() as p:
        launch_kwargs = dict(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                  "--single-process","--no-zygote",
                  "--disable-blink-features=AutomationControlled",
                  "--disable-background-networking","--no-first-run","--mute-audio"],
        )
        if proxy_url:
            launch_kwargs["proxy"] = {"server": proxy_url}
            debug.append(f"Using proxy: {proxy_url[:25]}...")

        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4}",
                           lambda r: r.abort())
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});"
            "window.chrome={runtime:{}};"
        )
        page.on("request", lambda req: (
            session.update({"f_sid": re.search(r"f\.sid=(-?\d+)", req.url).group(1)})
            if "batchexecute" in req.url and re.search(r"f\.sid=(-?\d+)", req.url) else None
        ))

        t0 = time.time()
        try:
            await page.goto(
                f"https://www.google.com/travel/search?q={quote(hotel_name)}&hl=en&gl={gl}&curr={currency}&num_adults={guests}",
                wait_until="commit", timeout=60000
            )
            debug.append(f"Page committed at {time.time()-t0:.1f}s")
        except Exception as e:
            debug.append(f"goto error: {e}")
            await browser.close()
            return session

        for i in range(30):
            await asyncio.sleep(1)
            try:
                html = await page.content()
                if len(html) < 500 and i < 5:
                    debug.append(f"t={i+1}s: short page ({len(html)} chars) - may be blocked")
                tokens = re.findall(r"/travel/hotels/entity/([A-Za-z0-9_=-]{20,})", html)
                if tokens:
                    session["token"] = tokens[0]
                    debug.append(f"Token found at t={i+1}s")
                    break
            except: pass
            if i == 5:
                try:
                    btn = page.locator('button:has-text("Accept all"), button:has-text("I agree")')
                    if await btn.count() > 0:
                        await btn.first.click()
                        debug.append("Dismissed consent popup")
                except: pass

        if session["token"]:
            try:
                await page.locator('a[href*="/travel/hotels/entity/"]').first.click(timeout=8000)
                await page.wait_for_timeout(3000)
            except: pass
        else:
            # Token search failed — capture what Google actually served so we
            # can tell a consent wall / "sorry" interstitial / CAPTCHA apart
            # from a genuine timeout, instead of just logging a bare ✗.
            try:
                final_url = page.url
                title = await page.title()
                html_now = await page.content()
                snippet = re.sub(r"\s+", " ", html_now)[:300]
                debug.append(f"Final URL: {final_url}")
                debug.append(f"Page title: {title!r}")
                debug.append(f"Body snippet: {snippet}")
                if "/sorry/" in final_url or "sorry" in title.lower():
                    debug.append("→ Google served a bot-check / 'sorry' interstitial, not the real results page. This points to an IP-reputation block, not a code bug.")
                elif "consent" in final_url.lower():
                    debug.append("→ Google served a consent page that wasn't dismissed in time.")
            except Exception as e:
                debug.append(f"Could not capture failure diagnostics: {e}")

        cookies = await context.cookies()
        session["cookies"] = {c["name"]: c["value"] for c in cookies}
        debug.append(f"Session: token={'✓' if session['token'] else '✗'} cookies={len(session['cookies'])}")
        await browser.close()

    return session


async def scrape_prices(hotel_name, start_date, end_date, currency="SGD", gl="sg", guests=2):
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end   = datetime.strptime(end_date, "%Y-%m-%d").date()
    debug = []

    debug.append(f"Step 1: Getting browser session ({guests} guest{'s' if guests != 1 else ''})...")
    session = await get_session(hotel_name, debug, gl=gl, currency=currency, guests=guests)

    if not session["token"]:
        return [], debug + [
            "ERROR: No hotel token found.",
            "→ Run /api/test-direct to check if batchexecute works without browser",
            "→ Run /api/test-proxy to check if PROXY_URL env var is working",
            "→ Run /api/test-playwright to diagnose Playwright timing",
        ]

    debug.append(f"Step 2: Fetching prices for {len(months_in_range(start,end))} month(s)...")
    all_prices = {}
    for year, month in months_in_range(start, end):
        status, body = batchexecute(
            session["token"], year, month,
            session["cookies"], session.get("f_sid"), session.get("bl"),
            currency=currency, gl=gl, guests=guests
        )
        prices = parse_prices(body)
        debug.append(f"  {year}-{month:02d}: HTTP {status}, {len(prices)} prices")
        all_prices.update(prices)

    results, current = [], start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        results.append({"date": ds, "price": all_prices.get(ds),
                        "day_of_week": current.strftime("%a"),
                        "month": current.strftime("%B %Y")})
        current += timedelta(days=1)

    found = sum(1 for r in results if r["price"])
    debug.append(f"Done: {found}/{len(results)} dates have prices")
    return results, debug


def calc_stats(results):
    monthly, all_p = {}, []
    for r in results:
        if r["price"] is None: continue
        monthly.setdefault(r["month"], []).append(r["price"])
        all_p.append(r["price"])
    return {
        "monthly": {m: {"average": round(sum(p)/len(p),2),"min":min(p),"max":max(p),"count":len(p)}
                    for m, p in monthly.items()},
        "overall_average": round(sum(all_p)/len(all_p),2) if all_p else None,
        "total_nights": len(all_p),
    }


@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json()
    hotel    = (data.get("hotel_name") or "").strip()
    s        = (data.get("start_date") or "").strip()
    e        = (data.get("end_date")   or "").strip()
    currency = (data.get("currency")   or "USD").strip().upper()
    gl       = (data.get("gl")         or "us").strip().lower()
    try:
        guests = max(1, min(int(data.get("guests", 2)), 6))
    except (TypeError, ValueError):
        guests = 2
    if not hotel or not s or not e:
        return jsonify({"error": "Missing fields"}), 400
    try:
        if datetime.strptime(e,"%Y-%m-%d") <= datetime.strptime(s,"%Y-%m-%d"):
            return jsonify({"error": "End date must be after start date"}), 400
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results, debug = loop.run_until_complete(
                scrape_prices(hotel, s, e, currency=currency, gl=gl, guests=guests)
            )
        finally:
            loop.close()
        return jsonify({"hotel":hotel,"start_date":s,"end_date":e,"guests":guests,
                        "results":results,"stats":calc_stats(results),"debug":debug})
    except Exception as ex:
        import traceback
        return jsonify({"error": str(ex), "trace": traceback.format_exc()}), 500


@app.route("/api/dump-raw", methods=["POST"])
def dump_raw():
    """
    Diagnostic: runs a real browser session + one batchexecute call and returns
    the fully parsed JSON structure so you can inspect exactly what each index contains.
    POST body: { "hotel_name": "...", "year": 2026, "month": 7, "currency": "USD", "gl": "us", "guests": 2 }
    """
    import asyncio, traceback

    data     = request.get_json()
    hotel    = (data.get("hotel_name") or "").strip()
    year     = int(data.get("year",  2026))
    month    = int(data.get("month", 7))
    currency = (data.get("currency") or "USD").strip().upper()
    gl       = (data.get("gl")       or "us").strip().lower()
    guests   = max(1, min(int(data.get("guests", 2)), 6))

    if not hotel:
        return jsonify({"error": "hotel_name required"}), 400

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            session, debug = loop.run_until_complete(_dump_session(hotel, currency, gl, guests))
        finally:
            loop.close()

        if not session["token"]:
            return jsonify({"error": "No token found", "debug": debug})

        status, body = batchexecute(
            session["token"], year, month,
            session["cookies"], session.get("f_sid"), session.get("bl"),
            currency=currency, gl=gl, guests=guests
        )

        # Parse outer wrapper
        m = re.search(r'\["wrb\.fr","yY52ce","(.+?)",null,null,null', body, re.DOTALL)
        if not m:
            return jsonify({
                "error": "wrb.fr pattern not found in response",
                "status": status,
                "body_preview": body[:500],
                "debug": debug,
            })

        try:
            parsed = json.loads(json.loads('"' + m.group(1) + '"'))
        except Exception as e:
            return jsonify({"error": f"JSON parse failed: {e}", "debug": debug})

        # Dump the first 3 entries with ALL their indices labelled
        entries_dump = []
        raw_entries = parsed[1] if len(parsed) > 1 else []
        for i, entry in enumerate(raw_entries[:5]):
            entry_info = {"entry_index": i, "total_indices": len(entry), "indices": {}}
            for j, val in enumerate(entry):
                entry_info["indices"][str(j)] = val
            entries_dump.append(entry_info)

        # Also run current parse_prices so we can compare
        current_prices = parse_prices(body)

        return jsonify({
            "status": status,
            "token": session["token"][:20] + "...",
            "total_entries": len(raw_entries),
            "parsed_top_level_keys": len(parsed),
            "entries_sample": entries_dump,
            "current_parse_prices_result": dict(list(current_prices.items())[:10]),
            "debug": debug,
        })

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()})


async def _dump_session(hotel_name, currency, gl, guests):
    debug = []
    session = await get_session(hotel_name, debug, gl=gl, currency=currency, guests=guests)
    return session, debug



def health():
    return jsonify({"status":"ok","proxy_configured": bool(os.environ.get("PROXY_URL"))})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=False, host="0.0.0.0", port=port)


