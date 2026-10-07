"""
把 daily_brief.md 解析成结构化数据，生成精致的 HTML 卡片邮件发出去

板块：今日总览 / 设计资讯精选 / 今日行动建议 / 问候语
"""
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.header import Header

QQ_EMAIL = os.environ.get("QQ_EMAIL", "")
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE", "")
SEND_TO = os.environ.get("SEND_TO", QQ_EMAIL)

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465

COLOR_DARK = "#2c3e50"
COLOR_ACCENT = "#3f6b8f"
COLOR_MUTED = "#8a95a3"
COLOR_BG_ACCENT = "#eaf0f5"
COLOR_BG_MUTED = "#f4f5f6"

_LEADING_MARKER_RE = re.compile(r"^[\s\-\*•·]*(\d+[\.\、\)]\s+)?")


def _split_line(line, min_parts):
    line = _LEADING_MARKER_RE.sub("", line).strip()
    if "|||" not in line:
        return None
    parts = [p.strip() for p in line.split("|||")]
    if len(parts) < min_parts:
        parts += [""] * (min_parts - len(parts))
    return parts


def parse_brief(content):
    date = ""
    slot = "morning"
    keys = ["overview", "design", "action", "greeting"]
    sections = {k: "" for k in keys}
    current = None
    for line in content.split("\n"):
        if line.startswith("DATE|||"):
            date = line.split("|||", 1)[1]
        elif line.startswith("SLOT|||"):
            slot = line.split("|||", 1)[1]
        elif line.startswith("SECTION|||"):
            current = line.split("|||", 1)[1]
        elif current in sections:
            sections[current] += line + "\n"
    return date, slot, sections


def render_overview(text):
    one_liner, design_view, trend = "", "", ""
    mode = None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "今日一句话" in line:
            mode = "one_liner"
            continue
        if "设计观察" in line or "AI观察" in line:
            mode = "design_view"
            continue
        if "趋势预测" in line:
            mode = "trend"
            continue
        if mode == "one_liner":
            one_liner += line
        elif mode == "design_view":
            design_view += line + " "
        elif mode == "trend":
            trend += line + " "

    trend_html = f'''<div style="font-size:15px; color:#cfd8e3; line-height:1.7; margin-top:12px; border-top:1px solid rgba(255,255,255,0.2); padding-top:12px;">🔮 {trend}</div>''' if trend else ""

    html = f'''<div style="background:{COLOR_DARK}; border-radius:8px; padding:22px; margin-bottom:20px; color:#fff;">
        <div style="font-size:19px; font-weight:700; line-height:1.6;">{one_liner}</div>
        <div style="font-size:15px; color:#cfd8e3; line-height:1.7; margin-top:14px; border-top:1px solid rgba(255,255,255,0.2); padding-top:14px;">💭 {design_view}</div>
        {trend_html}
    </div>'''
    return html


def render_design_cards(text):
    """六段式：来源|||标题|||链接|||标签|||深度摘要|||一句话点评"""
    html = ""
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = _split_line(line, 6)
        if not parts:
            continue
        if len(parts) >= 6:
            source, title, url, tags, digest, comment = parts[:6]
        else:
            source = ""
            title, url, tags, digest, comment = parts[:5]
        if not title:
            continue
        title_html = f'<a href="{url}" style="color:#222; text-decoration:none; border-bottom:1px dotted #222;">{title}</a>' if url else title
        tag_badges = "".join([
            f'<span style="display:inline-block; background:{COLOR_BG_ACCENT}; color:{COLOR_ACCENT}; font-size:12px; padding:3px 8px; border-radius:8px; margin-right:5px;">{t.strip()}</span>'
            for t in tags.split(",") if t.strip()
        ])
        source_badge = f'<span style="display:inline-block; background:{COLOR_ACCENT}; color:#fff; font-size:12px; padding:3px 10px; border-radius:10px; margin-right:6px; vertical-align:2px;">{source}</span>' if source else ""
        html += f'''<div style="background:{COLOR_BG_MUTED}; border-radius:6px; padding:16px 18px; margin-bottom:12px;">
            <div style="font-size:16.5px; font-weight:600; color:#222;">{source_badge}{title_html}</div>
            <div style="margin-top:8px;">{tag_badges}</div>
            <div style="font-size:14.5px; color:#555; margin-top:8px; line-height:1.6;">{digest}</div>
            <div style="font-size:13.5px; color:#888; margin-top:8px; line-height:1.6;">💬 {comment}</div>
        </div>'''
    return html


