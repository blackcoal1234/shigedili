"""可视化 HTML 输出的本地静态资源处理与高级统一视觉主题。"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path


PYECHARTS_ASSET_HOST = "https://assets.pyecharts.org/assets/v6/"
PYECHARTS_ASSETS = ("echarts.min.js",)


def localize_pyecharts_assets(html_path: Path, output_dir: Path) -> None:
    """把 pyecharts CDN 引用替换为 output 下的本地相对资源。"""
    asset_dir = output_dir / "assets" / "pyecharts" / "v6"
    replacements: dict[str, str] = {}

    for asset in PYECHARTS_ASSETS:
        local_path = asset_dir / asset
        if not local_path.exists() or local_path.stat().st_size <= 1024:
            raise RuntimeError(f"本地 pyecharts 资源缺失或异常：{local_path}")
        replacements[PYECHARTS_ASSET_HOST + asset] = f"assets/pyecharts/v6/{asset}"

    html = html_path.read_text(encoding="utf-8")
    for remote, local in replacements.items():
        html = html.replace(remote, local)

    html_path.write_text(html, encoding="utf-8")


def _ensure_viewport(html: str) -> str:
    viewport = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    if viewport in html:
        return html

    if '<meta charset="UTF-8">' in html:
        return html.replace('<meta charset="UTF-8">', f'<meta charset="UTF-8">\n    {viewport}', 1)

    if "<head>" in html:
        return html.replace("<head>", f"<head>\n    {viewport}", 1)

    return html


def _ensure_page_metadata(html: str, title: str | None = None) -> str:
    if title:
        title_tag = f"<title>{escape(title)}</title>"
        html, replacements = re.subn(
            r"<title\b[^>]*>.*?</title>",
            title_tag,
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if replacements == 0:
            html = _inject_before_head_close(html, title_tag)

    if not re.search(r"<link\b[^>]*\brel=[\"'](?:shortcut )?icon[\"']", html, re.IGNORECASE):
        html = _inject_before_head_close(html, '<link rel="icon" href="data:,">')
    return html


def _inject_before_head_close(html: str, snippet: str) -> str:
    if "</head>" in html:
        return html.replace("</head>", f"{snippet}\n</head>", 1)
    return f"{snippet}\n{html}"


def _inject_after_body_open(html: str, snippet: str) -> str:
    match = re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE)
    if match:
        return f"{html[:match.end()]}\n{snippet}\n{html[match.end():]}"
    return f"{snippet}\n{html}"


def inject_index_backlink(html: str, href: str = "index.html") -> str:
    """为内容页注入返回总入口的高级悬浮导航。"""
    if "shixing-index-backlink" in html:
        return html

    style = """
    <style id="shixing-index-backlink-style">
        .shixing-index-backlink {
            position: sticky;
            top: 12px;
            z-index: 9999;
            box-sizing: border-box;
            width: min(1240px, calc(100% - 32px));
            margin: 14px auto 0;
            font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
            pointer-events: none;
        }
        .shixing-index-backlink a {
            pointer-events: auto;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-height: 38px;
            padding: 8px 14px;
            border: 1px solid rgba(34, 211, 238, 0.35);
            border-radius: 999px;
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.70)),
                rgba(255, 255, 255, 0.08);
            color: #cffafe;
            font-size: 14px;
            font-weight: 800;
            line-height: 1.2;
            text-decoration: none;
            box-shadow:
                0 16px 42px rgba(0, 0, 0, 0.22),
                inset 0 0 0 1px rgba(255, 255, 255, 0.04);
            backdrop-filter: blur(18px);
            transition:
                transform .18s ease,
                border-color .18s ease,
                box-shadow .18s ease,
                color .18s ease;
        }
        .shixing-index-backlink a::before {
            content: "←";
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            border-radius: 999px;
            background: rgba(34, 211, 238, 0.16);
            color: #67e8f9;
            font-weight: 900;
        }
        .shixing-index-backlink a:focus-visible,
        .shixing-index-backlink a:hover {
            transform: translateY(-2px);
            border-color: rgba(34, 211, 238, 0.72);
            color: #ffffff;
            box-shadow:
                0 22px 54px rgba(0, 0, 0, 0.30),
                0 0 28px rgba(34, 211, 238, 0.18);
        }
        @media (max-width: 640px) {
            .shixing-index-backlink {
                width: calc(100% - 20px);
                margin-top: 10px;
            }
            .shixing-index-backlink a {
                width: 100%;
                justify-content: center;
            }
        }
    </style>
