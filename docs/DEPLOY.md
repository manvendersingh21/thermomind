# Deployment

ThermoMind is a single FastAPI process that serves the built React app and the `/api` routes. No database server, queue, or GPU is required to run the demo.

## Local (reproducible, what the demo uses)

```bash
cp .env.example .env            # set MODEL_API_KEY (alias MUSE_API_KEY accepted)
make setup                      # venv + pip + npm install
make data                       # fetch the UCI year files into data/raw/uci_551
make train                      # HGBR baseline -> data/models/baseline_v1.*
cd apps/web && npm run build && cd ../..
cd apps/api && ../../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. `make dev` runs the API and the Vite dev server (port 5173, `/api` proxied) with hot reload instead.

Optional GPU challenger: `pip install -r apps/api/requirements-gpu.txt` then `make gpu-train` (writes `data/models/mlp_v1.*`; shown at `/evaluation` and `GET /api/models/comparison`).

## Docker (written, not exercised on the build box: Docker was not installed there)

```bash
docker build -t thermomind .
docker run -p 8000:8000 -e MODEL_API_KEY=... -v $(pwd)/data:/app/data thermomind
```

The image has no raw data; run `make data` on the host (volume) or `POST /api/datasets/seed-uci` after copying the CSVs into `data/raw/uci_551`.

## Temporary public URL (your decision, not automated)

The build environment blocked opening an ingress tunnel automatically. If you want a live link for judges, run on the host where the server is up:

```bash
cloudflared tunnel --url http://localhost:8000 --no-autoupdate
```

It prints an ephemeral `https://*.trycloudflare.com` URL. The URL dies with the process and is not a production deployment. Put it in `docs/SUBMISSION.md` if used.

## What is not deployed

No cloud account, no managed database, no auth. The product is a read-only decision-support prototype; see `docs/SAFETY.md`.
