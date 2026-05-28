"""Report export helpers for HTML and PDF."""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ui.theme import Theme


_PDF_APP = None


def export_pdf(markdown_text: str, dst: Path, theme: Theme) -> None:
    from PySide6.QtGui import QTextDocument
    from PySide6.QtPrintSupport import QPrinter
    from PySide6.QtWidgets import QApplication

    global _PDF_APP

    if QApplication.instance() is None:
        _PDF_APP = QApplication([])
    dst.parent.mkdir(parents=True, exist_ok=True)
    document = QTextDocument()
    document.setDocumentMargin(24)
    document.setHtml(render_report_html(markdown_text, theme, title=dst.stem))

    printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(dst))
    document.print_(printer)


def export_html(markdown_text: str, dst: Path, theme: Theme) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_report_html(markdown_text, theme, title=dst.stem), encoding="utf-8")


def render_report_html(markdown_text: str, theme: Theme, *, title: str = "RIN Report") -> str:
    body = _markdown_body_html(markdown_text)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{escape(title)}</title>
  <style>
{_theme_css(theme)}
  </style>
</head>
<body>
  <main class=\"report-body\">{body}</main>
</body>
</html>
"""


def _markdown_body_html(markdown_text: str) -> str:
    try:
        import markdown

        return markdown.markdown(markdown_text, extensions=["fenced_code", "tables"])
    except ImportError:
        return f"<pre>{escape(markdown_text)}</pre>"


def _theme_css(theme: Theme) -> str:
    return f"""
    :root {{
      color-scheme: {theme.name};
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 32px;
      background: {theme.bg};
      color: {theme.text};
      font-family: 'Segoe UI Variable', 'Segoe UI', Arial, sans-serif;
      line-height: 1.6;
    }}

    .report-body {{
      max-width: 920px;
      margin: 0 auto;
      padding: 28px 32px;
      background: {theme.surface};
      border: 1px solid {theme.border};
      border-radius: {theme.radius_card}px;
    }}

    h1, h2, h3, h4, h5, h6 {{
      color: {theme.text};
      margin-top: 1.2em;
      margin-bottom: 0.5em;
      line-height: 1.25;
    }}

    h1 {{
      font-size: 28px;
      margin-top: 0;
    }}

    h2 {{
      font-size: 22px;
      border-bottom: 1px solid {theme.border};
      padding-bottom: 4px;
    }}

    h3 {{
      font-size: 18px;
      color: {theme.text_muted};
    }}

    p, ul, ol, blockquote, table, pre {{
      margin: 0 0 1em;
    }}

    blockquote {{
      margin-left: 0;
      padding-left: 12px;
      border-left: 3px solid {theme.accent};
      color: {theme.text_muted};
    }}

    code {{
      padding: 1px 5px;
      border: 1px solid {theme.border};
      border-radius: 4px;
      background: {theme.surface_alt};
      font-family: Consolas, 'Cascadia Code', monospace;
    }}

    pre {{
      padding: 12px;
      border: 1px solid {theme.border};
      border-radius: 6px;
      background: {theme.surface_alt};
      overflow-x: auto;
      white-space: pre-wrap;
    }}

    pre code {{
      padding: 0;
      border: 0;
      background: transparent;
    }}

    a {{
      color: {theme.accent};
      text-decoration: none;
    }}

    hr {{
      border: 0;
      border-top: 1px solid {theme.border};
      margin: 1.5em 0;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
    }}

    th, td {{
      padding: 6px 10px;
      border: 1px solid {theme.border};
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: {theme.surface_alt};
    }}
    """.strip()
