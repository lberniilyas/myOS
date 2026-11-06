# Personal OS

Tell your system what happened, by typing or speaking. It turns your words into structured, connected records (study, project work, spending, knowledge, habits, tasks) and answers questions about your own history.

- **Specs:** the ten `Personal OS - …md` files in this folder.
- **Plan and decisions:** [docs/build-plan.md](docs/build-plan.md).
- **Backend:** `backend/`, FastAPI + PostgreSQL. AI extraction uses Gemini by default.
- **App:** `frontend/`, a website you add to your iPhone home screen (PWA). The backend serves it at the same address.

## Run it on your PC

You need Python, [uv](https://docs.astral.sh/uv/), Node.js and PostgreSQL. PostgreSQL 18 is already installed on this machine; the project runs its own small database on port 5433 and doesn't touch your existing one.

1. Get a free Gemini API key at <https://aistudio.google.com/apikey>.
2. Copy `backend/.env.example` to `backend/.env` and paste the key after `GEMINI_API_KEY=`.
3. In PowerShell, from this folder: `.\start.ps1`
4. Open <http://localhost:8000> and create your account.

Without a key everything still works except understanding messages. Captures are saved as "not processed yet"; retry them once the key is set.

Interactive API docs: <http://localhost:8000/docs>.

## Put it on your iPhone

The PC runs the server, and the iPhone opens it in Safari.

**On the same Wi-Fi (quickest):**

1. On the PC, run `ipconfig` and note the IPv4 address, for example `192.168.1.20`. If Windows asks whether Python may use the network, allow it on private networks.
2. On the iPhone, open Safari at `http://192.168.1.20:8000`.
3. Tap **Share**, then **Add to Home Screen**. It opens full-screen like an app.

Over plain `http://`, iOS disables two things: offline loading and the in-app mic button. Typing works, and so does the 🎙 dictation key on the iPhone keyboard.

**Anywhere, over HTTPS (full features):** put the server behind an HTTPS address, for example [Tailscale](https://tailscale.com/) (`tailscale serve 8000`) or a Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8000`), then add that address to your home screen. To have it work when your PC is off, deploy it to Vercel (next section).

## Deploy on Vercel

Vercel serves the app over HTTPS and runs the backend as one Python function ([vercel.json](vercel.json), [api/index.py](api/index.py)). The database is a hosted PostgreSQL from Neon, which you add from inside Vercel. Both have free tiers.

1. On [vercel.com](https://vercel.com), choose **Add New → Project** and import the GitHub repository. Keep the build settings Vercel shows; `vercel.json` sets them. Deploy.
2. In the project, open **Storage → Create Database → Neon**. Pick the Frankfurt region (AWS `eu-central-1`), next to the backend (`fra1`). Connect it to the project; Vercel adds `DATABASE_URL` and `DATABASE_URL_UNPOOLED`.
3. In **Settings → Environment Variables**, add:
   - `GEMINI_API_KEY`: your Gemini key.
   - `ALLOWED_EMAILS`: the email (or comma-separated emails) allowed to create an account. Everyone else is refused, so strangers who find the URL can't use your AI key.
4. Create the tables. On your PC, in PowerShell:
   ```powershell
   cd backend
   .\scripts\migrate_production.ps1
   ```
   Paste the `DATABASE_URL_UNPOOLED` value from **Storage → your database**. Run this again whenever a change adds a migration.
5. In **Deployments**, open the latest one's **⋯** menu and choose **Redeploy**, so the new variables apply.
6. Open `https://<your-project>.vercel.app/health`; it should answer `{"status":"ok","ai_provider":"gemini"}`. Then open the site and create your account with an allowed email.
7. On the iPhone, open the same address in Safari and choose **Share → Add to Home Screen**, then open it from the home screen and sign in once there (the home-screen app keeps its own sign-in, separate from Safari). Over HTTPS the in-app mic button and offline loading work.

**Staying signed in.** The installed app stays signed in: each time you use it the session is renewed for another year, and a lost connection or a sleeping server never signs you out. Only **Me → Sign out**, or a year without opening the app, does.

**Updates.** Every push to `main` deploys again. When an update adds a database migration (a new file in `backend/alembic/versions/`), run `.\scripts\migrate_production.ps1` again *before* pushing it, so the new code finds the tables it expects. If you change Python dependencies, regenerate the list Vercel installs from: `cd backend; uv export --frozen --no-dev --no-hashes --no-emit-project -o ../requirements.txt`.

**Checks before deploys.** GitHub runs the tests on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)). To have Vercel deploy only commits that passed them, turn on **Settings → Git → Deployment Checks** in Vercel and select the CI checks.

## Deploy on Render

Render runs everything as one always-on server: it builds the web app, creates or updates the database tables on every start, then serves the API and the app. The setup is in [render.yaml](render.yaml).

1. Get a PostgreSQL connection string that lasts. If you set up Neon for Vercel, reuse it. Otherwise create a free project on [neon.tech](https://neon.tech) in the Frankfurt region and copy its connection string. Don't use Render's free database for real data: Render deletes it, with everything in it, 30 days after creation (plus 14 days' grace). A paid Render database is fine; use its **Internal Database URL**.
2. In the [Render dashboard](https://dashboard.render.com), choose **New → Blueprint** and connect the GitHub repository. Render reads `render.yaml` and asks for three values:
   - `DATABASE_URL`: the connection string from step 1.
   - `GEMINI_API_KEY`: your Gemini key.
   - `ALLOWED_EMAILS`: the email (or comma-separated emails) allowed to create an account.
3. Choose **Apply**. The first build takes a few minutes. There's no separate migration step: the tables are created when the server starts.
4. Open `https://<your-service>.onrender.com/health`; it should answer `{"status":"ok","ai_provider":"gemini"}`. Then create your account and add the address to your iPhone's home screen, as in step 7 of the Vercel section.

Render deploys a push to `main` only after the GitHub checks pass. On the free plan the server sleeps after 15 minutes without visits, and the next visit takes about a minute to wake it; anything you record meanwhile waits on the phone and is sent automatically. A paid plan doesn't sleep, and there you can move the migration from `startCommand` to `preDeployCommand` in `render.yaml`, so a failing migration stops the deploy instead of the server.

## Privacy note about Gemini's free tier

Google's pricing page states that content sent to the free tier is used to improve Google's products; the paid tier doesn't do this. Your entries are personal, so switch to a paid Gemini key, or set `AI_PROVIDER=anthropic` with a Claude key, before recording anything sensitive.

## Tests and evaluation

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest              # 188 tests, uses the local test database, no AI calls
.\.venv\Scripts\python.exe -m evals.run_extraction  # scores real Gemini extraction on 22 realistic inputs
cd ..\frontend
npm test                                         # the send queue and sign-in rules on the phone
```

The evaluation includes French, Darija, mixed-language and voice-style inputs. Run it after changing the prompt or the model.
