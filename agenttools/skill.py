from ..skill_load.loader import SKILL_LOADER


def load_skill(name: str) -> str:
    """load_skill 工具入口：按技能名返回完整 SKILL.md 文本。"""
    return SKILL_LOADER.load(name)