"""

    nav = f"""
    <nav class="shixing-index-backlink" aria-label="页面导航">
        <a href="{escape(href)}">返回总入口</a>
    </nav>
"""

    html = _inject_before_head_close(html, style)
    html = _inject_after_body_open(html, nav)
    return html


def premium_global_css(
    page_key: str,
    accent: str = "#22d3ee",
    accent_2: str = "#a78bfa",
    accent_3: str = "#34d399",
) -> str:
    """返回统一高级大屏风格 CSS。"""
    return f"""
    <style id="shixing-premium-style-{escape(page_key)}">
        :root {{
            --sx-bg-0: #050816;
            --sx-bg-1: #08111f;
            --sx-bg-2: #0f172a;
            --sx-panel: rgba(15, 23, 42, 0.76);
            --sx-panel-strong: rgba(15, 23, 42, 0.94);
            --sx-glass: rgba(255, 255, 255, 0.075);
            --sx-glass-strong: rgba(255, 255, 255, 0.13);
            --sx-line: rgba(148, 163, 184, 0.22);
            --sx-line-strong: rgba(148, 163, 184, 0.38);
            --sx-text: #e5edf9;
            --sx-muted: #9aa8bd;
            --sx-soft: #cbd5e1;
            --sx-accent: {accent};
            --sx-accent-2: {accent_2};
            --sx-accent-3: {accent_3};
            --sx-warn: #fbbf24;
            --sx-danger: #fb7185;
            --sx-shadow: 0 28px 80px rgba(0, 0, 0, 0.36);
            --sx-radius-xl: 28px;
            --sx-radius-lg: 22px;
            --sx-radius-md: 16px;
            --sx-radius-sm: 12px;
        }}

        * {{
            box-sizing: border-box;
        }}

        html {{
            scroll-behavior: smooth;
        }}

        html,
        body {{
            margin: 0;
            padding: 0;
            min-height: 100vh;
            overflow-x: hidden;
        }}

        body {{
            color: var(--sx-text);
            font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
            background:
                radial-gradient(circle at 8% 10%, color-mix(in srgb, var(--sx-accent), transparent 76%), transparent 30%),
                radial-gradient(circle at 88% 8%, color-mix(in srgb, var(--sx-accent-2), transparent 76%), transparent 28%),
                radial-gradient(circle at 60% 90%, color-mix(in srgb, var(--sx-accent-3), transparent 82%), transparent 30%),
                linear-gradient(135deg, var(--sx-bg-0), var(--sx-bg-1) 42%, #111827);
        }}

        body::before {{
            content: "";
            position: fixed;
            inset: 0;
            z-index: -2;
            pointer-events: none;
            opacity: 0.16;
            background-image:
                linear-gradient(rgba(255,255,255,.06) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,.06) 1px, transparent 1px);
            background-size: 42px 42px;
            mask-image: linear-gradient(to bottom, black, transparent 86%);
        }}

        body::after {{
            content: "";
            position: fixed;
            inset: 0;
            z-index: -1;
            pointer-events: none;
            background:
                radial-gradient(circle at 22% 26%, color-mix(in srgb, var(--sx-accent), transparent 88%), transparent 24%),
                radial-gradient(circle at 80% 70%, color-mix(in srgb, var(--sx-accent-2), transparent 90%), transparent 28%);
            filter: blur(2px);
        }}

        a {{
            color: inherit;
        }}

        .shixing-premium-shell {{
            width: min(1240px, calc(100vw - 36px));
            margin: 0 auto;
            padding: 24px 0 54px;
        }}

        .shixing-premium-hero {{
            position: relative;
            min-height: 330px;
            margin: 18px auto 22px;
            padding: 28px;
            border: 1px solid var(--sx-line);
            border-radius: var(--sx-radius-xl);
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.94), rgba(15, 23, 42, 0.64)),
                radial-gradient(circle at 82% 16%, color-mix(in srgb, var(--sx-accent), transparent 82%), transparent 38%);
            box-shadow: var(--sx-shadow);
            overflow: hidden;
        }}

        .shixing-premium-hero::before {{
            content: "";
            position: absolute;
            width: 360px;
            height: 360px;
            right: -120px;
            top: -150px;
            border-radius: 999px;
            background: var(--sx-accent);
            opacity: 0.16;
            filter: blur(22px);
        }}

        .shixing-premium-hero::after {{
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            background:
                linear-gradient(120deg, transparent, rgba(255,255,255,.07), transparent);
            transform: translateX(-130%);
            animation: shixingPremiumSheen 7s ease-in-out infinite;
        }}

        @keyframes shixingPremiumSheen {{
            0%, 62% {{
                transform: translateX(-130%);
            }}
            100% {{
                transform: translateX(130%);
            }}
        }}

        .shixing-premium-hero-inner {{
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
            gap: 24px;
            align-items: end;
        }}

        .shixing-premium-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #67e8f9;
            font-size: 12px;
            font-weight: 900;
            letter-spacing: 0.16em;
            text-transform: uppercase;
        }}

        .shixing-premium-eyebrow::before {{
            content: "";
            width: 28px;
            height: 1px;
            background: currentColor;
        }}

        .shixing-premium-hero h1 {{
            margin: 16px 0 16px;
            max-width: 780px;
            font-size: clamp(34px, 5vw, 62px);
            line-height: 1.02;
            letter-spacing: -0.06em;
            color: #f8fafc;
        }}

        .shixing-premium-gradient {{
            background: linear-gradient(90deg, #e0f2fe, #a7f3d0 44%, #c4b5fd);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }}

        .shixing-premium-subtitle {{
            margin: 0;
            max-width: 820px;
            color: var(--sx-muted);
            font-size: 15px;
            line-height: 1.9;
        }}

        .shixing-premium-metrics {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }}

        .shixing-premium-metric {{
            min-height: 96px;
            padding: 16px;
            border: 1px solid var(--sx-line);
            border-radius: var(--sx-radius-md);
            background: rgba(255, 255, 255, 0.075);
            backdrop-filter: blur(20px);
        }}

        .shixing-premium-metric span {{
            display: block;
            color: var(--sx-muted);
            font-size: 12px;
            font-weight: 800;
        }}

        .shixing-premium-metric strong {{
            display: block;
            margin-top: 9px;
            color: #f8fafc;
            font-size: 26px;
            line-height: 1.1;
            letter-spacing: -0.04em;
            overflow-wrap: anywhere;
        }}

        .shixing-premium-note {{
            margin-top: 12px;
            padding: 14px 16px;
            border: 1px solid rgba(251, 191, 36, 0.30);
            border-radius: var(--sx-radius-md);
            background:
                linear-gradient(135deg, rgba(120, 53, 15, 0.30), rgba(15, 23, 42, 0.58));
            color: #fde68a;
            font-size: 13px;
            line-height: 1.75;
        }}

        .shixing-premium-section {{
            width: min(1240px, calc(100vw - 36px));
            margin: 22px auto;
        }}

        .shixing-premium-panel {{
            border: 1px solid var(--sx-line);
            border-radius: var(--sx-radius-lg);
            background:
                linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.035)),
                rgba(15, 23, 42, 0.72);
            box-shadow: 0 24px 68px rgba(0, 0, 0, 0.28);
            backdrop-filter: blur(22px);
            overflow: hidden;
        }}

        .shixing-premium-panel-head {{
            padding: 18px 20px;
            border-bottom: 1px solid var(--sx-line);
            background: rgba(2, 6, 23, 0.20);
        }}

        .shixing-premium-panel-head h2 {{
            margin: 0;
            color: #f8fafc;
            font-size: 22px;
            letter-spacing: -0.03em;
        }}

        .shixing-premium-panel-head p {{
            margin: 8px 0 0;
            color: var(--sx-muted);
            font-size: 13px;
            line-height: 1.7;
        }}

        .shixing-premium-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }}

        .shixing-premium-info-card {{
            min-height: 118px;
            padding: 16px;
            border: 1px solid var(--sx-line);
            border-radius: var(--sx-radius-md);
            background: rgba(255, 255, 255, 0.06);
        }}

        .shixing-premium-info-card strong {{
            display: block;
            color: #f8fafc;
            font-size: 16px;
            line-height: 1.45;
        }}

        .shixing-premium-info-card span {{
            display: block;
            margin-top: 8px;
            color: var(--sx-muted);
            font-size: 13px;
            line-height: 1.7;
        }}

        .box {{
            width: 100%;
            box-sizing: border-box;
            justify-content: center !important;
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 24px !important;
            padding: 0 18px 44px !important;
        }}

        .chart-container {{
            box-sizing: border-box;
            min-width: 0;
            border: 1px solid var(--sx-line) !important;
            border-radius: var(--sx-radius-lg);
            background:
                linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.035)),
                rgba(15, 23, 42, 0.72) !important;
            box-shadow: 0 24px 68px rgba(0, 0, 0, 0.26);
            backdrop-filter: blur(22px);
            overflow: hidden;
        }}

        .chart-container canvas,
        .chart-container > div {{
            border-radius: inherit;
        }}

        .shixing-premium-table {{
            width: 100%;
            border-collapse: collapse;
            color: var(--sx-text);
        }}

        .shixing-premium-table th,
        .shixing-premium-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid var(--sx-line);
            text-align: left;
            vertical-align: top;
        }}

        .shixing-premium-table th {{
            color: #cbd5e1;
            font-size: 13px;
            background: rgba(2, 6, 23, 0.28);
        }}

        .shixing-premium-table td {{
            color: var(--sx-muted);
            font-size: 14px;
            line-height: 1.65;
        }}

        .shixing-premium-pill {{
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            padding: 0 9px;
            border: 1px solid color-mix(in srgb, var(--sx-accent), transparent 58%);
            border-radius: 999px;
            background: color-mix(in srgb, var(--sx-accent), transparent 86%);
            color: #cffafe;
            font-size: 12px;
            font-weight: 900;
        }}

        @media (max-width: 960px) {{
            .shixing-premium-hero-inner {{
                grid-template-columns: 1fr;
            }}

            .shixing-premium-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        @media (max-width: 720px) {{
            .shixing-premium-shell,
            .shixing-premium-section {{
                width: min(100vw - 22px, 1240px);
            }}

            .shixing-premium-hero {{
                padding: 18px;
                border-radius: 22px;
            }}

            .shixing-premium-hero h1 {{
                font-size: 34px;
            }}

            .shixing-premium-metrics {{
                grid-template-columns: 1fr;
            }}

            .box {{
                padding: 0 8px 32px !important;
                gap: 18px !important;
            }}

            .chart-container {{
                width: calc(100vw - 22px) !important;
                max-width: calc(100vw - 22px) !important;
                height: min(72vh, var(--chart-height, 640px)) !important;
                max-height: 72vh;
            }}
        }}
    </style>
"""


def _metric_html(metrics: list[tuple[str, str]] | None) -> str:
    if not metrics:
        return ""

    items = []
    for label, value in metrics:
        items.append(
            f"""
            <div class="shixing-premium-metric">
                <span>{escape(str(label))}</span>
                <strong>{escape(str(value))}</strong>
            </div>
            """
        )

    return f"""
        <div class="shixing-premium-metrics">
            {''.join(items)}
        </div>
    """


def premium_hero_html(
    title: str,
    subtitle: str,
    eyebrow: str = "Poetry Data Visualization",
    metrics: list[tuple[str, str]] | None = None,
    note: str | None = None,
) -> str:
    note_html = ""
    if note:
        note_html = f'<div class="shixing-premium-note">{escape(note)}</div>'

    return f"""
    <section class="shixing-premium-shell">
        <section class="shixing-premium-hero" aria-label="{escape(title)}">
            <div class="shixing-premium-hero-inner">
                <div>
                    <span class="shixing-premium-eyebrow">{escape(eyebrow)}</span>
                    <h1><span class="shixing-premium-gradient">{escape(title)}</span></h1>
                    <p class="shixing-premium-subtitle">{escape(subtitle)}</p>
                    {note_html}
                </div>
                {_metric_html(metrics)}
            </div>
        </section>
    </section>
"""


def replace_chart_container_style(html: str) -> str:
    """把 pyecharts 固定宽高容器改为响应式高级卡片。"""
    return re.sub(
        r'class="chart-container" style="width:(\d+)px; height:(\d+)px; ?"',
        (
            r'class="chart-container" data-chart-width="\1" data-chart-height="\2" '
            r'style="--chart-width:\1px; --chart-height:\2px; '
            r'width:100%; max-width:var(--chart-width); height:var(--chart-height);"'
        ),
        html,
    )


def inject_chart_resize_script(html: str) -> str:
    """为 ECharts 页面注入窗口变化时自动 resize 的脚本。"""
    if "shixing-premium-resize-charts" in html:
        return html

    script = """
    <script id="shixing-premium-resize-charts">
        (function () {
            function resizeCharts() {
                if (!window.echarts) { return; }
                document.querySelectorAll(".chart-container").forEach(function (el) {
                    var chart = echarts.getInstanceByDom(el);
                    if (chart) { chart.resize(); }
                });
            }
            window.addEventListener("resize", resizeCharts);
            window.addEventListener("orientationchange", resizeCharts);
            setTimeout(resizeCharts, 0);
            setTimeout(resizeCharts, 360);
        }());
    </script>
"""
    if "</body>" in html:
        return html.replace("</body>", f"{script}\n</body>", 1)
    return f"{html}\n{script}"


def inject_premium_chart_page(
    html: str,
    *,
    page_key: str,
    title: str,
    subtitle: str,
    eyebrow: str = "Poetry Data Visualization",
    metrics: list[tuple[str, str]] | None = None,
    note: str | None = None,
    accent: str = "#22d3ee",
    accent_2: str = "#a78bfa",
    accent_3: str = "#34d399",
    backlink_href: str = "index.html",
) -> str:
    """给 pyecharts 输出页统一注入高级风格、Hero、响应式容器和返回入口。"""
    html = _ensure_viewport(html)
    html = _ensure_page_metadata(html, title)

    if f"shixing-premium-style-{page_key}" not in html:
        html = _inject_before_head_close(
            html,
            premium_global_css(
                page_key=page_key,
                accent=accent,
                accent_2=accent_2,
                accent_3=accent_3,
            ),
        )

    if "shixing-premium-hero" not in html:
        html = _inject_after_body_open(
            html,
            premium_hero_html(
                title=title,
                subtitle=subtitle,
                eyebrow=eyebrow,
                metrics=metrics,
                note=note,
            ),
        )

    old_style = '<style>.box { justify-content:center; display:flex; flex-wrap:wrap;  } </style>'
    if old_style in html:
        html = html.replace(old_style, "", 1)

    html = replace_chart_container_style(html)
    html = inject_chart_resize_script(html)
    html = inject_index_backlink(html, href=backlink_href)

    return html


def write_premium_chart_page(
    html_path: Path,
    *,
    page_key: str,
    title: str,
    subtitle: str,
    eyebrow: str = "Poetry Data Visualization",
    metrics: list[tuple[str, str]] | None = None,
    note: str | None = None,
    accent: str = "#22d3ee",
    accent_2: str = "#a78bfa",
    accent_3: str = "#34d399",
    backlink_href: str = "index.html",
) -> None:
    """读取 HTML、注入高级主题并写回。"""
    html = html_path.read_text(encoding="utf-8")
    html = inject_premium_chart_page(
        html,
        page_key=page_key,
        title=title,
        subtitle=subtitle,
        eyebrow=eyebrow,
        metrics=metrics,
        note=note,
        accent=accent,
        accent_2=accent_2,
        accent_3=accent_3,
        backlink_href=backlink_href,
    )
    html_path.write_text(html, encoding="utf-8")


def premium_static_page_css(
    page_key: str,
    accent: str = "#22d3ee",
    accent_2: str = "#a78bfa",
    accent_3: str = "#34d399",
) -> str:
    """给手写 HTML 页面使用的高级主题 CSS。"""
    return premium_global_css(
        page_key=page_key,
        accent=accent,
        accent_2=accent_2,
        accent_3=accent_3,
    )


def inject_static_page_base(
    html: str,
    *,
    page_key: str,
    accent: str = "#22d3ee",
    accent_2: str = "#a78bfa",
    accent_3: str = "#34d399",
    backlink_href: str = "index.html",
) -> str:
    """给手写 HTML 页面注入基础高级背景和返回入口。"""
    html = _ensure_viewport(html)
    html = _ensure_page_metadata(html)

    if f"shixing-premium-style-{page_key}" not in html:
        html = _inject_before_head_close(
            html,
            premium_static_page_css(
                page_key=page_key,
                accent=accent,
                accent_2=accent_2,
                accent_3=accent_3,
            ),
        )

    html = inject_index_backlink(html, href=backlink_href)
    return html
