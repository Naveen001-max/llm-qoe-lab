# Research analysis

Install with `pip install -r requirements.txt`. Export the study from `/api/admin/export/study.json`, then run:

```bash
python analyse_study.py study-export.json --out results
```

The script creates a trace-level CSV, an inter-rater disagreement file and a JSON analysis report. It uses participant-grouped cross-validation; repeated traces from one participant are never split between train and test folds. It skips predictive modelling when the sample is too small. Do not interpret exploratory ML metrics as validated predictive performance. Pre-register primary outcomes, exclusions, sample size and statistical tests before WP6.
