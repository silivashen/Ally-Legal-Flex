"""Normalize explicit internal policy labels in generated analysis only."""

from __future__ import annotations

from collections.abc import Sequence
import re


def normalize_policy_labels(value: object, policy_ids: Sequence[str | int]) -> object:
    """Use only validated cited IDs; never infer policy identity from list order."""
    if isinstance(value, list):
        return [normalize_policy_labels(part, policy_ids) for part in value]
    if not isinstance(value, str) or not policy_ids:
        return value
    identifiers = sorted(
        {str(policy_id).strip() for policy_id in policy_ids if str(policy_id).strip()},
        key=len, reverse=True,
    )
    if not identifiers:
        return value
    identifier = "(?:" + "|".join(re.escape(key) for key in identifiers) + ")"
    # Ambiguous quantities and compound references are left unchanged.
    end = (
        r"(?![0-9A-Za-z_%％-]|[.．][0-9A-Za-z_]"
        r"|[零〇一二三四五六七八九十百千万亿两年月日天周元项倍个次条份笔种成]"
        r"|季度|小时|分钟|秒|人民币|美元|欧元"
        r"|(?:[、,，/–—]|和|及|至|到)[ \t]*[0-9零〇一二三四五六七八九十])"
    )
    chinese = (
        r"公司政策[ \t]*(?:编号[ \t]*[:：]?[ \t]*)?"
        r"(?:#[ \t]*)?" + identifier + end
    )
    english = (
        r"\b(?:the[ \t]+)?company[ \t]+policy[ \t]*"
        r"(?:(?:no\.?|id[:：]?|#)[ \t]*)?" + identifier + end
    )
    chinese_explicit = (
        r"公司[ \t]*政策[ \t]*(?:"
        r"[（(][ \t]*(?:政策[ \t]*)?(?:ID|编号|#)[ \t]*[:：]?[ \t]*"
        + identifier + r"[ \t]*[）)]"
        r"|(?:ID|编号|#)[ \t]*[:：]?[ \t]*" + identifier + end + r")"
    )
    english_explicit = (
        r"\b(?:the[ \t]+)?company[ \t]+policy[ \t]*"
        r"\([ \t]*(?:policy[ \t]*)?(?:ID|no\.?|#)[ \t]*[:：]?[ \t]*"
        + identifier + r"[ \t]*\)"
    )
    value = re.sub(chinese_explicit, "所选公司政策", value, flags=re.IGNORECASE)
    value = re.sub(english_explicit, "the selected company policy", value, flags=re.IGNORECASE)
    value = re.sub(chinese, "所选公司政策", value)
    return re.sub(english, "the selected company policy", value, flags=re.IGNORECASE)

