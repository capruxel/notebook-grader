import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from notebook_grader import app


class MatchingTest(unittest.TestCase):
    def test_week_assignment_and_ambiguity(self):
        with tempfile.TemporaryDirectory(prefix="D9999999-course-") as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/26_pattern-recognition_students-list.csv").write_text(
                "姓名,學號\n甲同學,D1234567\n乙同學,D2345678\n丙同學,D9999999\n", encoding="utf-8"
            )
            week = root / "homework/w1"
            week.mkdir(parents=True)

            def notebook(name, source="print(1)"):
                path = week / name
                path.write_text(json.dumps({"cells": [{"cell_type": "code", "source": source}]}), encoding="utf-8")
                return path

            notebook("w1_title.ipynb", "D9999999")
            valid = notebook("D1234567_甲同學.ipynb", "乙同學")
            conflict = notebook("D2345678.ipynb", "D1234567")
            hint = notebook("untitled.ipynb", "D9999999 甲同學")
            multiple = notebook("D1234567_D2345678.ipynb")
            with patch.object(app, "ROOT", root), patch.object(app, "HOMEWORK", root / "homework"):
                result = app.week_data("w1")
                students = {row["student_id"]: row for row in result["students"]}
                files = {Path(row["path"]).name: row for row in result["files"]}
                self.assertEqual(files[valid.name]["assigned_id"], "D1234567")
                self.assertIn("D2345678", files[valid.name]["candidates"])
                self.assertIsNone(files[conflict.name]["assigned_id"])
                self.assertEqual(files[conflict.name]["reason"], "conflict")
                self.assertIsNone(files[hint.name]["assigned_id"])
                self.assertEqual(files[hint.name]["reason"], "hint")
                self.assertEqual(files[multiple.name]["reason"], "conflict")
                self.assertEqual(files["w1_title.ipynb"]["reason"], "reference")
                self.assertEqual(students["D1234567"]["status"], "ready")
                self.assertEqual(students["D1234567"]["score"], "")
                self.assertEqual(students["D2345678"]["status"], "conflict")
                self.assertEqual(students["D9999999"]["status"], "unresolved")
                self.assertEqual(students["D9999999"]["score"], "0")
                self.assertEqual(app.save_grade("w1", "D2345678", "87", root=root)["score"], "87")
                self.assertEqual({row["student_id"]: row for row in app.week_data("w1")["students"]}["D2345678"]["score"], "87")
                notebook("D1234567_copy.ipynb")
                changed = {row["student_id"]: row for row in app.week_data("w1")["students"]}
                self.assertEqual(changed["D1234567"]["status"], "multiple")
                self.assertIsNone(changed["D1234567"]["path"])
                self.assertEqual(changed["D1234567"]["score"], "0")


if __name__ == "__main__":
    unittest.main()
