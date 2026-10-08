"""记忆候选与最终落库值共用的确定性隐私过滤。"""

import re
import unicodedata
from dataclasses import dataclass

_PHONE = re.compile(r"(?<!\d)1[3-9](?:[ -]?\d){9}(?!\d)")
_IDENTITY_CARD = re.compile(r"(?<!\d)[1-9]\d{16}[\dXx](?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
_EMAIL = re.compile(r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
#: 即时通讯账号（审查 I2）：「微信号 abc12345」「加我QQ 123456789」。
_IM_ACCOUNT = re.compile(r"(?i)(?:微信|wechat|weixin|vx|qq)\s*号?\s*[:：]?\s*[a-z0-9_-]{5,}")
_ADDRESS = re.compile(
    r"(?:住址|收货地址|家庭地址|邮寄地址|address|"
    r"住在|家住|"
    r"(?:省|市|区|县).{0,12}?(?:路|街|巷|道|弄|小区|园|苑|村|镇|大厦|公寓)|"
    r"(?:省|市|区|县).{0,30}?(?:路|街|巷|道|弄).{0,15}?\d+号|"
    r"(?:路|街|巷|道|弄).{0,15}?\d+号)",
    re.IGNORECASE,
)
_HEALTH = re.compile(
    r"健康|疾病|患病|生病|病史|糖尿病|癌症|抑郁症|过敏|残疾|怀孕|备孕|孕期|哺乳|"
    r"吃药|服药|用药|药物|降压药|处方|高血压|血压|血糖|哮喘|失眠|焦虑|看病|住院|手术|"
    r"health|disease|diagnos(?:is|ed)|disabilit(?:y|ies)|pregnan(?:t|cy)",
    re.IGNORECASE,
)
_RELIGION = re.compile(
    r"宗教|信仰|佛教|基督教|天主教|伊斯兰教|穆斯林|道教|犹太教|"
    r"信佛|信教|信主|念佛|吃斋|斋月|斋戒|礼拜|清真|教徒|"
    r"religio(?:n|us)|christian|muslim|buddhis(?:m|t)",
    re.IGNORECASE,
)
_POLITICS = re.compile(
    r"政治|政党|党员|选票|投票倾向|左翼|右翼|民主党|共和党|"
    r"politic(?:s|al)|political party|voting preference",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FilterResult:
    rejected: bool
    reason: str | None = None


def _texts(fact: object) -> tuple[str, ...]:
    if isinstance(fact, str):
        return (fact,)
    values = tuple(
        value
        for name in ("key", "value", "content", "category")
        if isinstance((value := getattr(fact, name, None)), str)
    )
    return values


def _filter(fact: object) -> FilterResult:
    texts = _texts(fact)
    if not texts:
        return FilterResult(rejected=True, reason="invalid_fact")
    # NFKC 处理全角字符；拼接后再扫，避免字段边界拆开标识符。另扫一份去掉全部空白的文本：
    # 正则不跨换行，两条各自干净的内容拼接后（如总结重建）可能凑出完整号码。
    text = unicodedata.normalize("NFKC", "".join(texts))
    compact = re.sub(r"\s+", "", text)
    identifiers = (_PHONE, _IDENTITY_CARD, _BANK_CARD, _EMAIL, _IM_ACCOUNT, _ADDRESS)
    if any(pattern.search(form) for pattern in identifiers for form in (text, compact)):
        return FilterResult(rejected=True, reason="identifier")
    if any(pattern.search(text) for pattern in (_HEALTH, _RELIGION, _POLITICS)):
        return FilterResult(rejected=True, reason="sensitive_inference")
    return FilterResult(rejected=False)


def filter_candidate(fact: object) -> FilterResult:
    """写入前过滤抽取出的候选事实。"""

    return _filter(fact)


def filter_persisted(fact: object) -> FilterResult:
    """合并、规范化后，紧贴落库操作再次过滤最终事实。"""

    return _filter(fact)
