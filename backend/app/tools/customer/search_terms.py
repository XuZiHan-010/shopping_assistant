"""商品搜索的检索词表：英文 → 中文，以及中文近义词（PRD C2）。

商品名称与描述只有中文，搜索是字面包含匹配：英文显示的顾客用 `shoes` 搜不到「运动鞋」
（2026-10-07 真实评测 QLT-N5-007）；中文也一样，搜「外套」找不到「夹克」、搜「裤子」找不到
「牛仔裤」，助手据此告诉顾客「本店没有」（2026-10-10 真实复测 QLT-N5-003）。
这里给出固定的对应关系，零 LLM 调用、结果可复现——与闸门里
`zh_business_terms_for_english_word` 把英文业务词反查成中文是同一思路。

范围是**常见的商品词、材质词与品类词**，不是通用翻译：没有收录的英文词查不到，由搜索工具在
说明里提示模型改用中文关键词。新增演示品类时在这里补词。
"""

from __future__ import annotations

import re
from typing import Final

#: 英文词（小写、单数）→ 中文检索词。一个英文词可以对应多个中文词，任一命中即返回。
_TERMS: Final[dict[str, tuple[str, ...]]] = {
    # 鞋靴
    "shoe": ("鞋",),
    "footwear": ("鞋", "靴"),
    "sneaker": ("运动鞋",),
    "trainer": ("运动鞋",),
    "boot": ("靴",),
    "loafer": ("乐福鞋",),
    "flat": ("平底鞋",),
    "sandal": ("凉鞋",),
    "heel": ("高跟",),
    # 上装
    "shirt": ("衬衫",),
    "blouse": ("衬衫",),
    "tee": ("T恤", "T 恤"),
    "tshirt": ("T恤", "T 恤"),
    "sweater": ("毛衣", "针织"),
    "jumper": ("毛衣", "针织"),
    "pullover": ("毛衣",),
    "knit": ("针织", "毛衣"),
    "knitwear": ("针织", "毛衣"),
    "cardigan": ("开衫",),
    "jacket": ("夹克", "外套"),
    "coat": ("大衣", "外套"),
    "hoodie": ("卫衣",),
    # 下装与裙装
    "pant": ("裤",),
    "trouser": ("裤",),
    "jean": ("牛仔裤",),
    "denim": ("牛仔",),
    "short": ("短裤",),
    "skirt": ("半裙", "裙"),
    "dress": ("连衣裙",),
    # 配饰
    "scarf": ("围巾",),
    "hat": ("帽",),
    "cap": ("帽",),
    "bag": ("包",),
    "belt": ("腰带", "皮带"),
    "sock": ("袜",),
    "glove": ("手套",),
    # 家居
    "candle": ("蜡烛",),
    "blanket": ("毯",),
    "throw": ("毯",),
    "tablecloth": ("桌布",),
    "board": ("砧板",),
    "mug": ("杯",),
    "cup": ("杯",),
    "plate": ("盘",),
    "bowl": ("碗",),
    "vase": ("花瓶",),
    "towel": ("毛巾",),
    "pillow": ("枕",),
    "cushion": ("抱枕", "靠垫"),
    # 美妆
    "perfume": ("香水",),
    "fragrance": ("香水", "香氛"),
    "cologne": ("香水",),
    "cream": ("面霜", "霜"),
    "moisturizer": ("面霜", "保湿"),
    "moisturiser": ("面霜", "保湿"),
    "cleanser": ("洁面",),
    "serum": ("精华",),
    "lotion": ("乳",),
    "skincare": ("面霜", "精华", "洁面"),
    "lipstick": ("口红",),
    "mask": ("面膜",),
    # 材质
    "wool": ("羊毛",),
    "merino": ("美利奴",),
    "cashmere": ("羊绒",),
    "linen": ("亚麻",),
    "silk": ("真丝", "丝"),
    "cotton": ("棉",),
    "canvas": ("帆布",),
    "leather": ("皮",),
    "sheepskin": ("羊皮",),
    "oak": ("橡木",),
    "ceramic": ("陶",),
    # 款式与场景
    "waterproof": ("防泼水", "防水"),
    "hiking": ("徒步",),
    "retro": ("复古",),
    "vintage": ("复古",),
    "floral": ("碎花", "印花"),
    "plaid": ("格纹",),
    "check": ("格纹",),
    "slim": ("修身",),
    "loose": ("宽松",),
    "casual": ("休闲",),
    "commute": ("通勤",),
    "office": ("通勤",),
    "gift": ("礼盒", "礼品"),
}

