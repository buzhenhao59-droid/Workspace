# -*- coding: utf-8 -*-
"""
OpenAPI Markdown 文档生成器
将 FastAPI 应用的 OpenAPI schema 自动生成为 Markdown 文档
用于 CI/CD 自动生成和版本化 API 文档

使用方式:
    # 生成 Markdown 文档
    python generate_openapi_docs.py

    # 指定输出路径
    python generate_openapi_docs.py --output docs/api.md

    # 指定服务名和版本
    python generate_openapi_docs.py --service ruitalk-seller --version 1.0.0

CI/CD 集成示例（GitHub Actions）:
    - name: Generate API Docs
      run: python docs/generate_openapi_docs.py --output docs/api/v1.md
"""
import sys
import os
import json
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict, List


def get_openapi_schema(app_or_url: Any) -> dict:
    """
    获取 OpenAPI schema
    支持直接传入 FastAPI app 实例或 URL
    """
    if hasattr(app_or_url, "openapi_schema"):
        # FastAPI app 实例
        return app_or_url.openapi()
    elif isinstance(app_or_url, str) and app_or_url.startswith("http"):
        # URL
        import requests
        resp = requests.get(f"{app_or_url}/openapi.json", timeout=10)
        resp.raise_for_status()
        return resp.json()
    else:
        raise ValueError("请传入 FastAPI app 实例或 URL")


