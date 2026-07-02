# Project Agents Overview

This document outlines the structure and potential agents/components within the project.

## Directory Analysis
The current project directory contains the following components:
*   **README.md**: Contains general project information.
*   **src/**: Contains the core source code for the application logic.
    *   **main.py**: Defines the agent loop, bash tool, LLM integration, and permission checks.
*   **prompts/**: Contains prompt templates.
    *   **system_prompt.txt**: Defines the behavior, workflow, and constraints of the coding agent.

## Potential Agents/Components
Based on the structure, potential agents or modules include:
1.  **Core Logic Agent (in src/)**: Responsible for handling main application functionality — executing commands, calling the LLM, and managing the agent loop.
2.  **Prompt Agent (in prompts/)**: Supplies the system-level instructions that govern the agent's behavior and tool usage.
3.  **Documentation Agent**: Manages and updates project documentation (e.g., README.md, AGENTS.md).

Please ensure that any new agent or component is documented here to maintain a clear understanding of the system architecture.