#: 品类词 → `products.category` 的闭集取值。比商品词宽得多（「women」会命中全部女装），
#: 所以只在查询里没有任何商品词命中时才用，免得把具体商品挤出结果。
_CATEGORY_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "women": ("女装",),
    "womenswear": ("女装",),
    "ladies": ("女装",),
    "men": ("男装",),
    "menswear": ("男装",),
    "home": ("家居",),
    "homeware": ("家居",),
    "beauty": ("美妆",),
    "makeup": ("美妆",),
    "cosmetic": ("美妆",),
    "clothing": ("女装", "男装"),
    "clothes": ("女装", "男装"),
    "apparel": ("女装", "男装"),
}

#: 多词短语先于单词匹配（按小写、单空格归一后的整串查）。
_PHRASES: Final[dict[str, tuple[str, ...]]] = {
    "t-shirt": ("T恤", "T 恤"),
    "cutting board": ("砧板",),
    "chopping board": ("砧板",),
    "chelsea boot": ("切尔西靴",),
    "chelsea boots": ("切尔西靴",),
    "ballet flat": ("芭蕾平底鞋",),
    "ballet flats": ("芭蕾平底鞋",),
    "scented candle": ("香氛蜡烛", "蜡烛"),
    "face wash": ("洁面",),
    "face cream": ("面霜",),
    "work shoes": ("鞋",),
    "commuter shoes": ("鞋",),
}

#: 中文近义词与上位词 → 商品名称里实际出现的字样。键按「查询词包含它」匹配，
#: 所以「秋季外套」「薄外套」都能命中「外套」。只收名称里的写法与口语说法不一致的词。
_ZH_SYNONYMS: Final[dict[str, tuple[str, ...]]] = {
    "外套": ("夹克", "开衫", "大衣"),
    "上衣": ("衬衫", "毛衣", "针织", "T恤"),
    "针织衫": ("针织", "毛衣"),
    "毛衫": ("毛衣", "针织"),
    "打底": ("衬衫", "毛衣", "针织"),
    "裤子": ("裤",),
    "长裤": ("裤",),
    "下装": ("裤", "裙"),
    "裙子": ("裙",),
    "鞋子": ("鞋", "靴"),
    "球鞋": ("运动鞋",),
    "靴子": ("靴",),
    "配饰": ("围巾", "帽", "腰带"),
    "帽子": ("帽",),
    "包包": ("包",),
    "护肤": ("面霜", "精华", "洁面"),
    "洗面奶": ("洁面",),
    "香薰": ("香氛", "蜡烛"),
    "香水": ("香水", "香氛"),
    "毯子": ("毯",),
    "杯子": ("杯",),
    "餐具": ("杯", "盘", "碗", "砧板"),
}

_WORD: Final = re.compile(r"[A-Za-z]+")
_ASCII_LETTER: Final = re.compile(r"[A-Za-z]")
#: 展开后的中文检索词上限：查询最多 5 个词，每个词至多两三个对应，足够覆盖又不让条件无限增长。
MAX_EXPANSIONS: Final = 12


def has_english(text: str) -> bool:
    return _ASCII_LETTER.search(text) is not None


def _singular_forms(word: str) -> tuple[str, ...]:
    """查表用的候选词形：原词在前，再试常见复数还原。不做通用词形还原。"""

    forms = [word]
    if word.endswith("ies") and len(word) > 4:
        forms.append(word[:-3] + "y")
    if word.endswith("ves") and len(word) > 4:
        forms.append(word[:-3] + "f")  # scarves → scarf
    if word.endswith("es") and len(word) > 3:
        forms.append(word[:-2])  # dresses → dress
    if word.endswith("s") and len(word) > 2:
        forms.append(word[:-1])
    return tuple(forms)


def zh_search_terms(query: str) -> tuple[str, ...]:
    """把查询词展开成商品名称里实际出现的中文检索词（去重、保序、最多 `MAX_EXPANSIONS` 个）。

    英文商品词按词表对应，中文口语说法按近义词表对应；都没命中时返回空元组。
    原始查询词仍由调用方照常匹配，这里只补充，不替换。
    """

    normalized = " ".join(query.lower().split())
    found: list[str] = []

    def add(terms: tuple[str, ...]) -> None:
        for term in terms:
            if term not in found:
                found.append(term)

    for synonym, terms in _ZH_SYNONYMS.items():
        if synonym in normalized:
            add(terms)
    if not has_english(query):
        return tuple(found[:MAX_EXPANSIONS])
    english_start = len(found)
    for phrase, terms in _PHRASES.items():
        if phrase in normalized:
            add(terms)
    words = _WORD.findall(normalized)
    for table in (_TERMS, _CATEGORY_TERMS):
        for word in words:
            for form in _singular_forms(word):
                if form in table:
                    add(table[form])
                    break
        if len(found) > english_start:
            break  # 有商品词就不再用品类词
    return tuple(found[:MAX_EXPANSIONS])
