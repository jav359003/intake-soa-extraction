# Hold-out protocols

Three clinical trial protocols downloaded from clinicaltrials.gov **after** the
pipeline was frozen, used to test the locator on documents nobody tuned it
against. Results in `../bench/HOLDOUT.md`.

| file | study | sponsor |
|---|---|---|
| NCT02568046.pdf | Sym004-09, metastatic colorectal cancer | Symphogen |
| NCT03235752.pdf | TJ301, ulcerative colitis | I-Mab |
| NCT05392192.pdf | ADX-629-CC-001, chronic cough | Aldeyra |

These are publicly posted on clinicaltrials.gov. The five protocols supplied
with the assignment are **not** in this repository, and neither is the scanned
version generated from one of them — `bench/score_scanned.py` rebuilds that on
demand.

To reproduce: put the supplied protocols in `../protocols/` and run
`./run_tests.sh`.
