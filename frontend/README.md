# CURIO Command Center

Single-page Vite + React demo. Requires Node.js 20.19+ or 22.12+ and the existing FastAPI backend.

```bash
cd frontend
pnpm install --frozen-lockfile
cp .env.example .env
pnpm dev
```

From the repository root, start the backend with your configured Python environment:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:5173. Set `VITE_API_BASE_URL` in `frontend/.env` to change the API origin, then restart Vite (or rebuild for production). Never put tokens in Vite variables: they are public browser configuration. GitHub authentication stays in the backend environment.

Enter `owner/repository`, select Railway or Vercel, and paste logs. **Load sample** fills a missing-stripe traceback; it does not submit a request or fabricate results. The source selector labels the incident; it does not connect to those deployment platforms.

- **Analyze** calls the diagnosis-only endpoint.
- **Autofix** calls the remediation endpoint and can push a fix branch/create a PR. Use a demo repository with a `dev` branch and tracked `requirements.txt`. All safety gates remain in the backend.
- The animated pipeline represents the workflow while waiting; the backend does not stream stage progress. Completed stage indicators come only from returned data. Compile-only validation is shown with its actual command/reason.
- Requests are not retried automatically. If the connection is lost during autofix, inspect GitHub/server logs before retrying because server-side work may continue.
- The 3D core falls back to a static graphic if WebGL is unavailable; reduced-motion preferences disable continuous animation.

```bash
pnpm build
pnpm preview
```

FastAPI permits the local Vite development (5173) and preview (4173) origins only. A different frontend origin needs an explicit CORS allowlist update. Typography uses optional Google Fonts with system fallbacks; no external graphics or model assets are required.
