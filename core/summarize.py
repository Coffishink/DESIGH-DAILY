"""
把抓好的设计类 RSS 丢给 AI，生成结构化的中文设计简报

结构：
1. 今日总览（今日一句话 + 设计观察 + 趋势预测）
2. 设计资讯精选（默认 15 条，优质内容多时最多 25 条）
3. 其他值得一看（标题 + 分类 + 链接，不展开摘要）
4. 今日行动建议
5. 问候语
"""
import json
import os
import random
import time
import urllib.parse
import requests
from datetime import datetime, timezone, timedelta

# ============ 双 API 渠道配置 ============
CHANNELS = [
    {
        "name": "TeamoRouter",
        "url": "https://api.teamorouter.com/v1/chat/completions",
        "api_key_env": "TEAMOROUTER_API_KEY",
        "model": "gpt-6-astra",
    },
    {
        "name": "HaoAI",
        "url": "https://api.hao.ai/v1/chat/completions",
        "api_key_env": "HAOAI_API_KEY",
        "model": "anthropic/claude-opus-5-5",
    },
]
# =======================================

DESIGN_TOP_N = 15        # 默认精选条数
DESIGN_TOP_N_MAX = 25    # 优质内容集中时的上限

NO_RHETORIC_RULE = "语言要求：绝对不要使用任何比喻、拟人、排比等修辞手法，不要写“就像”“仿佛”这类词，直接大白话说清楚事实就行，越直白越好。"

NO_JARGON_RULE = """语言风格提醒：写"对设计师的意义""为什么值得看"这类字段时，不要用"赋能""闭环"
"抓手""颗粒度"这类空洞的黑话或管理术语。要用"你可以..."这种第二人称、直接、具体的大白话表达，
说清楚这条信息对设计师本人具体有什么用、能借鉴什么，不要用万能模板去套。"""


# ============ 用户画像 ============
USER_NAME = os.environ.get("USER_NAME", "").strip() or "你"
_USER_PROFILE_TEXT = os.environ.get("USER_PROFILE_TEXT", "").strip()

_DEFAULT_PROFILE_TEXT = """身份：视觉设计师
核心目标：获取全球优质设计资讯，精选最值得看的内容
重点关注领域：所有设计方向，尤其偏向视觉设计、UI/UX、品牌视觉、字体设计、排版、配色、插画、动效、设计工具与行业趋势
信息过滤规则：排除广告、卖课、招聘信息、与设计无关的科技和政治新闻
内容解释偏好：发生了什么、对设计工作有什么启发、可借鉴的视觉案例
行动建议偏好：给具体可做的设计练习或灵感方向"""

USER_PROFILE_TEXT = _USER_PROFILE_TEXT or _DEFAULT_PROFILE_TEXT

USER_PROFILE_PRIORITY = """筛选内容时请参考这个人的背景（这份背景由她本人通过问卷填写，请严格按照
里面写的关注领域和排除规则来筛选，不要脑补里面没提到的偏好）：

{profile}

{jargon_rule}""".format(profile=USER_PROFILE_TEXT, jargon_rule=NO_JARGON_RULE)

USER_PROFILE_FULL = """这个人叫{name}，下面是她通过问卷填写的个人背景，请严格按照这份背景来理解她的
身份、目标和偏好，不要预设、不要脑补背景里没提到的信息：

{profile}

她不喜欢空泛鼓励、鸡汤、模糊建议，喜欢直接分析问题、指出风险、给出判断和具体建议。

{jargon_rule}""".format(name=USER_NAME, profile=USER_PROFILE_TEXT, jargon_rule=NO_JARGON_RULE)


# ============ 来源标注 ============
DOMAIN_SOURCE = {
    "itsnicethat.com": "It's Nice That",
    "fontsinuse.com": "Fonts In Use",
    "bpando.org": "BP&O",
    "slanted.de": "Slanted",
    "creativebloq.com": "Creative Bloq",
    "core77.com": "Core77",
    "designboom.com": "Designboom",
    "design-milk.com": "Design Milk",
    "yankodesign.com": "Yanko Design",
    "dezeen.com": "Dezeen",
    "smashingmagazine.com": "Smashing Magazine",
    "awwwards.com": "Awwwards",
    "hoverstat.es": "HOVERSTAT.ES",
    "thisiscolossal.com": "Colossal",
    "disegnojournal.com": "Disegno",
}


def call_deepseek(prompt, max_retries=4, temperature=0.3):
    last_error = None
    for channel in CHANNELS:
        api_key = os.environ.get(channel["api_key_env"], "")
        if not api_key:
            print(f"  ⚠️ 渠道 {channel['name']} 未配置 API Key，跳过")
            continue

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": channel["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(channel["url"], headers=headers, json=body, timeout=300)
                resp.raise_for_status()
                print(f"  ✅ 使用渠道：{channel['name']}")
                return resp.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait_seconds = attempt * 5
                    print(f"  ⚠️ {channel['name']} 第{attempt}次失败（{e}），{wait_seconds}秒后重试...")
                    time.sleep(wait_seconds)
                else:
                    print(f"  ⚠️ {channel['name']} 第{attempt}次失败（{e}），切换到下一个渠道")

    raise last_error if last_error else RuntimeError("所有渠道均失败")


