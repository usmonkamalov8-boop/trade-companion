# Trade Companion

Free companion app for your crypto bot: dashboard, charts, assistant, markets and news.
No paid API and no API keys except your own Binance key. The "AI" is a built-in
rule-based analyst (indicators, multi-timeframe scoring, keyword sentiment).

```
trade_companion/
  install.py        one-command backend installer (run on the VPS)
  backend/          FastAPI server + free analytics engine
  flutter_app/      Flutter source + .github/workflows/build_apk.yml
```

## 1. Install the backend on the VPS

```bash
cd ~ && tar -xzf trade_companion.tar.gz
cd trade_companion && python3 install.py
```

The installer asks for your Binance key/secret (optional, needed for positions, PnL and
Close All) and the bot's systemd service name (default `crypto_bot`). It creates a venv,
installs a `companion` systemd service on port 8000, opens the firewall port and prints
the **host** and **token** to enter in the app.

Useful commands:

```bash
systemctl status companion          # is it running?
journalctl -u companion -f          # logs
nano ~/trade_companion/backend/.env # change keys, then: systemctl restart companion
curl localhost:8000/ping            # {"ok":true}
```

## 2. Let the bot obey Halt and the risk sliders

`/halt`, `/resume` and the risk settings are written to `backend/control.json`.
Your bot reads them through `bot_gate.py`:

```bash
cp ~/trade_companion/backend/bot_gate.py ~/YOUR_BOT_FOLDER/
```

```python
import bot_gate
if bot_gate.halted():                    # before opening any NEW trade
    return
prof = bot_gate.cfg("hier")              # or "scalp"
if not prof.get("enabled", True):
    return
risk_pct = prof.get("risk_pct", 1.0)     # risk per trade set in the app
```

Close all works without the bot: it market-closes the 8 tracked pairs with reduce-only
orders, cancels their open orders, and halts new entries.

## 3. Build the APK with GitHub Actions

Only `flutter_app/` goes to GitHub (your backend and keys stay on the VPS).

```bash
apt install -y gh
git config --global user.name "me" && git config --global user.email "me@example.com"
cd ~/trade_companion/flutter_app
git init -b main && git add -A && git commit -m "trade companion"
gh auth login -s workflow      # GitHub.com > HTTPS > web browser; open the code page on your phone
gh repo create trade-companion-app --private --source=. --push
```

The push starts the build (about 6-8 minutes the first time).

- Watch it: `gh run watch`, or GitHub app/browser > repo > Actions
- Start it again by hand: `gh workflow run build_apk.yml`, or repo > Actions > Build APK > Run workflow
- Download: repo > Releases > newest "Trade Companion build N" > `app-release.apk`
  (also under the run's Artifacts). Stay signed in to GitHub in your browser for private repos.
- Install: open the downloaded file and allow "install unknown apps" for your browser.

After changing app code: `git add -A && git commit -m "update" && git push` builds a new APK.
The same commands work in Termux (`pkg install git gh`).

## 4. Connect the app

Settings tab: VPS address `IP:8000` (pre-filled) and the API token from the installer,
then Save and test.

## What the analyst does

- Data: Binance futures market data, Yahoo Finance (forex, gold, DXY), alternative.me
  Fear & Greed, RSS news. All free, no keys.
- Per asset and per timeframe (1H, 4H, 1D): EMA 20/50/200, RSI, MACD, ATR, Bollinger,
  swing support/resistance, combined into a -100..+100 score with a plain-language bias.
- Sentiment: Fear & Greed, funding rates, USD strength across the majors, and a simple
  headline keyword score (a crude signal, not a full reading of the news).
- Chat understands topics (positions, PnL, status, risk, a pair, gold, forex, news,
  sentiment, best setups). It answers from live data using templates, so it cannot
  handle open-ended questions outside those topics.

## Notes

- Traffic is plain HTTP. Anyone with the token can halt your bot or close positions.
  Put HTTPS in front (Caddy + domain) or use Tailscale when you can.
- Binance key: Futures enabled, withdrawals off, restricted to the VPS IP.
- Yahoo's endpoint and RSS feeds are unofficial and can change. Feeds are editable in
  `backend/app/config.py`.
- PnL is realized PnL before fees and funding, and is not split by hier/scalp.
- Test Close all with a small position first. The cancel call for algo SL/TP orders is
  best effort, so check your stops afterwards.
- This is analysis software, not financial advice.
