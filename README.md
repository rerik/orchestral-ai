# Project Name

This project demonstrates an agent framework capable of interacting with external tools, such as the shell (bash), and integrating with Large Language Models (LLMs).

## 📂 Structure

The project structure is organized as follows:

*   **`src/`**: Contains the core application logic.
    *   **`main.py`**: The main script that defines the agent's capabilities, including functions for running bash commands (`run_bash`), managing tool calls, and executing the primary agent loop (`agent_loop`).
*   **`prompts/`**: Contains prompt templates used by the agent.
    *   **`system_prompt.txt`**: The system prompt that defines the agent's behavior and available tools.

## 💡 Purpose

The primary purpose of this code is to simulate an AI agent workflow. It showcases:
1.  **Tool Use:** Defining and utilizing external tools (e.g., `bash` execution).
2.  **Safety/Permissions:** Implementing checks (`check_bash_permission`) to restrict shell commands to a predefined list of allowed utilities, enhancing security.
3.  **Agent Loop:** Managing the conversation flow between user input, LLM responses, and tool execution until a task is completed or maximum turns are reached.

## 🚀 How to Run

### Prerequisites

You must have Python installed. The script depends on the `requests` and `python-dotenv` libraries.

```bash
pip install requests python-dotenv
```

### Environment Variables (via `.env`)

1. Create a `.env` file in the project root (this file is excluded from version control via `.gitignore`):

```bash
echo 'DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' > .env
```

2. Replace `sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` with your actual DeepSeek API key.

### Execution

Run the main script from the root directory, passing a task prompt as an argument:

```bash
python src/main.py "list all files in the current directory"
```

If no prompt is provided, the agent will exit.
