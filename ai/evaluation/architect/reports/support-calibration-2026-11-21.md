# Support threshold calibration (AI-13), 2026-11-21T14:15:33Z

**Threshold: 0.67** (a claim below it is flagged *weakly supported*).

- Model: `local/BAAI/bge-small-en-v1.5` (local, no API cost). Data: passages.yaml 1.1.0 (141 positive pairs, 141 negative pairs).
- At the threshold: precision 85.81%, recall 94.33%, F1 0.899.
- Positive scores: {'min': 0.5418, 'p10': 0.6898, 'median': 0.8526, 'max': 1.0}.
- Negative scores: {'min': 0.349, 'p10': 0.513, 'median': 0.5948, 'max': 0.8318}.

**Method.** positive: a passage sentence (6+ words) vs its own passage; negative: the same sentence vs the most similar passage of another page in the same domain; threshold: best F1 (ties: the lower), rounded to 2 decimals. Fixture passages only, never seed results.

**Known limit.** A sentence taken from the passage scores higher than a fair paraphrase, so the threshold may flag some paraphrased claims; the seed reports' 10-claim human spot-check covers it.
