# CAD Expert Review

**For reviewers:** open the [reviewer README](docs/reviewers/README.md) for the illustrated guide to operating the app.

Web app for source-bound human review of **all 1,816 eligible TMCAD test candidates across eleven engineering roles**, giving **19,976 task–candidate assessments**. It also includes eleven task definitions and eleven generic knowledge priors. A fresh clone contains the app code, instructions, compressed STEP sources, source-view images, normalized meshes, and deployment configuration.

The app supports rotation, zoom, pan, cutaway, optional surface markers, source views, neutral STEP downloads, feature observations, four shortlist decisions, queue filters, autosave, resume, revision history, task and knowledge review, JSON/CSV exports, and reviewer comparison. **Cannot assess is stored as `null`.** Start with the [illustrated annotation tutorial](docs/ANNOTATION_TUTORIAL.md): a numbered workspace tour, an animated viewer demonstration, a six-view inspection guide, and four worked examples.

## Dataset coverage

TMCAD contains 9,799 parts: 6,859 training, 980 validation, and 1,960 test parts in the source catalog. The frozen experiment's eligibility and overlap checks retain 1,816 test candidates. This app presents every retained candidate for every role.

The earlier app used 424 distinct candidates and 674 assessments, selected from pooled top-five retrieval results, earlier controls, and random controls. This repository expands that queue to a complete 1,816 × 11 matrix. Its dataset ID is `tmcad-test1816-human-v1`. Source bindings identify this expanded cohort, and each reviewer starts with an empty workspace.

## Run locally

Install Python **3.12**, then clone this repository:

```sh
git clone https://github.com/OliverFanHL/CAD-Expert-Review.git
cd CAD-Expert-Review
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
# macOS / Linux
source .venv/bin/activate
```

Then run:

```sh
python -m pip install -r requirements.txt
python scripts/verify_data.py
python app.py
```

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. Local reviews persist in `workspace/reviews.sqlite3`. Keep this file to retain local work. Local startup uses SQLite automatically. `PORT` and `REVIEW_WORKSPACE` optionally change the port and storage folder.

## Deploy manually to Vercel

Import the repository when you are ready to create your Vercel deployment.

1. In Vercel, choose **Add New → Project**, connect your GitHub account, and import **OliverFanHL/CAD-Expert-Review**. Grant Vercel access to this private repository if needed.
2. Set **Root Directory** to the repository root (`./`) and **Framework Preset** to **Flask** if it is not detected. Use Python **3.12**. Leave Install Command at its automatic setting; dependencies are declared in `pyproject.toml` and `requirements.txt`. The committed Build Command is `python scripts/verify_data.py`. Leave Output Directory unset.
3. Provision a PostgreSQL database through **Storage / Marketplace** or use an existing PostgreSQL provider. Create a dedicated database for this app. Copy its connection URL, including the provider's TLS parameters, into the Vercel environment variable **`DATABASE_URL`**. The app uses this exact name even if your integration supplies `POSTGRES_URL` or another variable. A provider-recommended pooled URL is appropriate for serverless use.
4. Set `DATABASE_URL` for **Production**. For **Preview**, use a separate database to keep practice sessions separate. The database account needs permission to create the `expert_reviews` table and read/write its rows. The app creates this table automatically on first startup.
5. Click **Deploy**. The build verifies every frozen input and all **5,448 evidence files**. `vercel.json` configures the Flask entrypoint, static assets, security headers, and source verification. Vercel serves the compressed CAD assets from `public/` through its CDN. The browser decompresses STEP and mesh responses through standard HTTP content encoding. Files use ordinary Git storage. A complete clone includes the full review evidence.
6. Open the deployment URL and visit `/api/health`. Expect `status: "ok"`, `storage: "postgresql"`, `candidates: 1816`, `assessments: 19976`, and `tasks: 11`.
7. Use a temporary reviewer ID to verify opening a workspace, loading 3D geometry and source views, downloading STEP, saving a decision, refreshing to resume, and downloading review JSON. Use your permanent reviewer IDs for actual annotation. If you add or change `DATABASE_URL` after deployment, **redeploy** for the change to apply.

PostgreSQL stores reviews across Vercel instances and deployments. Set `DATABASE_URL` before the first deployment. Saves are transactional and serialized per reviewer, including simultaneous first saves. The interface reports save status and supports retries. Workspace loading and JSON export use streamed responses for the full review matrix. Back up the database and download JSON exports regularly.

Reviewer IDs and the human-review checkbox use **self-attestation**. Site visitors can open a workspace by its reviewer ID. Use Vercel Deployment Protection to restrict site access to your study group. STEP downloads retain the original source metadata.

The configuration follows Vercel's official [Flask deployment guide](https://vercel.com/docs/frameworks/backend/flask), [Python runtime guide](https://vercel.com/docs/functions/runtimes/python), and [project configuration reference](https://vercel.com/docs/project-configuration). Complete the production smoke check after your manual deployment.

### If the deployed page opens but the review queue stays empty

Open `/api/health` on your deployment. A `database_not_configured` response means the deployment needs `DATABASE_URL`:

1. In the Vercel project, open **Storage**, create or connect a PostgreSQL database, and connect it to this project.
2. Open **Settings → Environment Variables**. Add **`DATABASE_URL`** with the provider's PostgreSQL connection string for **Production**. If the integration created a variable with another name, copy that value into `DATABASE_URL`. Retain the provider's TLS parameters.
3. Open **Deployments** and redeploy the latest commit. Environment changes apply to new deployments.
4. Reopen `/api/health`. A working connection returns `status: "ok"` and `storage: "postgresql"`. Refresh the app and open your reviewer workspace.

