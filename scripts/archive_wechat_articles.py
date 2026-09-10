#!/usr/bin/env python3
"""Archive WeChat articles as text, Markdown, HTML, and original images."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote_to_bytes, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ArticleSpec:
    slug: str
    expected_title: str
    url: str


ARTICLES = (
    ArticleSpec(
        "01-review-and-outlook",
        "回到半个月前，复盘与展望",
        "https://mp.weixin.qq.com/s/yBNfRQVc6xHbrrNMJuoHtA",
    ),
    ArticleSpec(
        "02-bulls-vs-bears",
        "多空对决正在上演",
        "https://mp.weixin.qq.com/s/0N_9uxAais27qohI_rt2fg",
    ),
    ArticleSpec(
        "03-three-opportunities",
        "三次绝佳的机会",
        "https://mp.weixin.qq.com/s/QiGgllAmNAa8ORXUSv-rkw",
    ),
    ArticleSpec(
        "04-important-turning-point",
        "一个非常重要的转折点",
        "https://mp.weixin.qq.com/s/Mp_vHatQnWT1Vi_9i56qUA",
    ),
    ArticleSpec(
        "05-ten-trillion",
        "十万亿不是梦？",
        "https://mp.weixin.qq.com/s/o4UlHPBFUFh_gaPatoAmKA",
    ),
)

IMAGE_ATTRS = ("data-src", "data-original", "data-backsrc", "src")
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clean_managed_images(images_dir: Path) -> None:
    managed_name = re.compile(
        r"\d{3}\.(?:avif|bin|bmp|gif|jpe?g|png|svg|webp)", re.IGNORECASE
    )
    for path in images_dir.iterdir():
        if path.is_file() and managed_name.fullmatch(path.name):
            path.unlink()


def clean_url(url: str) -> str:
    parts = urlsplit(html.unescape(url.strip()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def fetch_html(session: requests.Session, url: str) -> tuple[bytes, str]:
    last_error = ""
    for attempt in range(3):
        response = session.get(
            url,
            headers={"Cache-Control": "no-cache"} if attempt else None,
            timeout=45,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        has_article = re.search(
            rb"id\s*=\s*(['\"])js_content\1", response.content, flags=re.IGNORECASE
        )
        if has_article:
            return response.content, response.url
        last_error = f"content-type={content_type}, bytes={len(response.content)}"
        if attempt < 2:
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Missing #js_content after 3 attempts ({last_error})")


def first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            if element.name == "meta":
                value = element.get("content", "")
            else:
                value = element.get_text(" ", strip=True)
            if value:
                return re.sub(r"\s+", " ", value).strip()
    return ""


def script_value(source: str, names: Iterable[str]) -> str:
    for name in names:
        match = re.search(
            rf"(?:var\s+)?{re.escape(name)}\s*=\s*(['\"])(.*?)\1\s*;",
            source,
            flags=re.DOTALL,
        )
        if match:
            value = match.group(2)
            try:
                return bytes(value, "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                return value
    return ""


def extract_metadata(
    soup: BeautifulSoup, source: str, canonical_url: str, expected_title: str
) -> dict[str, str]:
    title = first_text(
        soup,
        ("#activity-name", "meta[property='og:title']", "meta[name='twitter:title']"),
    )
    author = first_text(
        soup,
        ("#js_name", "meta[name='author']", "meta[property='og:article:author']"),
    )
    published_at = first_text(
        soup,
        (
            "#publish_time",
            "meta[property='article:published_time']",
            "meta[name='publication_date']",
        ),
    )
    if not published_at:
        published_at = script_value(source, ("publish_time", "ct"))
        if published_at.isdigit():
            published_at = time.strftime(
                "%Y-%m-%d %H:%M:%S %z", time.localtime(int(published_at))
            )
    description = first_text(
        soup,
        ("meta[name='description']", "meta[property='og:description']"),
    )
    if expected_title and title != expected_title:
        raise RuntimeError(
            f"Title mismatch: expected {expected_title!r}, received {title!r}"
        )
    return {
        "title": title,
        "author": author,
        "published_at": published_at,
        "description": description,
        "source_url": canonical_url,
    }


def choose_image_source(image: Tag) -> str:
    for attribute in IMAGE_ATTRS:
        value = image.get(attribute)
        if isinstance(value, str) and value.strip():
            if value.startswith("data:image/svg+xml") and attribute == "src":
                continue
            return clean_url(value)
    return ""


def image_extension(content: bytes, content_type: str, source_url: str) -> str:
    lowered_type = content_type.split(";", 1)[0].strip().lower()
    type_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "image/avif": ".avif",
    }
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if b"<svg" in content[:512].lower():
        return ".svg"
    if lowered_type in type_map:
        return type_map[lowered_type]
    suffix = Path(urlsplit(source_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(lowered_type)
    return guessed or ".bin"


def decode_data_image(source_url: str) -> tuple[bytes, str]:
    header, encoded = source_url.split(",", 1)
    media_type = header[5:].split(";", 1)[0] or "application/octet-stream"
    if ";base64" in header:
        content = base64.b64decode(encoded)
    else:
        content = unquote_to_bytes(encoded)
    return content, media_type


def download_image(
    session: requests.Session, source_url: str, referer: str
) -> tuple[bytes, str]:
    if source_url.startswith("data:image/"):
        return decode_data_image(source_url)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(
                source_url,
                headers={"Referer": referer},
                timeout=45,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not response.content:
                raise RuntimeError("empty response")
            if "text/html" in content_type.lower():
                raise RuntimeError(f"received HTML instead of an image ({content_type})")
            return response.content, content_type
        except (requests.RequestException, RuntimeError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def normalize_text(raw_text: str) -> str:
    raw_text = html.unescape(raw_text)
    raw_text = raw_text.replace("\xa0", " ").replace("\u200b", "")
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    previous_blank = True
    for raw_line in raw_text.split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if line:
            lines.append(line)
            previous_blank = False
        elif not previous_blank:
            lines.append("")
            previous_blank = True
    return "\n".join(lines).strip() + "\n"


def body_to_text(body: Tag, image_markers: dict[int, str] | None = None) -> str:
    clone = BeautifulSoup(str(body), "html.parser")
    root = clone.select_one("#js_content") or clone
    for unwanted in root.select("script, style, noscript, template"):
        unwanted.decompose()
    for break_element in root.find_all("br"):
        break_element.replace_with(NavigableString("\n"))
    for index, image in enumerate(root.find_all("img"), start=1):
        marker = image_markers.get(index, "") if image_markers else ""
        image.replace_with(NavigableString(f"\n{marker}\n" if marker else "\n"))
    for element in list(root.find_all(BLOCK_TAGS)):
        element.insert_after(NavigableString("\n"))
    return normalize_text(root.get_text("", strip=False))


def article_markdown(metadata: dict[str, str], body_text: str) -> str:
    frontmatter = {
        "title": metadata["title"],
        "author": metadata["author"],
        "published_at": metadata["published_at"],
        "source_url": metadata["source_url"],
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(("---", "", f"# {metadata['title']}", "", body_text.rstrip(), ""))
    return "\n".join(lines)


def local_html(metadata: dict[str, str], body: Tag) -> str:
    title = html.escape(metadata["title"])
    author = html.escape(metadata["author"])
    published = html.escape(metadata["published_at"])
    source = html.escape(metadata["source_url"], quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ color: #222; font-family: sans-serif; line-height: 1.75; margin: 0 auto; max-width: 760px; padding: 32px 20px 80px; }}
    img {{ display: block; height: auto; margin: 20px auto; max-width: 100%; }}
    .archive-meta {{ color: #666; margin-bottom: 32px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="archive-meta">{author} · {published} · <a href="{source}">原文</a></p>
  {str(body)}
</body>
</html>
"""


