# Golden dataset

This folder is the **pytest answer key**. It is not part of the live agent.

## What it is

A golden dataset is a small set of known inputs plus the output a human already judged correct. Tests run the same pipeline on those inputs and fail if the code drifts.

ClauseLens uses it to lock three things:

1. Which clauses must be flagged as unusual
2. Which protections must be reported missing — and which must not
3. The ranking order when amounts are calculable

It does **not** teach the model names, people, or a specific uploaded file. Agents never read this file. `run_analysis` sets `evaluation=None`.

## What it is not

- Not training data
- Not memory of past users
- Not a score shown in the Streamlit report
- Not a claim of real-world accuracy

Scores describe **that fixture only**.

## Cases

| Case ID | Input | What it locks |
| --- | --- | --- |
| `sample_rental_01` | Generated PDF from `agreement_text.py` (`sample_rental_01.pdf`) | Full graph: unusual `7.1`, `9.3`, `4.2`, `6.4`; missing refund and inspection; ranking by rupee exposure |
| `sample_rental_02` | Clause fixtures in `tests/test_sample_agreement.py` | Same unusual numbers, different ranking; `6.4` unknown / unranked |
| `sample_rental_03` | Clause fixtures in `tests/test_sample_agreement.py` | Pet clause not unusual; wear-excluded deduction not whole-deposit language; present topics not reported missing |

Regenerate the sample PDF with:

```bash
python -m evaluation.build_sample
```

## How to add a case

1. Add a fixture (PDF builder or clause list) with no personal names.
2. Add a row to `expected_results.json` with a generic `case_id` such as `sample_rental_04`.
3. Call `score_findings(...)` from a test. Do not call it from `graph/workflow.py`.
