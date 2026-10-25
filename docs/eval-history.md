# Evaluation history

All numbers are on the 18 sample emails in `data/sample_emails.json` against `data/expected.json` (12 expected commitments).

## Day 1 (real run, gemma3:1b via Ollama, ~181 s on CPU)

| Metric | Reported by the Day 1 evaluator | Re-scored with the fixed evaluator |
|---|---|---|
| Found | 10/12 | **6/12** |
| Dates correct | 6/12 | **5/12** |
| Kinds correct | not measured | 5/12 |
| False positives | 2 | **6** |

The Day 1 evaluator accepted the best title match even when it was poor, so unrelated rows were compared
(e.g. "Pay semester fee" vs "Submit data structures exam") and the score looked better than the output was.
The fixed evaluator pairs commitments one-to-one and requires real evidence (same date AND a shared content
word, or a very similar title). The re-score used the real `sloth.db` from that run.

What the real run showed: for 4 of 14 actionable emails (e02 correction, e05 meeting, e16 fee, e17 scholarship)
the model returned no task at all; it invented tasks for 2 informational emails (e04, e13); it rewrote dates and
quotes (an explicit "9 November" exam date was flagged uncertain); titles and kinds were often wrong.

## Day 2 (same model outputs, same prompt, new pipeline)

Replay of the recorded Day 1 answers (`backend/tests/fixtures/gemma_day1_outputs.json`, rebuilt from the real DB)
through the Day 2 pipeline, offline and deterministic:

| Metric | Day 1 | Day 2 replay |
|---|---|---|
| Found | 6/12 | 12/12 |
| Dates correct | 5/12 | 12/12 |
| Kinds correct | 5/12 | 12/12 |
| False positives | 6 | 0 |
| Found by the rule fallback | 0 | 3 (+ the e02 correction applied by it) |

Ablation on the same replay: without the rule fallback 10/12 found, 9/12 dates; without the grounding filter the
2 false positives return.

Caveats, stated plainly:

- The rules were written after seeing these 18 emails: this is a development-set score, not a generalisation claim.
- 12 extra emails written afterwards with different wording (`test_rules_generalise.py`) are all handled by the rules
  alone, but the same author wrote the rules and the emails. Probing with adversarial emails found and fixed two
  flaws (past events, subject-as-evidence).
- The prompt was NOT changed, so Day 1 and Day 2 are comparable. The replay reconstructs the model's answers from
  what Day 1 stored; emails that created no commitment are assumed to have returned no tasks.

## Day 2 (real re-run on the laptop)

Run `python -m app.cli demo` and paste the table here. (First run calls the model, ~3 min; later runs use the cache.)
