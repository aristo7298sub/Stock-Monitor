#!/usr/bin/env python3
"""Verify the integrity and offline completeness of archived WeChat articles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REQUIRED_FILES = (
    "article.txt",
    "article.md",
    "article.html",
    "metadata.json",
    "images.json",
    "source.html",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_valid_signature(path: Path) -> bool:
    content = path.read_bytes()
    suffix = path.suffix.lower()
    checks = {
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".gif": content.startswith((b"GIF87a", b"GIF89a")),
        ".webp": content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        ".bmp": content.startswith(b"BM"),
        ".svg": b"<svg" in content[:1024].lower(),
        ".avif": content[4:12] in (b"ftypavif", b"ftypavis"),
    }
    return bool(checks.get(suffix, False))


def local_reference(article_dir: Path, reference: str) -> bool:
    reference = reference.split("#", 1)[0].split("?", 1)[0]
    if not reference or reference.startswith(("http://", "https://", "//", "data:")):
        return False
    target = (article_dir / reference).resolve()
    try:
        target.relative_to(article_dir.resolve())
    except ValueError:
        return False
    return target.is_file()


def verify_article(article_dir: Path, manifest_entry: dict[str, object]) -> list[str]:
    issues: list[str] = []
    for filename in REQUIRED_FILES:
        path = article_dir / filename
        if not path.is_file():
            issues.append(f"missing {filename}")
        elif path.stat().st_size == 0:
            issues.append(f"empty {filename}")
    if issues:
        return issues

    metadata = json.loads((article_dir / "metadata.json").read_text(encoding="utf-8"))
    images = json.loads((article_dir / "images.json").read_text(encoding="utf-8"))
    if metadata.get("title") != manifest_entry.get("title"):
        issues.append("title differs between metadata.json and manifest.json")
    if metadata.get("image_elements") != len(images):
        issues.append("image_elements does not match images.json")
    downloaded = [image for image in images if image.get("status") == "downloaded"]
    if metadata.get("images_downloaded") != len(downloaded):
        issues.append("images_downloaded does not match images.json")
    if metadata.get("images_failed") != len(images) - len(downloaded):
        issues.append("images_failed does not match images.json")

    actual_images = {path.resolve() for path in (article_dir / "images").glob("*") if path.is_file()}
    expected_images: set[Path] = set()
    for image in downloaded:
        relative_path = str(image.get("local_path", ""))
        image_path = (article_dir / relative_path).resolve()
        expected_images.add(image_path)
        if not image_path.is_file():
            issues.append(f"missing image {relative_path}")
            continue
        if image_path.stat().st_size != image.get("bytes"):
            issues.append(f"byte count mismatch for {relative_path}")
        if sha256(image_path) != image.get("sha256"):
            issues.append(f"SHA-256 mismatch for {relative_path}")
        if not has_valid_signature(image_path):
            issues.append(f"invalid image signature for {relative_path}")
        prefix = image_path.read_bytes()[:1024].lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            issues.append(f"HTML payload stored as image {relative_path}")
    for extra_path in sorted(actual_images - expected_images):
        issues.append(f"unlisted image {extra_path.relative_to(article_dir)}")

    local_html = (article_dir / "article.html").read_text(encoding="utf-8")
    if re.search(r"\bdata-src\s*=", local_html, flags=re.IGNORECASE):
        issues.append("article.html still contains data-src")
    if "mmbiz.qpic.cn" in local_html:
        issues.append("article.html still contains a WeChat image URL")
    html_images = re.findall(
        r"<img\b[^>]*?\bsrc\s*=\s*(['\"])(.*?)\1",
        local_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    markdown = (article_dir / "article.md").read_text(encoding="utf-8")
    markdown_images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    for _, reference in html_images:
        if not local_reference(article_dir, reference):
            issues.append(f"invalid HTML image reference {reference}")
    for reference in markdown_images:
        if not local_reference(article_dir, reference):
            issues.append(f"invalid Markdown image reference {reference}")
    if len(html_images) != len(downloaded):
        issues.append("article.html image count does not match images.json")
    if len(markdown_images) != len(downloaded):
        issues.append("article.md image count does not match images.json")
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "research" / "source-articles",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.archive / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_issues: list[str] = []
    total_images = 0
    total_bytes = 0
    for entry in manifest.get("articles", []):
        article_dir = args.archive / str(entry["slug"])
        issues = verify_article(article_dir, entry)
        total_images += int(entry.get("images_downloaded", 0))
        total_bytes += sum(
            int(image.get("bytes", 0))
            for image in json.loads((article_dir / "images.json").read_text(encoding="utf-8"))
            if image.get("status") == "downloaded"
        )
        ending = [
            line.strip()
            for line in (article_dir / "article.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ][-2:]
        status = "PASS" if not issues else "FAIL"
        print(
            f"[{status}] {entry['title']}: {entry['text_characters']} chars, "
            f"{entry['images_downloaded']} images"
        )
        print(f"  ending: {' | '.join(ending)}")
        all_issues.extend(f"{entry['slug']}: {issue}" for issue in issues)
    if all_issues:
        print("\nDiscrepancies:")
        for issue in all_issues:
            print(f"- {issue}")
    print(
        f"\nArticles: {len(manifest.get('articles', []))}; "
        f"images: {total_images}; bytes: {total_bytes}; issues: {len(all_issues)}"
    )
    return 1 if all_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())