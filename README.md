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

The model is only trusted to **read**. Everything checkable is checked in code:

- **Dates are resolved by Python, not the model.** The model copies the words ("Thursday 5 PM"); `dates.py` turns them into a real date relative to when the email was sent. Small models are bad at calendar maths.
- **No invented commitments.** Every task must quote the email word for word. Quotes are verified against the text; failures are flagged `unverified` and can never overwrite a tracked task.
- **Made-up dates are caught.** If the model's date words are not in the email, confidence drops to low and the UI says "Date unsure".
- **Newsletters and promos never create tasks.**
- **Out-of-order safety.** An older email cannot undo a newer one.

## Run it

Needs Python 3.10+ and [Ollama](https://ollama.com).

```bash
ollama pull gemma3:1b            # or gemma3:4b for better accuracy (slower on CPU)

cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -q              # 37 tests, no Ollama needed (uses a scripted fake model)
python -m app.cli check          # is Ollama reachable, is the model pulled?
python -m app.cli demo           # load 18 sample emails, analyse them, score vs ground truth

uvicorn app.main:app --reload    # open http://localhost:8000
```

Ollama on another host (for example Windows host while the app runs in WSL):

```bash
export OLLAMA_URL=http://<host-ip>:11434
export SLOTH_MODEL=gemma3:4b     # default is gemma3:1b
```

## Measuring accuracy

`data/expected.json` holds the correct answer for the 18 sample emails (12 final commitments, including one corrected deadline and one rescheduled meeting). `python -m app.cli eval` reports how many commitments were found, how many dates were exactly right, and false positives. The same pipeline is covered end to end by `tests/test_pipeline.py` using a scripted model.

## Project layout

```
backend/app/dates.py         deterministic date resolver
backend/app/pipeline.py      prompt, validation, quote/date verification
backend/app/commitments.py   new-vs-update matching across emails
backend/app/llm.py           Ollama client (JSON-schema constrained output)
backend/app/db.py            SQLite storage (emails, commitments, history)
backend/app/main.py          FastAPI API + static frontend
frontend/                    plain HTML/CSS/JS
data/                        18 sample emails + expected results
```

## Privacy

Email text goes only to the model running on your machine. Gmail sync (stretch goal) would need internet to fetch mail, but analysis stays local.

## Status

Day 1 of the Week 3 build: extraction, commitment tracking, API and a first UI. Coming next: priority scoring by role, today/week dashboard, conflict detection, Gmail import.
