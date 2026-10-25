<!--
BEFORE YOU PUBLISH (delete this block):
 1. Run `python -m app.cli demo` on your laptop with real Gemma and paste the real table where it says [[REAL RUN]].
    If the numbers are worse than the replay, say so; the story still works (see "What the real run showed").
 2. Retake the 3 screenshots in docs/screenshots from YOUR real run. The ones in the repo were made from
    replayed Day 1 Gemma answers, so do not present them as the live run.
 3. Add your GitHub repo link and (optional) a 60-second screen recording.
 4. DEV tags: #devchallenge #hf26challenge (the template adds them). Partner category: Best Use of Gemma.
-->

---
title: "Inbox Sloth: a local Gemma that reads your inbox so you don't have to"
tags: devchallenge, hf26challenge, ai, python
---

## The lazy payoff

My professor emails on Monday: assignment due Friday. On Tuesday: *"correction, because of the holiday it's now Thursday."*

An email summariser gives me two accurate summaries and zero help. I still have to notice that they're about the same assignment, remember which one wins, and move the date in my head.

**Inbox Sloth** does that part for me. It reads the mailbox with a model running on my own laptop, turns emails into *commitments* (what, by when, which email said so), and notices when a later email changes an earlier one:

> **Submit Probability Assignment 3**: Thu 22 Oct, 11:59 PM. *Changed (was Fri 23 Oct).*
> Evidence: "Please submit Probability Assignment 3 by Thursday 22 October, 11:59 PM instead."

I open one page and see what to do first, what's due this week, what clashes, and which dates changed and are worth double-checking.

![Plan view](docs/screenshots/plan.png)

## What it does

- **Reads email, extracts commitments.** Assignments, meetings, exams, replies, with deadlines resolved to real dates.
- **Tracks them across emails.** A correction updates the original task and keeps the history; an older email can never overwrite a newer one.
- **Plans your day and week.** Ranked by urgency first, then by what you told it matters (a student's exam, a freelancer's client reply). Every ranking shows its reasons, so you can disagree with it.
- **Flags trouble.** Overlapping events, overloaded days, and moved dates.
- **Shows its evidence.** Every task links to the sentence it came from, highlighted in the original email.
- **Admits what it ignored.** Informational emails (a mess menu, an instruction tweak) create no task, and appear under "Ignored by the sloth" with the reason, so nothing disappears silently.

![The source sentence for a corrected deadline](docs/screenshots/source-correction.png)

## Why open models matter here

Email is the most private text most people have: grades, client names, medical appointments, offers. I didn't want to ship that to a third-party API to find out when my lab report is due.

- **Local inference.** Gemma (`gemma3:1b` via Ollama) runs on my CPU-only laptop. After mail is fetched, analysis never leaves the machine.
- **Free after setup.** No per-email bill, so running it over a whole mailbox is a non-event.
- **Swappable.** One environment variable (`SLOTH_MODEL=gemma3:4b`) changes the model. That mattered, because a 1B model made mistakes I'll describe below, and the architecture had to survive them.
- **Cacheable.** Valid answers are stored by (model, prompt, email), so after a code change, re-analysing all 18 emails takes about a second instead of three minutes. That is what made fast iteration possible on a CPU.

## How it works: the model is a noisy witness

```
email -> Gemma (local, JSON-schema output) -> checks in plain code -> commitment tracker -> plan
```

The model *reads*; code *decides*:

1. **Dates are never computed by the model.** It copies the words ("Thursday 5 PM"); a deterministic resolver turns them into a date relative to when the email was sent.
2. **A date has to be in the email.** If the model's date words don't appear, they're replaced by the email's own date (flagged "Date unsure") or dropped.
3. **A task needs a cue**: an action, deadline, meeting or exam word, in a sentence that isn't about the past or a cancellation.
4. **Evidence is chosen by code**, not trusted from the model's quote.
5. **Kind and title are normalised** from the subject: a quiz is an exam, and a meeting is named after the meeting, not a step inside it.
6. **Safety net.** If the model returns nothing for an email, rules may propose one task, subject to the same checks, and the UI marks it "found by rules".

## The part I almost didn't write

On Day 1, my evaluator told me: **10 of 12 commitments found, 6 of 12 dates right.** Not great, not terrible.

Then I looked at the rows. It was comparing *"Pay semester fee"* with *"Submit data structures exam"*. My matcher accepted the best title match even when the best was bad, so unrelated rows were scored against each other and the result looked better than the output was. After fixing the evaluator and re-scoring the same real output:

| Day 1 (real gemma3:1b run) | reported | actual |
|---|---|---|
| Commitments found | 10/12 | **6/12** |
| Dates correct | 6/12 | **5/12** |
| False positives | 2 | **6** |

### What the real run showed

- For **4 of the 14 actionable emails**, including the deadline correction, the run produced no commitment at all (the stored results show nothing usable from the model).
- It **invented tasks** for informational emails ("Khichdi and papad dinner" from a mess-menu notice).
- It **rewrote dates**, so an explicit "9 November" was flagged uncertain.
- Titles and kinds were often wrong: a quiz became "Attend class".

So the interesting problem wasn't prompting. It was building something that stays correct when the model doesn't. With the same recorded model answers and the same prompt, the Day 2 pipeline scores:

| | Day 1 (re-scored) | Day 2, same model answers |
|---|---|---|
| Found | 6/12 | 12/12 |
| Dates correct | 5/12 | 12/12 |
| Kinds correct | 5/12 | 12/12 |
| False positives | 6 | 0 |

An ablation shows where it comes from: without the rule safety net, 10/12 found and 9/12 dates; without the cue check, the two false positives come back.

**[[REAL RUN: paste your `python -m app.cli demo` table here, and say how it compares.]]**

### Honest caveats

- I wrote the rules *after* seeing these 18 emails, so that table is a development-set score, not a claim that it generalises.
- I then wrote 12 differently-worded emails and ran them through the rules alone (all handled), and tried adversarial ones. That found two real flaws: "Thanks for attending the workshop on Monday" became a future task, and an email's own *subject* could act as evidence for a title copied from it. Both are fixed and tested. But I wrote the rules and the tests, so treat this as a smoke test, not proof.
- All emails are synthetic. No real mailbox was used.

## Limitations

- A 1B model misses things; the rule fallback proposes at most one task per email, so multi-task emails depend on the model.
- A cancellation is ignored rather than applied to an existing task.
- English only, day/month date order, no Gmail sync yet (imported messages only).

## Try it

```bash
ollama pull gemma3:1b
cd backend && pip install -r requirements.txt
python -m pytest -q              # 130+ tests, no Ollama needed
python -m app.cli demo           # real model run, scored against ground truth
uvicorn app.main:app             # http://localhost:8000
```

Code: **[[GitHub link]]**

## What I learned

1. **A metric you wrote in ten minutes is a hypothesis.** Mine flattered me until I read the rows.
2. **Let the model read and let code decide.** Dates, evidence and "is this even a task?" are all things code can check.
3. **Make every judgment visible.** The evidence sentence, the reasons behind a ranking, and the list of ignored items turned out to be the features that made the tool trustworthy, and also the ones that made it debuggable.
