# GLPI Dashboard

A read-only web page showing the state of a GLPI instance: summary counts, health per area and per CI,
ranked risks, and work in flight. Every number links to the records behind it, each of which opens in GLPI.
It's a **FastAPI** backend (`app/main.py`, `app/glpi.py`, `app/model.py`) and a static page (`app/static/`,
no build step), shipped as one Docker image. [README.md](README.md) covers what it shows and how it works.

Repo: [github.com/sjefferson99/glpi-dashboard](https://github.com/sjefferson99/glpi-dashboard), **public**.
This repo holds the app only. The user's own deployment (host, reverse proxy, auth, real `.env`) is kept
privately elsewhere. Don't add it here.

**This file is general context for any branch.** Don't record work status, progress or per-issue history here.
That belongs in the issue and the PR.

## Layout

| Path | What |
|---|---|
| `app/glpi.py` | Read-only GLPI **v1** API client: session, paging, error codes |
| `app/model.py` | Turns raw GLPI rows into the page's views; status maps, `RISK_*` weights |
| `app/main.py` | FastAPI app: background refresh loop, `/api/snapshot`, `/api/refresh`, `/api/search`, `/api/explorer`, `/healthz`, security headers |
| `app/static/` | `index.html`, `app.js`, `style.css`, `logo.svg`, served by the same app |
| `Dockerfile` | Pinned `python:*-slim`, runs as UID 10001 |
| `compose.yml` | Generic deploy: pulls the GHCR image, publishes on localhost; commented reverse-proxy example |
| `compose.dev.yml` | Override that builds from the checkout instead (`glpi-dashboard:local`) |
| `.github/workflows/container.yml` | CI: both test suites, then the image. PRs build only; `main` and `v*.*.*` tags push to GHCR |
| `.github/dependabot.yml` | Weekly grouped updates (pip runtime, pip dev, base image patches, Actions), each after a 7-day cooldown |
| `.env.example` | Settings with placeholder values. Copy it to `.env` (gitignored) |
| `tests/demo_glpi.py` | A realistic demo dataset (fixed seed, generic names) for the README screenshots |
| `scripts/demo.py` | Serves the app on the demo data (port 8001), or takes one screenshot of it (`shot`) |

## Git workflow: issue → branch → PR → merge

- **Always ask before `git commit`, `git push`, opening a PR, or merging a PR.** Each of these four needs its
  own approval, every time. Before each one, summarize what would happen and wait for an explicit go-ahead,
  even if the same action was approved earlier in the session. A go-ahead covers only the work it was given
  for: "commit this" doesn't extend to a later fix, and "commit, PR and merge" once doesn't carry over to the
  next PR. If the scope is unclear, ask. **The user merges by default.** Only merge yourself when the current
  request says so.
- **The normal path for any change:** a GitHub issue, then a branch `<issue#>-<short-name>` (e.g.
  `1-ghcr-image`) off an up-to-date `main`, then a PR to `main`, then a merge. Don't commit straight to
  `main` unless the user says this change is an exception.
- If the work has no issue yet, offer to create one before starting.
- **Dependabot PRs are the exception: no issue.** Combine the open ones on one branch, `deps-<YYYY-MM-DD>`,
  by merging each Dependabot branch into it (fix any conflict and anything that breaks on that branch), then one
  PR, so `main` builds one image, not one per bump. **Merge that PR with a merge commit** (`gh pr merge --merge`):
  then Dependabot's commits land unchanged and their PRs show as merged. A squash or rebase leaves them open.
- **A PR for issue-driven work has `Closes #<n>` on its own line near the top of the body**, so merging
  closes the issue. The rest of the body is a summary and a test plan: what was checked, and how.
- One issue = one branch = one PR. For a multi-step feature, prefer one branch with sequential commits, with
  the PR body laid out as step 1 / step 2 / …. If steps really are independent, give each its own PR
  **targeted at `main`**, never at another PR's branch. GitHub auto-deletes a merged head branch and silently
  closes any PR based on it.
- **The user reviews on local Docker before anything is committed.** Once a change passes both test
  suites, rebuild and restart the local container yourself
  (`docker compose -f compose.yml -f compose.dev.yml up -d --build`). Check that `docker compose logs`
  shows `refreshed: N records` and no `failed` or `cannot read`, then tell the user it's ready at
  `http://127.0.0.1:8000`. Do this after every round of changes. The user tries it against their real GLPI
  and fine-tunes with you. Ask to commit only after they're happy with it. The local `.env` points
  `GLPI_URL` at GLPI's public address. Don't read or edit `.env`.
- **Review the README before every PR push.** Read it against the branch's changes (`git diff main...`) and
  update anything they made out of date: what the page shows, endpoints, settings, how it works. Do it
  every time, including pushes to an open PR, not only for big features.
- **README screenshots: retake only what a change visibly altered.** Every image in `docs/screenshots/` stays
  in git history for good, so they're never regenerated as a set. Before the PR is merged:
  - **Retake an image** only when the branch changed what that screen looks like: its layout, wording, colours,
    or what it shows. Retake just that image, with its own command from the table below, look at it, and
    update the README text beside it if needed.
  - **Add an image** for a new tab or a feature worth showing, beside its description in the README, and add
    its command to the table.
  - **Don't retake** anything else. That covers screens the change didn't touch, a change to the demo data on
    its own, and a retake "to refresh" one. A retake of an unchanged screen can differ by a few pixels, which
    would add a near-identical copy to history.
  - Images come only from the demo data (`scripts/demo.py shot`), never a real GLPI. Light theme only, for now:
    dark ones wait for a dark mode toggle. If a change needs the demo data to show it, extend
    `tests/demo_glpi.py`, keeping it generic.

  | Image | Command (`.venv\Scripts\python.exe scripts/demo.py shot docs/screenshots/<image> ...`) |
  |---|---|
  | `summary.png` | `--tab Summary` |
  | `in-flight.png` | `--tab "In flight"` |
  | `recurring.png` | `--tab "Recurring changes"` |
  | `cmdb.png` | `--tab CMDB` |
  | `risks.png` | `--tab "Risk analysis"` |
  | `explorer.png` | `--tab "Record explorer"` |
  | `list.png` | `--link "#list=high-priority" --element "#list"` |
  | `search.png` | `--link "#search=vpn&closed=1" --element "#list"` |
- **A Claude code review before every merge.** Run `/code-review` on the PR as **one sequential pass with no
  sub-agents**. Reproduce each finding against a crafted input before reporting it. Post the findings as PR
  comments (labelled as below), then stop. Fixes wait for the user's approval, even obvious ones. Re-run the
  reproduction after an approved fix. Once a fix is pushed, reply in the thread (labelled as below) with the
  fixing commit, what the reproduction shows now, and the new test, then resolve the thread. Resolve only
  threads documented that way. Leave any other thread (a question, a skipped finding, a reviewer's own
  comment) for the user.
- **CI must be green before a merge** (`gh pr checks <N>`). Also check that `gh pr view <N> --json
  mergeable,mergeStateStatus` reports `MERGEABLE`/`CLEAN`: CI green isn't the same as merge-clean.
- After a merge to `main`, confirm the `Container` workflow pushed the image (`gh run list --workflow
  container.yml --branch main --limit 1`).
- Commit messages use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `test:`, `refactor:` or `chore:`, plus an optional scope (`ui`, `api`, `model`, `glpi`, `ci`). Add
  `(#<n>)` to the subject when there's an issue.
- After a merge: `git checkout main && git pull`, then delete the local branch.

## Public repo: what must never be committed

- **Secrets.** `.env` is gitignored. `.env.example` holds placeholders only. Error messages and logs never
  include tokens or GLPI response bodies (`glpi.py` `_code()` returns just the `ERROR_*` code). Keep it that way.
- **Never read** `.env`, tokens or other credential files. If a script needs a secret, it prompts for it.
  Secrets never go on a command line.
- **Nothing site-specific**: no real domains, hostnames, IPs, CI names, people's names, change/KB ids or
  proxy/auth set-up, in code, comments, docs, tests, issues or PRs. Use `example.com` / `example.test`
  domains and generic names (`reverse-proxy`, `web1`). Describe network ranges in words ("the Docker
  network's subnet"). Configuration belongs in environment variables, with neutral placeholders in
  `.env.example`.

## Design rules (easy to break)

- **Read-only towards GLPI.** Nothing here writes to GLPI, and the `dashboard` profile is read-only. Don't
  add write calls.
- **v1 API only.** v2 has no endpoints for the links between records and CIs or projects.
- **A count is the length of its list.** Every number comes from `Builder.add_list()` and links to
  `#list=<key>`, so a count and its records can't disagree. A new tile or count must go through `add_list`,
  never through a separate count. The one exception is the Record explorer: its boxes are any combination of
  groupings, so the page groups `/api/explorer`'s rows itself, and each box's count and list are the same array.
- **GLPI text goes into the DOM with `textContent` only**, via the `el()` helper in `app.js`, never
  `innerHTML` (DOM-XSS). The CSP in `main.py` is `default-src 'self'`, so no inline scripts and no CDNs.
- **`/healthz` gives nothing away.** Deployments leave it reachable without auth for monitors, so it
  returns only `ok` and a time.
- **A refresh failure keeps the last snapshot**, flagged with the error. The loop must never die, which is
  why it has the broad `except`. `POST /api/refresh` is rate-limited by `MANUAL_MIN_SECONDS` and shares
  `refresh_lock` with the timer.
- **A missing GLPI right** fails the refresh with a single log line naming every unreadable type. A CI type
  the profile can't read shows as `Type #id` instead of failing. Rights are changed in GLPI by the user:
  describe the change and don't attempt it.
- The container runs read-only, with all capabilities dropped, as UID 10001. It holds no data to back up.
  Keep these properties when changing the `Dockerfile` or the compose file.
- Risk weights (`RISK_*` in `model.py`) are tuned with the user. Don't change them unasked.

## Code style

- **Python:** PEP 8 with 4-space indents, lines up to 120 characters (as the existing code), and double
  quotes. Docstrings are **Google style**: a one-line summary, then `Args:`, `Returns:` and `Raises:`
  sections where they add something. Every module, class and public function has one. A short helper may
  have just the summary line.
- **Comments say why, not what.** Keep them for the non-obvious: GLPI quirks, security reasons, ordering
  that matters.
- **JavaScript:** ES2022, 2-space indents, semicolons, **single quotes** (template literals for
  interpolation), `const` and arrow functions. JSDoc (`/** ... */`) on each top-level function, with
  `@param` and `@returns` when the types aren't obvious.
- **HTML/CSS:** 2-space indents, semantic elements, kebab-case class names.

## Frontend and accessibility

- Plain HTML/CSS/JS with no build step and no framework. Build the DOM with `el()`.
- **Semantic HTML first**: `<section>` with `aria-labelledby`, real `<table>`s with `<th>`, `<a>` for
  navigation, and `<button type="button">` for actions. Every interactive element must work from the
  keyboard, with a visible `:focus-visible` outline in `var(--focus)`.
- **RAG state is never colour alone.** It's an icon, a word (Act/Watch/OK) and a colour, with the icon
  `aria-hidden`. Keep all three for any new status.
- **Colours come from the CSS variables in `style.css`**, which have light and dark variants (via
  `prefers-color-scheme` and `data-theme`). Never hardcode a colour in a new rule. Text meets WCAG AA
  contrast (4.5:1, or 3:1 for large text and UI parts) in both themes.
- **The drill-down is a native `<dialog>`** opened with `showModal()`, labelled by `aria-labelledby`, and
  closed by Escape or ✕. Closing it clears the `#list=` hash so Back works. Reuse it rather than adding a
  second modal.
- Links into GLPI open in a new tab (`target="_blank" rel="noopener"`) and go through `safeUrl()`.
- **Failures don't block the page.** An error shows in the `role="alert"` banner, the last data stays on
  screen, and `alert()` is never used. Buttons that start a request are disabled while it runs, and get
  their label back afterwards.

## Testing

- **Every behaviour change gets a test. A bug fix gets a test that fails before the fix.** Cover the happy
  path, error cases, edge cases and security (XSS payloads in GLPI text, nothing leaking into errors).
- `tests/`: pytest, no network. `tests/fake_glpi.py` is a fake GLPI v1 API (an `httpx.MockTransport`
  handler) with a small fixed dataset. Tests drive the real `Glpi` client and FastAPI app through it.
  `test_model.py` asserts the exact numbers that dataset gives, so update those tests when you change it.
- `ui-tests/`: Playwright (pytest-playwright, headless Chromium) against the real app served by uvicorn
  on a free port, fed by the same fake GLPI. **Any change to `app/static/` needs a UI test.** Tests act
  as a user would (click, keyboard, visible text). Never reach into the page's JS state, except to check
  that an XSS payload didn't run.
- `tests/demo_glpi.py` is a second, larger dataset for the demo and screenshots only. Tests check it's
  repeatable, generic and fills every view, not its exact numbers. Changing it changes what every screenshot
  would show, so keep changes to what a new screen needs; leave `fake_glpi.dataset()` as the tests' fixed one.
- Match the run to the change: a frontend-only change needs `ui-tests/`, and a backend change needs
  both suites. Run both before asking for a merge.

## Commands

The venv is `.venv` at the repo root (gitignored): Python 3.14 via uv, the same minor version as the
`Dockerfile` base. Bump both together.

```powershell
uv venv --python 3.14 .venv                                        # once
uv pip install -r requirements.txt -r requirements-dev.txt         # after any requirements change
uv pip install pip                                                 # once: Snyk's SCA scan needs pip in the venv
.venv\Scripts\python.exe -m playwright install chromium            # once per Playwright version
.venv\Scripts\python.exe -m pytest                                 # unit + API tests (tests/)
.venv\Scripts\python.exe -m pytest ui-tests                        # UI tests, headless Chromium
.venv\Scripts\python.exe -m pytest ui-tests --headed --slowmo 300  # watch the UI tests run
.venv\Scripts\python.exe scripts/demo.py                           # the page on demo data, at 127.0.0.1:8001
.venv\Scripts\python.exe scripts/demo.py shot --help               # one README image: see the screenshots rule

```

The container, against a real GLPI:

```powershell
docker compose -f compose.yml -f compose.dev.yml up -d --build   # build from this checkout
bash scripts/smoke-test.sh glpi-dashboard:local                   # the CI image check: starts it with no GLPI
docker compose ps                 # expect (healthy)
docker compose logs -f            # expect "refreshed: N records"; look for "failed" / "cannot read"
```

`compose.yml` publishes on `127.0.0.1:8000` and needs a `.env` with a GLPI reachable at `GLPI_URL`. Without a
GLPI, the page shows the "first refresh still running" or error banner, and `/healthz` returns 503.

## Security

- Run a Snyk Code scan (`snyk_code_scan`) on new or modified first-party code. Fix any new findings in the
  changed code and rescan until it reports none.
- **GitHub Actions are pinned to a full commit SHA**, with the version in a trailing comment. When adding
  or bumping one, pick a release at least **one week** old. Lint workflow changes with actionlint:
  `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/repo:ro" -w /repo rhysd/actionlint:1.7.12 -no-color`.
- **Every dependency waits a week before it's taken: Actions, Python packages and the base image.** A hijacked
  release passes the tests: an Action runs with CI's token and could push a tampered image, and a Python
  package runs in the deployed container beside the GLPI tokens. Such releases are usually caught within days.
  Dependabot's `cooldown` enforces the week for its routine version updates only. Check the release date
  yourself for a Dependabot *security* update or a bump made by hand, and take a security fix sooner only when
  the user decides to. Beyond that wait, take the newest release and fix what breaks. The base image takes the
  newest **patch** only: a new Python minor is bumped deliberately, with the venv and CI (see Commands).
- After changing the `Dockerfile`, the base image or `requirements.txt`, also run a Snyk container scan
  and an SCA scan. Pins are exact: bump them deliberately, not with ranges.

## Working rules

- **No sub-agents unless the request explicitly asks for them.** This includes the `code-review` skill's
  default multi-agent mode. A plain "review this" means do the review directly.
- **Prompt before installing anything** on the machine.
- **Commands for the user: give the next complete, self-contained command.** Head it with where it runs
  (host and folder), start it with any `cd` and every variable it uses, and say what output to expect and
  what to paste back. Never refer back to earlier messages ("step 2 above"); repeat the command instead.
  Commands never print secrets.
- Update the README when user-visible behaviour changes.
- **AI-written PR or issue comments must say so.** They're posted from the user's account, so each comment
  body starts with this line, then a blank line:
  `> **⚠️ AI-generated comment, posted on behalf of @sjefferson99 — not written by them personally.**`
  Check the final body before posting.

## Windows gotchas

- The dev machine runs Windows 11 (PowerShell, plus Git Bash for the Bash tool). The `python` on PATH may be
  the Microsoft Store stub, so don't rely on it.
- `.gitattributes` forces LF. Scripted edits must keep LF and UTF-8. Python's `read_text()`/`write_text()`
  default to cp1252 on Windows and text mode writes CRLF, so pass `encoding="utf-8", newline="\n"` or use
  the Edit tool.
- Git Bash rewrites POSIX-looking arguments into Windows paths (e.g. `docker run -v host:/app`). Prefix the
  command with `MSYS_NO_PATHCONV=1`.
- Git Bash fakes the executable bit, so a new script can look executable locally and still be committed as
  100644. Use `git update-index --chmod=+x`.
- Installed packages' `*.dist-info\licenses` folders come out read-only, so a later `uv pip install` that
  upgrades or downgrades one fails with "failed to remove directory ... Access is denied" and leaves the venv
  half-changed. Recreate the venv instead: delete `.venv` (clear the read-only flags first), then run the
  once-only commands under Commands again.
