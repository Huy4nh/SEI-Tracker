# chatbot.py
import os, re, anthropic, json
from typing import Any, Dict, List, Optional
from tools import get_tools, run_client_tool
from mcp_bridge import MCPBridge  # dùng MCP server(s) có sẵn
from anthropic import APIStatusError
import random, time 
import ast 
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timezone
def _now_str():
    now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%d %H:%M:%S %z (%Z)")
SYSTEM_PROMPT = (
    
    "You are a SEI blockchain assistant powered by Anthropic Claude 3.7 Sonnet (2025-02-19).\n"
    "MCP here means Model Context Protocol.\n"
    "You have access to MCP tools (prefixed `sei:`) for live SEI data. "
    "Prefer MCP tools over browsing. Do NOT say 'I don't have a direct connection' — "
    "if a tool is needed, CALL it; if a tool fails, state which tool failed and why.\n"
    "When tabular data helps, call a PNG-rendering tool (e.g., `make_table_image` or an MCP tool that outputs images). "
    "Do not print ASCII/Markdown tables."
    f"""- Current local time is provided below. Treat it as ground truth; do not say you don't know the date/time.
    [Runtime]
    now: {_now_str()}"""
)
import json
# ---------------- Memory (per chat/session) ----------------
class _Memory:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def get(self, sid: str) -> Dict[str, Any]:
        if sid not in self.sessions:
            self.sessions[sid] = {"summary": None, "turns": []}
        return self.sessions[sid]

    def clear(self, sid: str):
        self.sessions.pop(sid, None)

