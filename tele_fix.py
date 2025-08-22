import re

# Ký tự cần escape trong Telegram MarkdownV2 (theo docs)
_MDv2_SPECIALS = r'[_*\[\]()~`>#+\-=|{}.!]'

def _escape_mdv2(s: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', s)

def markdown_to_markdown_v2(md: str) -> str:
    """
    Chuyển Markdown chuẩn sang MarkdownV2 (Telegram).
    - Bảo vệ code block ```...``` và inline `...`
    - Chuyển #, ##, ... thành dòng *đậm*
    - Chuyển **bold** và __bold__ -> *bold*
    - Giữ _italic_ (Markdown chuẩn) -> _italic_ (Telegram)
    - Chuyển ~~strike~~ -> ~strike~
    - Chuyển gạch đầu dòng '- ' hoặc '* ' -> '• '
    - Xử lý [label](url), escape label và () trong URL
    - Escape toàn bộ ký tự đặc biệt còn lại theo MarkdownV2
    """
    placeholders = {}
    pid = 0
    def put(val: str) -> str:
        nonlocal pid
        key = f"§§{pid}§§"
        placeholders[key] = val
        pid += 1
        return key

    text = md

    # 1) Bảo vệ code block ```...``` (đa dòng)
    text = re.sub(r"```[\s\S]*?```", lambda m: put(m.group(0)), text)
    # 2) Bảo vệ inline code `...`
    text = re.sub(r"`[^`\n]+`", lambda m: put(m.group(0)), text)

    # 3) Liên kết [label](url) -> giữ cấu trúc, escape label + () trong URL
    def _repl_link(m):
        label = _escape_mdv2(m.group(1))
        url = m.group(2).replace("(", r"\(").replace(")", r"\)")
        return put(f"[{label}]({url})")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _repl_link, text)

    # 4) Heading (#, ##, ...): chuyển thành dòng đậm
    text = re.sub(
        r"^\s*#{1,6}\s*(.+)$",
        lambda m: put(f"*{_escape_mdv2(m.group(1).strip())}*"),
        text,
        flags=re.MULTILINE
    )

    # 5) **bold** hoặc __bold__ -> *bold*
    def _repl_bold(m):
        inner = _escape_mdv2(m.group(1))
        return put(f"*{inner}*")
    text = re.sub(r"\*\*(.+?)\*\*", _repl_bold, text)
    text = re.sub(r"__(.+?)__", _repl_bold, text)

    # 6) _italic_ (Markdown chuẩn) -> _italic_ (Telegram). (Không đụng *italic* để tránh nhầm bullet)
    def _repl_italic_us(m):
        inner = _escape_mdv2(m.group(1))
        return put(f"_{inner}_")
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", _repl_italic_us, text)

    # 7) ~~strike~~ -> ~strike~
    def _repl_strike(m):
        inner = _escape_mdv2(m.group(1))
        return put(f"~{inner}~")
    text = re.sub(r"~~(.+?)~~", _repl_strike, text)

    # 8) Gạch đầu dòng '- ' hoặc '* ' -> '• ' để khỏi phải escape
    text = re.sub(r"(?m)^[ \t]*[-*]\s+", "• ", text)

    # 9) Blockquote '> ' -> escape ký tự '>'
    text = re.sub(r"(?m)^[ \t]*>\s?", r"\> ", text)

    # 10) Escape mọi ký tự đặc biệt còn lại
    text = _escape_mdv2(text)

    # 11) Khôi phục các khối đã bảo vệ (placeholders)
    # (placeholders không chứa ký tự đặc biệt nên không bị ảnh hưởng)
    for k, v in placeholders.items():
        text = text.replace(k, v)

    return text
