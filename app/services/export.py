"""Exportación de informes a Markdown, CSV y HTML imprimible.

No se usa ninguna dependencia de conversión: el subconjunto de Markdown que genera
el informe (títulos, listas, tablas, citas y énfasis) se convierte con reglas
explícitas. El HTML resultante es autocontenido y apto para imprimir a PDF desde el
navegador; el PDF no se genera en el servidor.
"""

from __future__ import annotations

import csv
import html
import io
import re
from typing import Any, Dict, Iterable, List

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}" rel="noopener">{m.group(1)}</a>', escaped)
    escaped = BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = ITALIC.sub(r"<em>\1</em>", escaped)
    escaped = INLINE_CODE.sub(r"<code>\1</code>", escaped)
    return escaped


def markdown_to_html(markdown: str, *, title: str = "Informe") -> str:
    lines = markdown.splitlines()
    body: List[str] = []
    index = 0
    in_list = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if in_list:
                body.append("</ul>")
                in_list = False
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and set(lines[index + 1].strip().replace("|", "").replace("-", "").replace(" ", "")) == set():
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: List[List[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            body.append("<table><thead><tr>")
            body.extend(f"<th>{_inline(cell)}</th>" for cell in header)
            body.append("</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
            body.append("</tbody></table>")
            continue
        if stripped.startswith("#"):
            level = min(6, len(stripped) - len(stripped.lstrip("#")))
            text = stripped[level:].strip()
            body.append(f"<h{level}>{_inline(text)}</h{level}>")
            index += 1
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(stripped[2:])}</li>")
            index += 1
            continue
        if stripped.startswith(">"):
            body.append(f"<blockquote>{_inline(stripped.lstrip('> '))}</blockquote>")
            index += 1
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        body.append(f"<p>{_inline(stripped)}</p>")
        index += 1
    if in_list:
        body.append("</ul>")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 15px/1.6 -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 860px;
         margin: 40px auto; padding: 0 20px; color: #12161f; }}
  h1 {{ font-size: 26px; border-bottom: 2px solid #12161f; padding-bottom: 10px; }}
  h2 {{ font-size: 19px; margin-top: 32px; color: #1b2436; }}
  h3 {{ font-size: 16px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 13px; }}
  th, td {{ border: 1px solid #cfd6e4; padding: 6px 8px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f2f5fa; }}
  blockquote {{ border-left: 3px solid #7b8794; margin: 16px 0; padding: 6px 14px; color: #414b5a; }}
  code {{ background: #f2f5fa; padding: 1px 4px; border-radius: 3px; }}
  @media print {{ body {{ margin: 0; }} h2 {{ break-after: avoid; }} table {{ break-inside: avoid; }} }}
</style>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""


def metrics_csv(rows: Iterable[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "label", "value", "unit", "period_end", "provenance", "source_url"])
    for row in rows:
        writer.writerow(
            [
                row.get("key", ""),
                row.get("label", ""),
                "" if row.get("value") is None else row.get("value"),
                row.get("unit", ""),
                row.get("period_end") or "",
                row.get("provenance") or "",
                row.get("source_url") or "",
            ]
        )
    return buffer.getvalue()


def scenarios_csv(rows: Iterable[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["scenario", "growth_rate", "discount_rate", "terminal_growth", "per_share_value", "enterprise_value", "equity_value"]
    )
    for row in rows:
        growth = row.get("growth_rates") or [""]
        writer.writerow(
            [
                row.get("name", ""),
                growth[0] if growth else "",
                row.get("discount_rate", ""),
                row.get("terminal_growth", ""),
                row.get("per_share_value", ""),
                row.get("enterprise_value", ""),
                row.get("equity_value", ""),
            ]
        )
    return buffer.getvalue()


def report_csv(payload: Dict[str, Any]) -> str:
    parts: List[str] = []
    metrics = payload.get("metrics") or []
    scenarios = payload.get("scenarios") or []
    if metrics:
        parts.append("# Métricas")
        parts.append(metrics_csv(metrics))
    if scenarios:
        parts.append("# Escenarios")
        parts.append(scenarios_csv(scenarios))
    if not parts:
        parts.append("# Sin datos tabulares para este informe")
    return "\n".join(parts)
