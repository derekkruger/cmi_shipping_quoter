# CMI Shipping Quoter

A small local web app that lets CMI shipping clerks compare package rates from
**UPS** and **FedEx** side by side. It runs on your own PC: nothing is hosted,
and your carrier API keys stay on this machine.

## Quick start (Windows)

1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>.
   During setup, tick **"Add python.exe to PATH"**.
2. Download or clone this repository.
3. Double-click **`start.bat`**.
   The first run installs dependencies into a private `.venv` folder (about a minute).
4. Your browser opens at <http://127.0.0.1:5050>. Leave the black console window
   open while you use the app; close it (or press Ctrl+C) to stop.

macOS / Linux: run `./start.sh` instead.

Manual start (any OS):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py
```

## Adding your UPS and FedEx API credentials

Open **Settings** (top of the page). For each carrier:

| Carrier | Where to get keys | Fields |
|---|---|---|
| UPS | <https://developer.ups.com/>: create an app and add the **Rating** API product | Client ID, Client Secret, 6-character UPS account (shipper) number |
| FedEx | <https://developer.fedex.com/>: create a project and enable the **Rates and Transit Times** API | API Key, Secret Key, 9-digit FedEx account number |

Then:

1. Tick **Use … for quotes**.
2. Choose **Sandbox** while testing, then switch to **Production** for live rates.
   Each carrier issues separate sandbox and production keys.
3. Click **Test connection**. This saves the form and checks the credentials with the carrier.
4. Fill in the **default ship-from address** (your warehouse). The quote form starts with it filled in.

Settings are saved to `data/settings.json`. Git ignores that file, so secrets are
never committed. Secrets aren't sent back to the browser after saving; leave a
secret field blank to keep the saved value.

## Getting a quote

Enter the destination ZIP (plus city/state for best accuracy), mark it
residential if it applies, and add one row per package (weight required,
dimensions optional but recommended because of dimensional-weight pricing). Click
**Get quotes**. Rates from all enabled carriers come back in one table,
cheapest first:

* **Rate**: your account/negotiated rate when the carrier returns one; otherwise the list rate.
  When both come back, the list rate is shown struck through next to it.
* **Transit / Est. delivery**: the carrier's estimate, when provided.
* If one carrier fails (bad keys, unsupported lane), its error appears above the
  table and the other carrier's rates still show.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `QUOTER_PORT` | `5050` | Port to listen on |
| `QUOTER_HOST` | `127.0.0.1` | Interface to bind. The default allows only this PC. Set `0.0.0.0` to let other PCs on the network use it (anyone who can reach it can change settings, so do this only on a trusted network). |
| `QUOTER_NO_BROWSER` | unset | Set to `1` to skip opening the browser on start |
| `QUOTER_SETTINGS_FILE` | `data/settings.json` | Where settings are stored |

## Project layout

```
app.py                     Flask app + JSON API (/api/quote, /api/settings, /api/carriers/<name>/test)
quoter/models.py           Address / Package / Rate types and input validation
quoter/settings.py         Load/save settings, secret masking
quoter/carriers/base.py    OAuth token caching + HTTP error handling shared by carriers
quoter/carriers/ups.py     UPS Rating API (v2409, "Shoptimeintransit")
quoter/carriers/fedex.py   FedEx Rate API (rate/v1/rates/quotes)
static/                    Quote page and settings page (plain HTML/JS, no internet needed)
tests/                     pytest suite (carrier APIs are mocked)
start.bat / start.sh       One-click launchers
```

### Adding another carrier (e.g. USPS)

1. Create `quoter/carriers/usps.py` with a `Carrier` subclass that implements
   `_fetch_token()` and `get_rates()`.
2. Register it in `quoter/carriers/__init__.py`.
3. Add its default settings under `carriers` in `quoter/settings.py` and a section in `static/settings.html`.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## License

AGPL-3.0. See [LICENSE](LICENSE).
