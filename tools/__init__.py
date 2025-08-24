# tools/__init__.py
from .table_image import MAKE_TABLE_IMAGE_TOOL_DEF, execute_make_table_image
import os

WEB_SEARCH_TOOL_DEF = {"name": "web_search","type": "web_search_20250305","max_uses": 1}

def get_tools():
    tools = [WEB_SEARCH_TOOL_DEF,MAKE_TABLE_IMAGE_TOOL_DEF]
    # if os.getenv("ENABLE_WEB_SEARCH", "1") == "1":
    #     tools.insert(0, WEB_SEARCH_TOOL_DEF)
    return tools

def run_client_tool(name: str, args: dict):
    if name == "make_table_image":
        cols      = args.get("columns", [])
        rows      = args.get("rows", [])
        title     = args.get("title")
        theme     = args.get("theme", "light")
        font_size = int(args.get("font_size", 18))
        cp        = args.get("cell_padding", [16, 10])
        if not isinstance(cp, (list, tuple)) or len(cp) != 2:
            cp = [16, 10]
        filename  = args.get("filename")
        return execute_make_table_image(cols, rows, title, theme, font_size, tuple(cp), filename)
    # web_search là server tool (Anthropic), không chạy local
    return None
