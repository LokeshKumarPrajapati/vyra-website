import re
import os

def remove_open_interpreter():
    vyra_path = "vyra.py"
    if os.path.exists(vyra_path):
        with open(vyra_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove import
        content = re.sub(r"from open_interpreter_agent import OpenInterpreterAgent.*?# type: ignore\n*", "", content)

        # Remove tool declarations
        content = re.sub(r"open_interpreter_chat_tool\s*=\s*\{.*?\n\}\n*", "", content, flags=re.DOTALL)
        content = re.sub(r"open_interpreter_tools\s*=\s*\[.*?\n\]\n*", "", content, flags=re.DOTALL)
        content = re.sub(r"\s*\+\s*open_interpreter_tools", "", content)

        # Remove prompts related to open_interpreter_chat
        content = re.sub(r"\s*\"  \* `open_interpreter_chat`:.*?\"\n?", "", content)
        content = re.sub(r"\s*\"  \* `open_interpreter_chat` —.*?\"\n?", "", content)
        content = re.sub(r", and `open_interpreter_chat` for FULL COMPUTER CONTROL \(clicking, typing, opening apps, automating screen flows\)", "", content)
        
        # Replace the entire prompt string for CODE EXECUTION
        content = re.sub(
            r"\"- CODE EXECUTION & COMPUTER CONTROL.*?(?=\")\"", 
            "\"- CODE EXECUTION: You can run actual code! Use `run_code` to run code, and `run_shell_command` for terminal commands. When he asks you to run code, USE these tools!\"", 
            content, flags=re.DOTALL
        )

        content = re.sub(
            r"\"CODE EXECUTION & FULL COMPUTER CONTROL \(CRITICAL CAPABILITY\):.*?(?=\")\"",
            "\"CODE EXECUTION: You have the ability to DIRECTLY EXECUTE code on the user's system. Use these tools immediately when requested:\n  * `run_code` — Execute Python/JavaScript/shell code snippets and return real output. Use when user says 'run this code', 'execute this', 'test this function'.\n  * `run_shell_command` — Run any terminal command: 'dir', 'pip install X', 'ipconfig', 'python script.py', etc.\"",
            content, flags=re.DOTALL
        )

        # Remove initialization
        content = re.sub(r"\s*# Code execution via Open Interpreter\s*self\.open_interpreter_agent = OpenInterpreterAgent\(\)\s*", "\n", content)

        # Remove from handle_tool_calls list
        content = content.replace(", \"open_interpreter_chat\"", "")

        # Remove implementation block
        pattern_impl = r"\s*elif fc\.name == \"open_interpreter_chat\":.*?function_responses\.append\(types\.FunctionResponse\(\s*# type: ignore\s*id=fc\.id, name=fc\.name,\s*response=\{\s*\"result\": \"Open Interpreter is working on your task\.\.\. will report when done\.\"\s*\}\s*\)\)\s*"
        content = re.sub(pattern_impl, "\n\n                                ", content, flags=re.DOTALL)

        with open(vyra_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated vyra.py")

    server_path = "server.py"
    if os.path.exists(server_path):
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        content = re.sub(r"\s*\"open_interpreter_chat\": True,?", "", content)
        
        with open(server_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Updated server.py")

if __name__ == "__main__":
    remove_open_interpreter()
