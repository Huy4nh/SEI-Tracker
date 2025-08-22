# tools/table.py
from typing import List, Any, Literal

MDV2_SPECIALS = r'_*[]()~`>#+-=|{}.!'

def _mdv2_escape(text: str) -> str:
    out = []
    for ch in text:
        out.append("\\" + ch if ch in MDV2_SPECIALS else ch)
    return "".join(out)

# --- 1) Chuẩn hoá đầu vào ---
def _coerce_table_input(columns, rows):
    # columns
    if columns is None:
        columns = []
    if not isinstance(columns, list):
        columns = [str(columns)]
    else:
        columns = [str(c) for c in columns]

    # rows:
    # - nếu rows là None -> []
    # - nếu rows không phải list -> [[rows]]
    # - nếu rows là list nhưng phần tử KHÔNG phải list -> biến thành [[item], ...]
    if rows is None:
        rows = []
    elif not isinstance(rows, list):
        rows = [[rows]]
    else:
        # nếu là list các dict: suy deduce cột nếu chưa có
        if rows and all(isinstance(r, dict) for r in rows):
            if not columns:
                keyset = set()
                for r in rows:
                    keyset |= set(r.keys())
                columns = list(keyset)
            rows = [[r.get(col, "") for col in columns] for r in rows]
        else:
            # list nhưng phần tử có thể là scalar
            if rows and not isinstance(rows[0], list):
                rows = [[v] for v in rows]

    # Căn padding/truncate số cột
    n = len(columns) if columns else (len(rows[0]) if rows and isinstance(rows[0], list) else 1)
    if not columns:
        columns = [f"C{i+1}" for i in range(n)]
    fixed_rows = []
    for r in rows:
        r = list(r) + [""] * (n - len(r))  # pad
        fixed_rows.append(r[:n])           # truncate

    return columns, fixed_rows

# --- 2) Renderers ---
def render_table_markdown(columns: List[str], rows: List[List[Any]], title: str | None = None) -> str:
    head = "|" + "|".join(columns) + "|\n"
    sep  = "|" + "|".join("---" for _ in columns) + "|\n"
    body = "".join("|" + "|".join("" if v is None else str(v) for v in r) + "|\n" for r in rows)
    return (f"**{title}**\n\n" if title else "") + head + sep + body

def render_table_csv(columns: List[str], rows: List[List[Any]], title: str | None = None) -> str:
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    w.writerows(rows)
    return (title + "\n\n" if title else "") + buf.getvalue()

def render_table_html(columns: List[str], rows: List[List[Any]], title: str | None = None) -> str:
    th = "".join(f"<th>{c}</th>" for c in columns)
    trs = []
    for r in rows:
        tds = "".join(f"<td>{'' if v is None else v}</td>" for v in r)
        trs.append(f"<tr>{tds}</tr>")
    table = f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
    return (f"<h3>{title}</h3>\n" if title else "") + table

def render_table_telegram_mdv2(columns: List[str], rows: List[List[Any]], title: str | None = None) -> str:
    # Tính width cột
    colw = []
    for i, c in enumerate(columns):
        header_w = len(str(c))
        cell_w = max((len(str(r[i])) for r in rows if i < len(r)), default=0)
        colw.append(max(header_w, cell_w))

    def fmt_row(r):
        return " | ".join(str(r[i] if i < len(r) else "").ljust(colw[i]) for i in range(len(columns)))

    head = fmt_row(columns)
    sep  = "-+-".join("-" * w for w in colw)
    body = "\n".join(fmt_row(r) for r in rows)

    # Toàn bộ nằm trong code block => không cần escape gì cả
    lines = []
    if title:
        lines.append(f"# {title}")
    lines.append(head)
    lines.append(sep)
    lines.append(body)
    return "```\n" + "\n".join(lines) + "\n```"


# --- 3) Entry point ---
def execute_make_table(
    columns,
    rows,
    fmt: Literal["markdown","csv","html","telegram_mdv2"] = "markdown",
    title: str | None = None
) -> str:
    columns, rows = _coerce_table_input(columns, rows)
    if fmt == "csv":
        return render_table_csv(columns, rows, title)
    if fmt == "html":
        return render_table_html(columns, rows, title)
    if fmt == "telegram_mdv2":
        return render_table_telegram_mdv2(columns, rows, title)
    return render_table_markdown(columns, rows, title)
# --- 4) Tool definition (để __init__.py import) ---
MAKE_TABLE_TOOL_DEF = {
    "name": "make_table",
    "description": (
        "Format tabular data as a table. Accepts 'columns' (headers) and 'rows' "
        "(2D values). Outputs one of: markdown, csv, html, telegram_mdv2."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
            "rows": {
                "type": "array",
                "items": {"type": "array", "items": {"type": ["string","number","boolean","null"]}}
            },
            "format": {
                "type": "string",
                "enum": ["markdown","csv","html","telegram_mdv2"],
                "default": "markdown"
            },
            "title": {"type": "string"}
        },
        "required": ["columns","rows"]
    }
}
