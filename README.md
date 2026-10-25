# Inbox Sloth 🦥

**Your inbox is full. Your brain doesn't have to be.**

Inbox Sloth reads your emails with a **local open-weight model (Gemma via Ollama)** and turns them into tracked commitments: what to do, by when, and which email said so. When a professor corrects a deadline, the existing task is *updated and flagged*, not duplicated.

Built for the DEV Hacktoberfest Open-Source AI Challenge, Week 3 (*Slow and Steady*).

## Why it is not "just an email summariser"

| Ordinary summariser | Inbox Sloth |
|---|---|
| Tells you what each email says | Extracts commitments with a deadline and a source |
| Forgets between messages | Tracks one task across several emails |
| "Due Friday" ... later "moved to Thursday" = two unrelated summaries | One task, updated, flagged "Changed (was Fri 23 Oct)" |

## How it works

```
emails -> Gemma (Ollama, local) -> checks in plain code -> commitment tracker -> dashboard
```

The model is only trusted to **read**. It is treated as one noisy witness, and plain code checks it
against the email text (`backend/app/grounding.py`):

- **Dates are resolved by Python, not the model.** The model copies the words ("Thursday 5 PM"); `dates.py` turns them into a real date relative to when the email was sent.
- **A date must be in the email.** If the model's date words are not in the email, they are replaced by the email's own date (flagged "Date unsure") or dropped. An invented date is never kept.
- **A task needs a cue.** Informational emails (menus, instruction changes, results) have no action, deadline or event wording, so nothing is tracked. They are listed under "Ignored by the sloth" with the reason, so nothing disappears silently.
- **Evidence is chosen by code.** The highlighted sentence in the UI is a real sentence from the email, not the model's quote.
- **Kinds and titles are normalised** from the subject and evidence (a quiz is an exam; a meeting is named after the meeting, not a step inside it).
- **Rule-based safety net.** If the model returns nothing for an email, rules may propose one task from the email itself, subject to the same checks. Such tasks are marked "found by rules".
- **Corrections update, they don't duplicate.** A correction is matched to the original by cleaned subject or thread, and an older email can never undo a newer one.
- **Newsletters and promos never create tasks.** Past events and cancellations don't either.

## Re-running without the model

Valid model answers are cached in SQLite. After changing any code (not the prompt), `python -m app.cli reprocess` re-analyses all emails in about a second. `python -m app.cli cache-clear` forces fresh model calls.

## Run it

Needs Python 3.10+ and [Ollama](https://ollama.com).

```bash
ollama pull gemma3:1b            # or gemma3:4b for better accuracy (slower on CPU)

cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -q              # ~110 tests, no Ollama needed (scripted + recorded model answers)
python -m app.cli check          # is Ollama reachable, is the model pulled?
python -m app.cli demo           # load 18 sample emails, analyse them, score vs ground truth

uvicorn app.main:app --reload    # open http://localhost:8000
```

Under WSL2 the Windows host is auto-detected. To point at another host explicitly:

```bash
export OLLAMA_URL=http://<host-ip>:11434
export SLOTH_MODEL=gemma3:4b     # default is gemma3:1b
```

## Measuring accuracy

`data/expected.json` holds the correct answer for the 18 sample emails (12 final commitments, including a corrected deadline and a rescheduled meeting). `python -m app.cli eval` matches extracted commitments to expected ones one-to-one (a shared date alone is not a match) and reports found / dates / kinds / flags / false positives next to the Day 1 baseline. History and caveats: [docs/eval-history.md](docs/eval-history.md).

## Known limits

- The rules were written after seeing the 18 sample emails, so the sample score is a development-set result. `backend/tests/test_rules_generalise.py` checks 12 differently-worded emails, but the same author wrote both.
- The rule fallback proposes at most one task per email; multi-task emails depend on the model.
- Cancellations are ignored, not yet applied to an existing task. Social invitations that use cue words ("join us Friday 5 PM") can still slip through when the model proposes them.

## Project layout

```
backend/app/dates.py         deterministic date resolver
backend/app/pipeline.py      prompt, validation, response cache, orchestration
backend/app/grounding.py     evidence, date support, kind/title normalisation, rule fallback
backend/app/textnorm.py      text helpers (sentences, tokens, subject cleaning)
backend/app/commitments.py   new-vs-update matching across emails
backend/app/priority.py      role-aware priority scores, daily/weekly plan, clash detection
backend/app/llm.py           Ollama client (JSON-schema constrained output)
backend/app/db.py            SQLite storage (emails, commitments, history)
backend/app/main.py          FastAPI API + static frontend
frontend/                    plain HTML/CSS/JS
data/                        18 sample emails + expected results
```

## Privacy

Email text goes only to the model running on your machine. Gmail sync (stretch goal) would need internet to fetch mail, but analysis stays local.

## Status

Day 3 of the Week 3 build: priority scoring by role, Today / This Week plan, clash and change detection,
Ollama auto-detect under WSL. Next: real-model validation, final write-up (`docs/devpost-draft.md`).
