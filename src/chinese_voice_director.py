"""Chinese-first voice casting presets and performance instructions.

The presets describe original audiobook archetypes.  They intentionally avoid
claiming to reproduce a named character or performer: the useful target is the
casting direction (age, register, rhythm, energy and emotional range).
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional


CHINESE_SAMPLE_TEXT = (
    "雨刚停，长街上的灯一盏接一盏亮了起来。"
    "那人推开窗，笑着说道：“别急，我已经想到办法了。"
    "你愿意和我一起去看看吗？”"
)

CHINESE_NOVEL_TEST_TEXTS: Dict[str, str] = {
    "qingxia": (
        "“你怎么还站在那里呀？快跟上！”她跑出几步，又回头笑道，"
        "“放心吧，这次有我在，肯定不会迷路的。”"
    ),
    "yanshu": (
        "“先别急着下结论。”他把地图平铺在桌上，沉声说道，"
        "“把已经知道的事情重新理一遍，答案自然会出现。”"
    ),
    "ash_prince": (
        "“跪下？你似乎误会了什么。”男人迎着烈焰向前一步，"
        "“从我踏进这座城开始，选择该如何结束的人，就已经不是你了。”"
    ),
    "frost_master": (
        "“收剑。”她的声音并不高，却让四周瞬间安静下来，"
        "“真正的强大，不是让愤怒替你挥出下一剑。”"
    ),
    "fox_lady": (
        "“小家伙，既然来了，又何必急着走呢？”她轻轻一笑，"
        "“不如坐下来，把你藏着的那个秘密，慢慢讲给我听。”"
    ),
    "tangxing": (
        "“哇，真的会发光！”小姑娘捧起那颗石头，眼睛亮晶晶的，"
        "“我们把它带回去吧，说不定晚上还能用它照路呢！”"
    ),
    "moon_guard": (
        "“退后。”青年横枪挡在众人面前，声音冷静得听不出波澜，"
        "“这里交给我。你们只管沿原路离开，不必回头。”"
    ),
    "gilded_gambler": (
        "“别这么紧张，只是一场小小的赌局。”他笑着推来最后一枚筹码，"
        "“当然，你也可以拒绝——如果你舍得放弃唯一的机会。”"
    ),
    "choir_priest": (
        "“我理解你的犹豫。”他温声说道，仿佛真在耐心倾听，"
        "“但为了所有人的明天，有些选择必须由今天的我们做出。”"
    ),
    "velvet_hunter": (
        "“听我说，慢慢呼吸。”她从容地走过满地碎片，笑意若有若无，"
        "“很好。现在，把门打开，剩下的事交给我。”"
    ),
    "cloud_general": (
        "“这盘棋，看起来是我输了。”将军懒洋洋地拈起棋子，忽然抬眼，"
        "“可惜真正的胜负，从来不在棋盘上。”"
    ),
    "songbird": (
        "“不用害怕自己的声音。”她轻轻握住女孩的手，"
        "“哪怕它此刻还很微弱，也一定能抵达想要守护的人。”"
    ),
    "void_walker": (
        "“我似乎来过这里。”她望着雨中的旧桥，沉默片刻，"
        "“记忆会褪色，但剑记得该斩向何处。”"
    ),
    "gentle_firefly": (
        "“我当然也会害怕。”少女望着远处将熄的灯火，轻声笑了笑，"
        "“可正因为时间珍贵，我才更想亲自选择要走的路。”"
    ),
    "ancient_gentleman": (
        "“旧物并非越古老越珍贵。”先生将茶盏轻轻放下，"
        "“真正难得的，是它所见证的承诺，至今仍有人记得。”"
    ),
    "chief_justice": (
        "“证词已经记录。”审判官合上卷宗，庄重地说道，"
        "“在事实澄清之前，我不会让偏见替任何人宣判。”"
    ),
    "stage_queen": (
        "“诸位，请把目光交给舞台中央！”她扬起下巴，华丽地张开双臂，"
        "片刻后却小声补了一句：“刚才……应该没有人看出我紧张吧？”"
    ),
    "mischief_director": (
        "“哎呀，别见到我就躲嘛。”少女笑眯眯地晃了晃手里的木牌，"
        "“放心，今天不谈生意，只请你去看一场好戏。”"
    ),
    "eternal_shogun": (
        "“此事不必再议。”她的声音平静而威严，停了停，又略显生涩地问，"
        "“不过，你方才说的甜点……当真能保存很久？”"
    ),
    "maple_swordsman": (
        "“风里有潮湿的松香。”浪客停下脚步，侧耳听了片刻，"
        "“前面不远应当有人家，我们可以在暴雨来临前借宿。”"
    ),
    "hearth_father": (
        "“规矩不是为了束缚你们。”家主的声音冷静得没有一丝多余起伏，"
        "“它至少能保证，当危险来临时，你们都知道如何活下来。”"
    ),
    "ink_narrator": (
        "夜色从群山背后漫上来，风穿过废弃的站台，卷起一张发黄的车票。"
        "没有人注意到，停摆多年的时钟，在这一刻轻轻走了一格。"
    ),
    "warm_narrator": (
        "清晨的第一束光落进小院时，檐下的雨珠还没有干。"
        "她推开木门，并不知道这封迟到了十年的信，会把往事重新带回眼前。"
    ),
}


VOICE_DESIGN_BASELINE = (
    "使用自然、标准的中国大陆普通话，母语者咬字和语流。"
    "整句连贯表达，按语义组织气息；逗号只短暂停顿，不逐字朗读，不播音腔，不唱读，"
    "不拖长句尾，普通逗号约停零点二秒，句号约停零点四秒，不在主谓宾之间自行停顿。"
    "保持真实对话速度，通常每秒说四到五个汉字；禁止为了表现低沉、威严、温柔或神秘而故意拖慢。"
    "声线稳定，辅音清楚但不过度用力，保留真实呼吸和细微情绪。"
)

PACING_RETRY_INSTRUCTION = (
    "上一版语速和停顿过慢。请用日常真人对话的连贯速度重新说一遍："
    "每秒约四到五个汉字，逗号只轻停，禁止逐字停顿，禁止添加长时间沉默。"
)


ACTING_STATES: Dict[str, Dict[str, str]] = {
    "neutral": {
        "label": "自然",
        "instruction": "情绪克制自然，像人物正在真实交谈，而不是朗诵台词。",
    },
    "bright": {
        "label": "兴奋",
        "instruction": "情绪明亮兴奋，语速略快，有自然笑意，但不要尖叫或过度抬高音调。",
    },
    "gentle": {
        "label": "温柔",
        "instruction": "降低音量和攻击性，语气柔和亲近，停顿来自思考而不是故意拖慢。",
    },
    "shy": {
        "label": "娇羞",
        "instruction": (
            "保持角色原本的年龄感、基础音高、共鸣位置和声纹，只在亲密场景中略微收声，"
            "用轻微犹豫和藏不住的笑意表现娇羞。禁止升高基础音调，禁止变成少女音，"
            "不使用夸张动漫腔。"
        ),
    },
    "cold": {
        "label": "冷峻",
        "instruction": "语气疏离克制，音量稳定，字头干净，以压迫性的平静代替大喊。",
    },
    "dangerous": {
        "label": "危险",
        "instruction": (
            "威胁感来自确信和精准重音，句尾收住，不咆哮、不故意压成气泡音。"
            "保持日常对话速度，绝不能用拖慢语速、拉长尾音或增加长停顿来表现危险。"
        ),
    },
    "angry": {
        "label": "愤怒",
        "instruction": "呼吸和重音变强，节奏更紧，但仍保持吐字完整，不持续吼叫。",
    },
    "whisper": {
        "label": "低声",
        "instruction": "像近距离压低声音说话，保留清晰辅音，不变成全程漏气的耳语。",
    },
}

VOICE_IDENTITY_CONSISTENCY = (
    "无论当前情绪如何，都必须保持同一个人的年龄感、基础音高、共鸣位置、口腔质感和声纹身份；"
    "情绪只能改变气息、重音、力度、节奏和收放，绝不能像换了配音演员。"
)

EMOTION_REFERENCE_TEXTS: Dict[str, str] = {
    "neutral": (
        "我知道了。我们先把眼前的事情处理好，再决定下一步该怎么走。"
        "时间还来得及，不必仓促。"
    ),
    "bright": "太好了，原来你也发现了！快跟我来，我已经等不及想看看前面还有什么了！",
    "gentle": "别担心，我就在这里。慢慢来，把想说的话说完就好，我会认真听着。",
    "shy": "我才没有一直等你……只是刚好还没走而已。你不许笑，也不许再问了。",
    "cold": "停下。此事到此为止，没有继续争辩的必要。收起你的武器，立刻离开。",
    "dangerous": "我只提醒你最后一次。再向前一步，你就必须承担自己选择的全部后果。",
    "angry": "够了！我已经给过你机会，别再挑战我的底线。现在，马上把手放开！",
    "whisper": "嘘，先别出声。有人正在门外，我们靠近一点说，千万不要让他听见。",
}

_EMOTION_CUES: Dict[str, tuple[tuple[str, float], ...]] = {
    "bright": (
        ("太好了", 4.0), ("好开心", 4.0), ("哈哈", 3.5), ("嘿嘿", 3.0),
        ("哇", 2.6), ("快看", 2.4), ("终于", 1.8), ("兴奋", 3.5),
        ("欢快", 3.5), ("笑着", 1.8), ("宝藏", 1.0),
    ),
    "gentle": (
        ("别担心", 4.0), ("别怕", 4.0), ("没事", 2.5), ("放心", 2.5),
        ("慢慢来", 3.0), ("我在这里", 3.0), ("温柔", 4.0),
        ("柔声", 4.0), ("柔声道", 4.5), ("轻声安慰", 4.0),
        ("轻轻", 1.8), ("安慰", 3.0),
    ),
    "shy": (
        ("害羞", 4.5), ("羞涩", 4.5), ("脸红", 4.0), ("耳根", 3.5),
        ("耳尖", 3.8), ("耳朵红", 4.0), ("赧然", 4.0), ("局促", 2.8),
        ("才没有", 4.0), ("不许笑", 4.0), ("别问", 3.0),
        ("低下头", 3.0), ("红着脸", 4.0), ("别过脸", 2.8),
        ("娇羞", 4.5), ("讨厌", 1.5),
    ),
    "cold": (
        ("冷冷", 4.0), ("冷声", 4.0), ("清冷", 4.0), ("淡淡地", 2.8),
        ("面无表情", 4.0), ("退下", 3.5), ("收剑", 3.0),
        ("冷声道", 4.5), ("不必再议", 3.5), ("到此为止", 3.0),
        ("疏离", 3.5),
    ),
    "dangerous": (
        ("最后一次", 4.0), ("后果", 2.6), ("跪下", 3.5), ("威胁", 4.0),
        ("你会后悔", 4.0), ("送你最后一程", 4.5), ("猎物", 3.0),
        ("阴沉", 3.2), ("杀意", 4.0), ("杀了", 3.0),
        ("火焰", 1.6), ("承担", 1.0),
    ),
    "angry": (
        ("够了", 4.5), ("闭嘴", 4.5), ("滚开", 4.5), ("放开", 2.5),
        ("混蛋", 4.0), ("该死", 3.5), ("愤怒", 4.5), ("怒吼", 4.5),
        ("吼道", 4.0), ("厉声", 3.8), ("喝道", 3.2),
        ("咬牙", 3.0), ("底线", 2.5), ("马上", 1.0),
    ),
    "whisper": (
        ("嘘", 5.0), ("别出声", 4.5), ("小声", 4.0), ("低声", 3.5),
        ("低声道", 4.2), ("压低声音", 4.5), ("耳语", 4.0),
        ("悄悄", 3.5), ("门外", 1.0),
        ("不要让", 1.0), ("靠近一点", 2.0),
    ),
}


VOICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "qingxia": {
        "id": "qingxia",
        "name": "晴夏",
        "label": "晴夏 · 明亮活泼少女",
        "gender": "Female",
        "description": "明亮、机灵、有行动力的年轻少女声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["三月七"],
        "tags": ["少女", "活泼", "元气", "伙伴", "可爱"],
        "match_keywords": ["明亮活泼少女", "元气少女", "开朗", "乐观", "机灵", "冒险伙伴", "摄影"],
        "default_state": "bright",
        "instruction": (
            "一位十八到二十二岁的年轻成年女性，音色明亮清透，中高音区，声音有弹性和朝气。"
            "保留成年女性较完整的胸口支撑和口腔空间，明确区别于八到十一岁儿童的短声道、奶音和稚嫩共鸣。"
            "反应快，笑意自然，尾音灵动但不发嗲；吐字轻巧完整，避免尖锐夹嗓和儿童化。"
        ),
    },
    "yanshu": {
        "id": "yanshu",
        "name": "岩叔",
        "label": "岩叔 · 可靠成熟男人",
        "gender": "Male",
        "description": "沉稳、可靠、知识丰富的成熟男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["瓦尔特"],
        "tags": ["成熟", "可靠", "学者", "长辈", "沉稳"],
        "match_keywords": ["可靠成熟男声", "成熟男人", "导师", "长辈", "稳重", "博学", "理性", "沉稳"],
        "default_state": "neutral",
        "instruction": (
            "一位四十五到五十五岁的成熟男性，中低音区，音色温厚、有阅历和可信度。"
            "语速从容但不迟缓，重音少而准确，句尾干净收住；不故作低沉，不含混，不端着领导腔。"
        ),
    },
    "ash_prince": {
        "id": "ash_prince",
        "name": "灰烬王储",
        "label": "灰烬王储 · 危险强势男声",
        "gender": "Male",
        "description": "强大、危险、极度自信的青年男性反派声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["万敌"],
        "tags": ["青年", "强势", "王者", "反派", "战士"],
        "match_keywords": ["危险强势青年", "反派", "王储", "霸道", "狂傲", "战士", "强大", "压迫"],
        "default_state": "dangerous",
        "instruction": (
            "一位二十五到三十五岁的强势青年男性，中低音偏亮，音色锋利而有力量。"
            "像久经战斗的王储，骄傲、危险、掌控局面；压迫感来自克制和确信，不靠沙哑咆哮。"
        ),
    },
    "frost_master": {
        "id": "frost_master",
        "name": "霜月师尊",
        "label": "霜月师尊 · 清冷成熟女声",
        "gender": "Female",
        "description": "清冷、强大、亲密时会显露柔软的成熟女性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["镜流"],
        "tags": ["成熟女性", "清冷", "剑客", "师尊", "反差"],
        "match_keywords": ["清冷师尊", "高冷", "女剑客", "师父", "剑仙", "冷艳", "克制", "外冷内柔"],
        "default_state": "cold",
        "instruction": (
            "一位三十岁左右的成熟女性，中音区，音色清冷、干净、略带距离感。"
            "平时语气简洁克制，有强者和师长的威严；柔软时只降低音量、放松字尾，不突然变成少女音。"
        ),
    },
    "fox_lady": {
        "id": "fox_lady",
        "name": "狐系御姐",
        "label": "狐系御姐 · 慵懒戏谑女声",
        "gender": "Female",
        "description": "成熟、聪明、慵懒而带戏谑感的女性声线",
        "source": "原神",
        "reference_characters": ["八重神子"],
        "tags": ["御姐", "妩媚", "聪明", "戏谑", "神秘"],
        "match_keywords": ["慵懒戏谑御姐", "狐系", "妩媚", "魅惑", "腹黑", "神秘", "成熟", "调戏"],
        "default_state": "neutral",
        "instruction": (
            "一位二十八到三十八岁的成熟女性，中音区，音色柔润、有磁性和轻微笑意。"
            "说话从容聪明，像早已看穿对方却仍愿意陪他周旋；魅力来自节奏和分寸，不使用低俗呻吟或过重气声。"
        ),
    },
    "tangxing": {
        "id": "tangxing",
        "name": "糖星",
        "label": "糖星 · 童真可爱小女孩",
        "gender": "Female",
        "description": "天真、好奇、精力充沛的小女孩声线",
        "source": "原神",
        "reference_characters": ["可莉"],
        "tags": ["儿童", "可爱", "天真", "好奇", "精力充沛"],
        "match_keywords": ["童真女孩", "小女孩", "儿童", "天真", "究极可爱", "软萌", "好奇", "淘气"],
        "default_state": "bright",
        "instruction": (
            "一位八到十一岁的真实小女孩，具有儿童较短声道、较小口腔空间和轻柔稚嫩的头腔共鸣，"
            "音色清亮柔软、带自然奶音和好奇感，必须明显区别于十八岁以上的少女或年轻成年女性。"
            "情绪直接、反应生动，吐字完整，保留自然儿童气息；不要成人媚感，不要挤嗓，不要全程尖叫。"
        ),
    },
    "moon_guard": {
        "id": "moon_guard",
        "name": "月衡",
        "label": "月衡 · 清峻寡言青年",
        "gender": "Male",
        "description": "冷静、克制、寡言而暗藏力量的青年男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["丹恒", "饮月君"],
        "tags": ["青年", "清冷", "寡言", "守护者", "龙裔"],
        "match_keywords": ["冷静青年", "寡言", "清冷男声", "守护", "前世", "龙", "枪客", "克制"],
        "default_state": "cold",
        "instruction": (
            "一位二十到二十八岁的青年男性，中低音区，音色清峻、干净，带轻微疏离感。"
            "惜字如金，语速平稳，情绪通常藏在短促呼吸与精准重音里；爆发时增加力度而不破坏冷静底色。"
        ),
    },
    "gilded_gambler": {
        "id": "gilded_gambler",
        "name": "金羽赌徒",
        "label": "金羽赌徒 · 优雅笑面青年",
        "gender": "Male",
        "description": "明快、优雅、擅长周旋且笑意下藏着脆弱的青年男声",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["砂金"],
        "tags": ["青年", "优雅", "商人", "赌徒", "笑面"],
        "match_keywords": ["笑面青年", "赌徒", "商人", "贵公子", "圆滑", "优雅", "算计", "幸运", "脆弱"],
        "default_state": "neutral",
        "instruction": (
            "一位二十三到三十岁的青年男性，中音偏亮，音色漂亮、松弛，谈吐像随时带着礼貌笑意。"
            "擅长社交和试探，句中重音灵巧；独处或受伤时收窄音量、露出短暂空白，不突然变得软弱。"
        ),
    },
    "choir_priest": {
        "id": "choir_priest",
        "name": "白羽司祭",
        "label": "白羽司祭 · 温雅掌控男声",
        "gender": "Male",
        "description": "温柔、端正、具有安抚力与隐性掌控感的青年男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["星期日"],
        "tags": ["青年", "温雅", "司祭", "理想主义", "掌控"],
        "match_keywords": ["温雅男声", "司祭", "神父", "哥哥", "理想主义", "温柔", "秩序", "掌控", "圣洁"],
        "default_state": "gentle",
        "instruction": (
            "一位二十五到三十五岁的青年男性，中音区，声线温雅端正，像受过严格礼仪训练。"
            "语速舒缓但不断字，先让人感到被理解，再以极轻的重音表现不容置疑的秩序感。"
        ),
    },
    "velvet_hunter": {
        "id": "velvet_hunter",
        "name": "绯夜猎手",
        "label": "绯夜猎手 · 从容危险御姐",
        "gender": "Female",
        "description": "低沉、从容、带危险亲昵感的成熟女性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["卡芙卡"],
        "tags": ["御姐", "猎手", "危险", "从容", "神秘"],
        "match_keywords": ["危险御姐", "猎手", "杀手", "从容", "神秘", "操控", "低沉女声", "亲昵", "母性"],
        "default_state": "dangerous",
        "instruction": (
            "一位三十岁左右的成熟女性，中音偏低，音色柔滑、稳定，语速与日常对话一致。"
            "每个语义句要连贯推进，危险感来自掌控局面的确信，亲近时像在耐心引导对方；"
            "少用气声，不拉长尾音，不用慢速和长停顿制造神秘感。"
        ),
    },
    "cloud_general": {
        "id": "cloud_general",
        "name": "云上将军",
        "label": "云上将军 · 松弛智将男声",
        "gender": "Male",
        "description": "成熟、松弛、聪敏而在关键时刻极有威严的男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["景元"],
        "tags": ["成熟", "将军", "智慧", "松弛", "威严"],
        "match_keywords": ["将军", "智将", "成熟男声", "松弛", "慵懒", "谋略", "可靠", "上位者"],
        "default_state": "neutral",
        "instruction": (
            "一位三十五到四十五岁的成熟男性，中低音区，音色温润、有分量，日常略带懒散笑意。"
            "思路清晰，像总比别人多看一步；下令时缩短停顿、压实重音，自然显出统帅威严。"
        ),
    },
    "songbird": {
        "id": "songbird",
        "name": "晨歌",
        "label": "晨歌 · 温柔治愈歌姬",
        "gender": "Female",
        "description": "柔和、纯净、优雅且具有安抚力的年轻女性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["知更鸟"],
        "tags": ["少女", "歌姬", "治愈", "优雅", "温柔"],
        "match_keywords": ["歌姬", "偶像", "温柔少女", "治愈", "优雅", "纯净", "圣洁", "安抚"],
        "default_state": "gentle",
        "instruction": (
            "一位二十到二十六岁的年轻女性，中高音区，音色纯净柔和，带训练良好的气息支撑。"
            "说话而非唱歌，语句流动自然；公众场合优雅稳定，真情流露时增加温度而不变得甜腻。"
        ),
    },
    "void_walker": {
        "id": "void_walker",
        "name": "忘川行者",
        "label": "忘川行者 · 低冷寂寥女声",
        "gender": "Female",
        "description": "低冷、寡言、带记忆迷雾与强大压迫感的成熟女声",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["黄泉"],
        "tags": ["成熟女性", "剑客", "寂寥", "强大", "寡言"],
        "match_keywords": ["低冷女声", "寂寥", "失忆", "剑客", "浪人", "强者", "沉默", "虚无"],
        "default_state": "cold",
        "instruction": (
            "一位二十八到三十八岁的成熟女性，中低音区，音色冷净、沉静，像思绪隔着一层雾。"
            "语速偏慢但句内连贯，停顿只用于回忆和判断；力量爆发时声音更凝实，不靠大喊。"
        ),
    },
    "gentle_firefly": {
        "id": "gentle_firefly",
        "name": "萤火",
        "label": "萤火 · 温柔坚韧少女",
        "gender": "Female",
        "description": "轻柔、真诚、带病弱感却意志坚定的少女声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["流萤"],
        "tags": ["少女", "温柔", "坚韧", "战士", "真诚"],
        "match_keywords": ["温柔坚韧少女", "病弱", "真诚", "少女战士", "守护", "萤火", "柔弱外表", "坚定"],
        "default_state": "gentle",
        "instruction": (
            "一位十八到二十四岁的年轻女性，中高音区，音色轻柔清澈，亲近感强。"
            "身体感略轻但气息不断，愿望与承诺说得坚定清楚；战斗状态增加节奏和力度，仍保留少女本音。"
        ),
    },
    "cyber_girl": {
        "id": "cyber_girl",
        "name": "像素骇客",
        "label": "像素骇客 · 酷拽游戏少女",
        "gender": "Female",
        "description": "年轻、随性、略显无聊又爱恶作剧的少女声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["银狼"],
        "tags": ["少女", "骇客", "酷", "游戏", "恶作剧"],
        "match_keywords": ["游戏少女", "骇客", "黑客", "宅女", "酷拽", "随性", "吐槽", "电子"],
        "default_state": "neutral",
        "instruction": (
            "一位十八到二十四岁的年轻女性，中音偏高，音色清脆但不甜，语气随性利落。"
            "像资深玩家一样用短句吐槽，偶尔带得意笑意；避免儿童化和持续冷漠，关键时刻反应极快。"
        ),
    },
    "scarred_blade": {
        "id": "scarred_blade",
        "name": "残刃",
        "label": "残刃 · 压抑孤狼男声",
        "gender": "Male",
        "description": "低沉、粗粝、疲惫并压抑着怒意的青年男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["刃"],
        "tags": ["青年", "孤狼", "剑客", "压抑", "复仇"],
        "match_keywords": ["孤狼", "复仇者", "压抑", "剑客", "低沉男声", "疲惫", "冷酷", "不死"],
        "default_state": "cold",
        "instruction": (
            "一位三十岁上下的青年男性，低音区，音色略粗粝、疲惫，像长期承受疼痛。"
            "话少且句尾收得很紧，怒意埋在呼吸和字头里；不要持续气泡音，也不要含糊吞字。"
        ),
    },
    "wild_ranger": {
        "id": "wild_ranger",
        "name": "荒星游侠",
        "label": "荒星游侠 · 豪放痞帅男声",
        "gender": "Male",
        "description": "豪放、痞气、戏剧化而战斗时极危险的成年男性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["波提欧"],
        "tags": ["成年男性", "游侠", "牛仔", "豪放", "痞帅"],
        "match_keywords": ["游侠", "牛仔", "豪放", "痞帅", "赏金猎人", "粗犷", "搞笑", "枪手"],
        "default_state": "bright",
        "instruction": (
            "一位三十岁上下的成年男性，中低音偏亮，音色有颗粒感，笑声明快，节奏富有弹性。"
            "日常像爱说俏皮话的荒野枪手，危险时立刻收住笑意、重音变硬；可豪放但不能喊麦。"
        ),
    },
    "sky_general": {
        "id": "sky_general",
        "name": "天风将军",
        "label": "天风将军 · 飒爽统帅女声",
        "gender": "Female",
        "description": "爽朗、强健、自信且极有行动力的成熟女性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["飞霄"],
        "tags": ["成熟女性", "将军", "飒爽", "豪迈", "统帅"],
        "match_keywords": ["女将军", "统帅", "飒爽", "豪迈", "大姐", "强健", "自信", "行动派"],
        "default_state": "bright",
        "instruction": (
            "一位三十岁上下的成熟女性，中音区，音色明朗结实，气息充足，具有运动者的生命力。"
            "说话直接爽快，笑意大方；发号施令时节奏紧凑、重音清晰，不刻意压低成男声。"
        ),
    },
    "dream_oracle": {
        "id": "dream_oracle",
        "name": "梦境忆者",
        "label": "梦境忆者 · 神秘叙事御姐",
        "gender": "Female",
        "description": "温润、神秘、善于讲述并带催眠般吸引力的成熟女声",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["黑天鹅"],
        "tags": ["御姐", "预言", "记忆", "神秘", "叙事"],
        "match_keywords": ["神秘御姐", "预言家", "占卜师", "忆者", "讲述者", "优雅", "梦境", "催眠"],
        "default_state": "gentle",
        "instruction": (
            "一位三十到四十岁的成熟女性，中低音区，音色温润幽深，像在近距离讲一个秘密。"
            "语句连贯、轻重层次细腻，神秘感来自信息留白而非过量气声；危险时仍保持优雅。"
        ),
    },
    "genius_madam": {
        "id": "genius_madam",
        "name": "天才女士",
        "label": "天才女士 · 锐利傲气女声",
        "gender": "Female",
        "description": "聪明、傲气、反应迅速且带一点戏弄感的女性声线",
        "source": "崩坏：星穹铁道",
        "reference_characters": ["黑塔", "大黑塔"],
        "tags": ["女性", "天才", "学者", "傲气", "锐利"],
        "match_keywords": ["天才女士", "科学家", "学者", "傲气", "聪明", "毒舌", "人偶", "研究员"],
        "default_state": "neutral",
        "instruction": (
            "一位二十五到三十五岁的女性，中音偏高，音色清晰锐利，思考和反应都很快。"
            "带理所当然的自信与轻微戏弄，复杂内容也说得轻松；不使用夸张尖笑，不变成任性儿童。"
        ),
    },
    "ancient_gentleman": {
        "id": "ancient_gentleman",
        "name": "玄岩先生",
        "label": "玄岩先生 · 深沉儒雅男声",
        "gender": "Male",
        "description": "低沉、儒雅、博古通今且极具安定感的成熟男性声线",
        "source": "原神",
        "reference_characters": ["钟离"],
        "tags": ["成熟", "绅士", "古老", "博学", "沉稳"],
        "match_keywords": ["儒雅男声", "先生", "古神", "博学", "沉稳", "契约", "贵族", "老者"],
        "default_state": "neutral",
        "instruction": (
            "一位四十岁上下、气质远比外表古老的成熟男性，低音区，音色醇厚端正。"
            "措辞考究，语速从容但句内保持流动，重音像落石般稳；不可故意拖长到像纪录片旁白。"
        ),
    },
    "chief_justice": {
        "id": "chief_justice",
        "name": "沧海审判官",
        "label": "沧海审判官 · 庄严克制男声",
        "gender": "Male",
        "description": "庄严、克制、措辞精确且内心敏感的成熟男性声线",
        "source": "原神",
        "reference_characters": ["那维莱特"],
        "tags": ["成熟", "审判官", "庄严", "克制", "非人感"],
        "match_keywords": ["审判官", "法官", "庄严", "克制", "冷静", "水", "非人", "公正", "正式"],
        "default_state": "cold",
        "instruction": (
            "一位三十五到四十五岁的成熟男性，中低音区，音色清澈庄重，吐字精确。"
            "正式场合严谨克制，像在衡量每个词的责任；被人类情感触动时放松字尾，不突然煽情。"
        ),
    },
    "stage_queen": {
        "id": "stage_queen",
        "name": "水镜名伶",
        "label": "水镜名伶 · 华丽戏剧少女",
        "gender": "Female",
        "description": "华丽、自信、表演感强而独处时柔软真实的年轻女性声线",
        "source": "原神",
        "reference_characters": ["芙宁娜"],
        "tags": ["少女", "名伶", "戏剧", "骄傲", "反差"],
        "match_keywords": ["戏剧少女", "演员", "名伶", "舞台", "女王", "骄傲", "夸张", "脆弱", "水神"],
        "default_state": "bright",
        "instruction": (
            "一位二十岁上下的年轻女性，中高音区，音色华丽明亮，公开讲话有舞台演员般的节奏。"
            "自信时重音鲜明但不能全程喊叫；卸下表演后音量变轻、语速自然，仍保持同一年龄和声纹。"
        ),
    },
    "mischief_director": {
        "id": "mischief_director",
        "name": "灵火堂主",
        "label": "灵火堂主 · 古灵精怪少女",
        "gender": "Female",
        "description": "机灵、俏皮、语速明快又能坦然面对生死的少女声线",
        "source": "原神",
        "reference_characters": ["胡桃"],
        "tags": ["少女", "堂主", "俏皮", "聪明", "生死观"],
        "match_keywords": ["古灵精怪", "堂主", "俏皮", "机灵", "鬼点子", "生死", "淘气", "少女"],
        "default_state": "bright",
        "instruction": (
            "一位十八到二十四岁的年轻女性，中高音区，音色灵巧有弹性，语速明快，转折敏捷。"
            "玩笑有聪明的节奏，不靠幼态装可爱；谈论严肃生死时收起笑意，声音清醒而温暖。"
        ),
    },
    "eternal_shogun": {
        "id": "eternal_shogun",
        "name": "雷霆将军",
        "label": "雷霆将军 · 威严寡言女声",
        "gender": "Female",
        "description": "威严、寡言、意志坚定且私下略显生涩的成熟女声",
        "source": "原神",
        "reference_characters": ["雷电将军", "雷电影"],
        "tags": ["成熟女性", "将军", "威严", "神明", "反差"],
        "match_keywords": ["雷霆将军", "女将军", "神明", "威严", "寡言", "永恒", "冷峻", "生涩"],
        "default_state": "cold",
        "instruction": (
            "一位三十岁左右的成熟女性，中音区，音色凝练威严，语句简洁，几乎没有多余语气词。"
            "命令时像雷霆落定；私下不熟悉人情时只增加轻微迟疑和柔和感，不变成天真小女孩。"
        ),
    },
    "wind_bard": {
        "id": "wind_bard",
        "name": "风歌少年",
        "label": "风歌少年 · 轻盈顽皮少年",
        "gender": "Male",
        "description": "轻盈、顽皮、自由且偶尔流露古老感的少年声线",
        "source": "原神",
        "reference_characters": ["温迪"],
        "tags": ["少年", "吟游诗人", "顽皮", "自由", "空灵"],
        "match_keywords": ["吟游诗人", "少年", "顽皮", "自由", "风", "精灵", "空灵", "歌者"],
        "default_state": "bright",
        "instruction": (
            "一位外表十六到二十岁的少年，中高音区，音色轻盈清澈，带顽皮笑意与自然少年感。"
            "语速灵活，像风一样松弛；回忆久远往事时稍降速度和亮度，但不要变成成年低音。"
        ),
    },
    "silent_adeptus": {
        "id": "silent_adeptus",
        "name": "夜叉少年",
        "label": "夜叉少年 · 冷峭孤独男声",
        "gender": "Male",
        "description": "冷峭、寡言、背负伤痛却守护欲强的青年男性声线",
        "source": "原神",
        "reference_characters": ["魈"],
        "tags": ["青年", "夜叉", "孤独", "守护", "清冷"],
        "match_keywords": ["夜叉", "仙人", "孤独", "守护者", "少年战士", "寡言", "清冷", "业障"],
        "default_state": "cold",
        "instruction": (
            "一位外表二十岁上下的青年男性，中音偏低，音色冷峭干净，带长期独处的距离感。"
            "句子短但不能逐字蹦出，关心他人时语气仍生硬，只在音量和停顿上显出柔软。"
        ),
    },
    "maple_swordsman": {
        "id": "maple_swordsman",
        "name": "枫叶浪客",
        "label": "枫叶浪客 · 温润诗意青年",
        "gender": "Male",
        "description": "温润、平和、诗意且面对危险依然从容的青年男声",
        "source": "原神",
        "reference_characters": ["枫原万叶"],
        "tags": ["青年", "浪客", "诗意", "温柔", "剑客"],
        "match_keywords": ["浪客", "诗人", "温润青年", "剑客", "从容", "温柔", "自然", "枫叶"],
        "default_state": "gentle",
        "instruction": (
            "一位二十到二十六岁的青年男性，中音区，音色温润清朗，呼吸松弛，语句有自然诗意。"
            "温柔不等于慢吞吞，叙述保持连贯；遇到危险时重音果断，仍不失平和本色。"
        ),
    },
    "sharp_wanderer": {
        "id": "sharp_wanderer",
        "name": "浮浪少年",
        "label": "浮浪少年 · 锐气毒舌男声",
        "gender": "Male",
        "description": "年轻、锐利、毒舌而把脆弱藏得很深的少年男声",
        "source": "原神",
        "reference_characters": ["流浪者", "散兵"],
        "tags": ["少年", "流浪者", "毒舌", "锐利", "反叛"],
        "match_keywords": ["流浪者", "毒舌少年", "反叛", "锐利", "傲娇", "人偶", "讥讽", "脆弱"],
        "default_state": "cold",
        "instruction": (
            "一位外表十八到二十二岁的青年男性，中高音区，音色锐利清晰，讥讽时字尾干脆上挑。"
            "不耐烦来自聪明和戒备，不使用尖叫或儿童哭腔；真正受伤时收紧声音而不是突然示弱。"
        ),
    },
    "rational_scribe": {
        "id": "rational_scribe",
        "name": "理性书记官",
        "label": "理性书记官 · 冷静知性男声",
        "gender": "Male",
        "description": "理性、清晰、低调自信且略带干式幽默的成年男性声线",
        "source": "原神",
        "reference_characters": ["艾尔海森"],
        "tags": ["成年男性", "学者", "理性", "知性", "冷静"],
        "match_keywords": ["书记官", "学者", "理性", "知性男声", "冷静", "逻辑", "毒舌", "研究者"],
        "default_state": "neutral",
        "instruction": (
            "一位二十八到三十五岁的成年男性，中低音区，音色清晰平直，表达高效准确。"
            "几乎不做多余表演，幽默来自事实本身与轻微重音；冷静但不能像机器播报。"
        ),
    },
    "hearth_father": {
        "id": "hearth_father",
        "name": "壁炉家主",
        "label": "壁炉家主 · 冷厉中性女声",
        "gender": "Female",
        "description": "低沉、中性、纪律严明且保护欲克制的成熟女声",
        "source": "原神",
        "reference_characters": ["阿蕾奇诺"],
        "tags": ["成熟女性", "家主", "中性", "冷厉", "保护者"],
        "match_keywords": ["家主", "父亲", "执行官", "冷厉女声", "中性女声", "纪律", "孤儿院", "保护"],
        "default_state": "cold",
        "instruction": (
            "一位三十到四十岁的成熟女性，中低音区，音色中性冷硬，语气简洁且极有纪律感。"
            "关心被保护者时仍不甜腻，只让声音稍微放松；威胁时保持低音量和绝对控制。"
        ),
    },
    "sun_chief": {
        "id": "sun_chief",
        "name": "烈阳领袖",
        "label": "烈阳领袖 · 热烈可靠女声",
        "gender": "Female",
        "description": "热烈、强大、坦荡并能鼓舞同伴的成熟领袖女声",
        "source": "原神",
        "reference_characters": ["玛薇卡"],
        "tags": ["成熟女性", "领袖", "热烈", "可靠", "战士"],
        "match_keywords": ["领袖", "火神", "热烈", "可靠", "大姐", "战士", "鼓舞", "坦荡", "太阳"],
        "default_state": "bright",
        "instruction": (
            "一位三十岁上下的成熟女性，中音区，音色明亮结实，笑意坦荡，具有领袖的号召力。"
            "鼓舞时热烈但不喊口号，严肃决断时稳住音高、压实重音，始终给人可靠感。"
        ),
    },
    "forest_sage": {
        "id": "forest_sage",
        "name": "梦林贤者",
        "label": "梦林贤者 · 稚嫩智慧少女",
        "gender": "Female",
        "description": "外表稚嫩、语气温和、充满智慧与同理心的少女声线",
        "source": "原神",
        "reference_characters": ["纳西妲"],
        "tags": ["少女", "贤者", "智慧", "温柔", "神明"],
        "match_keywords": ["小小贤者", "智慧少女", "神明", "温柔", "梦境", "草木", "同理心", "导师"],
        "default_state": "gentle",
        "instruction": (
            "一位外表十二到十五岁的少女，中高音区，音色柔软清澈，年龄感稚嫩但思想成熟。"
            "表达耐心、逻辑清楚，常带温柔好奇；不奶声奶气，不用成人御姐腔，也不故作老成。"
        ),
    },
    "battle_friend": {
        "id": "battle_friend",
        "name": "逐浪公子",
        "label": "逐浪公子 · 爽朗好战青年",
        "gender": "Male",
        "description": "爽朗、亲切、好胜且进入战斗会骤然锐利的青年男声",
        "source": "原神",
        "reference_characters": ["达达利亚", "公子"],
        "tags": ["青年", "战士", "爽朗", "好胜", "危险"],
        "match_keywords": ["公子", "战斗狂", "爽朗青年", "哥哥", "好胜", "武者", "亲切", "危险"],
        "default_state": "bright",
        "instruction": (
            "一位二十二到二十八岁的青年男性，中音偏亮，音色爽朗亲切，笑声有感染力。"
            "对朋友真诚随和，提到战斗时节奏加快、音色骤然锐利；危险反差来自兴奋而非咆哮。"
        ),
    },
    "rose_leader": {
        "id": "rose_leader",
        "name": "金蔷薇团长",
        "label": "金蔷薇团长 · 明朗坚强女声",
        "gender": "Female",
        "description": "明朗、优雅、重情义且悲伤后仍能振作的年轻女性声线",
        "source": "原神",
        "reference_characters": ["娜维娅"],
        "tags": ["年轻女性", "团长", "优雅", "坚强", "热情"],
        "match_keywords": ["团长", "大小姐", "明朗女声", "优雅", "坚强", "重情义", "领袖", "蔷薇"],
        "default_state": "bright",
        "instruction": (
            "一位二十三到三十岁的年轻女性，中高音区，音色明朗饱满，谈吐优雅却没有距离感。"
            "待人热情真诚，悲伤时允许呼吸变沉但不崩坏声线；重新振作时恢复清晰有力的节奏。"
        ),
    },
    "ink_narrator": {
        "id": "ink_narrator",
        "name": "墨川",
        "label": "墨川 · 自然沉浸男旁白",
        "gender": "Male",
        "description": "自然、耐听、画面感清晰但不抢角色戏份的成熟男旁白",
        "source": "通用有声书",
        "reference_characters": [],
        "tags": ["旁白", "叙述者", "自然", "耐听", "沉浸"],
        "match_keywords": ["narrator", "旁白", "叙述者", "说书人", "自然旁白", "男旁白", "沉浸"],
        "default_state": "neutral",
        "instruction": (
            "一位三十到四十岁的专业男叙述者，中低音区，音色自然耐听，存在感适中。"
            "根据句意连贯讲述，场景有画面但不抢角色表演；避免新闻播音腔、纪录片拖腔和逐字强调。"
        ),
    },
    "warm_narrator": {
        "id": "warm_narrator",
        "name": "晚晴",
        "label": "晚晴 · 温润沉浸女旁白",
        "gender": "Female",
        "description": "温润、清晰、情绪细腻但保持克制的成熟女旁白",
        "source": "通用有声书",
        "reference_characters": [],
        "tags": ["旁白", "叙述者", "温润", "细腻", "沉浸"],
        "match_keywords": ["narrator", "旁白", "叙述者", "说书人", "温润旁白", "女旁白", "沉浸"],
        "default_state": "neutral",
        "instruction": (
            "一位二十八到四十岁的专业女叙述者，中音区，音色温润清晰，情绪感细腻但克制。"
            "叙事节奏由语义和场景推动，不端着朗诵；角色对白只做轻微转述感，不与人物声线混淆。"
        ),
    },
}


DEFAULT_CHINESE_SPEAKER_PROFILE_PROMPT = """你是一名中文有声书选角导演。结合人物标签和已经标注的小说正文，为每个真正开口说话的人物建立中文声音档案。

