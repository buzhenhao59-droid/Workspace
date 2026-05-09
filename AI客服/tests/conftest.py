# -*- coding: utf-8 -*-
"""
项目统一测试配置
"""
import sys, os
# 根据测试文件来源动态添加路径
_this_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_this_dir)  # 项目根目录
_seller_backend = os.path.join(_root, "卖方终端", "backend")
_buyer_backend = os.path.join(_root, "AI客服买方系统", "backend")
_tools_dir = os.path.join(_root, "ruitalk_config", "tools")

def pytest_configure(config):
    """根据测试文件所在目录自动设置 sys.path"""
    pass  # 各测试文件内部已设置 sys.path