def schema_to_markdown(schema: dict, service_name: str = "Ruitalk API",
                       version: str = "1.0.0",
                       output_path: Optional[str] = None) -> str:
    """将 OpenAPI schema 转换为 Markdown 格式文档"""

    info = schema.get("info", {})
    title = info.get("title", service_name)
    description = info.get("description", "")
    doc_version = info.get("version", version)
    contact = info.get("contact", {})

    servers = schema.get("servers", [])
    security = schema.get("components", {}).get("securitySchemes", {})

    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**版本**: `{doc_version}`  |  **生成时间**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append("")
    if description:
        lines.append(f"{description}")
        lines.append("")
    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"- **服务名称**: {service_name}")
    lines.append(f"- **API 版本**: {doc_version}")
    if contact.get("name"):
        lines.append(f"- **联系人和**: {contact.get('name')}")
    if contact.get("email"):
        lines.append(f"- **联系邮箱**: [{contact.get('email')}](mailto:{contact.get('email')})")
    if contact.get("url"):
        lines.append(f"- **文档地址**: {contact.get('url')}")
    lines.append("")

    # 服务器地址
    if servers:
        lines.append("## 服务器地址")
        lines.append("")
        for s in servers:
            url = s.get("url", "")
            desc = s.get("description", "")
            lines.append(f"- **{desc}**: `{url}`" if desc else f"- `{url}`")
        lines.append("")

    # 安全机制
    if security:
        lines.append("## 认证方式")
        lines.append("")
        for name, scheme in security.items():
            stype = scheme.get("type", "")
            sinfo = scheme.get("description", "")
            lines.append(f"### {name}")
            lines.append(f"- **类型**: {stype}")
            if sinfo:
                lines.append(f"- **说明**: {sinfo}")
            lines.append("")

    # 路径分组
    paths = schema.get("paths", {})
    if not paths:
        lines.append("*暂无 API 路由定义*")
        return "\n".join(lines)

    # 按标签分组
    grouped: Dict[str, List] = {}
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
                continue
            tags = operation.get("tags", ["Other"])
            tag = tags[0]
            if tag not in grouped:
                grouped[tag] = []
            grouped[tag].append((path, method.upper(), operation))

    # 输出每个分组
    lines.append("## API 参考")
    lines.append("")

    for tag, operations in sorted(grouped.items()):
        lines.append(f"### {tag}")
        lines.append("")

        for path, method, op in sorted(operations, key=lambda x: (x[0], x[1])):
            summary = op.get("summary", "")
            desc = op.get("description", "")
            operation_id = op.get("operationId", "")
            deprecated = op.get("deprecated", False)

            # 方法 + 路径
            method_badge = {
                "GET": "![GET](https://img.shields.io/badge/GET-20BFFF?style=flat-square)",
                "POST": "![POST](https://img.shields.io/badge/POST-28A745?style=flat-square)",
                "PUT": "![PUT](https://img.shields.io/badge/PUT-FFC107?style=flat-square)",
                "DELETE": "![DELETE](https://img.shields.io/badge/DELETE-DC3545?style=flat-square)",
                "PATCH": "![PATCH](https://img.shields.io/badge/PATCH-6F42C1?style=flat-square)",
            }.get(method, f"![{method}](https://img.shields.io/badge/{method}-808080?style=flat-square)")

            lines.append(f"#### {method_badge} `{path}`")
            if summary:
                lines.append(f"**{summary}**")
            if desc:
                lines.append(f"{desc}")
            if deprecated:
                lines.append("> **已废弃**")
            lines.append("")
            if operation_id:
                lines.append(f"`OperationId`: `{operation_id}`")
                lines.append("")

            # 请求参数
            params = op.get("parameters", [])
            request_body = op.get("requestBody", {})
            if params or request_body:
                lines.append("**请求参数**")
                lines.append("")
                if params:
                    lines.append("| 参数名 | 位置 | 类型 | 必填 | 说明 |")
                    lines.append("|---|---|---|---|---|")
                    for p in params:
                        name = p.get("name", "")
                        loc = p.get("in", "")
                        required = "是" if p.get("required") else "否"
                        ptype = p.get("schema", {}).get("type", "string")
                        desc = p.get("description", "") or p.get("schema", {}).get("description", "")
                        lines.append(f"| `{name}` | {loc} | {ptype} | {required} | {desc} |")
                    lines.append("")

                if request_body:
                    content = request_body.get("content", {})
                    for ct, ct_schema in content.items():
                        schema_ref = ct_schema.get("schema", {})
                        lines.append(f"**请求体** (`Content-Type: {ct}`)")
                        lines.append("")
                        _render_schema(ct_schema.get("schema", {}), lines, indent=0)

            # 响应
            responses = op.get("responses", {})
            if responses:
                lines.append("**响应**")
                lines.append("")
                for code, resp in responses.get("200", responses.get("201", {})).items() if isinstance(responses.get("200"), dict) else [(k, v) for k, v in responses.items()]:
                    desc = resp.get("description", "")
                    content = resp.get("content", {})
                    lines.append(f"- `{code}`: {desc}")
                    for ct, ct_schema in content.items():
                        lines.append(f"  - Content-Type: {ct}")
                        _render_schema(ct_schema.get("schema", {}), lines, indent=4)
                lines.append("")

            lines.append("---")
            lines.append("")

    # 安全要求
    security_reqs = schema.get("components", {}).get("security", [])
    if security_reqs:
        lines.append("## 安全要求")
        lines.append("")
        lines.append("所有需要认证的接口，请在请求头中添加：")
        lines.append("")
        lines.append("```")
        lines.append("Authorization: Bearer <your-jwt-token>")
        lines.append("```")
        lines.append("")
        for req in security_reqs:
            for name in req.keys():
                lines.append(f"- {name}")
        lines.append("")

    # 全局错误码
    lines.append("## 错误码")
    lines.append("")
    lines.append("所有错误响应格式：")
    lines.append("")
    lines.append("```json")
    lines.append('{')
    lines.append('  "success": false,')
    lines.append('  "error": {')
    lines.append('    "code": "RTK_XXXXX",')
    lines.append('    "message": "人类可读的错误消息",')
    lines.append('    "detail": "详细信息（可选）"')
    lines.append('  }')
    lines.append('}')
    lines.append("```")
    lines.append("")
    lines.append("| 错误码 | HTTP状态 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| RTK_GEN00001 | 500 | 内部服务器错误 |")
    lines.append("| RTK_AUTH00101 | 401 | 未提供认证令牌 |")
    lines.append("| RTK_AUTH00102 | 401 | 认证令牌无效或已过期 |")
    lines.append("| RTK_RATE00201 | 429 | 请求过于频繁 |")
    lines.append("| RTK_PARAM00301 | 400 | 缺少必需参数 |")
    lines.append("| RTK_SESSION00501 | 404 | 会话不存在或已过期 |")
    lines.append("| RTK_AI00601 | 503 | AI 服务暂时不可用 |")
    lines.append("")

    md_content = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(md_content, encoding="utf-8")
        print(f"文档已生成: {output_path}")

    return md_content


