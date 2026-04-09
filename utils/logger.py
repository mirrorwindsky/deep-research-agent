def log_step(step: str, message: str) -> None:
    """
    打印流程日志，帮助你观察 agent 执行过程。

    参数：
    - step: 当前阶段名称，例如 Plan / Search / Report
    - message: 想打印的具体信息
    """
    print(f"[{step}] {message}")