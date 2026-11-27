# Deploying Bol-ke-Order

The app is one Docker container. Any host that can build a Dockerfile from a GitHub repo can run it: Render (`render.yaml` is ready), Railway, Fly.io, DigitalOcean App Platform or a plain VPS. The hackathon rules say "You host it yourself" and the live link is optional, but the phone microphone needs HTTPS, so the shop test needs a deploy. (dostack.ai's home page looked like an AI app builder taking early-access sign-ups, not a Docker host; check before planning on it.)

## What the host needs

| Setting | Value |
|---|---|
| Source | GitHub repo `chetankukreja4/bol-ke-order`, branch `main` |
| Build | `Dockerfile` in the repo root (no build command needed) |
| Port | Container listens on `$PORT`, default `8000`. If the host asks for a port, give `8000`. |
| Health check | `GET /healthz` returns `{"ok": true}` |
| HTTPS | Required for the live microphone in the browser. Turn on the host's free HTTPS / SSL. |
| Disk | Mount a persistent volume at `/data` (orders live in `/data/orders.db`). Without it, orders reset on every redeploy. 1 GB is plenty. |
| Memory | 512 MB should be enough; the voice model (64 MB file) is loaded on the first spoken line. Not measured on a host yet: watch the first day. |
| Env vars | All optional. See below. |

### Environment variables

| Name | Needed? | Purpose |
|---|---|---|
| `SARVAM_API_KEY` | Optional | Speech-to-text (Sarvam `saaras:v4`) for the live mic and uploaded recordings. Without it, the live mic uses the browser's speech recognition and uploads show "Speech key not set". |
| `PORT` | Set by most hosts | Port to listen on. Default `8000`. |
| `DB_PATH` | Optional | Default `/data/orders.db`. |
| `BKO_VOICE_MODEL` | Set by the Dockerfile | Path of the local Hindi voice (Piper). The Docker build downloads it (~64 MB) with `scripts/get_voice.py`. Without it the browser's own voice is used. |
| `BKO_DEMO` | Only for a demo copy | `1` shows Demo reset on the Pilot tab (deletes every order). Never set it on the shop's real app. |
| `BKO_PIN` | Recommended on a public URL | A shop PIN. When set, the app asks for it once on each phone. Without it anyone with the link can see orders. |

Put keys in the host's "secrets" or "environment" screen. Never put them in the repo.

## Steps for a Docker-from-GitHub host

1. Sign in to the host and connect your GitHub account.
2. Create a new app / service → choose **Dockerfile** (or "Docker") as the build type → pick the repo `bol-ke-order`, branch `main`.
3. Set the port to `8000` (or leave it if the host sets `$PORT`).
4. Add a persistent volume mounted at `/data`.
5. Set the health check path to `/healthz`.
6. Add `BKO_PIN` (a shop PIN) and `SARVAM_API_KEY` if you have it. Do not set `BKO_DEMO`.
7. Deploy. Open the HTTPS URL on your phone in Chrome and tap **Order bolo**.
8. Turn on auto-deploy from `main` so each push updates the app.

If the host only accepts `docker-compose.yml`, point it at the one in the repo; it already maps port 8000 and a volume for `/data`.

If the host only accepts a ready image, build and push it yourself:

```bash
docker build -t <registry>/bol-ke-order:latest .
docker push <registry>/bol-ke-order:latest
```

## Plain VPS (Ubuntu)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
git clone https://github.com/chetankukreja4/bol-ke-order.git && cd bol-ke-order
cp .env.example .env   # add keys if you have them
sudo docker compose up -d --build
```

Then put Caddy or Nginx in front for HTTPS (the browser mic does not work over plain http, except on localhost).

## Render

New → Blueprint → pick the repo. `render.yaml` sets the Docker build and the `/healthz` check, and asks for `SARVAM_API_KEY` and `BKO_PIN`.

- Render builds from the `Dockerfile` (not `docker-compose.yml`) and sets `$PORT`; the app already listens on it.
- The Dockerfile's `VOLUME` and `HEALTHCHECK` are ignored on Render; the health check comes from `render.yaml`.
- **Free plan: the disk is temporary** (orders are lost on a restart or redeploy) and the server sleeps after about 15 minutes idle (the first request then takes about a minute). Fine for a demo link. For the shop pilot use a paid plan with a Disk mounted at `/data`.
- If saving fails with a permission error after adding a Disk, the disk is not writable by the container's `appuser`; check Render's logs (not seen yet).

## After deploying, check

- `https://<your-url>/healthz` shows `{"ok":true}`.
- The home screen loads and asks for the PIN once; the header shows which keys are set.
- "Try sample phrases" → the first one → "Kaun sa soap brand?" → Lux → Confirm → parchi; "CSV for billing" downloads.
- On a phone over HTTPS: hold **Order bolo** and speak an order; the read-back is in the local Hindi voice.
- Items tab → "Busy / Excel se items laayein" and "Busy / Excel se parties laayein" with the shop's file (or the blank Excel template, filled). Check the preview, then "Haan": it replaces the sample lists.
- Pilot tab shows 0 orders on a fresh `/data`.
