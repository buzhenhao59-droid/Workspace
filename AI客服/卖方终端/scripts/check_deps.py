import sys

# 获取 Python site-packages 路径的可靠方式
site_packages = next((p for p in sys.path if 'site-packages' in p), None)
if site_packages:
    sys.path.append(site_packages)

try:
    import flask
    print("[OK] Flask installed")
except ImportError as e:
    print("[FAIL] Flask:", e)

try:
    import neo4j
    print("[OK] Neo4j installed")
except ImportError as e:
    print("[FAIL] Neo4j:", e)

try:
    import requests
    print("[OK] Requests installed")
except ImportError as e:
    print("[FAIL] Requests:", e)

print("\nAll dependency checks completed!")