只输出三列表格：
| Character Name | Full Description | Voice Profile |

要求：
1. Character Name 必须原样使用输入的人物标签，不能翻译、改名或遗漏。
2. Full Description 用一句中文写清：大致年龄、性别、身份气质、音高区间、音色质感、语速、重音习惯，以及情绪变化时仍需保持的核心声线。
3. 每条 Full Description 都必须包含“标准中国大陆普通话、母语者自然语流、整句连读、不逐字朗读”。
4. Voice Profile 使用一个简短的原创选角类别，例如“明亮活泼少女”“可靠成熟男声”“危险强势青年”“清冷师尊”“慵懒戏谑御姐”“童真女孩”。
5. 根据正文判断人物，不要照抄示例；信息不足时采用克制、中性的设计，不要擅自添加方言或外国口音。
6. narrator 也要建立档案：自然、耐听、不过度表演，并与主要角色拉开音色。
7. 不要模仿或声称复刻任何现实演员、配音演员或受版权保护的具体角色。

不要输出表格以外的解释。"""


def list_voice_presets() -> List[Dict[str, Any]]:
    """Return serializable copies of the built-in Chinese casting presets."""
    return [deepcopy(item) for item in VOICE_PRESETS.values()]


def list_acting_states() -> List[Dict[str, str]]:
    return [
        {"id": state_id, **deepcopy(payload)}
        for state_id, payload in ACTING_STATES.items()
    ]


def compose_voice_instruction(
    preset_id: Optional[str],
    *,
    acting_state: Optional[str] = None,
    custom_instruction: Optional[str] = None,
) -> str:
    """Compose a Chinese-native VoiceDesign instruction.

    A custom instruction augments the selected archetype instead of replacing
    the Chinese fluency baseline.  With no preset, it is still normalized for
    natural Mandarin delivery.
    """
    preset = VOICE_PRESETS.get((preset_id or "").strip())
    state_id = (acting_state or "").strip()
    if not state_id and preset:
        state_id = str(preset.get("default_state") or "neutral")
    state = ACTING_STATES.get(state_id) or ACTING_STATES["neutral"]

    parts = [VOICE_DESIGN_BASELINE]
    if preset:
        parts.append(str(preset["instruction"]))
        parts.append(VOICE_IDENTITY_CONSISTENCY)
    if custom_instruction and custom_instruction.strip():
        parts.append(custom_instruction.strip())
    parts.append(state["instruction"])
    return "".join(parts)


def get_voice_preset(preset_id: Optional[str]) -> Optional[Dict[str, Any]]:
    preset = VOICE_PRESETS.get((preset_id or "").strip())
    return deepcopy(preset) if preset else None


def _normalize_match_text(value: Optional[str]) -> str:
    return "".join(
        char.lower()
        for char in str(value or "")
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


def _infer_profile_gender(text: str, explicit_gender: Optional[str] = None) -> Optional[str]:
    explicit = (explicit_gender or "").strip().lower()
    if explicit in {"female", "woman", "girl", "女"}:
        return "Female"
    if explicit in {"male", "man", "boy", "男"}:
        return "Male"

    normalized = str(text or "").lower()
    female_terms = ("女性", "少女", "女孩", "女人", "女声", "御姐", "姑娘", "母亲", "姐姐", "妹妹", "female", "woman", "girl")
    male_terms = ("男性", "少年", "男孩", "男人", "男声", "大叔", "父亲", "哥哥", "弟弟", "male", "man", "boy")
    female_hit = any(term in normalized for term in female_terms)
    male_hit = any(term in normalized for term in male_terms)
    if female_hit and not male_hit:
        return "Female"
    if male_hit and not female_hit:
        return "Male"
    return None


def recommend_voice_presets(
    profile: Optional[str],
    *,
    gender: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Rank original Mandarin presets against a novel character description.

    Named game characters are treated only as casting references.  The returned
    preset remains an original VoiceDesign instruction and never requests voice
    cloning or impersonation.
    """
    raw_profile = str(profile or "").strip()
    normalized = _normalize_match_text(raw_profile)
    inferred_gender = _infer_profile_gender(raw_profile, gender)
    ranked: List[Dict[str, Any]] = []

    for preset in VOICE_PRESETS.values():
        score = 0
        reasons: List[str] = []
        preset_gender = str(preset.get("gender") or "")
        if inferred_gender:
            if inferred_gender == preset_gender:
                score += 8
                reasons.append("性别与年龄感方向相符")
            else:
                score -= 30

        identity_values = [
            preset.get("id"),
            preset.get("name"),
            *(preset.get("reference_characters") or []),
        ]
        identity_matches = [
            str(value)
            for value in identity_values
            if value and _normalize_match_text(str(value)) in normalized
        ]
        if identity_matches:
            score += 120
            reasons.append(f"命中人设参考：{'、'.join(identity_matches[:2])}")

        matched_keywords: List[str] = []
        for keyword in preset.get("match_keywords") or []:
            token = _normalize_match_text(str(keyword))
            if token and token in normalized:
                matched_keywords.append(str(keyword))
                score += 14 + min(len(token), 8)
        if matched_keywords:
            reasons.append(f"匹配特征：{'、'.join(matched_keywords[:3])}")

        matched_tags: List[str] = []
        for tag in preset.get("tags") or []:
            token = _normalize_match_text(str(tag))
            if token and token in normalized and str(tag) not in matched_keywords:
                matched_tags.append(str(tag))
                score += 6
        if matched_tags:
            reasons.append(f"匹配标签：{'、'.join(matched_tags[:3])}")

        # With sparse descriptions, prefer neutral audiobook voices over
        # arbitrarily assigning an extreme copyrighted-character archetype.
        if not normalized:
            if preset["id"] == ("warm_narrator" if inferred_gender == "Female" else "ink_narrator"):
                score += 10
        elif any(term in raw_profile.lower() for term in ("narrator", "旁白", "叙述者", "说书人")):
            if preset["id"] in {"ink_narrator", "warm_narrator"}:
                score += 36

        ranked.append({
            "id": preset["id"],
            "name": preset["name"],
            "label": preset["label"],
            "gender": preset_gender,
            "source": preset.get("source"),
            "reference_characters": deepcopy(preset.get("reference_characters") or []),
            "score": score,
            "reasons": reasons or ["通用声线候选"],
        })

    ranked.sort(key=lambda item: (-int(item["score"]), item["id"]))
    limited = ranked[: max(1, min(int(limit or 3), 10))]
    best_score = max((int(item["score"]) for item in limited), default=0)
    for item in limited:
        raw_score = int(item["score"])
        if raw_score >= 100:
            confidence = 0.99
        elif raw_score > 8:
            confidence = min(0.95, 0.48 + raw_score / 100)
        elif best_score > 0:
            confidence = 0.35
        else:
            confidence = 0.2
        item["confidence"] = round(confidence, 2)
    return limited


