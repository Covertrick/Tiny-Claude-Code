import yaml
from pathlib import Path

from ..config import SKILLS_DIR, WORKDIR


class SkillLoader:
    """扫描 skills/*/SKILL.md，提供目录摘要与按名加载全文。"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict[str, str]] = {}
        self.scan()

    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """按行拆 YAML frontmatter，兼容 \\r\\n。

        失败或没有 frontmatter 时返回 ({}, 原文)。
        """
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            return {}, text

        closing_index = next(
            (index for index, line in enumerate(lines[1:], start=1)
             if line.rstrip("\r\n") == "---"),
            None,
        )
        if closing_index is None:
            return {}, text
        frontmatter = "".join(lines[1:closing_index])
        body = "".join(lines[closing_index + 1:])

        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return metadata, body

    def scan(self) -> None:
        """重新扫描技能目录，刷新 self.skills。"""
        self.skills.clear()
        if not self.skills_dir.exists():
            return None

        skills_root = self.skills_dir.resolve()
        for manifest in sorted(self.skills_dir.glob("*/SKILL.md")):
            if (not manifest.is_file()
                    or not manifest.resolve().is_relative_to(skills_root)):
                continue
            content = manifest.read_text(encoding="utf-8")
            metadata, body = self.parse_frontmatter(content)
            raw_name = metadata.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            name = name or manifest.parent.name
            raw_description = metadata.get("description")
            description = raw_description.strip() if isinstance(raw_description, str) else ""
            description = description or body.split("\n", 1)[0]
            description = " ".join(str(description).lstrip("# ").split())
            self.skills[name] = {
                "name": name,
                "description": description,
                "content": content,
            }

    def catalog(self) -> str:
        """生成「- name: description」目录文本，供系统提示使用。"""
        if not self.skills:
            return "Error: 没有找到技能"
        return "\n".join(
            f"- {skill['name']}: {skill['description']}"
            for skill in self.skills.values()
        )

    def load(self, name: str) -> str:
        """按名称返回完整 SKILL.md；未知名称时列出可用技能。"""
        skill = self.skills.get(name)
        if skill:
            return skill["content"]
        available = ",".join(self.skills) or "none"
        return f"Error: 未找到技能 {name}\n可用技能: {available}"


SKILL_LOADER = SkillLoader(SKILLS_DIR)


def build_system_prompt() -> str:
    """拼父 Agent 系统提示：工作目录、todo / 持久化任务 / SubAgent / 技能。"""
    return (
        f"你是一个在 {WORKDIR} 运行的编程 Agent。"
        "简单多步骤会话内规划用 todo_write（内存列表，覆盖更新）；"
        "同一时间只能有一个 in_progress。"
        "若步骤之间有先后依赖、需要持久化跟踪，使用任务系统："
        "先 create_task 建齐所有节点，根据返回的 task_xxxxxxxx ID，"
        "再用 update_task 的 addBlockedBy 添加依赖；"
        "执行时 claim_task → 干活 → complete_task；可用 list_tasks / get_task 查看。"
        "不要编造任务 ID，必须使用 create_task 返回的精确 ID。"
        "耗时且可独立运行的 bash 可设 run_in_background=true，"
        "结果会在后续轮次以 task_notification 注入。"
        "遇到需要专注探索或相对独立的子任务时，使用 task 交给子 Agent 执行，"
        "你根据子 Agent 返回的总结继续决策；简单一步操作可直接使用基础工具。"
        f"技能可用:\n{SKILL_LOADER.catalog()}\n\n"
        "需要完整技能说明时，用 load_skill 按名称加载。"
    )


SYSTEM_PROMPT = build_system_prompt()

SUB_SYSTEM_PROMPT = (
    f"你是一个在 {WORKDIR} 运行的编程 Agent。"
    "完成交给你的任务,然后返回一个简洁的总结。"
)
