import yaml
from pathlib import Path

from ..config import SKILLS_DIR, WORKDIR


class SkillLoader:
    """技能加载器"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict[str, str]] = {}
        self.scan()

    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """解析 YAML frontmatter，返回 (元数据字典, 正文)，如果解析失败则返回空字典和原始文本"""
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
        """扫描技能目录，加载所有技能"""
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
        """返回技能目录"""
        if not self.skills:
            return "Error: 没有找到技能"
        return "\n".join(
            f"- {skill['name']}: {skill['description']}"
            for skill in self.skills.values()
        )

    def load(self, name: str) -> str:
        """加载技能"""
        skill = self.skills.get(name)
        if skill:
            return skill["content"]
        available = ",".join(self.skills) or "none"
        return f"Error: 未找到技能 {name}\n可用技能: {available}"


SKILL_LOADER = SkillLoader(SKILLS_DIR)


def build_system_prompt() -> str:
    """构建系统提示词"""
    return (
        f"你是一个在 {WORKDIR} 运行的编程 Agent。"
        "开始任何多步骤任务前，先用 todo_write 规划步骤；"
        "执行过程中及时更新任务状态（pending / in_progress / completed）。"
        "同一时间只能有一个 in_progress。"
        "遇到需要专注探索或相对独立的子任务时，使用 task 交给子 Agent 执行，"
        "你根据子 Agent 返回的总结继续决策；简单一步操作可直接使用基础工具。"
        f"技能可用:\n{SKILL_LOADER.catalog()}\n\n"
        "使用 load_skill 加载技能时，使用 load_skill 读取完整的技能说明。"
    )


SYSTEM_PROMPT = build_system_prompt()

SUB_SYSTEM_PROMPT = (
    f"你是一个在 {WORKDIR} 运行的编程 Agent。"
    "完成交给你的任务,然后返回一个简洁的总结。"
)
