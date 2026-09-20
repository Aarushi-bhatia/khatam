#!/usr/bin/env bash
# Every suite, in the order they should be read.
cd "$(dirname "$0")/.."
set +e
for t in test_matcher test_devanagari test_holdout test_vocabulary_gap test_alias_generation; do
  printf '\n\033[1m── %s ──\033[0m\n' "$t"
  python3 "tests/$t.py"
done
