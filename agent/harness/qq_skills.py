"""QQ 工具契约表。与 tools.qq.QQ_TOOL_NAMES 必须一一对应。"""

from __future__ import annotations

from agent.harness.effect import EffectClass
from agent.harness.skill_contract import SkillManifest

_V = "1.0.0"


def _m(
    name: str,
    effect: EffectClass,
    permissions: list[str],
    description: str,
) -> SkillManifest:
    return SkillManifest(
        name=name,
        version=_V,
        effect_class=effect,
        permissions=permissions,
        sandbox_policy="none",
        description=description,
    )


QQ_SKILL_MANIFESTS: dict[str, SkillManifest] = {
    m.name: m
    for m in (
        _m("web_search", EffectClass.IDEMPOTENT, ["net.read"], "公开检索"),
        _m("fetch_url", EffectClass.IDEMPOTENT, ["net.read"], "打开链接"),
        _m("save_memory", EffectClass.RETRYABLE, ["memory.write"], "写入记忆"),
        _m("get_memory", EffectClass.IDEMPOTENT, ["memory.read"], "检索记忆"),
        _m("delete_memory", EffectClass.IRREVERSIBLE, ["memory.write"], "删除记忆"),
        _m("synthesize_knowledge", EffectClass.RETRYABLE, ["memory.write"], "知识卡片"),
        _m("list_knowledge_cards", EffectClass.IDEMPOTENT, ["memory.read"], "列出卡片"),
        _m("schedule_reminder", EffectClass.RETRYABLE, ["schedule.write"], "创建催办"),
        _m("schedule_list", EffectClass.IDEMPOTENT, ["schedule.read"], "列出待办"),
        _m("schedule_done", EffectClass.IRREVERSIBLE, ["schedule.write"], "完成待办"),
        _m("schedule_cancel", EffectClass.IRREVERSIBLE, ["schedule.write"], "取消待办"),
        _m("download_file", EffectClass.RETRYABLE, ["file.write", "net.read"], "下载文件"),
        _m("list_files", EffectClass.IDEMPOTENT, ["file.read"], "列沙箱文件"),
        _m("list_my_files", EffectClass.IDEMPOTENT, ["file.read"], "列用户文件"),
        _m("send_local_file", EffectClass.IRREVERSIBLE, ["file.send"], "发送本地文件"),
        _m("delete_file", EffectClass.REQUIRES_CONFIRM, ["file.write"], "删除需确认"),
        _m("search_and_send_file", EffectClass.IRREVERSIBLE, ["file.send"], "检索并发送"),
        _m("search_vault", EffectClass.IDEMPOTENT, ["vault.read"], "检索 Vault"),
        _m("write_vault_note", EffectClass.IRREVERSIBLE, ["vault.write"], "写入 Vault"),
    )
}


def manifest_for(name: str) -> SkillManifest | None:
    return QQ_SKILL_MANIFESTS.get(name)


def assert_covers_qq_tools(names: set[str] | frozenset[str]) -> None:
    missing = set(names) - set(QQ_SKILL_MANIFESTS)
    extra = set(QQ_SKILL_MANIFESTS) - set(names)
    if missing or extra:
        raise RuntimeError(f"QQ Skill 契约不一致 missing={missing} extra={extra}")
