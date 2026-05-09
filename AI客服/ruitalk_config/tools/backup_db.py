#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库备份脚本 - 支持 SQLite、MySQL、PostgreSQL、Neo4j
自动备份到 ./backups 目录，保留最近 N 份

特性:
- 支持 SQLite / MySQL / PostgreSQL / Neo4j 全量备份
- 自动压缩（zip）、校验（SHA256）
- 备份失败自动上报 Sentry APM
- 可选邮件通知（配置 SMTP 后启用）
- 自动清理旧备份（保留最近 N 份）
- 支持定时任务模式（--cron）

用法:
    python backup_db.py                    # 全量备份（交互）
    python backup_db.py --seller           # 仅备份卖方
    python backup_db.py --buyer            # 仅备份买方
    python backup_db.py --retention 30     # 保留 30 份
    python backup_db.py --compress         # 压缩备份
    python backup_db.py --list             # 列出已有备份
    python backup_db.py --restore <file>   # 恢复指定备份
    python backup_db.py --cron             # 定时任务模式（静默，仅失败时输出）
"""
from __future__ import annotations

import os
import sys
import sqlite3
import shutil
import hashlib
import json
import subprocess
import argparse
import zipfile
import logging
from pathlib import Path
from datetime import datetime

# ===== 获取项目根目录（此文件位于 ruitalk_config/tools/）=====
_SCRIPT_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _SCRIPT_DIR                  # ruitalk_config/tools/
_CONFIG_DIR = _TOOLS_DIR.parent            # ruitalk_config/
_PROJECT_ROOT = _CONFIG_DIR.parent         # 项目根目录

_UNIFIED_CONFIG = _CONFIG_DIR / ".env.master"
if _UNIFIED_CONFIG.exists():
    for line in _UNIFIED_CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

# ===== Sentry APM 初始化 =====
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
_sentry_initialized = False
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            release=os.getenv("APP_VERSION", "ruitalk-backup-1.0.0"),
            max_breadcrumbs=10,
        )
        _sentry_initialized = True
        print(f"[Sentry] APM 已接入")
    except Exception as e:
        print(f"[Sentry] 初始化失败: {e}")

# ===== 日志配置 =====
_log_format = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=_log_format, datefmt="%Y-%m-%d %H:%M:%S")
_logger = logging.getLogger("backup")


PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(_PROJECT_ROOT)))
BACKUP_DIR = PROJECT_ROOT / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

RETENTION = 30  # 保留份数


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _compress_backup(src_path: Path, name: str) -> Path | None:
    """将备份文件压缩为 zip"""
    zip_path = BACKUP_DIR / f"{name}_{_stamp()}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src_path, arcname=src_path.name)
        size_kb = zip_path.stat().st_size / 1024
        print(f"  压缩完成: {zip_path.name} ({size_kb:.1f} KB)")
        # 删原文件
        src_path.unlink(missing_ok=True)
        return zip_path
    except Exception as e:
        print(f"  压缩失败: {e}，保留原文件")
        return src_path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _backup_sqlite(db_path: Path, name: str, compress: bool = False) -> dict:
    """备份 SQLite 数据库"""
    result = {"name": name, "ok": False, "path": None, "size_kb": 0, "sha12": ""}

    if not db_path.exists():
        print(f"  [SKIP] 文件不存在: {db_path}")
        return result

    ts = _stamp()
    bak_path = BACKUP_DIR / f"{name}_{ts}.db"

    # 使用迭代复制（大文件友好）
    shutil.copy2(db_path, bak_path)

    if compress:
        bak_path = _compress_backup(bak_path, name) or bak_path

    size_kb = bak_path.stat().st_size / 1024
    sha12 = _sha256(bak_path)

    # 写 metadata
    meta = {
        "name": name,
        "original": str(db_path),
        "backup": str(bak_path),
        "size_kb": round(size_kb, 1),
        "sha12": sha12,
        "created_at": datetime.now().isoformat(),
    }
    meta_path = bak_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  [OK] {name}: {bak_path.name} ({size_kb:.1f} KB, sha={sha12})")
    result = {"name": name, "ok": True, "path": str(bak_path), "size_kb": size_kb, "sha12": sha12}
    return result


def _backup_mysql(config: dict, name: str) -> dict:
    """备份 MySQL 数据库"""
    result = {"name": name, "ok": False, "path": None, "size_kb": 0, "sha12": ""}

    host = config.get("host", "localhost")
    port = config.get("port", 3306)
    user = config.get("user", "root")
    password = config.get("password", "")
    database = config.get("database", "shop_manager")

    dump_path = BACKUP_DIR / f"{name}_{_stamp()}.sql"

    cmd = [
        "mysqldump",
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        f"--password={password}",
        "--single-transaction",
        "--quick",
        "--lock-tables=False",
        "--routines",
        "--triggers",
        database,
    ]

    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, check=True)
    except FileNotFoundError:
        print(f"  [SKIP] mysqldump 未安装（跳过 MySQL 备份）")
        return result
    except subprocess.CalledProcessError as e:
        print(f"  [FAIL] mysqldump 失败: {e}")
        return result

    size_kb = dump_path.stat().st_size / 1024
    sha12 = _sha256(dump_path)
    print(f"  [OK] {name}: {dump_path.name} ({size_kb:.1f} KB, sha={sha12})")
    return {"name": name, "ok": True, "path": str(dump_path), "size_kb": size_kb, "sha12": sha12}


def _backup_postgres(config: dict, name: str) -> dict:
    """备份 PostgreSQL 数据库"""
    result = {"name": name, "ok": False, "path": None, "size_kb": 0, "sha12": ""}

    host = config.get("host", "localhost")
    port = config.get("port", 5432)
    user = config.get("user", "gold_cs")
    password = config.get("password", "")
    database = config.get("database", "gold_cs")

    env = {**os.environ, "PGPASSWORD": password}
    dump_path = BACKUP_DIR / f"{name}_{_stamp()}.dump"

    cmd = ["pg_dump", "--host=" + host, "--port=" + str(port),
           "--user=" + user, "--dbname=" + database, "--format=custom", "--file=" + str(dump_path)]

    try:
        subprocess.run(cmd, env=env, check=True)
    except FileNotFoundError:
        print(f"  [SKIP] pg_dump 未安装（跳过 PostgreSQL 备份）")
        return result
    except subprocess.CalledProcessError as e:
        print(f"  [FAIL] pg_dump 失败: {e}")
        return result

    size_kb = dump_path.stat().st_size / 1024
    sha12 = _sha256(dump_path)
    print(f"  [OK] {name}: {dump_path.name} ({size_kb:.1f} KB, sha={sha12})")
    return {"name": name, "ok": True, "path": str(dump_path), "size_kb": size_kb, "sha12": sha12}


def _backup_neo4j(uri: str, user: str, password: str, name: str) -> dict:
    """导出 Neo4j 所有数据为 JSON"""
    result = {"name": name, "ok": False, "path": None, "size_kb": 0, "sha12": ""}

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print(f"  [SKIP] neo4j 模块未安装，跳过 Neo4j 备份")
        return result

    dump_path = BACKUP_DIR / f"{name}_{_stamp()}.json"

    try:
        drv = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=10)
        with drv.session() as session:
            nodes_data = {}
            # 导出主要节点类型
            for label in ["Customer", "Order", "Product"]:
                r = session.run(f"MATCH (n:{label}) RETURN n LIMIT 10000")
                nodes_data[label] = [dict(row["n"]) for row in r]

        drv.close()

        # 写 JSON（不导出关系，JSON 只用于快速参考）
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(nodes_data, f, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        print(f"  [FAIL] Neo4j 导出失败: {e}，跳过")
        return result

    size_kb = dump_path.stat().st_size / 1024
    sha12 = _sha256(dump_path)
    print(f"  [OK] {name}: {dump_path.name} ({size_kb:.1f} KB, sha={sha12})")
    return {"name": name, "ok": True, "path": str(dump_path), "size_kb": size_kb, "sha12": sha12}


def _cleanup_old_backups(retention: int):
    """清理旧备份"""
    files = sorted(
        BACKUP_DIR.glob("*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    files += sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    files += sorted(BACKUP_DIR.glob("*.sql"), key=lambda p: p.stat().st_mtime, reverse=True)
    files += sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    files += sorted(BACKUP_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    kept = set(f.name for f in files[:retention])
    removed = 0
    for f in files[retention:]:
        # 不删除 meta.json
        if f.suffix == ".meta.json":
            continue
        f.unlink(missing_ok=True)
        removed += 1

    if removed > 0:
        print(f"  清理完成: 删除 {removed} 份旧备份")


def _list_backups():
    """列出所有备份"""
    print(f"\n--- 备份列表 ({BACKUP_DIR}) ---")
    files = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("  无备份")
        return

    for f in files[:60]:
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {mtime}  {size_kb:>8.1f} KB  {f.name}")


def _restore_sqlite(backup_path: Path, target_path: Path):
    """恢复 SQLite 备份"""
    if not backup_path.exists():
        print(f"[ERROR] 备份文件不存在: {backup_path}")
        return False
    shutil.copy2(backup_path, target_path)
    print(f"[OK] 已恢复到: {target_path}")
    return True


def _load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    parser = argparse.ArgumentParser(description="Ruitalk 数据库备份工具")
    parser.add_argument("--seller", action="store_true", help="仅备份卖方")
    parser.add_argument("--buyer", action="store_true", help="仅备份买方")
    parser.add_argument("--retention", type=int, default=RETENTION, help=f"保留份数（默认 {RETENTION}）")
    parser.add_argument("--compress", action="store_true", help="压缩备份")
    parser.add_argument("--list", action="store_true", help="列出已有备份")
    parser.add_argument("--restore", type=str, help="恢复指定备份文件")
    parser.add_argument("--cron", action="store_true", help="定时任务模式（静默，失败才输出）")
    parser.add_argument("--smtp", action="store_true", help="备份成功后发送邮件通知")
    args = parser.parse_args()

    # 定时任务模式：静默
    if args.cron:
        logging.getLogger().setLevel(logging.WARNING)
    _is_cron = args.cron

    if args.list:
        _list_backups()
        return 0

    # 恢复
    if args.restore:
        bak = Path(args.restore)
        targets = [
            PROJECT_ROOT / "卖方终端" / "data" / "gold_customer.db",
            PROJECT_ROOT / "AI客服买方系统" / "data" / "gold_customer.db",
        ]
        for t in targets:
            if t.exists():
                _restore_sqlite(bak, t)
                return 0
        print("[ERROR] 未找到可恢复的目标数据库")
        return 1

    # ===== 加载统一配置（用于 Neo4j 等）=====
    env = _load_env(_UNIFIED_CONFIG)

    print("=" * 60)
    print(f"  Ruitalk 数据库备份  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  备份目录: {BACKUP_DIR}")
    print(f"  保留份数: {args.retention}")
    print(f"  压缩: {'是' if args.compress else '否'}")
    print()

    results = []

    # ---------- SQLite gold_customer.db ----------
    if not args.buyer:
        # 卖方
        seller_db = PROJECT_ROOT / "卖方终端" / "data" / "gold_customer.db"
        if seller_db.exists():
            r = _backup_sqlite(seller_db, "seller_gold_customer", compress=args.compress)
            results.append(r)
        else:
            print(f"  [SKIP] 卖方 gold_customer.db 不存在")

    # ---------- 买方 SQLite ----------
    if not args.seller:
        buyer_db = PROJECT_ROOT / "AI客服买方系统" / "data" / "gold_customer.db"
        if buyer_db.exists():
            r = _backup_sqlite(buyer_db, "buyer_gold_customer", compress=args.compress)
            results.append(r)

        # 买方可能共用卖方路径
        if not buyer_db.exists():
            env = _load_env(PROJECT_ROOT / "AI客服买方系统" / ".env")
            shared = env.get("SHARED_DB_PATH", "")
            if shared and Path(shared).exists():
                r = _backup_sqlite(Path(shared), "shared_gold_customer", compress=args.compress)
                results.append(r)

    # ---------- MySQL 店铺管理 ----------
    if not args.buyer:
        env = _load_env(PROJECT_ROOT / "卖方终端" / ".env")
        mysql_cfg = {
            "host": env.get("MYSQL_HOST", "localhost"),
            "port": int(env.get("MYSQL_PORT", 3306)),
            "user": env.get("MYSQL_USER", "root"),
            "password": env.get("MYSQL_PASSWORD", ""),
            "database": env.get("MYSQL_DATABASE", "shop_manager"),
        }
        if mysql_cfg["password"]:
            r = _backup_mysql(mysql_cfg, "seller_mysql_shop")
            results.append(r)

    # ---------- PostgreSQL ----------
    if not args.buyer:
        pg_cfg = {
            "host": env.get("POSTGRES_HOST", "localhost"),
            "port": int(env.get("POSTGRES_PORT", 5432)),
            "user": env.get("POSTGRES_USER", "gold_cs"),
            "password": env.get("POSTGRES_PASSWORD", ""),
            "database": env.get("POSTGRES_DATABASE", "gold_cs"),
        }
        if pg_cfg["password"]:
            r = _backup_postgres(pg_cfg, "seller_postgres")
            results.append(r)

    # ---------- Neo4j ----------
    if not args.buyer:
        neo4j_cfg = {
            "uri": env.get("NEO4J_URI", ""),
            "user": env.get("NEO4J_USER", ""),
            "password": env.get("NEO4J_PASSWORD", ""),
        }
        if neo4j_cfg["uri"] and neo4j_cfg["password"]:
            r = _backup_neo4j(neo4j_cfg["uri"], neo4j_cfg["user"],
                              neo4j_cfg["password"], "seller_neo4j")
            results.append(r)

    # ---------- 清理旧备份 ----------
    _cleanup_old_backups(args.retention)

    # ---------- 汇总 ----------
    ok_count = sum(1 for r in results if r["ok"])
    total_size = sum(r["size_kb"] for r in results if r["ok"])

    # 发送邮件通知（可选）
    _send_backup_notification(ok_count, len(results), total_size, args.smtp)

    # 发送告警（钉钉/飞书/邮件任意一个成功即可）
    if ok_count < len(results):
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from alert import alert_error, alert_warning
            failed = [r["name"] for r in results if not r["ok"]]
            alert_warning(
                title="数据库备份部分失败",
                content=f"备份 {ok_count}/{len(results)} 成功，以下数据库备份失败: {', '.join(failed)}",
                source="Ruitalk-Backup",
                extra={"成功": f"{ok_count}/{len(results)}", "总大小": f"{total_size:.1f} KB"},
            )
        except Exception:
            pass
    elif ok_count == len(results) and ok_count > 0:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from alert import alert_info
            alert_info(
                title="数据库备份成功",
                content=f"备份 {ok_count}/{len(results)} 全部成功，总大小 {total_size:.1f} KB",
                source="Ruitalk-Backup",
            )
        except Exception:
            pass

    # Sentry 备份失败上报
    if ok_count < len(results) and _sentry_initialized:
        try:
            import sentry_sdk
            failed = [r["name"] for r in results if not r["ok"]]
            sentry_sdk.capture_message(
                f"数据库备份部分失败: {ok_count}/{len(results)} 成功",
                level="warning",
                extras={"failed_backups": failed},
            )
        except Exception:
            pass

    print()
    print("=" * 60)
    status = "成功" if ok_count == len(results) else "部分成功"
    print(f"  备份 {status}: {ok_count}/{len(results)} 成功, 共 {total_size:.1f} KB")
    print(f"  备份目录: {BACKUP_DIR}")
    print("=" * 60)

    # 备份失败 → 返回非0退出码（供定时任务检测）
    if ok_count == 0 and results:
        if _sentry_initialized:
            try:
                import sentry_sdk
                sentry_sdk.capture_message(
                    f"数据库备份全部失败！",
                    level="error",
                )
            except Exception:
                pass
        return 1
    return 0


def _send_backup_notification(ok_count: int, total: int, total_size_kb: float, force: bool = False):
    """发送邮件通知（仅在有配置时生效）"""
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host and not force:
        return

    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_tls = os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    notify_to = os.getenv("BACKUP_NOTIFY_EMAIL", "").strip()
    notify_from = os.getenv("SMTP_FROM", smtp_user)

    if not notify_to:
        return

    subject = f"[Ruitalk] 备份{'成功' if ok_count == total else '失败'}"
    if ok_count == total:
        body = f"数据库备份成功\n\n备份统计：\n  - 成功: {ok_count}/{total}\n  - 总大小: {total_size_kb:.1f} KB\n  - 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n  - 备份目录: {BACKUP_DIR}"
    else:
        body = f"数据库备份部分失败！\n\n备份统计：\n  - 成功: {ok_count}/{total}\n  - 总大小: {total_size_kb:.1f} KB\n  - 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n  - 备份目录: {BACKUP_DIR}\n\n请立即检查系统！"

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg["From"] = notify_from
        msg["To"] = notify_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print(f"  [邮件] 通知已发送至 {notify_to}")
    except Exception as e:
        print(f"  [邮件] 发送失败: {e}")


if __name__ == "__main__":
    sys.exit(main())
