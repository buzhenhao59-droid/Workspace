import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('ENVIRONMENT', 'production')

try:
    import db
    funcs = [f for f in dir(db) if 'init_enterprise' in f or 'audit' in f or 'notification' in f or 'advanced_stats' in f or 'system_setting' in f]
    print('db.py OK')
    print('Enterprise functions:', funcs)
except Exception as e:
    print('ERROR db.py:', e)
    import traceback
    traceback.print_exc()

try:
    import main as main_mod
    print('main.py OK - imported successfully, routes count:', len([x for x in dir(main_mod) if not x.startswith('_')]))
except Exception as e:
    print('ERROR main.py:', e)
    import traceback
    traceback.print_exc()
