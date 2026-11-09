# PaperLense assessment checklist

The application baseline was GitHub `main` at `14bafdf`. Verification used a fresh checkout with new Windows and Ubuntu WSL virtual environments and a clean npm install. The assessment brief asks for a single research PDF upload, a readable automatic summary with five named sections, natural-language Q&A, and a Git repository with setup instructions.

## Requirements and release checks

| Check | Status | Evidence |
| --- | --- | --- |
| Upload one research PDF and show extracted text | Verified | The Windows browser uploaded a synthetic three-page PDF and displayed the correct count and page 3 text after a blank page. A multipart upload also succeeded against the WSL backend. |
| Start the summary automatically after upload | Verified | The Windows browser sent one summary POST for the uploaded document. With no provider keys, the backend returned a configuration error and the preview and retry button stayed visible. Tests cover duplicate prevention and replacement. |
| Generate and display the five required sections | Partially verified | Automated tests exercised all five sections, response validation, caching, and display using mocked provider responses. This checkout was not tested with live credentials. |
| Ask a natural-language question about the PDF | Partially verified | A browser question unrelated to the synthetic PDF returned “Not enough evidence” locally. Automated tests cover relevant passages, page restrictions, follow-ups, grounded answers, and citation rendering with mocked providers. |
| Gemini, Groq, and OpenRouter fallback | Partially verified | Mocked transport tests verify the provider order, timeouts, failures, and response validation. Earlier live observations are recorded separately in the [final audit](FINAL_AUDIT_REPORT.md). |
| Clean Windows and WSL setup | Verified | Fresh environments installed the pinned direct requirements, started Uvicorn, and returned HTTP 200 from `/api/health` when called from PowerShell. The guarded environment-template copy created an absent file and preserved an existing one. |
| Frontend installation and production build | Verified | Clean `npm.cmd ci`, dev server startup, the frontend suite, and the Vite build passed. Production preview returned HTTP 200 on port 4180 because port 4173 was already occupied. The default preview origin is covered by API tests. |
| Accessible repository and commit history | Verified | The GitHub repository is public with `main` as its default branch. Its history contains the initial application import and the merges for PRs #1–#12. |
| Credential hygiene and dependency checks | Partially verified | Common credential signatures did not match any of 26 reachable `main` snapshots or the staged documentation. Git ignores the real `.env`, dependencies, and build output. npm reported zero advisories and `pip check` found no broken requirements. A signature scan and dependency consistency checks have limited scope. |
| Fresh live generation and factual accuracy | Unverified | This assessment run had no provider credentials and did not make outbound AI requests. Valid JSON and matching citation markers cannot establish factual accuracy. |
| Hosted deployment and assessment submission | Unverified | Verification was local. No hosted environment or submission was checked. |
| Automated GitHub CI and multi-user isolation | Missing | The repository has local test commands and no GitHub Actions workflow. The application keeps one document in a single backend process without authentication. These capabilities are outside the original assessment requirements. |

## Reproduced commands and results

| Environment | Commands | Result |
| --- | --- | --- |
| Windows PowerShell, repository root | `py -m venv backend\.venv`, `.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`, `.\backend\.venv\Scripts\python.exe -m pytest -q` | 257 passed, 0 failed |
| Ubuntu WSL, repository root | [README bootstrap and startup commands](../README.md#ubuntu-wsl-backend-alternative), then `backend/.venv-wsl/bin/python3 -m pytest -q` | 257 passed, 0 failed |
| Windows PowerShell, `frontend` | `npm.cmd ci`, `npm.cmd test`, `npm.cmd run build` | 88 tests passed across 3 files. Build succeeded. |
| Windows PowerShell, `frontend` | `npm.cmd run dev`, `npm.cmd run preview -- --port 4180`, `npm.cmd audit --json` | Both local pages returned HTTP 200. npm reported zero advisories at verification time. |

Tested versions were Python 3.14.6 on Windows, Python 3.14.4 on WSL, Node 24.19.0, and npm 11.17.0. Both backend runs reported one Starlette test-client deprecation warning. Backend tests use synthetic PDFs, dummy credentials, and mocked provider transport. Frontend tests stub fetch. The browser check used real local HTTP and no configured provider.

## Assessment handoff

Use the [README setup instructions](../README.md#run-on-windows-powershell) and the [developer handover](DEVELOPER_HANDOVER.md). For a live AI demonstration, configure at least one backend provider and use a public PDF with selectable text. Show the extracted preview, all five summary sections, and a cited answer with its supporting passage. The current evidence supports a local assessment setup and leaves provider availability and live answer quality for that demonstration.