def archive_article(
    session: requests.Session, spec: ArticleSpec, output_root: Path
) -> dict[str, object]:
    print(f"[fetch] {spec.expected_title}")
    raw_html, canonical_url = fetch_html(session, spec.url)
    source = raw_html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(source, "html.parser")
    body = soup.select_one("#js_content")
    if body is None:
        raise RuntimeError("Missing #js_content; WeChat may have returned a verification page")
    metadata = extract_metadata(soup, source, canonical_url, spec.expected_title)

    article_dir = output_root / spec.slug
    images_dir = article_dir / "images"
    article_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    clean_managed_images(images_dir)
    atomic_write_bytes(article_dir / "source.html", raw_html)

    image_manifest: list[dict[str, object]] = []
    markers: dict[int, str] = {}
    for index, image in enumerate(body.find_all("img"), start=1):
        source_url = choose_image_source(image)
        entry: dict[str, object] = {
            "index": index,
            "source_url": source_url,
            "alt": image.get("alt", ""),
            "width": image.get("data-w") or image.get("width") or "",
            "status": "missing_source",
        }
        if source_url:
            try:
                content, content_type = download_image(session, source_url, canonical_url)
                extension = image_extension(content, content_type, source_url)
                filename = f"{index:03d}{extension}"
                relative_path = f"images/{filename}"
                atomic_write_bytes(images_dir / filename, content)
                entry.update(
                    {
                        "status": "downloaded",
                        "local_path": relative_path,
                        "content_type": content_type.split(";", 1)[0],
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                image["src"] = relative_path
                for attribute in ("data-src", "data-original", "data-backsrc"):
                    image.attrs.pop(attribute, None)
                markers[index] = f"![图 {index:03d}]({relative_path})"
                print(f"  [image {index:03d}] {len(content):>9,} bytes")
            except Exception as error:  # Keep the archive usable even if one asset fails.
                entry.update({"status": "failed", "error": str(error)})
                markers[index] = f"[图 {index:03d} 下载失败：{source_url}]"
                print(f"  [image {index:03d}] FAILED: {error}", file=sys.stderr)
        image_manifest.append(entry)

    body_text = body_to_text(body, markers)
    plain_text = (
        f"{metadata['title']}\n"
        f"作者：{metadata['author']}\n"
        f"发布时间：{metadata['published_at']}\n"
        f"原文：{metadata['source_url']}\n\n"
        f"{body_to_text(body)}"
    )
    metadata.update(
        {
            "slug": spec.slug,
            "source_html_bytes": len(raw_html),
            "text_characters": len(plain_text),
            "image_elements": len(image_manifest),
            "images_downloaded": sum(
                item["status"] == "downloaded" for item in image_manifest
            ),
            "images_failed": sum(item["status"] == "failed" for item in image_manifest),
        }
    )
    atomic_write_text(article_dir / "article.txt", plain_text)
    atomic_write_text(article_dir / "article.md", article_markdown(metadata, body_text))
    atomic_write_text(article_dir / "article.html", local_html(metadata, body))
    atomic_write_json(article_dir / "metadata.json", metadata)
    atomic_write_json(article_dir / "images.json", image_manifest)
    print(
        f"[done] {metadata['title']}: {metadata['text_characters']:,} chars, "
        f"{metadata['images_downloaded']}/{metadata['image_elements']} images"
    )
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "research" / "source-articles",
        help="Archive output directory",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SLUG",
        help="Archive only the selected built-in slug; may be repeated",
    )
    return parser.parse_args()


def archived_metadata(output_root: Path) -> dict[str, dict[str, object]]:
    archived: dict[str, dict[str, object]] = {}
    for spec in ARTICLES:
        metadata_path = output_root / spec.slug / "metadata.json"
        if not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("slug") == spec.slug:
            archived[spec.slug] = metadata
    return archived


def main() -> int:
    args = parse_args()
    selected = [item for item in ARTICLES if not args.only or item.slug in args.only]
    unknown = sorted(set(args.only) - {item.slug for item in ARTICLES})
    if unknown:
        print(f"Unknown slug(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    completed: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for spec in selected:
        try:
            completed.append(archive_article(session, spec, args.output))
        except Exception as error:
            failures.append({"slug": spec.slug, "url": spec.url, "error": str(error)})
            print(f"[failed] {spec.expected_title}: {error}", file=sys.stderr)
    catalog = archived_metadata(args.output) if args.only else {}
    catalog.update({str(article["slug"]): article for article in completed})
    catalog_entries = [catalog[spec.slug] for spec in ARTICLES if spec.slug in catalog]
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_scope": "partial" if args.only else "full",
        "articles_requested": len(ARTICLES),
        "articles_attempted": len(selected),
        "articles_archived": len(catalog_entries),
        "articles_failed": len(failures),
        "articles": catalog_entries,
        "failures": failures,
    }
    atomic_write_json(args.output / "manifest.json", manifest)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())