# tools/table_image.py
import os, tempfile, time
from typing import List, Any, Literal, Tuple
from PIL import Image, ImageDraw, ImageFont

# ---- Font fallback: Arial -> Calibri -> DejaVu -> Noto -> default ----
def _load_font(size: int):
    candidates = [
        "arial.ttf",
        "calibri.ttf",
        "DejaVuSans.ttf",                 # đa số môi trường Linux có sẵn
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "NotoSans-Regular.ttf",
    ]
    for f in candidates:
        try:
            return ImageFont.truetype(f, size=size)
        except Exception:
            pass
    return ImageFont.load_default()

def _text_size(font: ImageFont.FreeTypeFont, text: str) -> Tuple[int, int]:
    bbox = font.getbbox(text or "")
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])

def _ensure_outdir_and_abs(filename: str | None) -> str:
    """
    - Nếu có filename:
        + nếu là relative -> join vào ./out_images
        + tạo thư mục nếu chưa có
    - Nếu không có:
        + tạo ./out_images/table_<ts>.png
    Trả về path tuyệt đối.
    """
    if filename:
        # nếu là path tương đối, ghi vào ./out_images
        if not os.path.isabs(filename):
            out_dir = os.path.join(os.getcwd(), "out_images")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, filename)
        else:
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            path = filename
        return os.path.abspath(path)

    # mặc định: ./out_images/table_<ts>.png (dễ debug hơn /tmp)
    out_dir = os.path.join(os.getcwd(), "out_images")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"table_{int(time.time()*1000)}.png"
    return os.path.abspath(os.path.join(out_dir, fname))

def render_table_image(
    columns: List[str],
    rows: List[List[Any]],
    title: str | None = None,
    theme: Literal["light","dark"] = "light",
    font_size: int = 18,
    cell_padding: Tuple[int,int] = (16,10),   # (x, y)
    out_path: str | None = None
) -> str:
    """
    Trả về đường dẫn file PNG đã lưu (tuyệt đối).
    """
    # Chuẩn hoá dữ liệu đầu vào
    columns = [str(c) for c in (columns or [])]
    if not isinstance(rows, list):
        rows = [[rows]]
    elif rows and not isinstance(rows[0], list):
        rows = [[v] for v in rows]
    ncol = len(columns) if columns else (len(rows[0]) if rows else 1)
    if not columns:
        columns = [f"C{i+1}" for i in range(ncol)]

    fixed_rows = []
    for r in rows:
        rr = list(r) + [""] * (ncol - len(r))
        fixed_rows.append([("" if v is None else str(v)) for v in rr[:ncol]])

    font = _load_font(font_size)
    font_bold = _load_font(font_size + 1)

    pad_x, pad_y = cell_padding
    col_widths = []
    for i, col in enumerate(columns):
        w_head, _ = _text_size(font_bold, str(col))
        w_cells = 0
        for r in fixed_rows:
            w, _ = _text_size(font, str(r[i]))
            w_cells = max(w_cells, w)
        col_widths.append(max(w_head, w_cells) + 2*pad_x)

    row_height  = max(_text_size(font, "Ag")[1] + 2*pad_y, font_size + 2*pad_y)
    head_height = max(_text_size(font_bold, "Ag")[1] + 2*pad_y, font_size + 2*pad_y)
    title_h = _text_size(font_bold, title)[1] + 2*pad_y if title else 0

    table_width  = sum(col_widths) + (ncol + 1) * 1
    table_height = head_height + len(fixed_rows) * row_height + (len(fixed_rows) + 2) * 1
    img_w = table_width + 40
    img_h = title_h + table_height + 40

    if theme == "dark":
        bg = (16, 18, 20)
        fg = (240, 240, 240)
        grid = (70, 70, 80)
        head_bg = (32, 35, 40)
    else:
        bg = (255, 255, 255)
        fg = (23, 23, 23)
        grid = (210, 210, 210)
        head_bg = (245, 247, 250)

    img = Image.new("RGB", (img_w, img_h), bg)
    drw = ImageDraw.Draw(img)

    x0, y0 = 20, 20
    y = y0

    # Tiêu đề
    if title:
        drw.text((x0, y), title, font=font_bold, fill=fg)
        y += title_h

    # Header
    drw.rectangle([x0, y, x0 + table_width, y + head_height], fill=head_bg)
    cx = x0 + 1
    for i, col in enumerate(columns):
        cell_w = col_widths[i]
        tw, th = _text_size(font_bold, col)
        tx = cx + (cell_w - tw) // 2
        ty = y + (head_height - th) // 2
        drw.text((tx, ty), col, font=font_bold, fill=fg)
        cx += cell_w + 1
    drw.line([(x0, y + head_height), (x0 + table_width, y + head_height)], fill=grid, width=1)
    y += head_height + 1

    # Dòng dữ liệu
    for r in fixed_rows:
        cx = x0 + 1
        for i, val in enumerate(r):
            cell_w = col_widths[i]
            tw, th = _text_size(font, str(val))
            tx = cx + pad_x
            ty = y + (row_height - th) // 2
            drw.text((tx, ty), str(val), font=font, fill=fg)
            drw.line([(cx + cell_w, y - 1), (cx + cell_w, y + row_height)], fill=grid, width=1)
            cx += cell_w + 1
        drw.line([(x0, y + row_height), (x0 + table_width, y + row_height)], fill=grid, width=1)
        y += row_height + 1

    # Khung ngoài
    drw.rectangle(
        [x0, y0 + (title_h if title else 0),
         x0 + table_width, y0 + (title_h if title else 0) + head_height + len(fixed_rows) * row_height + (len(fixed_rows) + 1)],
        outline=grid, width=1
    )

    # ---- Chọn đường dẫn xuất (tuyệt đối) ----
    out_path = _ensure_outdir_and_abs(out_path)

    img.save(out_path, format="PNG")
    return os.path.abspath(out_path)

MAKE_TABLE_IMAGE_TOOL_DEF = {
    "name": "make_table_image",
    "description": "Render tabular data to a PNG image for Telegram (or web).",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
            "rows": {
                "type": "array",
                "items": {"type": "array", "items": {"type": ["string","number","boolean","null"]}}
            },
            "title": {"type": "string"},
            "theme": {"type": "string", "enum": ["light","dark"], "default": "light"},
            "font_size": {"type": "integer", "minimum": 8, "maximum": 48, "default": 18},
            "cell_padding": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2, "maxItems": 2,
                "default": [16,10],
                "description": "[pad_x, pad_y] pixels"
            },
            "filename": {"type": "string", "description": "Optional output filename (relative -> ./out_images)."}
        },
        "required": ["columns","rows"]
    }
}

def execute_make_table_image(columns, rows, title=None, theme="light", font_size=18, cell_padding=(16,10), filename=None) -> str:
    return render_table_image(columns, rows, title, theme, font_size, tuple(cell_padding or (16,10)), filename)