def _render_schema(schema: dict, lines: list, indent: int = 0) -> None:
    """渲染 JSON Schema 为 Markdown 表格"""
    if not schema:
        return

    stype = schema.get("type", "object")
    props = schema.get("properties", {})
    required = schema.get("required", [])

    if props:
        lines.append("| 字段 | 类型 | 必填 | 说明 |")
        lines.append("|---|---|---|---|")
        for name, prop in props.items():
            ftype = _format_type(prop.get("type", "any"))
            req = "是" if name in required else "否"
            desc = prop.get("description", "") or schema.get("description", "")
            enum_vals = prop.get("enum", [])
            extra = ""
            if enum_vals:
                extra = f"（可选值: {', '.join(str(v) for v in enum_vals)}）"
            lines.append(f"| `{name}` | {ftype} | {req} | {desc}{extra} |")
    elif stype == "array":
        items = schema.get("items", {})
        lines.append(f"Array<{_format_type(items.get('type', 'any'))}>")
    else:
        example = schema.get("example", "")
        if example:
            lines.append(f"示例值: `{example}`")


def _format_type(t: str) -> str:
    """格式化 JSON Schema 类型"""
    mapping = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
        "null": "null",
    }
    return mapping.get(t, t)


# ============== CLI 入口 ==============
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 OpenAPI Markdown 文档")
    parser.add_argument("--app", type=str, default="",
                        help="FastAPI app 模块名（如 main）或 URL（如 http://localhost:8000）")
    parser.add_argument("--output", type=str, default="docs/api.md",
                        help="输出 Markdown 文件路径")
    parser.add_argument("--service", type=str, default="Ruitalk API",
                        help="服务名称")
    parser.add_argument("--version", type=str, default="1.0.0",
                        help="API 版本")
    parser.add_argument("--url", type=str, default="",
                        help="API 服务的 URL（替代 --app）")
    args = parser.parse_args()

    schema = None

    # 方式1：从 URL 获取
    if args.url:
        import requests
        resp = requests.get(f"{args.url.rstrip('/')}/openapi.json", timeout=10)
        resp.raise_for_status()
        schema = resp.json()
    elif args.app:
        # 方式2：从 Python 模块导入
        try:
            module = __import__(args.app.replace("-", "_"), fromlist=["app"])
            app = getattr(module, "app", None)
            if app:
                schema = get_openapi_schema(app)
            else:
                print(f"错误: 模块 '{args.app}' 中未找到 'app' 对象", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"错误: 无法加载 app: {e}", file=sys.stderr)
            # 尝试从 URL 获取
            fallback_url = "http://127.0.0.1:8000"
            print(f"尝试从 {fallback_url} 获取...", file=sys.stderr)
            try:
                import requests
                resp = requests.get(f"{fallback_url}/openapi.json", timeout=5)
                resp.raise_for_status()
                schema = resp.json()
            except Exception:
                print(f"无法从 {fallback_url} 获取，跳过文档生成", file=sys.stderr)
                print("提示: 请先启动服务，然后运行: python generate_openapi_docs.py --url http://localhost:8000")
                sys.exit(0)

    if schema:
        schema_to_markdown(
            schema,
            service_name=args.service,
            version=args.version,
            output_path=args.output
        )
    else:
        print("未获取到 OpenAPI schema，请检查参数", file=sys.stderr)
        sys.exit(1)