class chatbot:
    def __init__(self, model: str):
        self.model = model
        self.mem = _Memory()
        # web_search (server tool) bật qua header beta
        self.client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            default_headers={"anthropic-beta": "web-search-2025-03-05"}
        )
        # window & tóm tắt
        self.MAX_TURNS = 14
        self.KEEP_TURNS = 6
        # MCP bridge (từ file riêng mcp_bridge.py)
        # Đổi "mcp.json" -> "mcp.sei.json" nếu file của bạn tên khác
        self.mcp = MCPBridge("mcp.json")
        self.mcp.start()  # nếu không có/khởi tạo lỗi → export 0 tool, chatbot vẫn chạy
        print("[MCP] tools:", [t["name"] for t in self.mcp.anthropic_tools()])
        # detect bảng text để chuyển sang ảnh (fallback)
        self._fence_pat = re.compile(r"```(?:[^\n]*\n)?([\s\S]*?)```", re.MULTILINE)
        self._table_line_pat = re.compile(r"^\s*[\|\+].*[\|\+]\s*$")
        self._sep_line_pat = re.compile(r"^\s*[-=\+\|\s:]+\s*$")
    def _remove_markdown_images(self, s: str) -> str:
        """Loại bỏ mọi Markdown image ![alt](url) khỏi text."""
        if not s:
            return s
        s = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', s)
        return re.sub(r'\n{3,}', '\n\n', s).strip()

    def _extract_apr_value(self, s: str):
        """
        Cố tìm 1 số APR % trong đoạn văn (EN/VN).
        Ví dụ: 'APR is around 10.8%' hoặc 'APR hiện tại ~ 9,76%'.
        Trả về float hoặc None.
        """
        if not s:
            return None
        # chuẩn hoá dấu phẩy-dấu chấm
        ss = s.replace(",", ".")
        m = re.search(r'(?i)\bapr\b[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)\s*%', ss)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        return None

    def _strip_mcp_noise_and_md_images(self, s: str) -> str:
        """Gộp 2 bước: xoá 'sei:...' & xoá Markdown images."""
        s = self._strip_mcp_noise(s)
        s = self._remove_markdown_images(s)
        return s

    def _remove_markdown_images(self, s: str) -> str:
        """Xoá mọi Markdown image ![...](...)."""
        if not s:
            return s
        return re.sub(r"!\[[^\]]*\]\([^)]+\)", "", s)

    def _extract_series_tables_from_md_images(self, s: str):
        """
        Tìm các Markdown image có tham số series=[...] trong URL (đồ thị),
        trích thành bảng Date, APR (%) để vẽ ảnh local.
        Return: list[ {columns, rows, code_block} ]
        """
        out = []
        if not s:
            return out
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", s):
            url = m.group(1)
            try:
                pr = urlparse(url)
            except Exception:
                continue
            qs = parse_qs(pr.query or "")
            raw_series = (qs.get("series") or [None])[0]
            if not raw_series:
                continue
            try:
                arr = json.loads(unquote(raw_series))
                # kỳ vọng dạng [{"name":"...","data":[{"x":"2024-01-01","y":11.2}, ...]}]
                if not isinstance(arr, list) or not arr:
                    continue
                series0 = arr[0] or {}
                data = series0.get("data") or []
                rows = []
                for pt in data:
                    x = pt.get("x")
                    y = pt.get("y")
                    if x is None or y is None:
                        continue
                    try:
                        yv = float(y)
                    except Exception:
                        continue
                    rows.append([str(x), f"{yv:.2f}"])
                if rows:
                    out.append({
                        "columns": ["Date", "APR (%)"],
                        "rows": rows,
                        "code_block": m.group(0)   # nguyên cụm ![...](...)
                    })
            except Exception:
                continue
        return out
    def _strip_mcp_noise(self, s: str) -> str:
        """
        Xoá các dòng gọi MCP trần kiểu 'sei:xxx' hoặc 'sei:xxx(...)' / 'sei_xxx(...)'.
        """
        if not s:
            return s
        out_lines = []
        pat = re.compile(r'^\s*(sei[:_][\w:]+)\s*(\([^)]*\))?\s*$', re.I)
        for ln in s.splitlines():
            if pat.match(ln.strip()):
                continue
            out_lines.append(ln)
        s = "\n".join(out_lines)
        return re.sub(r"\n{3,}", "\n\n", s).strip()

    def _iter_code_fences(self, text: str):
        """
        Duyệt toàn bộ code fences dạng ```...```, trả về nguyên block (kể cả ```).
        """
        if not text:
            return
        for m in re.finditer(r"```[\s\S]*?```", text):
            yield m.group(0)

    def _remove_matplotlib_blocks(self, text: str) -> str:
        """
        Bỏ các code block có chứa matplotlib/pandas (không thực thi).
        """
        if not text:
            return text
        out = text
        for blk in list(self._iter_code_fences(text)):
            low = blk.lower()
            if "matplotlib" in low or "plt." in low or "pandas" in low:
                out = out.replace(blk, "")
        return re.sub(r"\n{3,}", "\n\n", out).strip()

    def _extract_apr_from_python(self, code_block: str):
        """
        Tìm current_apr = 9.76 trong code python để dựng bảng ảnh đơn giản.
        """
        m = re.search(r'current_apr\s*=\s*([0-9]+(?:\.[0-9]+)?)', code_block)
        if not m:
            return None
        try:
            return float(m.group(1))
        except Exception:
            return None

    def _extract_make_table_image_args_from_text(self, s: str):
        """
        Bắt make_table_image({...}) nếu model lỡ in ra text thay vì gọi tool.
        Hỗ trợ 'headers'→'columns'.
        """
        if not s:
            return None
        m = re.search(r"make_table_image\s*\(\s*(\{[\s\S]*?\})\s*\)", s, re.I)
        if not m:
            return None
        raw_obj = m.group(1)
        try:
            payload = json.loads(raw_obj)
        except Exception:
            try:
                payload = json.loads(re.sub(r"'", '"', raw_obj))
            except Exception:
                return None
        cols = payload.get("columns") or payload.get("headers") or []
        rows = payload.get("rows") or payload.get("data") or []
        return {
            "columns": [str(c) for c in cols],
            "rows": rows,
            "title": payload.get("title"),
            "theme": payload.get("theme", "light"),
            "font_size": int(payload.get("font_size", 18)),
            "cell_padding": payload.get("cell_padding", [16, 10]),
            "code_block": m.group(0),
        }


    # ---------------- public ----------------
    def _normalize_tool_def(self, t: dict) -> dict:
        """Đảm bảo mọi tool đều có 'name' nhất quán để khử trùng theo tên."""
        t = dict(t or {})
        # Một số web_search beta dùng 'type' đặc biệt, thêm 'name' thống nhất
        if not t.get("name"):
            ty = (t.get("type") or "").lower()
            if ty.startswith("web_search_"):
                t["name"] = "web_search"
        return t

    def _dedupe_tools_by_name(self, tool_list: list) -> list:
        """Giữ nguyên thứ tự, loại bỏ tool trùng theo 'name' (không phân biệt hoa thường)."""
        seen = set()
        out = []
        for t in tool_list or []:
            tt = self._normalize_tool_def(t)
            name = (tt.get("name") or "").strip()
            if not name:
                # Không có name thì bỏ qua để tránh 400 của Anthropic
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tt)
        return out
    def _is_overloaded(self, e: Exception) -> bool:
        s = str(e).lower()
        if "overloaded" in s or "rate limit" in s or "temporarily" in s:
            return True
        # Thêm bắt theo class APIStatusError (nếu body có type)
        if isinstance(e, APIStatusError):
            try:
                body = e.body if hasattr(e, "body") else None
                err = (body or {}).get("error") or {}
                if (err.get("type") or "").lower() == "overloaded_error":
                    return True
            except Exception:
                pass
        return False
    def reset(self, session_id: str):
        self.mem.clear(session_id)
        
    def asking_stream(
        self,
        message: str,
        *,
        session_id: str,
        telegram: bool = True,
        sink=None,                 # callback đẩy event ra UI (tuỳ chọn)
        print_live: bool = True,   # mặc định: in realtime ra terminal
    ) -> Dict[str, Any]:
        """
        Stream trực tiếp trong hàm (không cần iterate bên ngoài).
        Tự quyết định khi nào dùng tool/MCP dựa trên nội dung câu hỏi.
        Trả về: {"text": final_text, "images": [...]}

        Event cho UI (nếu có sink):
        - {"type":"tool_call", "name": str, "args": dict}
        - {"type":"tool_result", "name": str, "text": str} | {"type":"tool_result","name":str,"image_path":str}
        - {"type":"text_delta", "text": str}
        - {"type":"done", "final_text": str, "images": [str]}
        """
        store = self.mem.get(session_id)
        mcp_tools = self.mcp.anthropic_tools()

        # ---------- emit helper ----------
        def _emit(ev: Dict[str, Any]):
            if sink is not None:
                try:
                    sink(ev)
                except Exception:
                    pass
            if print_live:
                t = ev.get("type")
                if t == "tool_call":
                    from json import dumps
                    print(f"\n🛠️ tool_call: {ev.get('name')} args={dumps(ev.get('args', {}), ensure_ascii=False)}", flush=True)
                elif t == "tool_result":
                    if ev.get("image_path"):
                        print(f"\n📷 tool_result image: {ev['image_path']}", flush=True)
                    else:
                        txt = ev.get("text", "")
                        if txt: print(f"\n🔎 tool_result text:\n{txt}", flush=True)
                elif t == "text_delta":
                    print(ev.get("text", ""), end="", flush=True)
                elif t == "done":
                    print("\n✅ done.\n", flush=True)

        # ---------- Heuristic: quyết định tool ----------
        q = (message or "").strip().lower()

        def _need_mcp(q_: str) -> bool:
            onchain_markers = [
                "sei1", "tx", "transaction", "hash", "block", "height",
                "contract", "cw20", "balance", "address", "mcp", "bằng mcp",
                "airnode", "earthnode", "validator", "delegat", "stake", "unstake",
            ]
            return any(tok in q_ for tok in onchain_markers)

        def _need_web(q_: str) -> bool:
            if any(kw in q_ for kw in ["đừng search", "đừng browse", "no search", "do not browse", "không tìm web"]):
                return False
            recency_markers = [
                "latest", "mới nhất", "today", "hôm nay", "hiện tại", "now",
                "news", "tin tức", "update", "cập nhật", "price", "giá", "apr", "aprs",
                "changelog", "thay đổi", "gần đây", "recent", "tăng/giảm", "volume",
            ]
            return any(tok in q_ for tok in recency_markers)
        explicit_tool = self._explicit_mcp_tool(q, mcp_tools)
        allow_mcp = (_need_mcp(q) and bool(mcp_tools)) or bool(explicit_tool)
        allow_web = _need_web(q)
        allow_client_table = True  # luôn cho phép vẽ bảng khi model chủ động gọi

        # ---------- “Tôi vừa hỏi gì?” ----------
        if self._is_ask_last_question(message):
            last_q = self._last_user_text(store)
            txt = f"Bạn vừa hỏi: “{last_q}”." if last_q else "Mình chưa thấy câu hỏi trước đó trong lịch sử chat này."
            _emit({"type": "done", "final_text": txt, "images": []})
            return {"text": txt, "images": []}

        # ---------- build system + tools ----------
        # --- build system + tools ---
        system_txt = SYSTEM_PROMPT
        if store["summary"]:
            system_txt += "\n\n[Conversation summary]\n" + store["summary"]

        want_docs = self._need_docs(q)
        user_msg = {"role": "user", "content": [{"type": "text", "text": message}]}
        if mcp_tools and allow_mcp:
            # chỉ preview khi thực sự cho dùng MCP
            preview = []
            for t in mcp_tools[:16]:
                if self._is_doc_search_tool(t.get("name"), t.get("description")) and not want_docs:
                    continue
                desc = (t.get("description") or "").strip()
                preview.append(f"- {t['name']}" + (f": {desc}" if desc else ""))
            if preview:
                system_txt += "\n\n[Available MCP tools]\n" + "\n".join(preview)
        
        # ===== Chọn tools =====
