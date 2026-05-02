#!/usr/bin/env python3
"""Static blog generator for sigreturn.com.

Usage: python3 build.py

Reads posts/*.md (front-matter + markdown), renders to blog/<slug>.html,
generates blog/index.html and blog/feed.xml, and regenerates sitemap.xml.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import string
import sys
from email.utils import format_datetime
from pathlib import Path

import frontmatter
import markdown as md_lib

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
BLOG_DIR = ROOT / "blog"
TEMPLATES_DIR = ROOT / "templates"
SITEMAP_PATH = ROOT / "sitemap.xml"

SITE_URL = "https://sigreturn.com"
SITE_TITLE = "Sigreturn Labs Blog"
SITE_DESCRIPTION = "Notes from the lab — research, writeups, and product updates from Sigreturn Labs."

REQUIRED_FIELDS = ("title", "author", "date", "category", "description")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

STATIC_PAGES = [
    {"loc": "/", "changefreq": "monthly", "priority": "1.0"},
    {"loc": "/terms.html", "changefreq": "yearly", "priority": "0.3"},
    {"loc": "/privacy.html", "changefreq": "yearly", "priority": "0.3"},
]


class BuildError(Exception):
    pass


def load_template(name: str) -> string.Template:
    return string.Template((TEMPLATES_DIR / name).read_text(encoding="utf-8"))


def coerce_date(value, source: Path) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as e:
            raise BuildError(f"{source.name}: invalid date '{value}' (use YYYY-MM-DD)") from e
    raise BuildError(f"{source.name}: date must be YYYY-MM-DD, got {type(value).__name__}")


def slug_from_path(path: Path) -> str:
    slug = path.stem
    if not SLUG_RE.match(slug):
        raise BuildError(
            f"{path.name}: filename must be lowercase letters, digits, and dashes only"
        )
    return slug


def parse_post(path: Path) -> dict | None:
    post = frontmatter.load(path)

    if post.metadata.get("draft") is True:
        return None

    missing = [f for f in REQUIRED_FIELDS if f not in post.metadata]
    if missing:
        raise BuildError(f"{path.name}: missing required front-matter field(s): {', '.join(missing)}")

    tags = post.metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        raise BuildError(f"{path.name}: 'tags' must be a list")

    return {
        "slug": slug_from_path(path),
        "title": str(post.metadata["title"]),
        "author": str(post.metadata["author"]),
        "date": coerce_date(post.metadata["date"], path),
        "category": str(post.metadata["category"]),
        "description": str(post.metadata["description"]),
        "tags": [str(t) for t in tags],
        "body_md": post.content,
        "source": path,
    }


def render_markdown(body: str) -> str:
    md = md_lib.Markdown(
        extensions=["fenced_code", "tables", "smarty", "sane_lists"],
        output_format="html5",
    )
    return md.convert(body)


def fmt_date_human(d: dt.date) -> str:
    return d.strftime("%B %-d, %Y") if sys.platform != "win32" else d.strftime("%B %#d, %Y")


def render_post_card(post: dict) -> str:
    return (
        '      <a class="blog-card" href="/blog/{slug}.html">\n'
        '        <div class="blog-card-meta">\n'
        '          <span class="kicker blog-card-cat">{category}</span>\n'
        '          <time class="blog-card-date" datetime="{date_iso}">{date_human}</time>\n'
        '        </div>\n'
        '        <h2 class="blog-card-title">{title}</h2>\n'
        '        <p class="blog-card-desc">{description}</p>\n'
        '        <p class="blog-card-author">{author}</p>\n'
        '      </a>'
    ).format(
        slug=html.escape(post["slug"], quote=True),
        category=html.escape(post["category"]),
        date_iso=post["date"].isoformat(),
        date_human=html.escape(fmt_date_human(post["date"])),
        title=html.escape(post["title"]),
        description=html.escape(post["description"]),
        author=html.escape(post["author"]),
    )


def render_tags_block(tags: list[str]) -> str:
    if not tags:
        return ""
    pills = "\n".join(
        f'        <span class="post-tag">{html.escape(t)}</span>' for t in tags
    )
    return f'      <div class="post-tags">\n{pills}\n      </div>'


def render_post_page(post: dict, template: string.Template, content_html: str) -> str:
    return template.substitute(
        title=html.escape(post["title"]),
        description=html.escape(post["description"]),
        canonical_url=f"{SITE_URL}/blog/{post['slug']}.html",
        slug=post["slug"],
        category=html.escape(post["category"]),
        author=html.escape(post["author"]),
        date_iso=post["date"].isoformat(),
        date_human=html.escape(fmt_date_human(post["date"])),
        content_html=content_html,
        tags_html=render_tags_block(post["tags"]),
    )


def render_index_page(template: string.Template, posts: list[dict]) -> str:
    if posts:
        cards = "\n".join(render_post_card(p) for p in posts)
    else:
        cards = '      <p class="blog-list-empty">No posts yet.</p>'
    return template.substitute(post_cards=cards)


def render_feed(posts: list[dict], rendered_html: dict[str, str]) -> str:
    items = []
    for p in posts:
        pub = dt.datetime.combine(p["date"], dt.time(12, 0), tzinfo=dt.timezone.utc)
        categories = "".join(
            f"      <category>{html.escape(c)}</category>\n"
            for c in [p["category"], *p["tags"]]
        )
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(p['title'])}</title>\n"
            f"      <link>{SITE_URL}/blog/{p['slug']}.html</link>\n"
            f"      <guid isPermaLink=\"true\">{SITE_URL}/blog/{p['slug']}.html</guid>\n"
            f"      <pubDate>{format_datetime(pub)}</pubDate>\n"
            f"      <author>contact@sigreturn.com ({html.escape(p['author'])})</author>\n"
            f"{categories}"
            f"      <description><![CDATA[{rendered_html[p['slug']]}]]></description>\n"
            "    </item>"
        )
    items_xml = "\n".join(items)
    last_build = ""
    if posts:
        latest = dt.datetime.combine(posts[0]["date"], dt.time(12, 0), tzinfo=dt.timezone.utc)
        last_build = f'    <lastBuildDate>{format_datetime(latest)}</lastBuildDate>\n'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        f'    <title>{SITE_TITLE}</title>\n'
        f'    <link>{SITE_URL}/blog/</link>\n'
        f'    <description>{html.escape(SITE_DESCRIPTION)}</description>\n'
        '    <language>en</language>\n'
        f'{last_build}'
        f'    <atom:link href="{SITE_URL}/blog/feed.xml" rel="self" type="application/rss+xml" />\n'
        f'{items_xml}\n'
        '  </channel>\n'
        '</rss>\n'
    )


def render_sitemap(posts: list[dict]) -> str:
    entries = []
    for page in STATIC_PAGES:
        entries.append(
            "  <url>\n"
            f"    <loc>{SITE_URL}{page['loc']}</loc>\n"
            f"    <changefreq>{page['changefreq']}</changefreq>\n"
            f"    <priority>{page['priority']}</priority>\n"
            "  </url>"
        )
    blog_lastmod = (
        f"    <lastmod>{posts[0]['date'].isoformat()}</lastmod>\n" if posts else ""
    )
    entries.append(
        "  <url>\n"
        f"    <loc>{SITE_URL}/blog/</loc>\n"
        f"{blog_lastmod}"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>0.7</priority>\n"
        "  </url>"
    )
    for p in posts:
        entries.append(
            "  <url>\n"
            f"    <loc>{SITE_URL}/blog/{p['slug']}.html</loc>\n"
            f"    <lastmod>{p['date'].isoformat()}</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.6</priority>\n"
            "  </url>"
        )
    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{body}\n'
        '</urlset>\n'
    )


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") or part.startswith("_") for part in rel.parts)


def sync_assets() -> tuple[list[Path], set[Path]]:
    """Mirror non-.md files from posts/ to blog/. Returns (written, all_relpaths)."""
    written: list[Path] = []
    all_assets: set[Path] = set()
    for src in POSTS_DIR.rglob("*"):
        if not src.is_file() or src.suffix == ".md":
            continue
        rel = src.relative_to(POSTS_DIR)
        if is_hidden(rel):
            continue
        all_assets.add(rel)
        dest = BLOG_DIR / rel
        if not dest.exists() or dest.read_bytes() != src.read_bytes():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            written.append(dest)
    return written, all_assets


def clean_stale(active_slugs: set[str], active_assets: set[Path]) -> list[Path]:
    """Remove anything in blog/ that is no longer produced by the build."""
    removed: list[Path] = []
    if not BLOG_DIR.exists():
        return removed
    for path in BLOG_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(BLOG_DIR)
        if len(rel.parts) == 1 and rel.name in ("index.html", "feed.xml"):
            continue
        if len(rel.parts) == 1 and path.suffix == ".html":
            if path.stem in active_slugs:
                continue
        elif rel in active_assets:
            continue
        path.unlink()
        removed.append(path)
    for d in sorted(
        (p for p in BLOG_DIR.rglob("*") if p.is_dir()),
        key=lambda p: -len(p.parts),
    ):
        try:
            d.rmdir()
        except OSError:
            pass
    return removed


def main() -> int:
    if not POSTS_DIR.exists():
        POSTS_DIR.mkdir(parents=True)
    BLOG_DIR.mkdir(parents=True, exist_ok=True)

    sources = sorted(p for p in POSTS_DIR.glob("*.md") if not is_hidden(p.relative_to(POSTS_DIR)))
    posts: list[dict] = []
    drafts = 0
    errors: list[str] = []

    for src in sources:
        try:
            parsed = parse_post(src)
        except BuildError as e:
            errors.append(str(e))
            continue
        if parsed is None:
            drafts += 1
        else:
            posts.append(parsed)

    if errors:
        print("Build failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)

    post_template = load_template("post.html")
    index_template = load_template("index.html")

    rendered_html: dict[str, str] = {}
    written: list[Path] = []

    for post in posts:
        content_html = render_markdown(post["body_md"])
        rendered_html[post["slug"]] = content_html
        page = render_post_page(post, post_template, content_html)
        out = BLOG_DIR / f"{post['slug']}.html"
        if write_if_changed(out, page):
            written.append(out)

    if write_if_changed(BLOG_DIR / "index.html", render_index_page(index_template, posts)):
        written.append(BLOG_DIR / "index.html")

    if write_if_changed(BLOG_DIR / "feed.xml", render_feed(posts, rendered_html)):
        written.append(BLOG_DIR / "feed.xml")

    if write_if_changed(SITEMAP_PATH, render_sitemap(posts)):
        written.append(SITEMAP_PATH)

    asset_writes, active_assets = sync_assets()
    written.extend(asset_writes)

    removed = clean_stale({p["slug"] for p in posts}, active_assets)

    summary = f"Built {len(posts)} post(s)"
    if drafts:
        summary += f", skipped {drafts} draft(s)"
    print(summary + ".")
    if written:
        print("Updated:")
        for f in written:
            print(f"  {f.relative_to(ROOT)}")
    else:
        print("No changes.")
    if removed:
        print("Removed stale:")
        for f in removed:
            print(f"  {f.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
