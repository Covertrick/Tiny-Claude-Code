from ..skill_load.loader import SKILL_LOADER


def load_skill(name: str) -> str:
    """load_skill 工具入口。"""
    return SKILL_LOADER.load(name)
