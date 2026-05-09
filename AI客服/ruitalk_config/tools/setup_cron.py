# -*- coding: utf-8 -*-
"""
Ruitalk 定时任务安装脚本（Windows）
在 Windows 任务计划程序中注册备份和监控任务

用法:
    python setup_cron.py                    # 安装所有任务
    python setup_cron.py --list            # 查看已注册任务
    python setup_cron.py --uninstall        # 卸载所有任务
"""
import subprocess
import sys
import argparse
from pathlib import Path

# 自动计算项目根目录（此文件位于 ruitalk_config/tools/）
_SCRIPT_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _SCRIPT_DIR                         # ruitalk_config/tools/
CONFIG_DIR = _TOOLS_DIR.parent                    # ruitalk_config/
PROJECT_ROOT = CONFIG_DIR.parent                  # 项目根目录
BACKUP_SCRIPT = PROJECT_ROOT / "ruitalk_config" / "tools" / "backup_db.py"
ALERT_SCRIPT = PROJECT_ROOT / "ruitalk_config" / "tools" / "alert.py"
VENV_PYTHON = PROJECT_ROOT / "卖方终端" / ".venv" / "Scripts" / "python.exe"

TASKS = {
    "Ruitalk_DBBackup_Hourly": {
        "description": "每小时数据库备份（Ruitalk）",
        "trigger": "HOURLY",
        "script": BACKUP_SCRIPT,
        "args": "--compress --cron",
    },
    "Ruitalk_DBBackup_Daily": {
        "description": "每日凌晨3点完整备份（Ruitalk）",
        "trigger": "DAILY",   # /st 03:00
        "start_time": "03:00",
        "script": BACKUP_SCRIPT,
        "args": "--compress --cron --retention 90",
    },
}


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def install_task(name: str, cfg: dict):
    """注册单个任务"""
    script = cfg["script"]
    if not script.exists():
        print(f"  [SKIP] 脚本不存在: {script}")
        return False

    python = str(VENV_PYTHON)
    trigger = cfg.get("trigger", "DAILY")
    start_time = cfg.get("start_time", "02:00")
    desc = cfg.get("description", "")
    args_str = cfg.get("args", "")

    # 先删除旧任务
    _run(["schtasks", "/Delete", "/TN", name, "/F"])

    # 构建 schtasks 命令
    cmd = [
        "schtasks", "/Create",
        "/TN", name,
        "/TR", f'"{python}" "{script}" {args_str}',
        "/SC", trigger,
        "/ST", start_time,
        "/F",
    ]

    result = _run(cmd)
    if result.returncode == 0:
        print(f"  [OK] 已注册: {name} ({desc})")
        return True
    print(f"  [FAIL] 注册失败: {name}")
    print(f"         {result.stderr.strip()}")
    return False


def list_tasks():
    """列出已注册的 Ruitalk 任务"""
    result = _run(["schtasks"])
    ruitalk_tasks = [line for line in result.stdout.splitlines() if "Ruitalk" in line]
    if ruitalk_tasks:
        print("已注册的 Ruitalk 定时任务:")
        for t in ruitalk_tasks:
            print(f"  {t.strip()}")
    else:
        print("未找到已注册的 Ruitalk 定时任务。")


def uninstall_tasks():
    """卸载所有 Ruitalk 定时任务"""
    for name in TASKS:
        result = _run(["schtasks", "/Delete", "/TN", name, "/F"])
        if result.returncode == 0:
            print(f"  [OK] 已删除: {name}")
        else:
            print(f"  [SKIP] 未找到或删除失败: {name}")


def main():
    parser = argparse.ArgumentParser(description="Ruitalk 定时任务安装")
    parser.add_argument("--list", action="store_true", help="列出已注册任务")
    parser.add_argument("--uninstall", action="store_true", help="卸载所有任务")
    args = parser.parse_args()

    if args.list:
        list_tasks()
        return 0

    if args.uninstall:
        print("卸载 Ruitalk 定时任务...")
        uninstall_tasks()
        return 0

    # 检查 Python 虚拟环境
    if not VENV_PYTHON.exists():
        print(f"[WARN] 虚拟环境 Python 不存在: {VENV_PYTHON}")
        print("       将使用系统 Python（请确保已安装所需依赖）")
        python = "python"
    else:
        python = str(VENV_PYTHON)
        print(f"使用 Python: {python}")

    print("=" * 60)
    print("  Ruitalk 定时任务注册")
    print("=" * 60)
    print(f"  备份脚本: {BACKUP_SCRIPT}")
    print(f"  告警脚本: {ALERT_SCRIPT}")
    print()

    ok = 0
    for name, cfg in TASKS.items():
        if install_task(name, cfg):
            ok += 1

    print()
    print("=" * 60)
    print(f"  注册完成: {ok}/{len(TASKS)} 成功")
    print()
    print("  定时任务说明:")
    print("  - Ruitalk_DBBackup_Hourly: 每小时备份（压缩，保留30份）")
    print("  - Ruitalk_DBBackup_Daily:  每天凌晨3点完整备份（保留90份）")
    print()
    print("  查看任务: python setup_cron.py --list")
    print("  卸载任务: python setup_cron.py --uninstall")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
