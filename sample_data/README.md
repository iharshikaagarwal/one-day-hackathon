# Sample agreement

`evaluation/test_agreements/karthik_agreement.pdf` is a synthetic eleven-page rental agreement for the hackathon demonstration.

It is not a real contract. The tenant and owner are fictional. Regenerate it with:

```bash
python -m evaluation.build_sample
```

The file includes ordinary rent and notice clauses, two alarming low-value charges, one reasonable-sounding clause that can expose the full security deposit, no deposit-return timeline, no inspection process, and one hostile instruction. ClauseLens should treat that instruction as document text.
