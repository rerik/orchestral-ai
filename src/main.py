import os
import subprocess
import re
import json
import sys
import shutil

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------
#  Load environment variables from .env
# ---------------------------------------------------------

load_dotenv()


# ---------------------------------------------------------
#  BASH
# ---------------------------------------------------------


ALLOWED_CMD = [
    "ls",
    "cd",
    "pwd",
    "cat"
]


def is_allowed(cmd: str) -> bool:
    for allowed in ALLOWED_CMD:
        if cmd.startswith(allowed):
            return True
    return False


def check_bash_permission(cmd: str) -> bool:
    delimiters = r'&&|\|\||>>|<<|\||;|&|>|<'
    cmd_parts = [part.strip() for part in re.split(delimiters, cmd) if part.strip()]
    if all(map(is_allowed, cmd_parts)):
        return True
    max_width = shutil.get_terminal_size().columns - 2
    question = f"Execute `{cmd}`? y/n\n"
    wrap = '# ' + '-' * min((len(question) - 2), max_width)
    expliscit_permission: str = input('\n' + wrap + '\n' + question + wrap + '\n')
    if expliscit_permission.lower() in ["y", "yes"]:
        return True
    return False


def run_bash(command: str) -> str:
    try:
        if check_bash_permission(command):
            command_result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
            out = command_result.stdout + (f"\nSTDERR:\n{command_result.stderr}" if command_result.stderr else "")
            return f"Exit code: {command_result.returncode}\n{out}"
        return "Error: not allowed by user"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"
        
        
# ---------------------------------------------------------
#  TOOLS
# ---------------------------------------------------------


TOOLS = {
    "bash": run_bash
}


def call_tool(name: str, arguments: dict) -> str:
    func = TOOLS.get(name)
    if not func:
        return f"Error: unknown tool '{name}'"
    try:
        return func(**arguments)
    except Exception as e:
        return f"Error calling {name}: {e}"
        
        
# ---------------------------------------------------------
#  LLM
# ---------------------------------------------------------


# Load API key from environment (populated via .env by dotenv)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not found. Create a .env file in the project root with:")
    print('  DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    sys.exit(1)

LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"
LLM_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}


LLM_TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a shell command and return the output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute."}
            },
            "required": ["command"]
        }
    }
}]


# ---------------------------------------------------------
#  SYSTEM PROMPT
# ---------------------------------------------------------


SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts", "system_prompt.txt")
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read().strip()


def call_llm(messages):
    payload = {
        "model": LLM_MODEL, 
        "messages": messages, 
        "tools": LLM_TOOLS, 
        "tool_choice": "auto",
        "temperature": 0.1, 
        "max_tokens": 4096
    }
    llm_http_response = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=LLM_HEADERS)
    llm_http_response.raise_for_status()
    msg = llm_http_response.json()["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls") or []
    return content, tool_calls
    
    
# ---------------------------------------------------------
#  CHAT LOOP
# ---------------------------------------------------------


MAX_TURNS = 1000


def agent_turn(messages: list, user_message: str) -> list:
    """Append a user message and run the agent loop until no more tool calls.
    
    Returns the updated messages list.
    """
    messages.append({"role": "user", "content": user_message})
    
    for _ in range(1, MAX_TURNS + 1):
        content, tool_calls = call_llm(messages)
        
        if content:
            print(f"\n🤖 {content}")
        
        if not tool_calls:
            if not content:
                print("(no text output)")
            print()
            return messages
        
        assistant_msg = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)
        
        prefix = "\n" if content else ""
        for tool_call in tool_calls:
            function = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            tool_call_id = tool_call["id"]
            
            print(f"{prefix}🔧 Tool: {function}({json.dumps(arguments, ensure_ascii=False)})")
            result = call_tool(function, arguments)
            print(f"   → {result[:500]}{'...' if len(result)>500 else ''}")
            
            messages.append({
                "role": "tool", 
                "tool_call_id": tool_call_id, 
                "content": result
            })
    
    print(f"\n⚠️ Max turns ({MAX_TURNS}) reached. Stopping.")
    return messages


if __name__ == "__main__":
    print("🤖 Coding Agent — Chat mode")
    print("Type your task below. Type 'exit' or 'quit' to end the session.")
    print()
    
    # Initialise conversation history with the system prompt
    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    
    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 Goodbye!")
            sys.exit(0)
        
        if not user_input:
            continue
        
        if user_input.lower() in ("exit", "quit"):
            print("👋 Goodbye!")
            break
        
        messages = agent_turn(messages, user_input)
