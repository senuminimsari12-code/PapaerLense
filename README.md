# PaperLense

Upload a research PDF to get a five-section summary, ask questions about the paper, and open cited pages in the original PDF. Evidence Explorer shows the passages retrieved for an answer. The app supports English, Sinhala, and Tamil, light and dark themes, and adjustable text size.

## Run locally

Install Git, Python 3.14, and Node.js 24 with npm.

```sh
git clone https://github.com/senuminimsari12-code/PaperLense.git
cd PaperLense
```

### 1. Configure an AI provider

Copy `.env.example` to `.env` at the repository root. In PowerShell, run `Copy-Item .env.example .env`. In Bash, run `cp .env.example .env`.

Set at least one backend key to enable summaries and Q&A: `GEMINI_API_KEY`, `GROQ_API_KEY`, or `OPENROUTER_API_KEY`. PaperLense tries configured providers in that order. The corresponding `*_MODEL` settings are optional overrides. PDF extraction works without an AI key. Keep `.env` and provider keys private.

### 2. Start the backend

Run from the repository root. On Windows PowerShell:

```powershell
py -3.14 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

On Linux or Ubuntu WSL, use a Python installation with virtual environment support:

```sh
python3.14 -m venv backend/.venv-wsl
backend/.venv-wsl/bin/python -m pip install -r backend/requirements.txt
backend/.venv-wsl/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Check [backend health](http://localhost:8000/api/health) or open the [API docs](http://localhost:8000/docs).

### 3. Start the frontend

Open a second terminal at the repository root:

```sh
cd frontend
npm ci
npm run dev
```

In Windows PowerShell, use `npm.cmd` if the PowerShell script wrapper is blocked. Open [http://localhost:5173](http://localhost:5173), upload a PDF with selectable text, and wait for the automatic summary. Ask a question and select a citation to open its page.

## Tests

Run backend tests from the repository root using the same virtual environment as the backend. Run frontend tests and the build from `frontend/`.

```sh
python -m pytest -q
npm test
npm run build
```

The backend tests mock AI requests. The frontend build is written to `frontend/dist`.

## Deploy with Render and Vercel

1. **Render backend.** Create a Python Web Service from the repository, leaving the Root Directory blank, or use [render.yaml](render.yaml). Set the health check path to `/api/health` and use these commands:

   ```sh
   pip install -r backend/requirements.txt
   uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1
   ```

   Set `PYTHON_VERSION=3.14.4`, `PAPERLENS_ALLOWED_ORIGINS` to the exact Vercel origin (for example `https://paperlense.vercel.app`), and the AI provider keys on Render. Render supplies `PORT`. Confirm the public Render URL returns `{"status":"ok"}` at `/api/health`.
2. **Vercel frontend.** Import the same repository, choose the Vite preset, and set the Root Directory to `frontend`. Set Production `VITE_API_BASE_URL` to the Render HTTPS base URL without `/api`, then deploy or redeploy. Provider keys belong on the backend.
3. **Verify.** Open the production frontend, upload a small public PDF, and confirm that the preview, summary, and cited answers work. If the browser reports a CORS error, compare its exact origin with `PAPERLENS_ALLOWED_ORIGINS` on Render.

## Limits

- PDFs must contain selectable text and be at most 20 MiB. The app does not perform OCR.
- The backend holds one temporary document per browser session. Documents expire after 30 minutes. A backend restart or Render Free sleep clears in-memory documents and caches. Upload the PDF again when prompted.
- Citation excerpts show the passages retrieved for the answer. Verify important claims against the original paper.
- This is a single-process prototype without user accounts or persistent storage. Upload only public or non-sensitive papers.

[License](LICENSE)