def readable_character_count(text: Optional[str]) -> int:
    """Count spoken CJK/alphanumeric units while ignoring punctuation."""
    return len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", str(text or "")))


def has_abnormally_slow_delivery(
    text: Optional[str],
    sample_count: int,
    sample_rate: int,
    *,
    minimum_characters_per_second: float = 2.35,
) -> bool:
    """Flag grossly over-slow Mandarin generations for a single retry."""
    units = readable_character_count(text)
    if units < 16 or sample_count <= 0 or sample_rate <= 0:
        return False
    duration_seconds = float(sample_count) / float(sample_rate)
    if duration_seconds <= 0:
        return False
    return (units / duration_seconds) < float(minimum_characters_per_second)


def resolve_acting_state(instruction: Optional[str]) -> Optional[str]:
    """Map free-form Chinese/English emotion text to a supported acting state."""
    normalized = (instruction or "").strip().lower()
    if not normalized:
        return None
    if normalized in ACTING_STATES:
        return normalized
    keyword_groups = (
        ("shy", ("娇羞", "害羞", "羞涩", "shy", "bashful")),
        ("whisper", ("低声", "耳语", "悄声", "whisper", "whispering")),
        ("angry", ("愤怒", "生气", "暴怒", "angry", "furious")),
        ("dangerous", ("危险", "威胁", "压迫", "dangerous", "threatening")),
        ("cold", ("冷峻", "冷淡", "清冷", "疏离", "cold", "aloof")),
        ("gentle", ("温柔", "柔和", "亲近", "gentle", "tender", "soft")),
        ("bright", ("兴奋", "开心", "活泼", "欢快", "excited", "happy", "bright")),
        ("neutral", ("自然", "平静", "克制", "neutral", "natural", "calm")),
    )
    for state_id, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            return state_id
    return None