# ===== Chọn tools (chuẩn, không trùng) =====
        local_tools_all = get_tools()

        # 1) Lọc local tools một lần
        filtered_local: List[Dict[str, Any]] = []
        for t in local_tools_all:
            nm, tp, ds = t.get("name") or "", t.get("type") or "", t.get("description") or ""
            is_web = (nm == "web_search") or (tp == "web_search_20250305")
            if is_web and not allow_web:
                continue
            if self._is_doc_search_tool(nm, ds) and not want_docs:
                continue
            if (nm == "make_table_image") and not allow_client_table:
                continue
            filtered_local.append(t)

        # 2) Lọc MCP tools một lần (nếu cho phép)
        filtered_mcp: List[Dict[str, Any]] = []
        if allow_mcp:
            for t in mcp_tools:
                if self._is_doc_search_tool(t.get("name"), t.get("description")) and not want_docs:
                    continue
                filtered_mcp.append(t)

        # 3) Gộp & khử trùng theo name
        tools = filtered_local + filtered_mcp
        tools = self._dedupe_tools_by_name(tools)

        if print_live:
            print("[DBG] tools sending:", [t.get("name") for t in tools], flush=True)

        first = None
        if tools:
            _delays = [0.8, 1.6, 3.2, 6.4]
            for _i, _d in enumerate(_delays, 1):
                try:
                    first = self.client.messages.create(
                        model=self.model,
                        max_tokens=8000,
                        temperature=0.7,
                        system=system_txt,
                        messages=[*store["turns"], user_msg],
                        tools=tools,
                    )
                    break
                except Exception as e:
                    if self._is_overloaded(e) and _i < len(_delays):
                        if sink: sink({"type":"tool_result","name":"system","text":f"⏳ Model quá tải, thử lại lần {_i+1}/{len(_delays)}..."})
                        time.sleep(_d + random.random()*0.5)
                        continue
                    raise


        images: List[str] = []
        tool_results: List[Dict[str, Any]] = []

        if first is not None:
            # Tìm tool_use do model đề xuất (chỉ những tool ta vừa cho phép)
            client_tool_uses = [
                b for b in first.content
                if getattr(b, "type", None) == "tool_use" and b.name == "make_table_image"
            ]
            mcp_tool_uses = [
                b for b in first.content
                if getattr(b, "type", None) == "tool_use" and self.mcp.is_mcp_tool(b.name)
            ]

            # ---- Thực thi client tool ----
            for tu in client_tool_uses:
                args = tu.input or {}
                _emit({"type": "tool_call", "name": tu.name, "args": args})
                out_path = run_client_tool("make_table_image", args)
                if isinstance(out_path, str):
                    images.append(out_path)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": [{"type": "text", "text": json.dumps({"path": out_path}, ensure_ascii=False)}],
                    })
                    _emit({"type": "tool_result", "name": tu.name, "image_path": out_path})
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": [{"type": "text", "text": "[client tool make_table_image returned no path]"}],
                        "is_error": True
                    })
                    _emit({"type": "tool_result", "name": tu.name, "text": "[client tool make_table_image returned no path]"})


            # ---- Thực thi MCP tool ----
            for tu in mcp_tool_uses:
                args = tu.input or {}
                _emit({"type": "tool_call", "name": tu.name, "args": args})
                try:
                    out = self.mcp.exec_tool(tu.name, args)
                except Exception as e:
                    out = {"text": f"[MCP] exec_tool raised: {type(e).__name__}: {e}"}

                if not isinstance(out, dict) or out is None:
                    out = {"text": f"[MCP] invalid result from {tu.name}"}

                if out.get("image_path"):
                    images.append(out["image_path"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": [{"type": "text", "text": json.dumps({"path": out['image_path']}, ensure_ascii=False)}],
                    })
                    _emit({"type": "tool_result", "name": tu.name, "image_path": out["image_path"]})
                else:
                    raw_txt = out.get("text", "[MCP] no text")
                    # nếu là tool dạng doc-search → làm sạch
                    txt = self._clean_doc_text(raw_txt) if self._looks_like_doc_tool(tu.name) else raw_txt

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": [{"type": "text", "text": txt}],
                    })
                    _emit({"type": "tool_result", "name": tu.name, "text": txt})


        # ---------- STREAM câu trả lời & IN RA TRỰC TIẾP ----------
        buf: List[str] = []
        if tool_results:
            buf = []
            _delays = [0.8, 1.6, 3.2]
            _stream_ok = False
            for _i, _d in enumerate(_delays, 1):
                try:
                    second_tools = tools if allow_web else []
                    with self.client.beta.messages.stream(
                        model=self.model,
                        max_tokens=8000,
                        temperature=0.7,
                        system=system_txt,
                        tools=second_tools,  # giữ tắt tools ở vòng 2
                        messages=[
                            *store["turns"],
                            user_msg,
                            {"role": "assistant", "content": first.content},
                            {"role": "user", "content": tool_results},
                        ],
                    ) as stream:
                        stream_text_acc = ""
                        last_emitted = ""
                        for ev in stream:
                            if getattr(ev, "type", "") == "content_block_delta" and hasattr(ev, "delta") and getattr(ev.delta, "text", None):
                                piece = ev.delta.text or ""
                                stream_text_acc += piece

                                # chặn dòng MCP đơn
                                stream_text_acc = re.sub(r'(?m)^\s*sei[:_][\w:]+(\([^)]*\))?\s*$','', stream_text_acc)
                                # chặn markdown image
                                stream_text_acc = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', stream_text_acc)

                                # chỉ emit phần mới sau khi đã lọc
                                new_chunk = stream_text_acc[len(last_emitted):]
                                if new_chunk:
                                    _emit({"type": "text_delta", "text": new_chunk})
                                    last_emitted = stream_text_acc
                    _stream_ok = True
                    break
                except Exception as e:
                    if self._is_overloaded(e) and _i < len(_delays):
                        _emit({"type":"tool_result","name":"system","text":f"⏳ Stream quá tải, thử lại lần {_i+1}/{len(_delays)}..."})
                        time.sleep(_d + random.random()*0.5)
                        continue
                    # Fallback: gọi create() không stream để lấy full text
                    try:
                        resp = self.client.messages.create(
                            model=self.model,
                            max_tokens=8000,
                            temperature=0.7,
                            system=system_txt,
                            tools=[],  # vẫn tắt tools vòng 2
                            messages=[
                                *store["turns"],
                                user_msg,
                                {"role": "assistant", "content": first.content},
                                {"role": "user", "content": tool_results},
                            ],
                        )
                        text_blocks = [getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"]
                        final_text = "".join(text_blocks).strip()
                        if final_text:
                            _emit({"type":"text_delta","text":final_text})
                            buf = [final_text]
                            _stream_ok = True
                            break
                    except Exception as e2:
                        if self._is_overloaded(e2) and _i < len(_delays):
                            time.sleep(_d + random.random()*0.5)
                            continue
                        else:
                            raise

            final_text = "".join(buf).strip()
            if not final_text and first is not None:
                final_text = "".join(getattr(b, "text", "") for b in first.content if getattr(b, "type", None) == "text").strip()

        else:
            # Không có tool cần chạy → stream thẳng câu trả lời (và tắt tools nếu không cần)
            second_tools = tools if allow_web else []  # tắt tools trong lượt stream này để tránh model "tự dưng" gọi tool
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=8000,
                temperature=0.7,
                system=system_txt,
                tools=second_tools,
                messages=[*store["turns"], user_msg],
            ) as stream:
                stream_text_acc = ""
                last_emitted = ""
                for ev in stream:
                    if getattr(ev, "type", "") == "content_block_delta" and hasattr(ev, "delta") and getattr(ev.delta, "text", None):
                        piece = ev.delta.text or ""
                        stream_text_acc += piece

                        # chặn dòng MCP đơn
                        stream_text_acc = re.sub(r'(?m)^\s*sei[:_][\w:]+(\([^)]*\))?\s*$','', stream_text_acc)
                        # chặn markdown image
                        stream_text_acc = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', stream_text_acc)

                        # chỉ emit phần mới sau khi đã lọc
                        new_chunk = stream_text_acc[len(last_emitted):]
                        if new_chunk:
                            _emit({"type": "text_delta", "text": new_chunk})
                            last_emitted = stream_text_acc
            final_text = "".join(buf).strip()
            if not final_text and first is not None:
                final_text = "".join(getattr(b, "text", "") for b in first.content if getattr(b, "type", None) == "text").strip()
        print()
        print("[DBG] allow_mcp=", allow_mcp, "allow_web=", allow_web, "want_docs=", want_docs)
        print("[DBG] tools_v1=", [t.get("name") for t in tools])

        # ---------- Fallback: nếu model in code python tạo bảng -> trích dữ liệu & vẽ ảnh ----------
        if not images and final_text:
            tables = self._extract_series_tables_from_md_images(final_text)
            for tb in tables:
                img_path = self._table_to_image(tb["columns"], tb["rows"], _emit)
                if img_path:
                    images.append(img_path)
                    final_text = final_text.replace(tb["code_block"], "").strip()
                    break 
        # 2.x) Xoá mọi markdown image còn sót lại
        final_text = self._remove_markdown_images(final_text)
        # 2.1) Xoá các dòng MCP thô như 'sei:staking_apr' / 'sei:staking_info()'
        final_text = self._strip_mcp_noise(final_text)

        # 2.2) Nếu model in 'make_table_image({...})' → tự render ảnh & xoá code
        if not images and final_text:
            mt = self._extract_make_table_image_args_from_text(final_text)
            if mt and mt["columns"] and mt["rows"]:
                args2 = {
                    "columns": mt["columns"],
                    "rows": mt["rows"],
                    "title": mt.get("title"),
                    "theme": mt.get("theme", "light"),
                    "font_size": mt.get("font_size", 18),
                    "cell_padding": mt.get("cell_padding", [16, 10]),
                }
                _emit({"type": "tool_call", "name": "make_table_image", "args": args2})
                out_path = run_client_tool("make_table_image", args2)
                if isinstance(out_path, str):
                    images.append(out_path)
                    _emit({"type": "tool_result", "name": "make_table_image", "image_path": out_path})
                    final_text = final_text.replace(mt["code_block"], "").strip()

        # 2.3) Nếu còn code matplotlib → cố gắng rút current_apr và dựng ảnh bảng
        if not images and final_text:
            made_img = False
            for blk in list(self._iter_code_fences(final_text)):
                low = blk.lower()
                if "matplotlib" in low or "plt." in low or "pandas" in low:
                    apr = self._extract_apr_from_python(blk)
                    if apr is not None:
                        args2 = {
                            "columns": ["Thông số", "Giá trị"],
                            "rows": [["APR hiện tại", f"{apr:.2f}%"]],
                            "title": "Thông tin APR của SEI",
                            "theme": "light",
                        }
                        _emit({"type": "tool_call", "name": "make_table_image", "args": args2})
                        out_path = run_client_tool("make_table_image", args2)
                        if isinstance(out_path, str):
                            images.append(out_path)
                            _emit({"type": "tool_result", "name": "make_table_image", "image_path": out_path})
                            final_text = final_text.replace(blk, "").strip()
                            made_img = True
                            break
            # Nếu không parse được → ít nhất cũng bỏ hẳn code matplotlib cho sạch
            if not made_img:
                final_text = self._remove_matplotlib_blocks(final_text)
        # 2.4) Bỏ mọi Markdown image, rồi nếu CHƯA có ảnh => cố gắng tự dựng PNG từ số APR nhặt được trong text
        final_text = self._strip_mcp_noise_and_md_images(final_text)

        if not images and final_text:
            apr_val = self._extract_apr_value(final_text)
            if apr_val is not None:
                args2 = {
                    "columns": ["Thông số", "Giá trị"],
                    "rows": [["APR hiện tại", f"{apr_val:.2f}%"]],
                    "title": "Thông tin APR của SEI",
                    "theme": "light",
                }
                _emit({"type": "tool_call", "name": "make_table_image", "args": args2})
                out_path = run_client_tool("make_table_image", args2)
                if isinstance(out_path, str):
                    images.append(out_path)
                    _emit({"type": "tool_result", "name": "make_table_image", "image_path": out_path})


        
        # ---------- Fallback: bảng chữ (Markdown/ASCII) -> ảnh ----------
        if not images and final_text:
            tbl = self._extract_first_table_block(final_text)
            if tbl:
                parsed = self.md_table(tbl)  # <— dùng hàm md_table đã có
                if parsed:
                    img_tool = self.mcp.find_image_table_tool()
                    if img_tool:
                        _emit({"type": "tool_call", "name": img_tool, "args": {"columns": parsed["columns"], "rows": parsed["rows"]}})
                        out = self.mcp.exec_tool(img_tool, {"columns": parsed["columns"], "rows": parsed["rows"]})
                        if isinstance(out, dict) and out.get("image_path"):
                            images.append(out["image_path"])
                            _emit({"type": "tool_result", "name": img_tool, "image_path": out["image_path"]})
                            final_text = final_text.replace(tbl, "").replace("```", "").strip()
                    else:
                        args2 = {"columns": parsed["columns"], "rows": parsed["rows"], "title": None, "theme": "light"}
                        _emit({"type": "tool_call", "name": "make_table_image", "args": args2})
                        out_path = run_client_tool("make_table_image", args2)
                        if isinstance(out_path, str):
                            images.append(out_path)
                            _emit({"type": "tool_result", "name": "make_table_image", "image_path": out_path})
                            final_text = final_text.replace(tbl, "").replace("```", "").strip()


        # ---------- lưu history + done ----------
        store["turns"].append(user_msg)
        store["turns"].append({"role": "assistant", "content": [{"type": "text", "text": final_text or "(sent an image)"}]})
        self._maybe_summarize(session_id)

        _emit({"type": "done", "final_text": final_text, "images": images})
        return {"text": final_text, "images": images}





    def asking(
        self,
        message: str,
        *,
        session_id: str,
        telegram: bool = True,
    ) -> Dict[str, Any]:
        """
        Return: {"text": "...", "images": ["path.png", ...]}
        - Claude Q&A bình thường (có web_search khi không có MCP).
        - Nếu cần bảng → ưu tiên tool ảnh: make_table_image (client) hoặc MCP tool tương đương.
        - Nếu Claude lỡ in bảng chữ → tự chuyển sang ảnh (fallback).
        """
        store = self.mem.get(session_id)

        # Danh sách MCP tools khả dụng
        mcp_tools = self.mcp.anthropic_tools()

        # Nếu user nói "kết nối MCP/SEI MCP" mà không nêu tác vụ cụ thể:
        if self._is_generic_mcp_request(message) and mcp_tools:
            # 1) Cố gọi 1 tool “status/network/info/...” làm default
            default_tool = self._pick_default_status_tool(mcp_tools)
            text = ""
            images: List[str] = []
            if default_tool:
                out = self.mcp.exec_tool(default_tool, {})
                if "image_path" in out:
                    images.append(out["image_path"])
                else:
                    text = out.get("text", "") or f"Đã gọi MCP tool: {default_tool}"
            else:
                # 2) Không có tool phù hợp → trả menu MCP
                text = self._build_mcp_quick_menu(mcp_tools)

            # Lưu history rồi trả sớm
            user_msg = {"role": "user", "content": [{"type": "text", "text": message}]}
            store["turns"].append(user_msg)
            store["turns"].append({"role": "assistant", "content": [{"type": "text", "text": text or "(sent an image)"}]})
            return {"text": text, "images": images}

        # Trả lời nhanh "tôi vừa hỏi gì?"
        if self._is_ask_last_question(message):
            last_q = self._last_user_text(store)
            if last_q:
                return {"text": f"Bạn vừa hỏi: “{last_q}”.", "images": []}
            return {"text": "Mình chưa thấy câu hỏi trước đó trong lịch sử chat này.", "images": []}

        # System + tóm tắt (nếu có), kèm preview MCP tools (nếu có)
        system_txt = SYSTEM_PROMPT
        if store["summary"]:
            system_txt += "\n\n[Conversation summary]\n" + store["summary"]
        if mcp_tools:
            preview = []
            for t in mcp_tools[:16]:
                desc = (t.get("description") or "").strip()
                preview.append(f"- {t['name']}" + (f": {desc}" if desc else ""))
            system_txt += "\n\n[Available MCP tools]\n" + "\n".join(preview)

        user_msg = {"role": "user", "content": [{"type": "text", "text": message}]}

        # ===== Tools truyền vào Claude =====
        tools: List[Dict[str, Any]] = []
        local_tools = get_tools()  # tools local (web_search server + make_table_image client)
        if mcp_tools:
            # Có MCP → loại web_search để model không nói “I'll do a quick search”
            local_tools = [
                t for t in local_tools
                if not (t.get("name") == "web_search" or t.get("type") == "web_search_20250305")
            ]
        tools.extend(local_tools)
        tools.extend(mcp_tools)  # tools từ MCP servers (nếu có)

        # ----- Vòng 1: non-stream để xem có client/MCP tool cần chạy không -----
        first = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            temperature=0.7,
            system=system_txt,
            messages=[*store["turns"], user_msg],
            tools=tools,
        )

        images: List[str] = []
        tool_results: List[Dict[str, Any]] = []

        # 1) tool client local (make_table_image)
        client_tool_uses = [
            b for b in first.content
            if getattr(b, "type", None) == "tool_use" and b.name == "make_table_image"
        ]

        # 2) tool MCP (được prefix 'server:tool' trong mcp_bridge)
        mcp_tool_uses = [
            b for b in first.content
            if getattr(b, "type", None) == "tool_use" and self.mcp.is_mcp_tool(b.name)
        ]


        # Thực thi client tool
        for tu in client_tool_uses:
            args = tu.input or {}
            out_path = run_client_tool("make_table_image", args)
            if isinstance(out_path, str):
                images.append(out_path)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": [{"type": "text", "text": json.dumps({"path": out_path}, ensure_ascii=False)}],
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "[client tool make_table_image returned no path]",
                    "is_error": True
                })

