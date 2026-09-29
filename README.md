# Notebook Grader

Local, standard-library-only viewer for saved Jupyter notebook outputs and weekly grades. It does not execute notebooks.

```bash
python3 grader.py --course-root /path/to/course
```

The course directory contains `homework/<week>/` and `docs/26_pattern-recognition_students-list.csv` (CSV columns `姓名` and `學號`). Use `--roster docs/other-roster.csv` for a different roster filename; the path is relative to the course directory. Grades are written to `submission/<week>/scores.csv` in the course directory. Open `http://127.0.0.1:8000` if the browser does not open automatically. Use `--course-root /path/to/course --self-test` for the built-in logic check.

Only code belongs in this repository. Keep student rosters, notebooks, and grades in the course repository or another appropriately protected data location.
