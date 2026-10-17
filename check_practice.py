"""Score the solver against the practice answer keys."""
import csv
import sys

from solver import solve

keys = {(r["round_id"], r["q_index"]): r["answer"] for r in csv.DictReader(open("data/practice_keys.csv"))}
ok = bad = none = 0
for r in csv.DictReader(open("data/questions.csv")):
    k = keys.get((r["round_id"], r["q_index"]))
    if k is None:
        continue
    opts = [r["option_" + c] for c in "abcd"]
    a = solve(r["question_text"], opts)
    if a == k:
        ok += 1
    else:
        bad += a is not None
        none += a is None
        print("NONE" if a is None else f"WRONG {a}", f"key={k}", r["question_text"], opts)
print(f"correct={ok} wrong={bad} unrecognised={none}")
sys.exit(1 if bad or none else 0)
