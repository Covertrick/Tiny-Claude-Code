import os
import subprocess

from dotenv import load_dotenv

load_dotenv(override=True)

#request 代替Anthropic
import requests
import json
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
END_POINT = f"{BASE_URL.rstrip('/')}/chat/completions"

SYSTEM_PROMPT = f"你的Agent在 {os.getcwd()}运行，请根据系统提示完成任务"

# OPENAI TOOLS 定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在本地执行shell命令",
            "parameters": {
                "type": "object",
                "properties" :{
                    "command": {"type": "string", "description": "要执行的shell命令"}
                },
                "required": ["command"]
            }
        }
    }
]

#============Bash Tool 实现============
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: 危险操作被拒绝"
    
    try:
        r = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, timeout=120,
            # Windows 默认 GBK，读 UTF-8 文件会解码失败；用 utf-8 + replace 更稳
            encoding="utf-8", errors="replace",
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[:5000] if out else "命令执行成功，但未返回任何输出"
    except subprocess.TimeoutExpired:
        return "Error: 命令执行超时"
    except (FileNotFoundError, OSError) as e:
        return f"Error: 命令执行失败\n错误信息: {str(e)}"

# ========== 核心Agent循环====================
def agent_loop(messages: list):
    while True:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model" : MODEL_NAME,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "max_tokens": 5000
        }

        response = requests.post(END_POINT, headers = headers, json = payload, timeout = 180)
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        msg = choice["message"]

        # 将assistant的回复添加到messages中
        messages.append(msg)

        # 如果不是tool_calls，则返回结果
        if not msg.get("tool_calls"):
            return
        
        # 处理tool_calls
        tool_results = []
        for tool_call in msg["tool_calls"]:
            func = tool_call["function"]

            if func["name"] == "bash":
                args = json.loads(func["arguments"])
                command = args["command"]
                print(f"执行命令: {command}")
                out_put = run_bash(command)
                print(f"命令输出: {out_put}")

                #组装工具返回消息格式
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": func["name"],
                    "content": out_put
                })
        
        # 必须用 extend：逐条追加 tool 消息，不能 append 整个列表
        messages.extend(tool_results)

# ========== 终端交互入口 ==========
if __name__ == "__main__":
    print(f"Agent正在运行，模型: {MODEL_NAME}")
    print("输入任务，回车发送，输入exit退出。 \n")

    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m") 
        except (EOFError, KeyboardInterrupt):
            break
        if query.lower() in ("exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        final_resp = history[-1]
        if final_resp.get("role") == "assistant" and final_resp.get("content"):
            print(final_resp["content"])
        print()
