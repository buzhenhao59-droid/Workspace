#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Ruitalk 项目一键打包脚本
========================
将当前项目打包为 Ruitalk_Seller_System.zip，
自动排除 __pycache__、.venv、.env、node_modules、前端 node 项目 等无用文件。
压缩包可直接发给客户使用。

用法：
    双击运行 或 python build_pack.py
"""

import os
import sys
import zipfile
from pathlib import Path

# ================================================================
#  配置
# ================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ZIP = SCRIPT_DIR / "Ruitalk_Seller_System.zip"

# 黑名单 — 必须排除的目录名（任意层级出现即跳过整个子树）
EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".git",
    ".idea",
    ".vscode",
    ".svn",
    ".hg",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".npm",
    ".yarn",
    "bower_components",
    "dist",
    "build",
}

# 黑名单 — 从项目根目录出发必须跳过的完整路径（相对于项目根）
EXCLUDE_REL_PATHS = {
    "frontend",               # 34k+ 文件的 React 项目，不是卖方系统前端
}

# 黑名单 — 必须排除的单个文件（精确匹配文件名）
EXCLUDE_FILE_NAMES = {
    ".env",                   # 本地真实配置，绝对不能打包
}

# 黑名单 — 必须排除的文件扩展名
EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".pid",
    ".lock",
    ".map",
}

# 白名单 — 虽然名字在黑名单里，但必须保留
KEEP_FILE_NAMES = {
    ".env.example",           # 客户需要这个模板
}


def should_skip_dir(current_rel: Path, dirname: str) -> bool:
    """判断目录是否应该跳过"""
    name_lower = dirname.lower()

    # 1. 按目录名跳过
    if name_lower in {d.lower() for d in EXCLUDE_DIR_NAMES}:
        return True

    # 2. 按相对路径跳过（精确匹配根目录下的特定目录）
    if str(current_rel) == "." and dirname in EXCLUDE_REL_PATHS:
        return True

    return False


def should_exclude_file(name: str) -> bool:
    """判断文件名是否应该排除"""
    # 白名单优先
    if name in KEEP_FILE_NAMES:
        return False
    # 黑名单文件名
    if name in EXCLUDE_FILE_NAMES:
        return True
    # 黑名单扩展名
    ext = Path(name).suffix.lower()
    if ext in EXCLUDE_EXTS:
        return True
    return False


def pack_project() -> int:
    """打包项目，返回打包的文件数"""
    root = SCRIPT_DIR
    total = 0
    skipped_dirs = 0
    skipped_files = 0

    print("=" * 55)
    print("  Ruitalk 项目打包工具")
    print("  输出: " + OUTPUT_ZIP.name)
    print("=" * 55)
    print()
    print("  正在扫描 " + str(root) + " ...")
    print()

    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()
        print("  [清理] 已删除旧的压缩包")
        print()

    with zipfile.ZipFile(
        OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            curr = Path(dirpath)
            rel_dir = curr.relative_to(root)

            # 跳过被排除的当前目录
            if curr != root:
                if should_skip_dir(rel_dir.parent, curr.name):
                    skipped_dirs += 1
                    print("  [跳过目录] " + str(rel_dir))
                    dirnames.clear()
                    continue

            # 过滤子目录 - 阻止 os.walk 进入黑名单目录
            i = 0
            while i < len(dirnames):
                if should_skip_dir(rel_dir, dirnames[i]):
                    skipped_dirs += 1
                    child_rel = rel_dir / dirnames[i] if str(rel_dir) != "." else Path(dirnames[i])
                    print("  [跳过目录] " + str(child_rel))
                    dirnames.pop(i)
                else:
                    i += 1

            # 处理文件
            for fname in filenames:
                if should_exclude_file(fname):
                    skipped_files += 1
                    file_rel = rel_dir / fname if str(rel_dir) != "." else Path(fname)
                    if skipped_files <= 20:  # 只显示前 20 个跳过文件，避免刷屏
                        print("  [跳过文件] " + str(file_rel))
                    continue

                # 写入 zip
                fpath = curr / fname
                arcname = fpath.relative_to(root).as_posix()
                # 获取文件时间戳，修正 <1980 的问题
                st = fpath.stat()
                ts = int(st.st_mtime)
                from datetime import datetime as _dt
                dt = _dt.fromtimestamp(ts)
                if dt.year < 1980:
                    # 强制设为 1980-01-01
                    zi = zipfile.ZipInfo(arcname, (1980, 1, 1, 0, 0, 0))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(zi, fpath.read_bytes())
                    print("  [修正时间戳] " + str(arcname) + " (原: " + str(dt) + ")")
                else:
                    zf.write(fpath, arcname)
                total += 1

    # 统计
    zip_size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print()
    print("=" * 55)
    print("  [完成] 打包完成！")
    print("  打包文件数: " + str(total))
    print("  跳过目录数: " + str(skipped_dirs))
    print("  跳过文件数: " + str(skipped_files))
    print("  压缩包大小: " + "{:.2f}".format(zip_size_mb) + " MB")
    print("  输出路径: " + str(OUTPUT_ZIP))
    print("=" * 55)
    print()
    print("  压缩包 " + OUTPUT_ZIP.name + " 可直接发给客户使用。")
    print("  客户收到后: 解压 -> 复制 .env.example 为 .env")
    print("             -> 安装依赖 -> 双击启动")
    print()

    return total


def main():
    try:
        total = pack_project()
        if total == 0:
            print("[WARN] 压缩包为空，请检查项目文件。")
            sys.exit(1)
    except UnicodeEncodeError:
        # Windows GBK 控制台编码兼容
        print()
        print("[ERROR] 打包失败：控制台编码不支持某些字符。")
        print("  解决办法：在 CMD 中执行  chcp 65001  后重试。")
        print("  或直接运行: python build_pack.py > pack_log.txt")
        sys.exit(1)
    except Exception as e:
        msg = str(e)
        if "'gbk'" in msg or "'cp936'" in msg:
            print("\n[ERROR] 打包失败：控制台编码不支持某些字符。")
            print("  解决办法：在 CMD 中执行  chcp 65001  后重试。")
        else:
            print("\n[ERROR] 打包失败: " + msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
