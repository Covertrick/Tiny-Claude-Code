from .config import MODEL_NAME
from .core.loop import agent_loop
from .hooks import trigger_hook
from .skill_load import SYSTEM_PROMPT


def main() -> None:
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

        trigger_hook("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history, active_request=query)

        final_resp = history[-1]
        if final_resp.get("role") == "assistant" and final_resp.get("content"):
            print(final_resp["content"])
        print()


if __name__ == "__main__":
    main()
