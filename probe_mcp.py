from mcp_bridge import MCPBridge

b = MCPBridge("mcp.json")  # đổi đúng tên file JSON của bạn
b.start()
tools = b.anthropic_tools()
print("TOOLS:", [t["name"] for t in tools])
if tools:
    # gọi thử tool đầu (nếu tool yêu cầu args, hãy xem tools[i]["input_schema"])
    name = tools[0]["name"]
    print("CALL:", name)
    out = b.exec_tool(name, {})
    print("RESULT:", out)