# --- Thực thi MCP tool(s) (AN TOÀN) ---
        for tu in mcp_tool_uses:
            args = tu.input or {}
            try:
                out = self.mcp.exec_tool(tu.name, args)
            except Exception as e:
                out = {"text": f"[MCP] exec_tool raised: {type(e).__name__}: {e}"}

            if not isinstance(out, dict) or out is None:
                out = {"text": f"[MCP] invalid result from {tu.name}"}

            img_path = out.get("image_path")
            if img_path:
                images.append(img_path)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": [{"type": "text", "text": json.dumps({"path": out_path}, ensure_ascii=False)}],
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": out.get("text", "[MCP] no text"),
                })


        # ----- Vòng 2: CHỈ stream nếu có tool_result (client hoặc MCP). Nếu không, trả text vòng 1 -----
        if tool_results:
            full_chunks: List[str] = []
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=8000,
                temperature=0.7,
                system=system_txt,
                tools=tools,
                messages=[
                    *store["turns"],
                    user_msg,
                    {"role": "assistant", "content": first.content},
                    {"role": "user", "content": tool_results},
                ],
            ) as stream:
                for ev in stream:
                    if ev.type == "content_block_delta" and hasattr(ev.delta, "text"):
                        full_chunks.append(ev.delta.text)
            final_text = "".join(full_chunks).strip()
            if not final_text:
                final_text = "".join(
                    getattr(b, "text", "") for b in first.content if getattr(b, "type", None) == "text"
                ).strip()
        else:
            # KHÔNG có client/MCP tool → KHÔNG gọi vòng 2
            final_text = "".join(
                getattr(b, "text", "") for b in first.content if getattr(b, "type", None) == "text"
            ).strip()

        # ----- Fallback: nếu Claude in bảng chữ → chuyển sang ảnh (ưu tiên MCP nếu có) -----
        if not images and final_text:
            tbl = self._extract_first_table_block(final_text)
            if tbl:
                parsed = self._parse_ascii_or_md_table(tbl)
                if parsed:
                    # Ưu tiên MCP tool ảnh nếu có
                    img_tool = self.mcp.find_image_table_tool()
                    if img_tool:
                        out = self.mcp.exec_tool(img_tool, {"columns": parsed["columns"], "rows": parsed["rows"]})
                        if isinstance(out, dict) and out.get("image_path"):
                            images.append(out["image_path"])
                            final_text = final_text.replace(tbl, "").replace("```", "").strip()
                    else:
                        # fallback sang client tool local
                        out_path = run_client_tool("make_table_image", {
                            "columns": parsed["columns"], "rows": parsed["rows"], "title": None, "theme": "light"
                        })
                        if isinstance(out_path, str):
                            images.append(out_path)
                            final_text = final_text.replace(tbl, "").replace("```", "").strip()

        # ----- Cập nhật history -----
        store["turns"].append(user_msg)
        store["turns"].append({"role": "assistant", "content": [{"type": "text", "text": final_text or "(sent an image)"}]})
        self._maybe_summarize(session_id)

        return {"text": final_text, "images": images}
    
    def _looks_like_doc_tool(self, name: str, desc: str = "") -> bool:
        n = (name or "").lower()
        d = (desc or "").lower()
        # coi là tool tìm docs/tài liệu
        return any(k in n for k in ("search_docs", "docs", "search_sei_js_docs")) or \
            ("docs" in d or "documentation" in d or "search" in d)

    def _dedupe_paragraphs(self, s: str) -> str:
        import re
        paras = [p.strip() for p in re.split(r"\n{2,}", s.replace("\r\n","\n")) if p.strip()]
        seen, out = set(), []
        for p in paras:
            key = re.sub(r"\W+", "", p.lower())[:160]  # fingerprint ngắn
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return "\n\n".join(out)

    def _clean_doc_text(self, s: str, max_len: int = 6000) -> str:
        import re
        if not s: return s
        s = s.replace("\r\n","\n")

        # 1) loại rác phổ biến
        s = re.sub(r"(?mi)^\s*title:\s*undefined\s*$", "", s)
        s = re.sub(r"(?mi)^\s*link:\s*(null|none)\s*$", "", s)
        s = re.sub(r"(?m)^\s*[-]{3,}\s*$", "", s)   # '---' ngăn block

        # 2) gộp heading trùng lặp
        # ví dụ: "# Sei Giga Overview" lặp nhiều lần
        lines = [ln for ln in s.split("\n")]
        seen_h = set(); out_lines = []
        for ln in lines:
            if ln.lstrip().startswith("#"):
                key = ln.strip().lower()
                if key in seen_h: 
                    continue
                seen_h.add(key)
            out_lines.append(ln)
        s = "\n".join(out_lines)

        # 3) dedupe paragraph + gọn trắng
        s = self._dedupe_paragraphs(s)
        s = re.sub(r"\n{3,}", "\n\n", s).strip()

        # 4) cắt chiều dài (giữ token budget giai đoạn stream 2)
        if len(s) > max_len:
            s = s[:max_len] + "\n…(đã rút gọn)"
        return s

    # ---------------- helpers ----------------
    def _maybe_summarize(self, session_id: str):
        store = self.mem.get(session_id)
        if len(store["turns"]) <= self.MAX_TURNS:
            return
        transcript = []
        for t in store["turns"][-40:]:
            if t["role"] in ("user", "assistant"):
                texts = [c.get("text", "") for c in t["content"] if c.get("type") == "text"]
                if texts: transcript.append(f"{t['role'].upper()}: {texts[0]}")
        resp = self.client.messages.create(
            model=self.model, max_tokens=512,
            system="Summarize briefly the conversation so far; keep key facts and open items.",
            messages=[{"role": "user", "content": "\n".join(transcript)}],
        )
        summary = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
        if summary: store["summary"] = summary
        store["turns"] = store["turns"][-self.KEEP_TURNS:]

    def _extract_first_table_block(self, text: str) -> Optional[str]:
        m = self._fence_pat.search(text)
        if m:
            body = m.group(1)
            if "|" in body or "+-" in body:
                return body.strip()
        lines = text.splitlines()
        buf, best = [], None
        for ln in lines:
            if self._table_line_pat.match(ln):
                buf.append(ln)
            else:
                if len(buf) >= 3:
                    best = "\n".join(buf).strip(); break
                buf = []
        if not best and len(buf) >= 3:
            best = "\n".join(buf).strip()
        return best

    def md_table(self, raw: str) -> Optional[Dict[str, List[List[str]]]]:
        lines = [ln for ln in raw.splitlines() if not self._sep_line_pat.match(ln.strip())]
        rows = []
        for ln in lines:
            if "|" in ln:
                rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
        if not rows or len(rows[0]) < 2:
            return None
        cols = rows[0]
        data = [r[:len(cols)] + [""] * max(0, len(cols)-len(r)) for r in rows[1:]]
        return {"columns": cols, "rows": data}
    def _need_docs(self,q_: str) -> bool:
        markers = ["docs", "documentation", "hướng dẫn", "api", "sdk", "tutorial", "reference", "tham khảo"]
        return any(m in q_ for m in markers)

    def _is_doc_search_tool(self,name: str, desc: str) -> bool:
        n, d = (name or "").lower(), (desc or "").lower()
        return ("search" in n or "docs" in n or "search" in d or "docs" in d)

    # “tôi vừa hỏi gì?”
    def _last_user_text(self, store: Dict[str, Any]) -> Optional[str]:
        for turn in reversed(store["turns"]):
            if turn.get("role") == "user":
                texts = [c.get("text", "") for c in turn.get("content", []) if c.get("type") == "text"]
                if texts: return texts[0].strip()
        return None

    def _is_ask_last_question(self, msg: str) -> bool:
        q = msg.strip().lower()
        triggers = [
            "tôi vừa hỏi gì", "mình vừa hỏi gì", "vừa hỏi gì",
            "câu trước", "hồi nãy tôi hỏi gì",
            "what did i just ask", "what was my last question", "last question", "previous question",
        ]
        return any(t in q for t in triggers)

    # ==== MCP intent helpers ====
    def _is_generic_mcp_request(self, msg: str) -> bool:
        q = (msg or "").lower()
        triggers = [
            "mcp", "sei mcp", "kết nối mcp", "connect mcp", "connect to mcp",
            "kết nối sei", "connect sei", "use mcp", "dùng mcp"
        ]
        has_specific = ("sei1" in q) or ("0x" in q and len(q) >= 8) or ("tx" in q and len(q) >= 6)
        return any(t in q for t in triggers) and not has_specific

    def _pick_default_status_tool(self, mcp_tools: List[Dict[str, Any]]) -> Optional[str]:
        if not mcp_tools:
            return None
        prios = [
            ("status",), ("network",), ("info",), ("health",), ("ping",),
            ("chain",), ("height",), ("latest",), ("block",)
        ]
        for kws in prios:
            for t in mcp_tools:
                name = (t.get("name") or "").lower()
                desc = (t.get("description") or "").lower()
                if any(kw in name or kw in desc for kw in kws):
                    return t["name"]
        return None  
    
    def _normalize_tool_key(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = s.replace("sei:", "sei_")  # unify colon vs underscore
        return s
    def _extract_python_table_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Quét các block ```python ...``` để tìm:
        - data = { "col": [..], ... }  -> columns/rows từ dict
        - hoặc cặp: columns=[...], rows=[[...], ...]
        Trả về: {"columns": [...], "rows": [[...]], "code_block": "```python ...```"} hoặc None.
        """
        if not text:
            return None
        for m in re.finditer(r"```python\s+([\s\S]*?)```", text, flags=re.IGNORECASE):
            code = m.group(1)

            # 1) Dạng data = { ... }
            dmatch = re.search(r"(?s)\bdata\s*=\s*({[\s\S]*?})", code)
            if dmatch:
                raw = dmatch.group(1)
                try:
                    data = ast.literal_eval(raw)
                    if isinstance(data, dict) and data:
                        cols = list(map(str, data.keys()))
                        vals = list(data.values())
                        # đảm bảo mọi cột là list có cùng độ dài
                        if all(isinstance(v, (list, tuple)) for v in vals):
                            max_len = max(len(v) for v in vals)
                            norm = [list(v) + [""] * (max_len - len(v)) for v in vals]
                            rows = [list(map(lambda x: "" if x is None else str(x), r)) for r in zip(*norm)]
                            return {"columns": cols, "rows": rows, "code_block": m.group(0)}
                except Exception:
                    pass

            # 2) Dạng columns=[...], rows=[[...], ...]
            cmatch = re.search(r"(?s)\bcolumns?\s*=\s*(\[[\s\S]*?\])", code)
            rmatch = re.search(r"(?s)\brows?\s*=\s*(\[[\s\S]*?\])", code)
            if cmatch and rmatch:
                try:
                    cols = ast.literal_eval(cmatch.group(1))
                    rows = ast.literal_eval(rmatch.group(1))
                    if isinstance(cols, list) and isinstance(rows, list) and cols:
                        cols = [str(c) for c in cols]
                        rows = [[("" if c is None else str(c)) for c in (r if isinstance(r, (list, tuple)) else [r])] for r in rows]
                        return {"columns": cols, "rows": rows, "code_block": m.group(0)}
                except Exception:
                    pass

        return None

    def _table_to_image(self, columns: List[str], rows: List[List[str]], _emit) -> Optional[str]:
        """
        Gọi MCP tool tạo ảnh nếu có, không thì fallback qua client tool 'make_table_image'.
        Trả về image_path hoặc None.
        """
        args = {"columns": columns, "rows": rows, "title": None, "theme": "light"}
        # Ưu tiên MCP image tool nếu bridge có
        img_tool = None
        try:
            img_tool = self.mcp.find_image_table_tool()
        except Exception:
            img_tool = None

        if img_tool:
            _emit({"type": "tool_call", "name": img_tool, "args": args})
            out = self.mcp.exec_tool(img_tool, args)
            if isinstance(out, dict) and out.get("image_path"):
                _emit({"type": "tool_result", "name": img_tool, "image_path": out["image_path"]})
                return out["image_path"]

        # Fallback: client tool local
        _emit({"type": "tool_call", "name": "make_table_image", "args": args})
        out_path = run_client_tool("make_table_image", args)
        if isinstance(out_path, str):
            _emit({"type": "tool_result", "name": "make_table_image", "image_path": out_path})
            return out_path
        _emit({"type": "tool_result", "name": "make_table_image", "text": "[client tool returned no path]"})
        return None

    
    
    def _explicit_mcp_tool(self, q: str, mcp_tools: list[dict]) -> str | None:
        """Nếu user gõ đúng tên tool hoặc biến thể của nó, trả về tên tool thật (exact name)."""
        qn = self._normalize_tool_key(q)
        for t in (mcp_tools or []):
            name = t.get("name") or ""
            nn = self._normalize_tool_key(name)
            # chấp nhận: full, bỏ prefix 'sei_', hoặc chỉ phần sau dấu '_' đầu tiên
            candidates = {nn}
            if nn.startswith("sei_"):
                candidates.add(nn[len("sei_"):])          # 'get_chain_info'
            if ":" in (t.get("name") or ""):
                candidates.add((t["name"].lower().split(":", 1)[-1]))  # 'get_chain_info' từ 'sei:get_chain_info'
            # match “từ khóa nằm trong câu”
            for c in candidates:
                if c and c in qn:
                    return t["name"]
        return None

    def _build_mcp_quick_menu(self, mcp_tools: List[Dict[str, Any]]) -> str:
        if not mcp_tools:
            return ("Đã bật MCP bridge nhưng chưa phát hiện tool nào từ server.\n"
                    "Hãy kiểm tra file mcp.json (mcpServers) và biến môi trường.")
        lines = ["MCP đã sẵn sàng. Một số tác vụ bạn có thể yêu cầu ngay:"]
        for t in mcp_tools[:10]:
            nm = t.get("name", "")
            ds = (t.get("description") or "").strip()
            lines.append(f"• {nm}" + (f": {ds}" if ds else ""))
        lines.append("")
        lines.append("Ví dụ:")
        lines.append("- “Kiểm tra trạng thái mạng Sei bằng MCP.”")
        lines.append("- “Lấy số dư ví <địa_chỉ> bằng MCP.”")
        lines.append("- “Tra cứu giao dịch gần nhất của địa chỉ <địa_chỉ> bằng MCP.”")
        return "\n".join(lines)     
# if __name__ == "__main__":
#     try:
#         print("Khởi tạo chatbot với model claude-3-7-sonnet-20250219...")
#         llm = chatbot("claude-3-7-sonnet-20250219")
#         result = llm.asking_stream("cho tôi bảng giá 5 đồng tiền tiêu biểu nhất", session_id="demo")
#     except Exception as e:
#         if "overloaded" in str(e).lower():
#             print("🚥 Model đang quá tải. Hãy chạy lại sau ít phút.", flush=True)
#         else:
#             raise

