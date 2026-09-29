# Notebook Grader

Local, standard-library-only viewer for saved Jupyter notebook outputs and weekly grades. It does not execute notebooks.

```bash
uv sync --locked
uv run --locked nbgrader --course-root /path/to/course
```

The course directory contains `homework/<week>/` and `docs/26_pattern-recognition_students-list.csv` (CSV columns `姓名` and `學號`). Use `--roster docs/other-roster.csv` for a different roster filename; the path is relative to the course directory. Grades are written to `submission/<week>/scores.csv` in the course directory. Open `http://127.0.0.1:8000` if the browser does not open automatically. Run `uv run --locked nbgrader --course-root /path/to/course --self-test` for the built-in logic check.

Notebook assignment uses roster student IDs found in paths relative to `homework/<week>/`. A notebook with one path ID is assigned only when its contents contain no different roster ID. Names and IDs found only in contents are hints, not automatic assignments. Conflicting IDs or multiple notebooks for one student need manual review; `*_title.ipynb` is a reference notebook, not a submission. Unassigned students show an initial score of `0` unless a grade was already saved. Ambiguous files can be previewed but not assigned from the viewer.

Only code belongs in this repository. Keep student rosters, notebooks, and grades in the course repository or another appropriately protected data location.
