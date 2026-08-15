# Workflow files to add manually

GitHub blocks Apps without the `workflows` permission from creating or updating
anything under `.github/workflows/`, via **both** `git push` and the REST
contents API. The files here are ready to go — they just need to be copied in
by a human (or any token that has the `workflow` scope).

## `scheduled-refresh.yml`

Pings `/cron/refresh` at the five schedule times so prices update even while the
host has the service hibernated.

### Option A — from your machine

```bash
git checkout arena/01a0064b-product-price-tracker
git pull
mkdir -p .github/workflows
git mv .workflows-to-add/scheduled-refresh.yml .github/workflows/scheduled-refresh.yml
git commit -m "Add scheduled price refresh workflow"
git push
```

### Option B — GitHub web UI

**Add file → Create new file**, name it
`.github/workflows/scheduled-refresh.yml`, paste the contents of
`scheduled-refresh.yml` from this directory, and commit to
`arena/01a0064b-product-price-tracker`.

### Then configure it

**Settings → Secrets and variables → Actions**

- **Variables** tab → New variable: `APP_URL` = `https://<your-app>.onrender.com`
- **Secrets** tab → New secret: `CRON_TOKEN` = the same value as the
  `CRON_TOKEN` env var on your server

Trigger it once by hand from the **Actions** tab (**Run workflow**) to confirm
it returns `202 Scrape cycle started`.

## Optional: run the catch-up test in CI

Add the new test to the existing `.github/workflows/ci.yml` — change the last
step's `run:` to:

```yaml
        run: |
          python3 test_scheduler_catchup.py
          python3 test_price_stats.py --case 1 --offset 1
```

## Note

None of this is required for the fix to work. The catch-up-on-wake logic in
`app.py` already recovers missed slots on the next incoming request with no
external trigger at all — these workflows only make the scrapes land closer to
the exact slot times.
