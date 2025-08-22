# chatbot.py
import os, re, anthropic
from typing import Any, Dict, List, Optional
from tools import get_tools, run_client_tool
from mcp_bridge import MCPBridge  # dùng MCP server(s) có sẵn

SYSTEM_PROMPT = (
    "You are a helpful assistant specialized in the SEI blockchain.\n"
    "MCP here means Model Context Protocol.\n"
    "You have access to MCP tools (prefixed `sei:`) for live SEI data. "
    "Prefer MCP tools over browsing. Do NOT say 'I don't have a direct connection' — "
    "if a tool is needed, CALL it; if a tool fails, state which tool failed and why.\n"
    "When tabular data helps, call a PNG-rendering tool (e.g., `make_table_image` or an MCP tool that outputs images). "
    "Do not print ASCII/Markdown tables."
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

    # ---------------- public ----------------
    def reset(self, session_id: str):
        self.mem.clear(session_id)

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
                    "content": f'{{"path":"{out_path}"}}'
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
                    "content": json.dumps({"path": img_path}, ensure_ascii=False),
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

    def _parse_ascii_or_md_table(self, raw: str) -> Optional[Dict[str, List[List[str]]]]:
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
