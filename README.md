# Notebook Grader

Local viewer for saved Jupyter notebook outputs and weekly grades. Runtime uses only the Python standard library; notebooks are displayed, never executed.

## Run

Install [uv](https://docs.astral.sh/uv/), then run from this repository:

```bash
uv run --locked nbgrader --course-root /path/to/course
```

The course directory must contain `homework/<week>/` and `docs/26_pattern-recognition_students-list.csv` with columns `姓名` and `學號`. For another roster filename, pass `--roster docs/other-roster.csv` (relative to the course directory). The viewer listens on `http://127.0.0.1:8000`; open that address if no browser opens automatically. Scores are written to `submission/<week>/scores.csv` in the course directory.

## Review and grading

Each notebook is assigned to a student only when its path **within the week directory** contains exactly one roster ID and its contents contain no *different* roster ID. A name in the path or notebook, or an ID found only in notebook contents, is a hint, not an assignment. Conflicting IDs and multiple notebooks assigned to one student require manual review; they remain available in the file list for preview. `*_title.ipynb` is a reference for code comparison and never a student submission.

Students without a uniquely reviewable notebook show a default score of `0`; a previously saved score takes precedence. You can select a student and grade separately, but previewing an ambiguous file cannot assign it or save a grade for it.

## Check

```bash
uv run --locked nbgrader --course-root /path/to/course --self-test
uv run --locked python -m unittest discover -s tests -v
```

Keep student rosters, notebooks, and grades in the course repository or another appropriately protected data location, not in this repository.
