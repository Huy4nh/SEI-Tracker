# mcp_bridge.py
import os, json, base64, tempfile, traceback, threading, asyncio
from typing import Any, Dict, List, Optional, Tuple
import re
# ===== Import API MCP mới (1.13.x) =====
MCP_AVAILABLE = True
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception as e:
    MCP_AVAILABLE = False
    print("[MCP] Python MCP SDK import failed:", type(e).__name__, e)
    traceback.print_exc()

class MCPBridge:

    def __init__(self, config_path: str = "mcp.json"):
        self.config_path = config_path

        # background loop & thread
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._san_to_full: Dict[str, str] = {}   # sanitized -> "server:tool"
        self._full_to_san: Dict[str, str] = {}   # "server:tool" -> sanitized

        # MCP state (chỉ truy cập trong loop nền)
        self._sessions: Dict[str, ClientSession] = {}    # server_name -> session
        self._tools: Dict[str, Tuple[str, Dict[str, Any]]] = {}  # full_tool_name -> (server_name, meta)
        from contextlib import AsyncExitStack
        self._AsyncExitStack = AsyncExitStack
        self._stacks: Dict[str, Any] = {}  # server_name -> AsyncExitStack

        self._started = False

    # ---------- public ----------
    def _sanitize_name(self, full: str) -> str:
        # thay mọi ký tự không hợp lệ bằng "_"
        s = re.sub(r"[^a-zA-Z0-9_-]", "_", full)
        # gộp nhiều "_" liên tiếp
        s = re.sub(r"_+", "_", s)
        # cắt chiều dài nếu cần
        return s[:128]

    def start(self) -> None:
        """
        Khởi động background loop (nếu chưa) và kết nối servers đồng bộ (block tới khi xong).
        Gọi an toàn ở bất kỳ thread nào, kể cả khi uvicorn đang chạy loop của nó.
        """
        if not MCP_AVAILABLE:
            print("[MCP] Python MCP SDK not available (see import error above).")
            return

        self._ensure_loop_thread()

        # chạy phần connect trong loop nền
        try:
            self._run_coro_blocking(self._start_async())
        except Exception as e:
            print(f"[MCP] Start failed: {type(e).__name__}: {e}")
            traceback.print_exc()

    async def start_async(self) -> None:
        """Nếu muốn tự await trong async context, dùng hàm này. (Không bắt buộc)"""
        if not MCP_AVAILABLE:
            print("[MCP] Python MCP SDK not available.")
            return
        self._ensure_loop_thread()
        await self._start_async()

    def anthropic_tools(self) -> List[Dict[str, Any]]:
        # Truy cập an toàn: copy snapshot từ loop nền
        def _get():
            return [meta for (_, meta) in self._tools.values()]
        return self._run_func_in_loop(_get) or []

    def is_mcp_tool(self, name: str) -> bool:
        def _has():
            return name in self._tools
        return bool(self._run_func_in_loop(_has))
    def _resolve_full_name(self, maybe_san: str) -> Optional[str]:
        # nếu đã là full (có trong map) thì trả ngay
        if maybe_san in self._san_to_full:
            return self._san_to_full[maybe_san]
        # hoặc nếu đã là full (chứa ':') và có map ngược
        if ":" in maybe_san and maybe_san in self._full_to_san:
            return maybe_san
        # không biết -> None
        return None
    def exec_tool(self, full_or_san: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Nhận tên tool ở dạng sanitize (ví dụ: 'sei_get_chain_info') hoặc full 'server:tool'.
        Luôn trả về dict {"text": "..."} hoặc {"image_path": "..."}.
        """
        try:
            if not full_or_san:
                return {"text": "[MCP] tool name is empty"}

            # Resolve: sanitize -> full "server:tool"
            full = self._resolve_full_name(full_or_san)
            if not full:
                return {"text": f"[MCP] unknown tool: {full_or_san}"}

            # Lấy tên sanitize để tra self._tools (self._tools lưu key = sanitize)
            san = self._full_to_san.get(full, full_or_san)

            # Chạy coroutine thực thi trên loop nền
            result = self._run_coro_blocking(self._exec_tool_async(san, args or {}))
            return result if isinstance(result, dict) else {"text": str(result)}
        except Exception as e:
            return {"text": f"[MCP] exec_tool error: {type(e).__name__}: {e}"}


    def find_image_table_tool(self) -> Optional[str]:
        def _find():
            for name, (_srv, meta) in self._tools.items():
                nm = meta["name"].lower()
                desc = (meta.get("description") or "").lower()
                if ("table" in nm or "table" in desc) and any(
                    k in nm or k in desc for k in ("image", "png", "render", "plot", "chart")
                ):
                    return name
            return None
        return self._run_func_in_loop(_find)

    # ---------- internal: loop/thread ----------
    def _ensure_loop_thread(self):
        if self._loop and self._thread and self._thread.is_alive():
            return
        # tạo loop riêng và chạy ở background thread
        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_runner, name="MCPLoopThread", daemon=True)
        self._thread.start()
        self._loop_ready.wait(timeout=10)

        if not self._loop:
            raise RuntimeError("Failed to start MCP background loop")

    def _run_coro_blocking(self, coro: asyncio.Future) -> Any:
        """
        Chạy 1 coroutine trên loop nền và đợi kết quả (blocking) — an toàn vì loop ở thread khác.
        """
        if not self._loop:
            raise RuntimeError("MCP loop not started")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    def _run_func_in_loop(self, fn):
        """
        Chạy 1 hàm đồng bộ nhỏ ngay trong thread loop để truy cập state an toàn.
        """
        async def _wrapper():
            return fn()
        return self._run_coro_blocking(_wrapper())

    # ---------- internal: connect & tools ----------
    async def _start_async(self):
        if self._started:
            return
        cfg = await self._load_config()
        servers = cfg.get("mcpServers") or cfg.get("servers") or {}
        if not isinstance(servers, dict) or not servers:
            print("[MCP] No servers in config.")
            self._started = True
            return

        for name, spec in servers.items():
            cmd = (spec or {}).get("command")
            args = (spec or {}).get("args", [])
            env  = (spec or {}).get("env", None)
            if not cmd:
                print(f"[MCP] Server '{name}' missing command — skip.")
                continue
            cmd_resolved = self._resolve_cmd(cmd)
            try:
                await self._connect_and_list(name, cmd_resolved, args, env)
            except Exception as e:
                print(f"[MCP] Connect '{name}' failed: {type(e).__name__}: {e}")
                traceback.print_exc()
                continue

        self._started = True

    async def _load_config(self) -> Dict[str, Any]:
            if not os.path.exists(self.config_path):
                print(f"[MCP] Config not found: {self.config_path} — skipping MCP.")
                return {}
            try:
                # Đọc đồng bộ là OK vì đang ở background thread
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[MCP] Read config error: {e}")
                import traceback; traceback.print_exc()
                return {}

    async def _connect_and_list(self, name: str, cmd: str, args: List[str], env_map: Optional[Dict[str, str]]):
        merged_env = os.environ.copy()
        if isinstance(env_map, dict):
            for k, v in env_map.items():
                if v is not None:
                    merged_env[str(k)] = str(v)

        # mở stdio client & ClientSession bằng AsyncExitStack để giữ persistent
        stack = self._AsyncExitStack()
        stdio_transport = await stack.enter_async_context(
            stdio_client(StdioServerParameters(command=cmd, args=args, env=merged_env))
        )

        if isinstance(stdio_transport, tuple) and len(stdio_transport) == 2:
            reader, writer = stdio_transport
            session = await stack.enter_async_context(ClientSession(reader, writer))
        else:
            # 1 số version trả thẳng client wrapper
            session = await stack.enter_async_context(stdio_transport)  # type: ignore

        await session.initialize()
        self._sessions[name] = session
        self._stacks[name] = stack

        # list tools
        resp = await session.list_tools()
        tools = getattr(resp, "tools", []) or []
        count = 0
        for t in tools:
            count += 1
            full = f"{name}:{t.name}"                 # tên gốc có dấu ':'
            san  = self._sanitize_name(full)          # tên hợp lệ cho Anthropic

            # lưu map 2 chiều
            self._san_to_full[san] = full
            self._full_to_san[full] = san

            meta = {
                "name": san,                          # <-- QUAN TRỌNG: đưa tên đã sanitize cho Claude
                "description": getattr(t, "description", "") or "",
                "input_schema": getattr(t, "input_schema", None)
                                or getattr(t, "inputSchema", {"type": "object", "properties": {}}),
            }
            self._tools[san] = (name, meta)  # lưu cả tên server để gọi tool sau này 
        print(f"[MCP] Server '{name}' ready with {count} tool(s).")

    # ---------- internal: exec ----------
    async def _exec_tool_async(self, san_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # san_name: tên đã sanitize (key trong self._tools)
        if san_name not in self._tools:
            return {"text": f"[MCP] unknown tool: {san_name}"}

        server_name, _ = self._tools[san_name]
        # Map ngược về tên full "server:tool" để lấy local name
        full = self._san_to_full.get(san_name, san_name)
        local_tool = full.split(":", 1)[1] if ":" in full else full

        session = self._sessions.get(server_name)
        if session is None:
            return {"text": f"[MCP] server '{server_name}' not connected"}

        try:
            result = await session.call_tool(local_tool, args or {})
        except Exception as e:
            return {"text": f"[MCP] call_tool error on {full}: {type(e).__name__}: {e}"}

        # 1) dict đặc biệt
        if isinstance(result, dict):
            out = self._normalize_payload_dict(result)
            if out:
                return out

        # 2) MCP result .content (list các text item)
        payload = getattr(result, "content", None)
        if isinstance(payload, list):
            texts = self._extract_texts_from_payload(payload)
            if texts:
                raw = "\n".join(t for t in texts if t).strip()
                pretty = self._maybe_parse_json_text(raw)
                return {"text": pretty if pretty is not None else raw}

        # 3) fallback stringify
        try:
            return {"text": json.dumps(result, ensure_ascii=False, default=str)}
        except Exception:
            return {"text": str(result)}


    # ---------- helpers ----------
    def _resolve_cmd(self, cmd: str) -> str:
        if os.name == "nt":
            if cmd.lower() == "npx":  return "npx.cmd"
            if cmd.lower() == "npm":  return "npm.cmd"
        return cmd

    def _normalize_payload_dict(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # ảnh theo đường dẫn
        p = payload.get("path") or payload.get("image_path")
        if isinstance(p, str) and p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return {"image_path": p}
        # ảnh base64
        b64 = payload.get("png_base64") or payload.get("image_base64")
        if isinstance(b64, str):
            try:
                raw = base64.b64decode(b64)
                fd, temp_path = tempfile.mkstemp(prefix="mcp_img_", suffix=".png")
                os.close(fd)
                with open(temp_path, "wb") as f:
                    f.write(raw)
                return {"image_path": temp_path}
            except Exception as e:
                return {"text": f"[MCP] invalid base64: {e}"}
        # text (thử pretty json)
        if isinstance(payload.get("text"), str):
            pretty = self._maybe_parse_json_text(payload["text"])
            return {"text": pretty if pretty is not None else payload["text"]}
        return None

    def _maybe_parse_json_text(self, s: str) -> Optional[str]:
        s = (s or "").strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return None

    def _extract_texts_from_payload(self, payload_list) -> List[str]:
        texts = []
        for p in payload_list:
            if isinstance(p, dict):
                if p.get("type") == "text" and isinstance(p.get("text"), str):
                    texts.append(p["text"])
                continue
            ttype = getattr(p, "type", None)
            ttext = getattr(p, "text", None)
            if ttype == "text" and isinstance(ttext, str):
                texts.append(ttext)
        return texts
