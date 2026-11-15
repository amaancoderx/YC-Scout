# Deploy YC Scout on Render (free)

This puts the dashboard online at `https://<name>.onrender.com`, behind a login, for free.

| Render Free limit | How YC Scout handles it |
|---|---|
| Sleeps after 15 minutes without visitors | The app pings its own public URL every 10 minutes, plus an external uptime monitor (step 6) as a backup |
| No persistent disk (files are wiped on restart) | Data lives in a free **Turso** cloud database (step 1) |
| Outbound SMTP ports 465/587 are blocked | Emails are sent through the **Gmail API** over HTTPS (step 3). Reply tracking still uses IMAP (port 993, allowed) |
| 750 free hours a month | Enough for one service running 24/7 |

You need: a GitHub account (the repo), a Google account (Gmail), about 20 minutes.

---

## 1. Create the cloud database (Turso, free)

1. Go to [turso.tech](https://turso.tech) and sign up with GitHub.
2. **Create database**: name `yc-scout`, location **AWS AP SouthEast (Singapore)**. It must be in the same region as the Render service (Singapore in `render.yaml`, the closest Render region to India) so every query is fast.
3. Open the database and copy its **URL** (looks like `libsql://yc-scout-<you>.aws-ap-southeast-1.turso.io`).
4. **Create token** (read and write, no expiry) and copy it.

> Living somewhere else? Pick the Render region closest to you (Oregon, Ohio, Virginia, Frankfurt or Singapore) in `render.yaml`, and the Turso location in the same place.

## 2. Copy your current data into it

On your computer, add the two values to `.env`:

```
TURSO_DATABASE_URL=libsql://yc-scout-<you>.aws-ap-southeast-1.turso.io
TURSO_AUTH_TOKEN=<token>
```

Then run:

```
python scout.py push-db
```

It copies every company, founder, email, job, setting, chat and memory from `data/ycscout.db`.
Afterwards, remove (or comment out) the two lines from your local `.env` if you want your local app to keep using the fast local file. Leave them in if you want local and online to share the same data.

## 3. Connect Gmail for sending (Gmail API)

In [Google Cloud](https://console.cloud.google.com), project **YC Scout**:

1. **Enable the Gmail API**: APIs & Services > Library > Gmail API > Enable.
2. **Google Auth Platform > Branding**: app name `YC Scout`, your email as support and developer contact. Save.
3. **Audience**: User type **External**, add yourself as a test user, then click **Publish app** (status: In production). This keeps the sign-in from expiring every 7 days. Google will show an "unverified app" screen once; that is expected for a personal app.
4. **Clients > Create client > Desktop app**, name `YC Scout`. Copy the **Client ID** and **Client secret** into `.env`:

   ```
   GMAIL_CLIENT_ID=...
   GMAIL_CLIENT_SECRET=...
   ```
5. Run:

   ```
   python scout.py gmail-auth
   ```

   Your browser opens: pick `amaan.coderx@gmail.com`, click **Advanced > Go to YC Scout**, then **Continue**. The refresh token is saved to `.env` as `GMAIL_REFRESH_TOKEN`.

## 4. Create the Render service

1. Go to [render.com](https://render.com) and sign up with GitHub. Allow access to the `YC-Scout` repo.
2. **New > Blueprint**, pick `amaancoderx/YC-Scout`. Render reads `render.yaml` and creates a free web service.
3. Fill in the secret values it asks for (copy them from your local `.env`):

| Key | Value |
|---|---|
| `APP_PASSWORD` | your login password |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | from step 1 |
| `GEMINI_API_KEY` | your Gemini key |
| `SMTP_PASSWORD` | your Gmail App Password (used for reply tracking) |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | from step 3 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the whole content of `google-key.json` (optional, for Sheets) |
| `GOOGLE_SHEET_ID` | your sheet id (optional) |

4. Click **Apply**. The first build takes a few minutes. When it shows **Live**, open the URL.

## 5. Sign in

Open `https://<name>.onrender.com`, sign in with `amaan.coderx@gmail.com` and your password.
Settings > Integrations should show Gemini, Email sending (via Gmail API), Reply tracking and Google Sheets in green.

## 6. Keep it awake (backup monitor)

The app already pings itself every 10 minutes. Add a free external monitor too, so it wakes up even after a Render restart:

1. [uptimerobot.com](https://uptimerobot.com) > sign up (free) > **New monitor**.
2. Type **HTTP(s)**, URL `https://<name>.onrender.com/healthz`, interval **5 minutes**. Save.

## Updating

Push to `main` on GitHub and Render redeploys automatically. Your data stays in Turso.

## Troubleshooting

| Problem | Fix |
|---|---|
| Page takes ~1 minute to open | The service was asleep (first visit after a restart). The monitor in step 6 prevents this. |
| "Wrong email or password" | Check `APP_PASSWORD` in Render > Environment. 10 wrong tries lock the IP for 15 minutes. |
| Email sending shows off | `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` and `FROM_EMAIL` must all be set. Re-run `python scout.py gmail-auth` if Google says the token expired. |
| Data is empty | `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` are missing, or step 2 was skipped. |
| Gemini quota errors | Free keys have small daily limits; the app switches models automatically. A paid key removes this. |
