# main.py

"""
项目命令行主入口。

职责：
1. 读取用户输入的研究问题
2. 通过 runtime 执行完整 research workflow
3. 输出最终研究报告

说明：
- 该文件只保留入口职责
- 模型调用、节点逻辑、搜索实现、workflow 编排均已拆分到独立模块
"""

from services.workflow_runner import run_full_v2_workflow


def main():
    """
    执行项目主流程。

    流程：
    1. 获取研究问题
    2. 校验输入是否为空
    3. 通过 runtime 执行 full v2 workflow
    4. 保存标准运行产物
    5. 输出最终报告
    """
    question = input("请输入你的研究问题：\n> ").strip()

    # 空输入直接返回，避免构建无意义任务
    if not question:
        print("研究问题不能为空。")
        return

    result = run_full_v2_workflow(
        question=question,
        save_artifacts=True,
    )
    state = result["state"]
    summary = result["summary"]

    print("\n========== 最终研究报告 ==========\n")
    print(state.get("final_report", "未生成报告"))

    print("\n========== 运行摘要 ==========\n")
    print(f"run_id: {summary['run_id']}")
    print(f"status: {summary['status']}")
    print(f"report_validation_valid: {summary['report_validation_valid']}")


if __name__ == "__main__":
    main()