def emotion_reference_text(
    preset_id: Optional[str],
    acting_state: Optional[str],
) -> str:
    """Return a transcript whose wording naturally supports the target emotion."""
    state_id = (acting_state or "neutral").strip()
    preset = VOICE_PRESETS.get((preset_id or "").strip())
    if preset and state_id == str(preset.get("default_state") or "neutral"):
        persona_text = CHINESE_NOVEL_TEST_TEXTS.get(str(preset.get("id") or ""))
        if persona_text:
            return persona_text
    return EMOTION_REFERENCE_TEXTS.get(
        state_id,
        EMOTION_REFERENCE_TEXTS["neutral"],
    )


def infer_acting_state(
    text: Optional[str],
    *,
    explicit_instruction: Optional[str] = None,
    default_state: Optional[str] = None,
    previous_state: Optional[str] = None,
    context_before: Optional[str] = None,
    context_after: Optional[str] = None,
) -> Dict[str, Any]:
    """Infer one audiobook acting state from Chinese dialogue or narration.

    Explicit emotion tags and per-role overrides win.  Otherwise a deterministic
    cue scorer chooses a state.  A weak adjacent sentence inherits the previous
    state so performance does not snap back to neutral between closely related
    lines.
    """
    explicit_state = resolve_acting_state(explicit_instruction)
    if explicit_state:
        return {
            "state": explicit_state,
            "label": ACTING_STATES[explicit_state]["label"],
            "confidence": 1.0,
            "source": "manual",
            "reason": "使用正文情绪标签或角色手动设置",
        }

    content = re.sub(r"\s+", "", str(text or ""))
    surrounding_context = re.sub(
        r"\s+",
        "",
        f"{str(context_before or '')[-160:]}{str(context_after or '')[:120]}",
    )
    scores: Dict[str, float] = {state: 0.0 for state in _EMOTION_CUES}
    reasons: Dict[str, List[str]] = {state: [] for state in _EMOTION_CUES}

    def score_cues(candidate: str, multiplier: float, source_label: str) -> None:
        if not candidate:
            return
        for state_id, cues in _EMOTION_CUES.items():
            for cue, weight in cues:
                count = candidate.count(cue)
                if count:
                    scores[state_id] += float(weight) * min(count, 2) * multiplier
                    reasons[state_id].append(f"{source_label}{cue}")

    score_cues(content, 1.0, "")
    # Fiction often places the delivery cue outside the quotation:
    # “她厉声喝道”“他压低声音说”. Nearby narration is therefore a
    # strong secondary signal, but receives less weight than the spoken line.
    score_cues(surrounding_context, 0.78, "上下文：")

    exclamations = content.count("！") + content.count("!")
    questions = content.count("？") + content.count("?")
    if exclamations >= 2:
        scores["bright"] += 1.2
        reasons["bright"].append("连续感叹")
    elif exclamations == 1:
        scores["bright"] += 0.45
    if "……" in content or "..." in content:
        scores["shy"] += 0.6
        scores["whisper"] += 0.3
    if questions >= 2:
        scores["bright"] += 0.45

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_state, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    fallback = (default_state or "neutral").strip()
    if fallback not in ACTING_STATES:
        fallback = "neutral"

    if best_score < 1.5:
        if previous_state in ACTING_STATES and previous_state != "neutral":
            return {
                "state": previous_state,
                "label": ACTING_STATES[previous_state]["label"],
                "confidence": 0.52,
                "source": "continuity",
                "reason": "相邻句线索较弱，延续上一句表演状态",
            }
        return {
            "state": fallback,
            "label": ACTING_STATES[fallback]["label"],
            "confidence": 0.42,
            "source": "persona",
            "reason": "使用角色默认表演状态",
        }

    margin = max(0.0, best_score - second_score)
    confidence = min(0.98, 0.58 + best_score * 0.055 + margin * 0.035)
    matched = "、".join(reasons[best_state][:3]) or "标点与语气"
    return {
        "state": best_state,
        "label": ACTING_STATES[best_state]["label"],
        "confidence": round(confidence, 2),
        "source": "automatic",
        "reason": f"命中：{matched}",
    }


__all__ = [
    "ACTING_STATES",
    "CHINESE_NOVEL_TEST_TEXTS",
    "CHINESE_SAMPLE_TEXT",
    "DEFAULT_CHINESE_SPEAKER_PROFILE_PROMPT",
    "EMOTION_REFERENCE_TEXTS",
    "PACING_RETRY_INSTRUCTION",
    "VOICE_DESIGN_BASELINE",
    "VOICE_IDENTITY_CONSISTENCY",
    "VOICE_PRESETS",
    "compose_voice_instruction",
    "emotion_reference_text",
    "get_voice_preset",
    "has_abnormally_slow_delivery",
    "infer_acting_state",
    "list_acting_states",
    "list_voice_presets",
    "readable_character_count",
    "recommend_voice_presets",
    "resolve_acting_state",
]