A `database_unavailable` response means the database connection or table setup failed. Check the provider's connection details, database availability, and table-creation permissions, then retry. Vercel runtime logs identify failures that happen before the app can return JSON.

The CAD assets are stored in `public/evidence/`: 1,816 compressed `.step.gz` sources, 1,816 `.bin.gz` meshes, and 1,816 `.png` source-view images. You can check static delivery directly at `/evidence/Z0005.png` or `/evidence/Z0005.step.gz` while diagnosing the API.

## Expert workflow

1. Enter a stable reviewer ID (2–64 letters, digits, dots, hyphens, or underscores) and attest that the decisions are your own human review. Reuse the ID to resume work.
2. In **Task definitions**, review the frozen request and rubric. Accept or document requested changes. Requested changes are saved as review notes for the study coordinator.
3. In **CAD relevance**, inspect the source CAD and observe each required feature. Drag to rotate, wheel to zoom, Shift-drag to pan, and double-click for an optional surface marker. Cutaway is an uncapped visual slice. Source views and STEP remain available when WebGL is unavailable.
4. Choose **Shortlist / Conditional / Reject / Cannot assess**, an evidence reason, and any required note. Shortlist requires every required visible feature. Valid CAD decisions autosave. **Save & next** validates before moving. Queue filters distinguish unreviewed items from unresolved cases.
5. Review **Generic knowledge** independently, then click **Save review**. Only accepted generic priors enter knowledge exports; candidate judgments remain separate.
6. Click **Download review JSON** for a portable source-bound record with reviewer ID, timestamps, provenance, feature evidence, and revision history.

**Team progress** (left sidebar) shows how many of the 19,976 assessments at least one expert has reviewed, coverage for the selected task, and an anonymous count per reviewer. Each candidate shows how many experts have reviewed it, and the **Not reviewed by anyone** queue lists uncovered candidates. The `/api/progress` endpoint returns counts only, never other reviewers' IDs, decisions or notes, so assessments stay independent. Counts refresh every minute and after each of your saves. Practice IDs stored in the same database count as reviewers.

Use the [annotation tutorial](docs/ANNOTATION_TUTORIAL.md) for complete worked examples and the [reviewer guide](docs/REVIEWER_GUIDE.md) for pilot and disagreement handling. Each reviewer records their own decisions for the expanded cohort.

## Export, compare, or migrate reviews

Commands use local SQLite by default. To target the deployed database, set `DATABASE_URL` in your terminal first. `.env.example` documents the variable. Set environment variables in the shell or hosting dashboard; keep credentials there.

```sh
python manage.py export --reviewer expert_a --output exports/expert_a
python manage.py export --all --output exports/all
python manage.py compare --reviewers expert_a expert_b --output exports/comparison
python manage.py import --file /path/to/existing/review.json
python manage.py backup --output backups
```

Export writes `review.json`, `judgments.csv`, task/knowledge reviews, and `knowledge/{functions,class_functions,interfaces}.csv`. Every autosave is already stored in the database, and **Download review JSON** is a copy of that stored record. Coordinators can therefore export all experts at any time without asking reviewers for files. `export --all` writes the standard export for every stored reviewer into `<output>/<reviewer>/`, plus a combined `all_judgments.csv`. It reads the database without changing it. Comparison writes `agreement.json` and `disagreements.csv`; unresolved decisions are counted separately from assessable agreement. Import accepts a human-review JSON export from this expanded dataset with matching source bindings and a new reviewer ID. Reviewer records stay in the database and downloaded exports.

`backup` is read-only. It writes a new `backups/review-backup-<UTC time>/` folder (ignored by Git) with every stored row verbatim (`rows.jsonl`), one importable JSON file per reviewer, and a `manifest.json` with per-row SHA-256 hashes. It never overwrites an earlier backup. To recover one reviewer, run `import --file backups/.../reviewers/<id>__<key>.json`; import refuses to overwrite a reviewer who already exists. Schedule backups with `DATABASE_URL` set to the production database, and also enable your PostgreSQL provider's point-in-time restore.

Exports retain the original record schema and add the expanded dataset ID to the source binding. The 424-part queue has a different pool binding. For subsequent retrieval evaluation, use this repository's frozen protocol, pool manifest, task definitions, and exported judgments together in a matching evaluation run. The app provides annotation, export, and reviewer comparison; retrieval evaluation is performed in the research project.

## Verify and test

```sh
python -m pip install -r requirements-dev.txt
python scripts/verify_data.py
python -m pytest -q
```

Tests cover the full queue, evidence routes, decision rules, unknown handling, revisions, resume, exports, source bindings, large streamed responses, concurrent saves, label-free shared progress, and read-only backup and restore. Set **`TEST_DATABASE_URL`** to a disposable PostgreSQL database to include the database integration test. GitHub Actions supplies PostgreSQL and runs it automatically. Software checks use synthetic fixture records.

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Flask entrypoint and review API |
| `expert_review/` | Decision rules, provenance, export, agreement, and transactional persistence |
| `public/` | Existing HTML/CSS/JavaScript interface and source evidence |
| `data/` | Frozen tasks, pools, knowledge, protocol, rankings for binding only, and checksums |
| `manage.py` | Standalone review export, import, comparison, and read-only backup |
| `scripts/verify_data.py` | Required integrity check before deployment |
| `vercel.json`, `pyproject.toml` | Vercel configuration and Python requirements |
| `.env.example` | Documented production configuration |
| `tests/`, `.github/workflows/` | Workflow checks and PostgreSQL CI |

The app resolves all active inputs relative to this repository. Frozen data and checksums identify the current annotation study. Use a new protocol and a separate database when changing a task or cohort.

See [provenance and attribution](docs/PROVENANCE.md). Source CAD and upstream materials retain their original terms.
