#!/usr/bin/env python3
import re, subprocess
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
html_path = _SCRIPT_DIR / 'pre-sale-notes.html'

with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
for i, js in enumerate(scripts):
    print("Script %d (%d chars):" % (i, len(js)), end=" ")
    try:
        r = subprocess.run(['node', '--check'], input=js.encode(), capture_output=True, timeout=5)
        if r.returncode:
            stderr = r.stderr.decode()
            print("ERROR")
            for le in stderr.split('\n'):
                if le.strip() and ('error' in le.lower() or 'line' in le.lower() or 'SyntaxError' in le):
                    print("  " + le.strip())
        else:
            print("OK")
    except Exception as e:
        print("Node not available: " + str(e))
