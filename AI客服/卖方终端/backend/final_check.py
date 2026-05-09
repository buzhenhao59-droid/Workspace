# -*- coding: utf-8 -*-
"""Final system health check"""
import requests

print("=== Ruitalk System Final Check ===")

# Check homepage
r = requests.get("http://127.0.0.1:8000/", timeout=5)
status = "OK" if r.status_code == 200 else "FAIL"
print(f"Homepage: {r.status_code} - {status}")

# Check admin pages
pages = ["/admin/login.html", "/admin/dashboard.html", "/admin/pre-sale-notes.html", "/admin/after-sales.html"]
for p in pages:
    r = requests.get(f"http://127.0.0.1:8000{p}", timeout=5)
    status = "OK" if r.status_code == 200 else "FAIL"
    print(f"{p}: {r.status_code} - {status}")

# Check API docs
r = requests.get("http://127.0.0.1:8000/docs", timeout=5)
status = "OK" if r.status_code == 200 else "FAIL"
print(f"/docs: {r.status_code} - {status}")

# Quick login test
r = requests.post("http://127.0.0.1:8000/api/admin/login", json={"username":"admin","password":"123456789"}, timeout=5)
status = "OK" if r.status_code == 200 else "FAIL"
print(f"Login API: {r.status_code} - {status}")

print("\n=== All checks completed ===")
