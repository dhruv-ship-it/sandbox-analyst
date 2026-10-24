# deploy.md

How to put the public demo live on Azure. You create every Azure
resource by hand, following the steps below -- nothing here creates
Azure resources for you. It assumes the resource group `zonewise-rg`
and its App Service plan (Basic B1, UAE North) already exist from the
ZoneWise project, and that you have a GitHub account with this repo's
CI already green.

```
  browser ──HTTPS──▶  App Service (Linux, B1, same plan as ZoneWise)
                      ghcr.io/dhruv-ship-it/sandbox-analyst:latest
                      one uvicorn worker on $PORT
                             │                          │
                             ├──HTTPS──▶ api.groq.com    (per question)
                             └──HTTPS──▶ Modal           (per attempt, sandboxed exec)
```

**Cost.** Basic B1 is already paid for by the existing plan (shared
with ZoneWise -- this just adds a second Web App on it, not a second
plan). Groq's free tier and Modal's $1 no-card free credit cover the
LLM/sandbox traffic, bounded by the public-safety limits below.

**Time.** About 20 minutes, assuming the image is already built.

## Prerequisites

- **The image exists.** CI's `image` job (`.github/workflows/ci.yml`)
  builds and pushes `ghcr.io/dhruv-ship-it/sandbox-analyst` on every
  push to `main`, automatically, after tests pass -- there's no manual
  "Run workflow" button for it (unlike ZoneWise's image job). Check
  GitHub → Actions → the latest `CI` run on `main` → the `image` job
  is green, and its summary prints the two tags it pushed.
- **A Groq API key** -- <https://console.groq.com/keys>.
- **A Modal token** (`MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`) -- from
  `uvx modal token new` or the Modal dashboard's API Tokens page.

## 1. Make the GHCR package reachable

Default: make it public. The image contains code only -- no data, no
keys (see `Dockerfile`'s own header comment) -- so this publishes
nothing the repository doesn't already.

1. GitHub → your **profile** (not the repo) → **Packages**.
2. Click **sandbox-analyst** → **Package settings** → **Danger Zone**
   → **Change visibility** → **Public** → confirm with the package name.

**If you'd rather keep it private:** leave it private, create a GitHub
personal access token (classic) scoped to `read:packages` only, and use
it as the registry password in step 2 below instead of leaving the
registry fields blank.

## 2. Create the Web App

1. Portal → **Create a resource** → **Web App**.
2. **Basics** tab:
   - **Resource group**: `zonewise-rg` (existing)
   - **Name**: `sandbox-analyst-<suffix>` -- pick something globally
     unique; this becomes
     `https://sandbox-analyst-<suffix>.azurewebsites.net`
   - **Publish**: **Container** (not Code)
   - **Operating System**: **Linux**
   - **Region**: **UAE North** -- must match the existing plan's region
   - **Linux Plan**: select the **existing** App Service plan (the one
     ZoneWise already runs on, Basic B1) -- do **not** create a new plan
3. **Container** tab:
   - **Image Source**: **Other container registries**
   - **Access Type**: **Public** (or **Private**, with the token from
     step 1, if you kept the package private)
   - **Registry server URL**: `https://ghcr.io`
   - **Image and tag**: `dhruv-ship-it/sandbox-analyst:latest` -- all
     lower case
4. **Review + create** → **Create**. Wait for *Your deployment is
   complete* → **Go to resource**.

It won't answer questions yet -- it has no key.

## 3. App Settings

Left menu → **Settings** → **Environment variables** → **App settings**
tab. Add each of these with **+ Add**, then **Apply** and confirm the
restart.

| Name | Value | Why |
|---|---|---|
| `WEBSITES_PORT` | `8000` | tells App Service which port to route to (matches the Dockerfile's `EXPOSE` and `Settings.port`'s default) |
| `WEBSITES_ENABLE_APP_SERVICE_STORAGE` | `true` | mounts `/home` persistently -- `SA_DATA_DIR` lives there |
| `SA_LLM_PROVIDER` | `groq` | the live demo's provider (D-065) |
| `SA_LLM_MODEL` | `openai/gpt-oss-20b` | the same model used for every benchmark number |
| `GROQ_API_KEY` | *(your key from step "Prerequisites")* | **secret** |
| `SA_SANDBOX` | `modal` | the real, network-isolated sandbox backend |
| `MODAL_TOKEN_ID` | *(from your Modal token)* | **secret** -- read directly by the Modal SDK, never by this project's own code |
| `MODAL_TOKEN_SECRET` | *(ditto)* | **secret** |
| `SA_SANDBOX_BUDGET_USD` | `0.30` | production's share of the shared $1 Modal free credit (D-072) |
| `SA_DATA_DIR` | `/home/sa-data` | the persistent mount from `WEBSITES_ENABLE_APP_SERVICE_STORAGE` |
| `SA_TRUST_PROXY` | `true` | trust `X-Forwarded-For`'s one hop from Azure's own front end (D-074) -- **do not** set this unless you're actually behind Azure's proxy |
| `SA_RATE_LIMIT_PER_IP_HOUR` | `5` | already the built-in default (D-071); set explicitly here for operational clarity, or omit |
| `SA_RATE_LIMIT_PER_IP_DAY` | `20` | ditto |
| `SA_RATE_LIMIT_GLOBAL_DAY` | `50` | ditto |
| `SA_MAX_CONCURRENT_RUNS` | `2` | ditto |

Nothing else. In particular, don't set `APP_VERSION` -- it's baked into
the image at build time (the CI `image` job's `--build-arg`) and an App
Setting would silently override that with a stale value.

## 4. Health check

Left menu → **Monitoring** → **Health check** → **Enable** → **Path**:
`/api/health` → **Save**. App Service then restarts the container if
that path stops answering -- a separate mechanism from the Dockerfile's
own `HEALTHCHECK`, which a plain Docker daemon reads and App Service
does not.

## 5. How auto-redeploy on push works

**By default, redeploy is a manual step**, exactly like ZoneWise's own
deploy flow (checked directly -- ZoneWise has no automatic
Azure-redeploy step either, see DECISIONS.md D-079): after the `image`
job finishes on a push to `main`, go to the Web App → **Restart** (top
bar). App Service pulls `:latest` fresh on every restart.

**To turn on continuous deployment instead** (so a push to `main`
redeploys automatically, with no manual Restart click):

1. Web App → **Overview** → **Get publish profile** (downloads an XML
   file).
2. GitHub → this repo → **Settings** → **Secrets and variables** →
   **Actions** → **New repository secret** → name it
   `AZURE_WEBAPP_PUBLISH_PROFILE_SA`, paste the whole downloaded XML as
   the value.
3. Same page, **Variables** tab → **New repository variable** → name it
   `AZURE_WEBAPP_NAME_SA`, value the exact Web App name from step 2
   above (e.g. `sandbox-analyst-<suffix>`) -- this one is not a secret.
4. The next push to `main` will have CI's `deploy-azure` job actually
   deploy, instead of printing "skipped" in its step summary.

Leaving either one unset is completely fine -- the `deploy-azure` job
no-ops cleanly and the manual-Restart flow keeps working exactly as
before.

## 6. Verify the live URL

In this order:

1. **`https://<your app>.azurewebsites.net/api/health`**

   ```json
   {"status": "ok", "version": "<short sha>", "provider": "groq",
    "model": "openai/gpt-oss-20b", "sandbox": "modal"}
   ```

   `version` should match the short SHA printed in the `image` job's
   step summary for the build you expect to be running.

2. **`https://<your app>.azurewebsites.net/`** -- the placeholder page
   (project name, one-line description, "UI coming soon", a link to
   `/api/health` until Prompt 6 ships the real UI.

3. **One real question**, the same shape as the local smoke in
   `docs/api.md`:

   ```powershell
   $base = "https://<your app>.azurewebsites.net"
   $ds = (Invoke-RestMethod -Method Post "$base/api/examples/sales/load").dataset_id
   $run = Invoke-RestMethod -Method Post "$base/api/runs" -ContentType "application/json" `
       -Body (@{dataset_id = $ds; question = "Which product has the highest average unit price?"} | ConvertTo-Json)
   Invoke-RestMethod "$base/api/runs/$($run.run_id)"   # poll until status isn't pending/running
   ```

   A real answer back (not a `429`/`5xx`) confirms Groq, Modal, and the
   whole request path all work end to end on the live URL.

## Updating it later

**Code changed:** `git push` to `main` (after `uv run ruff check`,
`uv run ruff format --check`, `uv run pytest`, per CLAUDE.md). CI
builds and pushes the new image automatically; redeploy per step 5
above (automatic if configured, otherwise **Restart**).

**Rolling back:** Web App → **Container** settings → change **Image
and tag** to `dhruv-ship-it/sandbox-analyst:<short sha>` of the earlier
build (from that commit's `image` job summary) → **Save** → **Restart**.
That's exactly what the short-SHA tag is for.
