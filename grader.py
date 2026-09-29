#!/usr/bin/env python3
"""Review stored Jupyter homework outputs and maintain weekly score CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from difflib import SequenceMatcher
import tempfile
import webbrowser
from typing import cast
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
ROSTER_PATH = Path("docs/26_pattern-recognition_students-list.csv")
HOMEWORK = ROOT / "homework"
ID_PATTERN = re.compile(r"\b[Dd]\d{7}\b")


def text(value: object) -> str:
    return "".join(map(str, value)) if isinstance(value, list) else str(value or "")


def load_roster(path: Path | None = None) -> list[dict[str, str]]:
    with (path or ROOT / ROSTER_PATH).open(encoding="utf-8-sig", newline="") as file:
        return [
            {"name": row["姓名"].strip(), "student_id": row["學號"].strip()}
            for row in csv.DictReader(file)
        ]


def score_path(week: str, root: Path | None = None) -> Path:
    return (root or ROOT) / "submission" / week / "scores.csv"


def load_grades(week: str, root: Path | None = None) -> dict[str, dict[str, str]]:
    path = score_path(week, root)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {
            row["學號"].strip(): {"score": row["成績"].strip(), "note": row.get("備註", "").strip()}
            for row in csv.DictReader(file)
        }


def validate_score(value: object) -> str:
    value = str(value).strip()
    if not value:
        return ""
    try:
        score = float(value)
    except ValueError as error:
        raise ValueError("成績必須是 0 到 100 的數字") from error
    if not 0 <= score <= 100:
        raise ValueError("成績必須介於 0 到 100")
    return value


def save_grade(week: str, student_id: str, score: object, note: object = "", root: Path | None = None) -> dict[str, str]:
    grade = {"score": validate_score(score), "note": str(note).strip()}
    roster = load_roster((root or ROOT) / ROSTER_PATH)
    if student_id not in {student["student_id"] for student in roster}:
        raise ValueError("學號不在名冊中")
    grades = load_grades(week, root)
    grades[student_id] = grade
    path = score_path(week, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as file:
        writer = csv.writer(file)
        writer.writerow(["姓名", "學號", "成績", "備註"])
        writer.writerows((student["name"], student["student_id"], *(grades.get(student["student_id"], {}).get(key, "") for key in ("score", "note"))) for student in roster)
        temp = Path(file.name)
    _ = temp.replace(path)
    return grade


def path_candidates(path: Path, roster: list[dict[str, str]]) -> set[str]:
    haystack = str(path).upper()
    ids = {match.upper() for match in ID_PATTERN.findall(haystack)}
    candidates = {student["student_id"] for student in roster if student["student_id"].upper() in ids}
    if candidates:
        return candidates
    return {student["student_id"] for student in roster if student["name"] in str(path)}


def notebook_candidates(path: Path, roster: list[dict[str, str]]) -> set[str]:
    candidates = path_candidates(path, roster)
    if candidates:
        return candidates
    try:
        contents = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        contents = path.read_text(encoding="utf-8-sig")
    ids = {match.upper() for match in ID_PATTERN.findall(contents)}
    candidates = {student["student_id"] for student in roster if student["student_id"].upper() in ids}
    return candidates or {student["student_id"] for student in roster if student["name"] in contents}


def normalize_output(output: dict[str, object]) -> dict[str, object]:
    kind = output.get("output_type")
    if kind == "stream":
        return {"kind": "stream", "name": output.get("name", "stdout"), "text": text(output.get("text"))}
    if kind == "error":
        return {"kind": "error", "text": text(output.get("traceback")) or f"{output.get('ename', '')}: {output.get('evalue', '')}"}
    raw_data = output.get("data")
    if not isinstance(raw_data, dict):
        return {"kind": "result", "plain": ""}
    data = cast(dict[str, object], raw_data)
    rendered: dict[str, object] = {"kind": "result", "plain": text(data.get("text/plain"))}
    for mime in ("image/png", "image/jpeg", "text/html"):
        if mime in data:
            rendered[mime] = text(data[mime])
    return rendered


def read_notebook(path: Path) -> dict[str, object]:
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"error": f"無法解析 notebook：{error}"}
    return {
        "path": str(path.relative_to(ROOT)),
        "cells": [
            {
                "type": cell.get("cell_type", "unknown"),
                "source": text(cell.get("source")),
                "outputs": [normalize_output(output) for output in cell.get("outputs", [])],
            }
            for cell in notebook.get("cells", [])
        ],
    }

def reference_notebook(week: str, homework: Path | None = None) -> Path | None:
    notebooks = sorted(((homework or HOMEWORK) / week).glob("*_title.ipynb"))
    return notebooks[0] if len(notebooks) == 1 else None


def code_lines(path: Path) -> list[str]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return [
        line
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
        for line in text(cell.get("source")).splitlines()
    ]


def notebook_diff(reference: Path, submission: Path, root: Path | None = None) -> dict[str, object]:
    expected, actual = code_lines(reference), code_lines(submission)
    rows: list[dict[str, object]] = []
    changes = 0
    for group_index, group in enumerate(SequenceMatcher(None, expected, actual, autojunk=False).get_grouped_opcodes(2)):
        if group_index:
            rows.append({"gap": True})
        for tag, start_expected, end_expected, start_actual, end_actual in group:
            for offset in range(max(end_expected - start_expected, end_actual - start_actual)):
                expected_index, actual_index = start_expected + offset, start_actual + offset
                expected_present, actual_present = expected_index < end_expected, actual_index < end_actual
                rows.append({
                    "reference": {"number": expected_index + 1 if expected_present else None, "text": expected[expected_index] if expected_present else "", "kind": "removed" if tag in ("delete", "replace") else "same"},
                    "student": {"number": actual_index + 1 if actual_present else None, "text": actual[actual_index] if actual_present else "", "kind": "added" if tag in ("insert", "replace") else "same"},
                })
                changes += tag != "equal"
    return {
        "reference_path": str(reference.relative_to(root or ROOT)),
        "rows": rows,
        "changes": changes,
    }


def week_data(week: str) -> dict[str, object]:
    if Path(week).name != week or not (HOMEWORK / week).is_dir():
        raise ValueError("找不到作業週次")
    roster = load_roster()
    notebooks = sorted((HOMEWORK / week).rglob("*.ipynb"))
    files = sorted(path for path in (HOMEWORK / week).rglob("*") if path.is_file())
    matches: dict[str, list[Path]] = defaultdict(list)
    file_candidates: dict[Path, set[str]] = {}
    for notebook in notebooks:
        candidates = notebook_candidates(notebook, roster)
        file_candidates[notebook] = candidates
        if len(candidates) == 1:
            matches[next(iter(candidates))].append(notebook)
    grades = load_grades(week)
    students = []
    for student in roster:
        paths = matches[student["student_id"]]
        if len(paths) == 1:
            status, path = "ready", paths[0]
            default = ""
        elif len(paths) > 1:
            status, path = "multiple", None
            default = "0"
        else:
            status, path = "unresolved", None
            default = "0"
        if path and "error" in read_notebook(path):
            status, default = "invalid", "0"
        students.append({
            **student,
            "status": status,
            "score": grades.get(student["student_id"], {}).get("score") or default,
            "note": grades.get(student["student_id"], {}).get("note", ""),
            "path": str(path.relative_to(ROOT)) if path else None,
        })
    return {
        "week": week,
        "students": students,
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "kind": path.suffix.lower() or "file",
                "candidates": sorted(file_candidates.get(path, path_candidates(path, roster))),
            }
            for path in files
        ],
    }


def weeks() -> list[str]:
    return sorted((path.name for path in HOMEWORK.iterdir() if path.is_dir()), reverse=True)


PAGE = r'''<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notebook Grader</title>
<style>
:root{--ink:#142033;--ink-soft:#26364d;--muted:#66758a;--line:#d9e1eb;--canvas:#f3f6fa;--paper:#fff;--blue:#315fca;--blue-soft:#edf3ff;--green:#19714a;--red:#ad3028;--rail:344px}*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,select{font:inherit}button{cursor:pointer}.skip{position:absolute;top:-48px;left:12px;z-index:5;padding:9px 12px;background:#fff;color:var(--ink)}.skip:focus{top:12px}header{height:62px;display:flex;align-items:center;gap:18px;padding:0 22px;background:var(--ink);color:#fff}.brand{display:flex;align-items:baseline;gap:9px}.brand strong{font-size:17px;letter-spacing:-.02em}.brand span{font-size:12px;color:#aebcd0}.week-picker{display:flex;align-items:center;gap:7px;color:#b9c7d8;font-size:12px}.week-picker select{max-width:300px;padding:7px 9px;border:1px solid #4a5b72;border-radius:5px;background:var(--ink-soft);color:#fff}.stats{display:flex;gap:6px;margin-left:auto}.stat{padding:4px 8px;border:1px solid #405169;border-radius:999px;color:#c9d4e2;font-size:12px;white-space:nowrap}.stat strong{color:#fff}.layout{display:grid;grid-template-columns:minmax(0,1fr) var(--rail);height:calc(100vh - 62px)}main{min-width:0;overflow:auto;background:var(--canvas)}.rail{display:grid;grid-template-rows:minmax(300px,1.15fr) minmax(220px,.85fr);min-width:0;background:#fff;border-left:1px solid var(--line)}.rail-section{min-height:0;overflow:auto;border-bottom:1px solid var(--line)}.rail-section:last-child{border-bottom:0}.panel-title{position:sticky;top:0;z-index:1;display:flex;align-items:baseline;justify-content:space-between;padding:13px 16px 10px;background:#fff;border-bottom:1px solid #eef2f6;font-weight:750}.panel-title small{color:var(--muted);font-size:12px;font-weight:500}.student{width:100%;display:grid;grid-template-columns:1fr auto;gap:1px;padding:10px 16px;text-align:left;border:0;border-left:3px solid transparent;border-bottom:1px solid #eef2f6;background:#fff;color:inherit}.student:hover{background:#f7f9fd}.student.selected{border-left-color:var(--blue);background:var(--blue-soft)}.student-name{font-weight:700}.student-score{align-self:start;min-width:30px;text-align:right;font-variant-numeric:tabular-nums;font-weight:750}.meta{grid-column:1/-1;color:var(--muted);font-size:12px}.ready{color:var(--green)}.zero{color:var(--red)}.file-group{border-bottom:1px solid #eef2f6}.file-group summary{padding:9px 16px;color:#44546a;cursor:pointer;font-size:12px;font-weight:700;list-style:none}.file-group summary::-webkit-details-marker{display:none}.file-group summary:before{content:"›";display:inline-block;width:13px;transition:transform .12s}.file-group[open] summary:before{transform:rotate(90deg)}.file{width:100%;padding:8px 16px 8px 29px;text-align:left;border:0;border-left:3px solid transparent;background:#fff;color:var(--ink)}.file:hover{background:#f7f9fd}.file.selected{border-left-color:var(--blue);background:var(--blue-soft)}.file-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file .meta{display:block;margin-top:2px}.reader{max-width:1040px;margin:0 auto;padding:34px 42px 72px}.reader-head{display:grid;grid-template-columns:1fr auto;gap:28px;align-items:center;margin:0 0 18px;padding:24px 26px;background:var(--paper);border:1px solid var(--line);border-top:4px solid var(--ink);box-shadow:0 1px 2px rgb(20 32 51 / .04)}.reader-head h1{margin:2px 0;font-size:26px;line-height:1.2;letter-spacing:-.035em}.reader-head p{margin:0;color:var(--muted)}.reader-kicker{color:var(--blue);font-size:12px;font-weight:750}.grade-box{display:flex;align-items:end;gap:8px}.grade-box label{display:flex;flex-direction:column;gap:3px;color:var(--muted);font-size:12px}.grade-box input{width:78px;padding:8px;border:1px solid #aab8ca;border-radius:4px;text-align:center;color:var(--ink);font-size:18px;font-weight:750}.grade-box button{padding:9px 12px;border:1px solid var(--blue);border-radius:4px;background:var(--blue);color:#fff;font-weight:700}.grade-box button:hover{background:#274fa9}.grade-box button:disabled{cursor:wait;opacity:.7}.message{max-width:130px;color:var(--red);font-size:12px}.reader-nav{display:flex;justify-content:space-between;align-items:center;margin:0 0 12px;color:var(--muted);font-size:12px}.reader-nav strong{color:var(--ink)}.keymap{display:flex;gap:10px;flex-wrap:wrap}kbd{padding:1px 4px;border:1px solid #bdc8d6;border-radius:3px;background:#f8fafc;color:#506075;font:11px ui-monospace,monospace}.cell{position:relative;margin:15px 0;background:var(--paper);border:1px solid var(--line);border-left:4px solid #cdd6e2;box-shadow:0 1px 1px rgb(20 32 51 / .025);scroll-margin:24px}.cell.active{border-left-color:var(--blue);box-shadow:0 0 0 3px #dce9ff}.cell-label{padding:7px 14px;background:#f8fafc;border-bottom:1px solid #e9eef4;color:var(--muted);font-size:12px;font-weight:700}.source,.output{margin:0;padding:16px 18px;white-space:pre-wrap;overflow:auto;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}.output{border-top:1px solid #e7edf4}.error{color:#8c1d18;background:#fff6f5}.markdown{padding:23px 26px;line-height:1.7}.markdown h1,.markdown h2,.markdown h3{margin-top:0}.markdown pre{padding:12px;background:#f3f6fa;overflow:auto}.html-output{width:100%;min-height:80px;border:0;padding:0 18px}.image-output{display:block;max-width:100%;padding:18px}.empty{max-width:620px;margin:76px auto;padding:32px;background:#fff;border:1px dashed #b9c7d8;text-align:center}.empty h2{margin:0 0 8px}.empty p{margin:0;color:var(--muted)}#saved{min-width:52px;color:#bbf7d0;font-size:12px}@media(max-width:900px){:root{--rail:300px}.reader{padding:24px}.reader-head{padding:20px}}@media(max-width:700px){header{height:auto;min-height:62px;flex-wrap:wrap;padding:11px 14px}.stats{margin-left:0}.layout{display:block;height:auto}.rail{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:minmax(230px,auto);border-left:0;border-top:1px solid var(--line)}.rail-section:first-child{border-right:1px solid var(--line)}main{min-height:70vh}.reader{padding:18px 12px}.reader-head{grid-template-columns:1fr;gap:16px}.reader-head h1{font-size:23px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}:focus-visible{outline:3px solid #7da8f5;outline-offset:2px}
</style>
<style>.rail{height:calc(100vh - 62px);min-height:0}@media(max-width:700px){.rail{height:auto}}</style>
<style>.source{background:#1f2937;color:#e8eef7}.source::selection{background:#496481}.cell-label{background:#edf1f6}</style>
<style>.mode{padding:4px 6px;border:1px solid #c8d2df;border-radius:3px;color:#5d6c80;font:700 10px ui-monospace,monospace;letter-spacing:.04em}.mode.insert{border-color:#8cabeb;background:#edf3ff;color:#244fba}</style>
<style>.note-field{display:flex;flex-direction:column;gap:5px;margin:0 0 16px;padding:14px 16px;background:#fff;border:1px solid var(--line);color:var(--muted);font-size:12px;font-weight:700}.note-field textarea{min-height:62px;resize:vertical;border:1px solid #aab8ca;border-radius:4px;padding:8px;color:var(--ink);font:14px/1.5 ui-sans-serif,system-ui,sans-serif}.note-field textarea[readonly]{border-color:transparent;background:#f8fafc;color:#46566c;resize:none}</style>
<style>.diff-toggle{margin-top:8px;border:1px solid #9db1d0;background:#fff;color:#244fba;padding:7px 9px;font-size:12px;font-weight:700}.comparison{border:1px solid var(--line);background:#fff}.comparison-head{display:flex;justify-content:space-between;gap:16px;padding:12px 16px;border-bottom:1px solid var(--line);color:var(--muted)}.comparison-head strong{color:var(--ink)}.diff-columns,.diff-row{display:grid;grid-template-columns:minmax(390px,1fr) minmax(390px,1fr);min-width:780px}.diff-columns{background:#f0f4f9;color:#52627a;font-size:12px;font-weight:700}.diff-columns span{padding:8px 12px}.diff-columns span+span,.diff-line+.diff-line{border-left:1px solid var(--line)}.diff-scroll{overflow:auto}.diff-line{display:grid;grid-template-columns:48px minmax(0,1fr);min-height:23px;padding:2px 8px;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.diff-number{padding-right:8px;color:#8794a8;text-align:right;user-select:none}.diff-line.added{background:#e5f5eb;color:#145b38}.diff-line.removed{background:#fff0ef;color:#922d27}.diff-gap{height:18px;background:repeating-linear-gradient(135deg,#f6f8fb,#f6f8fb 4px,#edf1f6 4px,#edf1f6 8px)}@media(max-width:850px){.diff-columns,.diff-row{min-width:680px}}</style>
<header><a class="skip" href="#viewer">跳到 notebook</a><div class="brand"><strong>Notebook Grader</strong><span>批改工作台</span></div><label class="week-picker">週次 <select id="week" aria-label="選擇批改週次"></select></label><div id="stats" class="stats" aria-live="polite"></div><span id="saved" aria-live="polite"></span></header>
<div class="layout"><main id="viewer" tabindex="-1"><div class="reader">載入中…</div></main><aside class="rail"><section class="rail-section" aria-label="學生名冊"><div class="panel-title">學生 <small id="student-count"></small></div><div id="students"></div></section><section class="rail-section" aria-label="作業檔案"><div class="panel-title">檔案 <small id="file-count"></small></div><div id="files"></div></section></aside></div>
<script>
const $=s=>document.querySelector(s);let data,current,currentPath,currentCell=0,pendingG=false,mode='normal';
async function api(path,options){const r=await fetch(path,options),body=await r.json();if(!r.ok)throw Error(body.error);return body}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function markdown(source){let s=esc(source),fenced=false;return s.split('\n').map(line=>{if(line.startsWith('```')){fenced=!fenced;return fenced?'<pre>':'</pre>'}if(fenced)return line+'\n';const m=line.match(/^(#{1,3})\s+(.*)/);if(m)return `<h${m[1].length}>${m[2]}</h${m[1].length}>`;if(line.match(/^[-*]\s+/))return '<div>• '+line.slice(2)+'</div>';return line?'<div>'+line+'</div>':'<br>'}).join('')}
function status(s){return s.status==='ready'?'已辨識作業':s.status==='multiple'?'多個 notebook，初始 0 分':s.status==='invalid'?'無法解析，初始 0 分':'未辨識作業，初始 0 分'}
function renderStats(){const ready=data.students.filter(s=>s.status==='ready').length,review=data.students.length-ready;$('#stats').innerHTML=`<span class="stat">名冊 <strong>${data.students.length}</strong></span><span class="stat">已辨識 <strong>${ready}</strong></span><span class="stat">待人工 <strong>${review}</strong></span>`}
function renderStudents(){$('#student-count').textContent=`名冊順序 · ${data.students.length}`;$('#students').innerHTML=data.students.map(s=>`<button class="student ${s.student_id===current?'selected':''}" data-id="${s.student_id}"><span class="student-name">${esc(s.name)}</span><span class="student-score">${esc(s.score)}</span><span class="meta ${s.status==='ready'?'ready':'zero'}">${status(s)}</span></button>`).join('');document.querySelectorAll('.student').forEach(b=>b.onclick=()=>selectStudent(b.dataset.id))}
function renderFiles(){const groups=new Map;[...data.files].sort((a,b)=>a.path.localeCompare(b.path,'zh-Hant')).forEach(f=>{const dir=f.path.split('/').slice(2,-1).join('/')||'作業說明';if(!groups.has(dir))groups.set(dir,[]);groups.get(dir).push(f)});$('#file-count').textContent=`檔名字母順序 · ${data.files.length}`;$('#files').innerHTML=[...groups].map(([dir,files])=>`<details class="file-group"><summary>${esc(dir)} · ${files.length}</summary>${files.map(f=>{const id=f.candidates.length===1?f.candidates[0]:'';return `<button class="file" data-path="${encodeURIComponent(f.path)}" data-id="${id}"><span class="file-name">${esc(f.path.split('/').pop())}</span><span class="meta">${f.kind}${id?' · '+id:f.candidates.length?' · 無法唯一比對':''}</span></button>`}).join('')}</details>`).join('');document.querySelectorAll('.file').forEach(b=>b.onclick=()=>openFile(decodeURIComponent(b.dataset.path),b.dataset.id))}
function markSelection(){const student=[...document.querySelectorAll('.student')].find(b=>b.dataset.id===current);document.querySelectorAll('.student').forEach(b=>b.classList.toggle('selected',b===student));const file=[...document.querySelectorAll('.file')].find(b=>decodeURIComponent(b.dataset.path)===currentPath);document.querySelectorAll('.file').forEach(b=>b.classList.toggle('selected',b===file));if(file)file.closest('details').open=true;requestAnimationFrame(()=>[student,file].filter(Boolean).forEach(item=>{const panel=item.closest('.rail-section'),rect=item.getBoundingClientRect(),box=panel.getBoundingClientRect();panel.scrollTo({top:panel.scrollTop+rect.top-box.top-panel.clientHeight/2+rect.height/2,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}))}
function renderNotebook(notebook){const student=data.students.find(s=>s.student_id===current);currentCell=0;let body='<div class="reader">';if(student)body+=`<section class="reader-head"><div><div class="reader-kicker">正在批改</div><h1>${esc(student.name)} <span>${esc(student.student_id)}</span></h1><p>${status(student)}</p></div><div class="grade-box"><label for="score">總分<input id="score" value="${esc(student.score)}" inputmode="decimal" aria-label="總分"></label><button id="save">儲存 <kbd>Ctrl+S</kbd></button><span id="message" class="message"></span></div></section>`;else body+=`<section class="reader-head"><div><div class="reader-kicker">檔案預覽</div><h1>${esc(notebook.path||'Notebook')}</h1><p>此檔案未對應唯一學生，不能直接寫入成績。</p></div></section>`;if(notebook.error)body+=`<div class="empty"><h2>無法解析 notebook</h2><p>${esc(notebook.error)}</p></div>`;else if(!notebook.cells.length)body+=`<div class="empty"><h2>尚未選定可批改作業</h2><p>此學生的作業無法唯一辨識，初始成績已設為 0。可從右側檔案清單開啟檔案人工覆核。</p></div>`;else{body+=`<nav class="reader-nav" aria-label="Notebook 快捷鍵"><strong id="cell-state">Cell 1 / ${notebook.cells.length}</strong><span class="keymap"><span><kbd>j</kbd>/<kbd>k</kbd> cell</span><span><kbd>gg</kbd>/<kbd>G</kbd> 首尾</span><span><kbd>n</kbd>/<kbd>p</kbd> 學生</span><span><kbd>Ctrl+d</kbd>/<kbd>Ctrl+u</kbd> 捲動</span></nav>`;body+=notebook.cells.map((cell,i)=>`<article class="cell ${i===0?'active':''}" id="cell-${i}" tabindex="-1"><div class="cell-label">${cell.type} · cell ${i+1}</div>${cell.type==='markdown'?`<div class="markdown">${markdown(cell.source)}</div>`:`<pre class="source">${esc(cell.source)}</pre>`}${cell.outputs.map(output=>{let html=`<pre class="output ${output.kind==='error'?'error':''}">${esc(output.text||output.plain||'')}</pre>`;if(output['image/png'])html+=`<img class="image-output" src="data:image/png;base64,${output['image/png']}">`;if(output['image/jpeg'])html+=`<img class="image-output" src="data:image/jpeg;base64,${output['image/jpeg']}">`;if(output['text/html'])html+=`<iframe class="html-output" sandbox srcdoc="${esc(output['text/html'])}"></iframe>`;return html}).join('')}</article>`).join('')}$('#viewer').innerHTML=body+'</div>';if(student){$('#save').onclick=save;$('#score').onkeydown=e=>{if(e.key==='Enter')save()}}}
function renderNote(note){const head=$('.reader-head');if(!head||!current)return;const field=document.createElement('label'),area=document.createElement('textarea');field.className='note-field';field.textContent='備註';area.id='note';area.rows=2;area.value=note;area.setAttribute('aria-label','備註');field.append(area);head.after(field);if(currentPath){const button=document.createElement('button');button.id='diff-toggle';button.className='diff-toggle';button.type='button';button.innerHTML='比對修改 <kbd>d</kbd>';button.onclick=showDiff;head.querySelector('.grade-box').append(button)}}
function setMode(next){mode=next;const score=$('#score'),note=$('#note');if(!score)return;const fields=[score,note].filter(Boolean);fields.forEach((field,index)=>field.onkeydown=e=>{if(e.key==='Tab'&&mode==='insert'){e.preventDefault();fields[(index+(e.shiftKey?-1:1)+fields.length)%fields.length].focus()}else if(e.key==='Enter'&&field===score)save()});let badge=$('#mode');if(!badge){badge=document.createElement('span');badge.id='mode';score.closest('.grade-box').prepend(badge)}const inserting=mode==='insert';badge.textContent=inserting?'INSERT':'NORMAL';badge.classList.toggle('insert',inserting);fields.forEach(field=>field.readOnly=!inserting);if(inserting){score.focus();score.select()}else{score.blur();note?.blur()}}
function diffLine(line){const row=document.createElement('div');row.className=`diff-line ${line.kind}`;const number=document.createElement('span'),source=document.createElement('span');number.className='diff-number';number.textContent=line.number??'';source.textContent=line.text;row.append(number,source);return row}
function renderDiff(diff){const reader=$('.reader');reader.querySelectorAll('.reader-nav,.cell,.empty,.comparison').forEach(node=>node.remove());const panel=document.createElement('section'),head=document.createElement('div'),scroll=document.createElement('div'),columns=document.createElement('div');panel.className='comparison';head.className='comparison-head';head.innerHTML=`<strong>程式修改</strong><span>${diff.changes?`共 ${diff.changes} 行差異`:'與作業說明相同'}</span>`;scroll.className='diff-scroll';columns.className='diff-columns';columns.innerHTML='<span>作業說明</span><span>學生程式</span>';scroll.append(columns);diff.rows.forEach(row=>{if(row.gap){const gap=document.createElement('div');gap.className='diff-gap';scroll.append(gap);return}const pair=document.createElement('div');pair.className='diff-row';pair.append(diffLine(row.reference),diffLine(row.student));scroll.append(pair)});panel.append(head,scroll);reader.append(panel);const button=$('#diff-toggle');button.innerHTML='返回 notebook <kbd>d</kbd>';button.onclick=()=>openFile(currentPath,current)}
async function showDiff(){const button=$('#diff-toggle');button.disabled=true;try{renderDiff(await api('/api/diff?path='+encodeURIComponent(currentPath)))}catch(error){$('#message').textContent=error.message}finally{button.disabled=false}}
function focusCell(index){const cells=[...document.querySelectorAll('.cell')];if(!cells.length)return;currentCell=Math.max(0,Math.min(index,cells.length-1));cells.forEach((cell,i)=>cell.classList.toggle('active',i===currentCell));$('#cell-state').textContent=`Cell ${currentCell+1} / ${cells.length}`;cells[currentCell].scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
async function openFile(path,id){current=id||null;currentPath=path;markSelection();renderNotebook(await api('/api/notebook?path='+encodeURIComponent(path)));const student=data.students.find(s=>s.student_id===current);if(student){renderNote(student.note);setMode('normal')}}
async function selectStudent(id){current=id;const student=data.students.find(s=>s.student_id===id);currentPath=student.path;markSelection();renderNotebook(student.path?await api('/api/notebook?path='+encodeURIComponent(student.path)):{path:'',cells:[]});renderNote(student.note);setMode('normal')}
async function save(){setMode('normal');const button=$('#save');button.disabled=true;button.textContent='儲存中…';try{const result=await api('/api/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({week:data.week,student_id:current,score:$('#score').value,note:$('#note').value})});const student=data.students.find(s=>s.student_id===current);student.score=result.score;student.note=result.note;renderStudents();$('#message').textContent='已儲存';$('#saved').textContent='已儲存'}catch(error){$('#message').textContent=error.message}finally{button.disabled=false;button.innerHTML='儲存 <kbd>Ctrl+S</kbd>'}}
async function load(week){data=await api('/api/week?week='+encodeURIComponent(week));const first=data.students.find(s=>s.status==='ready')||data.students[0];current=first?.student_id;currentPath=first?.path;renderStats();renderStudents();renderFiles();if(current)selectStudent(current)}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();setMode('normal');return}if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();if(current)save();return}if(e.target.matches('input,select,textarea'))return;if(e.key==='i'){e.preventDefault();setMode('insert');return}if(e.key==='d'&&mode==='normal'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&$('#diff-toggle')){e.preventDefault();$('#diff-toggle').click();return}const students=data?.students||[],i=students.findIndex(s=>s.student_id===current),modifier=e.ctrlKey||e.metaKey;if(e.key==='j'){e.preventDefault();focusCell(currentCell+1)}else if(e.key==='k'){e.preventDefault();focusCell(currentCell-1)}else if((e.key==='n'||modifier&&e.key==='n')&&i<students.length-1){e.preventDefault();selectStudent(students[i+1].student_id)}else if((e.key==='p'||modifier&&e.key==='p')&&i>0){e.preventDefault();selectStudent(students[i-1].student_id)}else if(e.key==='g'&&!e.shiftKey){if(pendingG){focusCell(0);pendingG=false}else{pendingG=true;setTimeout(()=>pendingG=false,400)}}else if(e.key==='G'){focusCell(Number.MAX_SAFE_INTEGER)}else if(e.ctrlKey&&e.key==='d'){e.preventDefault();$('#viewer').scrollBy(0,$('#viewer').clientHeight/2)}else if(e.ctrlKey&&e.key==='u'){e.preventDefault();$('#viewer').scrollBy(0,-$('#viewer').clientHeight/2)}else pendingG=false});
(async()=>{const weeks=await api('/api/weeks');$('#week').innerHTML=weeks.map(w=>`<option>${esc(w)}</option>`).join('');$('#week').onchange=e=>load(e.target.value);load(weeks[0])})().catch(e=>$('#viewer').textContent=e.message);
</script>'''


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value: object, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                body = PAGE.encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/weeks":
                self.send_json(weeks())
            elif parsed.path == "/api/week":
                self.send_json(week_data(query["week"][0]))
            elif parsed.path == "/api/notebook":
                path = (ROOT / query["path"][0]).resolve()
                if HOMEWORK not in path.parents or path.suffix != ".ipynb":
                    raise ValueError("不允許讀取此檔案")
                self.send_json(read_notebook(path))
            elif parsed.path == "/api/diff":
                path = (ROOT / query["path"][0]).resolve()
                if HOMEWORK not in path.parents or path.suffix != ".ipynb":
                    raise ValueError("不允許讀取此檔案")
                reference = reference_notebook(path.relative_to(HOMEWORK).parts[0])
                if reference is None:
                    raise ValueError("找不到唯一的作業說明 notebook")
                if path == reference:
                    raise ValueError("作業說明不能與自己比對")
                self.send_json(notebook_diff(reference, path))
            else:
                self.send_json({"error": "找不到路徑"}, HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        if self.path != "/api/score":
            self.send_json({"error": "找不到路徑"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            self.send_json(save_grade(request["week"], request["student_id"], request["score"], request.get("note", "")))
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        pass


def self_test() -> None:
    assert validate_score("87.5") == "87.5"
    try:
        validate_score("101")
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range score accepted")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "docs").mkdir()
        (root / "docs/26_pattern-recognition_students-list.csv").write_text("姓名,學號,成績\n甲,D1234567,\n", encoding="utf-8")
        assert save_grade("week", "D1234567", "80", "很好", root) == {"score": "80", "note": "很好"}
        assert load_grades("week", root) == {"D1234567": {"score": "80", "note": "很好"}}
        homework = root / "homework/week"
        homework.mkdir(parents=True)
        reference = homework / "week_title.ipynb"
        submission = homework / "D1234567.ipynb"
        reference.write_text(json.dumps({"cells": [{"cell_type": "code", "source": "a\nb\nc"}]}), encoding="utf-8")
        submission.write_text(json.dumps({"cells": [{"cell_type": "code", "source": "a\nx\nc\nd"}]}), encoding="utf-8")
        assert reference_notebook("week", root / "homework") == reference
        diff = notebook_diff(reference, submission, root)
        assert diff["changes"] == 2
        assert any(row.get("student", {}).get("text") == "x" for row in cast(list[dict[str, object]], diff["rows"]))


def main() -> None:
    global ROOT, HOMEWORK, ROSTER_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-root", type=Path, required=True, help="課程資料根目錄")
    parser.add_argument("--roster", type=Path, default=ROSTER_PATH, help="相對於課程根目錄的名冊 CSV")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    ROOT = args.course_root.resolve()
    HOMEWORK = ROOT / "homework"
    ROSTER_PATH = args.roster
    if args.roster.is_absolute() or not (ROOT / args.roster).resolve().is_relative_to(ROOT):
        parser.error("--roster 必須是課程根目錄內的相對路徑")
    if not HOMEWORK.is_dir() or not (ROOT / ROSTER_PATH).is_file():
        parser.error("課程根目錄須包含 homework/ 與指定的名冊 CSV")
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Notebook Grader: http://127.0.0.1:8000", flush=True)
    webbrowser.open("http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