def render_action_advice(text):
    directions, not_worth, recommend = [], "", ""
    mode = None
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if "可能的方向" in line:
            mode = "directions"
            continue
        if "不建议投入" in line:
            mode = "not_worth"
            continue
        if "今日推荐行动" in line:
            mode = "recommend"
            continue
        if mode == "directions":
            parts = _split_line(line, 2)
            if parts and parts[0]:
                directions.append((parts[0], parts[1]))
        elif mode == "not_worth":
            not_worth += line
        elif mode == "recommend":
            recommend += line

    if not directions and not not_worth and not recommend:
        return ""

    directions_html = "".join([
        f'''<div style="padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.15);">
            <div style="font-size:15px; font-weight:600; color:#fff;">🧭 {name}</div>
            <div style="font-size:14px; color:#cfd8e3; margin-top:4px; line-height:1.6;">{detail}</div>
        </div>'''
        for name, detail in directions
    ])

    not_worth_html = f'''<div style="margin-top:14px; padding:12px 14px; background:rgba(255,255,255,0.08); border-radius:6px;">
        <div style="font-size:13px; color:#a8b4c2;">⚠️ 不建议现在投入</div>
        <div style="font-size:14px; color:#e5eaf0; margin-top:4px; line-height:1.6;">{not_worth}</div>
    </div>''' if not_worth else ""

    recommend_html = f'''<div style="margin-top:14px; padding:14px 16px; background:{COLOR_ACCENT}; border-radius:6px;">
        <div style="font-size:13px; color:#dce6f0;">✅ 今日推荐行动</div>
        <div style="font-size:15.5px; color:#fff; font-weight:600; margin-top:4px; line-height:1.6;">{recommend}</div>
    </div>''' if recommend else ""

    return f'''<h2 style="font-size:18px; color:{COLOR_DARK}; margin-top:26px;">🎯 今日行动建议</h2>
    <div style="background:{COLOR_DARK}; border-radius:8px; padding:18px 20px;">
        {directions_html}
        {not_worth_html}
        {recommend_html}
    </div>'''


def render_greeting(text):
    opening, closing = "", ""
    mode = None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "开头" in line and line.startswith("【"):
            mode = "opening"
            continue
        if "结尾" in line and line.startswith("【"):
            mode = "closing"
            continue
        if mode == "opening":
            opening += line
        elif mode == "closing":
            closing += line
    return opening, closing


def build_html(date, slot, sections):
    overview_html = render_overview(sections.get("overview", ""))
    design_html = render_design_cards(sections.get("design", ""))
    action_html = render_action_advice(sections.get("action", ""))
    opening, closing = render_greeting(sections.get("greeting", ""))

    opening_html = f'''<div style="font-size:15px; color:{COLOR_DARK}; background:{COLOR_BG_ACCENT}; border-radius:8px; padding:14px 18px; margin-bottom:16px; line-height:1.6;">早安👋 {opening}</div>''' if opening else ""

    closing_html = f'''<div style="background:{COLOR_BG_ACCENT}; border-radius:8px; padding:18px 22px; margin-top:30px; text-align:center;">
        <div style="font-size:15px; font-weight:600; color:{COLOR_DARK}; line-height:1.6;">💌 {closing}</div>
    </div>''' if closing else ""

    design_section = f'''<h2 style="font-size:18px; color:{COLOR_DARK}; margin-top:26px;">🎨 设计资讯精选</h2>
    {design_html}''' if design_html else ""

    return f"""
    <div style="max-width:620px; margin:0 auto; font-family:-apple-system,'PingFang SC',sans-serif;">
        <h1 style="font-size:23px; color:{COLOR_DARK}; margin-bottom:6px;">📋 每日设计简报</h1>
        <div style="font-size:15px; color:{COLOR_MUTED}; margin-bottom:18px;">{date}</div>

        {opening_html}

        {overview_html}

        {design_section}

        {action_html}

        {closing_html}
    </div>
    """


def send_brief_email():
    try:
        with open("daily_brief.md", "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError as e:
        print("❌ 没找到 daily_brief.md，无法发送邮件")
        raise RuntimeError("daily_brief.md 不存在") from e

    date, slot, sections = parse_brief(content)
    html_content = build_html(date, slot, sections)

    msg = MIMEText(html_content, "html", "utf-8")
    msg["From"] = QQ_EMAIL
    msg["To"] = SEND_TO
    msg["Subject"] = Header(f"每日设计简报 {date}", "utf-8")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(QQ_EMAIL, QQ_AUTH_CODE)
            server.sendmail(QQ_EMAIL, [SEND_TO], msg.as_string())

        print(f"✅ 简报已发送到 {SEND_TO}")

    except Exception as e:
        print(f"❌ 发送失败：{e}")
        raise


if __name__ == "__main__":
    send_brief_email()