def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ 没找到 {filename}，先跑对应的抓取脚本再来跑这个")
        return None


def source_from_domain(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    if domain.startswith("www."):
        domain = domain[4:]
    for key, name in DOMAIN_SOURCE.items():
        if domain == key or domain.endswith("." + key):
            return name
    return domain


def attach_source_to_lines(text, item_pool):
    if not text or not item_pool:
        return text
    by_url = {}
    for item in item_pool:
        url = (item.get("url") or "").strip()
        if url and url not in by_url:
            by_url[url] = item
    out_lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if "|||" not in line:
            out_lines.append(raw_line)
            continue
        parts = [p.strip() for p in line.split("|||")]
        url = parts[1] if len(parts) >= 2 else ""
        item = by_url.get(url.strip()) if url else None
        if item:
            source = item.get("source") or source_from_domain(url)
        else:
            source = source_from_domain(url)
        if source:
            out_lines.append(f"{source}|||{line}")
        else:
            out_lines.append(raw_line)
    return "\n".join(out_lines)


def summarize_design(rss_data):
    """一次 AI 调用返回两个板块：精选（六段式）+ 其余（三段式）"""
    if not rss_data or not rss_data.get("items"):
        return "", ""

    # 每个源最多取8条，避免prompt过长导致API超时
    by_source = {}
    for x in rss_data["items"]:
        src = x.get("source", "")
        by_source.setdefault(src, []).append(x)

    all_lines = []
    item_pool = []
    for src, items in by_source.items():
        for x in items[:8]:
            title = x.get("title", "")
            url = x.get("url", "")
            all_lines.append(f"- [{src}] {title} (链接: {url})")
            item_pool.append(x)

    combined = "\n".join(all_lines)

    prompt = f"""下面是今天从多个设计媒体抓到的原始信息。请你处理：

1. 把英文标题全部翻译成中文
2. 合并多家媒体报道同一项目的内容，只保留一条，但保留多个来源名
3. 按下面的规则筛选和分类

【精选规则】
- 默认精选 {DESIGN_TOP_N} 条；如果当天优质内容特别集中，最多可放宽到 {DESIGN_TOP_N_MAX} 条，
  并在【精选】开头单独一行用一句话说明为什么增加（格式：REASON|||说明原因）
- 优质内容不足 {DESIGN_TOP_N} 条时，按实际数量输出，不凑数
- 兼顾视觉、字体、品牌包装、UI与交互、产品与空间设计，不要只集中在某一类
- 每个来源最多入选 3 条，仍有明显高价值内容时可以突破
- 优先选具体作品和设计分析，降低纯宣传、导购、重复新闻的优先级

【其余内容】
- 精选之外，仍然值得一看的内容，附标题、分类和原文链接，不展开摘要
- 分类从这些里选：视觉、字体、品牌包装、UI与交互、产品、空间、其他
- 已经在精选里出现过的不再重复

行首方括号（如[Design Milk]）表示这条来自哪个媒体，供你判断用，不要写进标题。

{USER_PROFILE_PRIORITY}

输出格式严格如下（两个板块之间用 【其余】 分隔）：

【精选】
（可选）REASON|||为什么增加条数的说明
中文标题|||链接|||关键词标签|||深度摘要|||一句话点评
（每条一行，不要加序号或"-"开头）

【其余】
中文标题|||分类|||链接
（每条一行，不要加序号或"-"开头）

各部分要求：
- 链接：原样使用对应内容后面给的真实网址，不要编造
- 关键词标签：2-3个词，逗号分隔
- 深度摘要：用大白话讲清楚"这是什么设计、有什么特点"，18-22字左右
- 一句话点评：说清楚"为什么值得看、对设计师有什么启发"，20-25字，要具体

{NO_RHETORIC_RULE}

{NO_JARGON_RULE}

不要写多余的开场白。

原始信息：
{combined}
"""
    result = call_deepseek(prompt)

    # 按【其余】切分
    selected_text = ""
    more_text = ""
    if "【其余】" in result:
        parts = result.split("【其余】", 1)
        selected_text = parts[0].replace("【精选】", "").strip()
        more_text = parts[1].strip()
    else:
        selected_text = result.replace("【精选】", "").strip()

    selected_with_source = attach_source_to_lines(selected_text, item_pool)
    return selected_with_source, more_text


def summarize_overview(design_text):
    prompt = f"""下面是今天的设计资讯摘要，请你写一段"今日设计总览"，格式严格如下：

【今日一句话】
用抽象但有信息量的方式概括今天的设计主题/趋势，不超过25字。要求：
- 不要写"今日多条设计资讯发布"这种空话
- 也不要罗列多个具体品牌名/产品名堆在一起
- 类似"极简主义回潮与材质实验成为今日焦点"这种程度——概括出一个主题/趋势，
  可以带1个简短例子帮助理解

【设计观察】
1-2句话，讲清楚今天资讯里出现了哪类共同点或趋势，直接说事实和判断。

【趋势预测】
1-2句话，基于今天的信息往前看一步：接下来设计圈可能会怎样发展。

{NO_RHETORIC_RULE}

{NO_JARGON_RULE}

不要写多余的开场白。

设计资讯摘要：
{design_text}
"""
    return call_deepseek(prompt)


def generate_action_advice(design_text):
    prompt = f"""{USER_PROFILE_FULL}

下面是今天的设计简报内容，请你基于这些信息，给这个人生成一段"今日行动建议"。

严格按这个结构输出：

【可能的方向】
列出2-3个今天内容里能延伸出的具体方向，每个方向必须是"今天几十分钟到1小时内能实际做完的具体小事"，
比如"打开这个网站看3个案例，记录2个可复用的配色方案"这种程度，
绝对不能是"整理XX清单""输出XX笔记"这类模糊的任务式表达。
格式：方向名称|||具体做法（20-30字，要具体到"打开什么、看什么、做什么"）

【不建议投入】
指出1个不值得现在投入时间的方向，并说明为什么，1-2句话，不超过40字。

【今日推荐行动】
从上面的方向里选1个，给一个今天就能开始做的具体动作，必须具体到"打开什么、做什么、大概花多久"，
不超过40字，不能是模糊的"了解一下""关注一下"。

{NO_RHETORIC_RULE}

不要写多余的开场白。

今天的设计简报内容：
{design_text}
"""
    return call_deepseek(prompt)


def generate_greeting(todo_hint, action_hint):
    mood_rule = """现在是早上，写给刚起床准备开始一天的她。语气要像朋友一样自然温暖，
提醒她看一眼今天的安排、准备开始行动。"""
    health_pool = ["记得喝水", "起来活动一下、别久坐", "好好吃早饭", "让眼睛歇一歇别一直盯屏幕",
                   "做几个深呼吸调整状态", "有空开窗透透气、晒会儿太阳"]

    health_topic = random.choice(health_pool)
    tone_anchor = random.choice([
        "像刚聊完天顺口说一句的语气", "像发消息提醒朋友的语气", "简短利落，不要铺垫太多",
        "带点俏皮但不浮夸", "平静温和，像很熟的朋友", "直接一点，像在催她赶紧行动",
    ])

    prompt = f"""这个人叫{USER_NAME}。请你以"每日设计简报"这个AI助手的身份，给她写一段开头问候和一段结尾道别。

{mood_rule}

今天的问候要包含三个要素，自然揉在一起说，不要写成三条并列的清单：
1. 提到"{USER_NAME}"这个名字
2. 提醒她今天该做的事——参考下面"今日待办参考"里的内容，挑最值得提一句的说
3. 带一句健康小提示，这次要提的方向是："{health_topic}"（用你自己的话自然说出来）

今日待办参考：
{todo_hint}
{action_hint}

写作要求：
- 这次的语气基调：{tone_anchor}
- 开头问候2句话左右，40字以内
- 结尾道别1句话，20字以内，呼应今天的行动
- 不要写"祝你度过美好的一天"这类通用客套话
- 不要写日期、天气这类你不确定的信息
- 每次遣词造句都要有变化，避免使用固定的开头句式

{NO_RHETORIC_RULE}

格式严格按：
【开头】
（开头问候内容）
【结尾】
（结尾道别内容）

不要写多余的开场白。
"""
    return call_deepseek(prompt, temperature=0.95)


if __name__ == "__main__":
    slot = "morning"
    print("正在生成今日设计简报...\n")

    today = datetime.now().strftime("%Y-%m-%d")
    sections = {}

    rss_data = load_json("rss_sources.json")

    if rss_data:
        print("正在生成设计资讯精选 + 其余目录...")
        sections["design"], sections["more"] = summarize_design(rss_data)
        print(sections["design"] + "\n")

        print("正在生成今日设计总览...")
        sections["overview"] = summarize_overview(sections.get("design", "无"))
        print(sections["overview"] + "\n")

        print("正在生成今日行动建议...")
        sections["action"] = generate_action_advice(sections.get("design", "无"))
        print(sections["action"] + "\n")

        print("正在生成早间问候语...")
        sections["greeting"] = generate_greeting(
            sections.get("overview", "（今天没有总览内容）"),
            sections.get("action", "（今天没有行动建议）"),
        )
        print(sections["greeting"] + "\n")
    else:
        print("⚠️ 没有抓到设计资讯，跳过所有摘要生成")

    with open("daily_brief.md", "w", encoding="utf-8") as f:
        f.write(f"DATE|||{today}\n")
        f.write(f"SLOT|||{slot}\n")
        f.write("SECTION|||overview\n")
        f.write(sections.get("overview", "") + "\n")
        f.write("SECTION|||design\n")
        f.write(sections.get("design", "") + "\n")
        f.write("SECTION|||more\n")
        f.write(sections.get("more", "") + "\n")
        f.write("SECTION|||action\n")
        f.write(sections.get("action", "") + "\n")
        f.write("SECTION|||greeting\n")
        f.write(sections.get("greeting", "") + "\n")

    print("✅ 简报已生成：daily_brief.md")
