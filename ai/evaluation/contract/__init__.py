"""The frontend contract's generated files (docs/ai/frontend-contract.md).

python -m evaluation.contract export          # schemas, tables and examples, without the gap ones
python -m evaluation.contract export --gap    # the gap examples: the local embedding model, no key
python -m evaluation.contract check           # exit 1 when a generated file is out of date

Every example comes from the real code path, over the fake model gateway or the repo's fixtures;
none is written by hand. Where a fake model answer is needed, it is a fixture file or an example
from ai/examples/, and the doc says which.
"""
