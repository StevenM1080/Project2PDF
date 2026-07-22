from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .models import ProjectRecord, ProvenanceCandidate
from .util import clean_text, site_for_url, unique_strings


@dataclass(slots=True)
class PageMetadata:
    url: str = ""
    site: str = ""
    title: str = ""
    creator: str = ""
    creator_url: str = ""
    description: str = ""
    print_instructions: str = ""
    license_name: str = ""
    license_url: str = ""
    published: str = ""
    updated: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    model_files: list[str] = field(default_factory=list)


class CachedWebClient:
    def __init__(self, cache_dir: Path | None = None, timeout: float = 20.0) -> None:
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36 Project2PDF/0.1"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def close(self) -> None:
        self.client.close()

    def get_text(self, url: str, max_age: int = 86400) -> tuple[str, str]:
        cache_file = self._cache_file(url, ".html")
        if cache_file and cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age:
            return cache_file.read_text(encoding="utf-8", errors="replace"), url
        headers = None
        if site_for_url(url) == "Cults3D":
            # Cults serves public listing metadata through its crawler view while
            # rejecting ordinary non-interactive HTTP clients with a 403.
            headers = {"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}
        response = self.client.get(url, headers=headers)
        response.raise_for_status()
        text = response.text
        if cache_file:
            cache_file.write_text(text, encoding="utf-8")
        return text, str(response.url)

    def get_bytes(self, url: str, max_age: int = 604800) -> bytes:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".img"
        cache_file = self._cache_file(url, suffix)
        if cache_file and cache_file.exists() and time.time() - cache_file.stat().st_mtime < max_age:
            return cache_file.read_bytes()
        response = self.client.get(url)
        response.raise_for_status()
        data = response.content
        if cache_file:
            cache_file.write_bytes(data)
        return data

    def _cache_file(self, url: str, suffix: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}{suffix}"


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if isinstance(tag, Tag) and tag.get("content"):
            return clean_text(str(tag["content"]))
    return ""


def _json_ld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            items.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue
    return items


def _as_name_and_url(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        return clean_text(value), ""
    if isinstance(value, dict):
        return clean_text(str(value.get("name") or "")), str(value.get("url") or "")
    if isinstance(value, list) and value:
        return _as_name_and_url(value[0])
    return "", ""


def parse_page_metadata(html_text: str, final_url: str) -> PageMetadata:
    soup = BeautifulSoup(html_text, "html.parser")
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical = ""
    if isinstance(canonical_tag, Tag) and canonical_tag.get("href"):
        canonical = urljoin(final_url, str(canonical_tag["href"]))
    data = PageMetadata(url=canonical or final_url, site=site_for_url(canonical or final_url))
    data.title = _meta_content(soup, "og:title", "twitter:title")
    data.description = _meta_content(soup, "og:description", "twitter:description", "description")
    data.creator = _meta_content(soup, "author", "article:author")
    data.published = _meta_content(soup, "article:published_time", "datePublished")
    data.updated = _meta_content(soup, "article:modified_time", "dateModified")
    data.category = _meta_content(soup, "article:section")
    data.images = unique_strings(
        [
            urljoin(final_url, value)
            for value in (
                _meta_content(soup, "og:image", "twitter:image", "twitter:image:src"),
                *[
                    urljoin(final_url, str(tag.get("content")))
                    for tag in soup.find_all("meta", attrs={"property": "og:image"})
                    if tag.get("content")
                ],
            )
            if value
        ]
    )
    keywords = _meta_content(soup, "keywords", "article:tag")
    if keywords:
        data.tags = unique_strings(re.split(r"\s*,\s*", keywords))

    for item in _json_ld_items(soup):
        item_type = item.get("@type")
        types = set(item_type if isinstance(item_type, list) else [item_type])
        if not types.intersection({"Product", "CreativeWork", "Thing", "Article", "SoftwareApplication"}):
            continue
        data.title = data.title or clean_text(str(item.get("name") or item.get("headline") or ""))
        data.description = data.description or clean_text(str(item.get("description") or ""))
        creator, creator_url = _as_name_and_url(item.get("author") or item.get("creator"))
        data.creator = data.creator or creator
        data.creator_url = data.creator_url or (urljoin(final_url, creator_url) if creator_url else "")
        data.published = data.published or str(item.get("datePublished") or "")
        data.updated = data.updated or str(item.get("dateModified") or "")
        image = item.get("image")
        if isinstance(image, str):
            data.images.append(urljoin(final_url, image))
        elif isinstance(image, list):
            data.images.extend(urljoin(final_url, str(value)) for value in image if isinstance(value, str))
        elif isinstance(image, dict) and image.get("url"):
            data.images.append(urljoin(final_url, str(image["url"])))
        license_value = item.get("license")
        if isinstance(license_value, str):
            if license_value.startswith("http"):
                data.license_url = license_value
            else:
                data.license_name = clean_text(license_value)

    if not data.title and soup.title:
        data.title = clean_text(soup.title.get_text())

    license_anchor = soup.find("a", href=re.compile(r"creativecommons\.org/licenses", re.I))
    if isinstance(license_anchor, Tag):
        data.license_url = urljoin(final_url, str(license_anchor.get("href") or ""))
        data.license_name = clean_text(license_anchor.get_text(" ")) or data.license_name

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = clean_text(heading.get_text(" ")).lower()
        if not any(token in heading_text for token in ("print settings", "printing settings", "print instructions")):
            continue
        sections: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and re.match(r"^h[1-6]$", sibling.name or ""):
                break
            if isinstance(sibling, Tag):
                value = clean_text(sibling.get_text("\n"))
                if value:
                    sections.append(value)
        data.print_instructions = "\n\n".join(sections[:8])
        break

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        text = clean_text(anchor.get_text(" "))
        if re.search(r"\.(stl|3mf|obj|step|stp)(?:\?|$)", href, re.I):
            data.model_files.append(Path(urlparse(href).path).name or text)
        if not data.creator_url and data.creator and data.creator.casefold() in text.casefold():
            data.creator_url = urljoin(final_url, href)

    data.images = unique_strings(data.images)
    data.model_files = unique_strings(data.model_files)
    data.tags = unique_strings(data.tags)
    data.title = _clean_site_title(data.title, data.site)
    if data.site == "Printables":
        _enhance_printables(data, soup, html_text, final_url)
    elif data.site == "Cults3D":
        _enhance_cults(data, soup, final_url)
    return data


def _clean_site_title(title: str, site: str) -> str:
    suffixes = {
        "Printables": [" | Printables.com", " - Printables"],
        "MakerWorld": [" - MakerWorld", " | MakerWorld"],
        "Thingiverse": [" by Thingiverse", " - Thingiverse"],
        "Thangs": [" - Thangs", " | Thangs"],
        "Creality Cloud": [" - Creality Cloud", " | Creality Cloud"],
    }
    for suffix in suffixes.get(site, []):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title.strip()


def _enhance_printables(
    data: PageMetadata,
    soup: BeautifulSoup,
    html_text: str,
    final_url: str,
) -> None:
    product = next(
        (
            item
            for item in _json_ld_items(soup)
            if item.get("@type") == "Product" and item.get("name")
        ),
        None,
    )
    if product:
        data.title = clean_text(str(product.get("name") or data.title))
        data.description = clean_text(str(product.get("description") or data.description))

    user_card = soup.select_one('a[data-testid="user-card"]')
    if isinstance(user_card, Tag):
        name = user_card.select_one(".name")
        if isinstance(name, Tag):
            data.creator = clean_text(name.get_text(" "))
        data.creator_url = urljoin(final_url, str(user_card.get("href") or ""))

    rich_bodies = [
        body
        for body in soup.find_all("body")
        if len(body.find_all("p", recursive=False)) >= 2 and not body.find("div", recursive=False)
    ]
    if rich_bodies:
        body = max(rich_bodies, key=lambda item: len(item.get_text("\n")))
        chunks = [
            clean_text(child.get_text("\n"))
            for child in body.children
            if isinstance(child, Tag) and child.name in {"p", "ul", "ol", "h1", "h2", "h3", "h4"}
        ]
        chunks = [chunk for chunk in chunks if chunk]
        split_at = next(
            (
                index
                for index, chunk in enumerate(chunks)
                if re.search(r"\b(print settings|printing settings|print instructions|print with)\b", chunk, re.I)
            ),
            -1,
        )
        if split_at > 0:
            data.description = "\n\n".join(chunks[:split_at])
            data.print_instructions = "\n\n".join(chunks[split_at:])
        else:
            data.description = "\n\n".join(chunks) or data.description

    published = re.search(r'\\?"datePublished\\?":\\?"([^"\\]+)', html_text)
    modified = re.search(r'\\?"modified\\?":\\?"([^"\\]+)', html_text)
    if published:
        data.published = published.group(1)
    if modified:
        data.updated = modified.group(1)

    license_match = re.search(
        r"https?://creativecommons\.org/licenses/([a-z-]+)/([0-9.]+)/?", html_text, re.I
    )
    if license_match:
        data.license_url = license_match.group(0).replace("\\/", "/")
        data.license_name = f"CC {license_match.group(1).upper()} {license_match.group(2)}"
    elif embedded_license := re.search(r'license\\?"\s*:\s*\{\\?"id\\?"\s*:\s*\\?"(\d+)', html_text):
        known_printables_licenses = {
            "3": ("CC BY-NC 4.0", "https://creativecommons.org/licenses/by-nc/4.0/"),
            "4": ("CC BY-NC-SA 4.0", "https://creativecommons.org/licenses/by-nc-sa/4.0/"),
        }
        license_info = known_printables_licenses.get(embedded_license.group(1))
        if license_info:
            data.license_name, data.license_url = license_info

    media_images: list[str] = []
    for image in soup.find_all("img", src=True):
        src = urljoin(final_url, str(image["src"]))
        lowered = src.lower()
        if "media.printables.com/media/prints/" in lowered and not any(
            token in lowered for token in ("avatar", "icon", "badge")
        ):
            media_images.append(src)
    data.images = unique_strings(data.images + media_images)[:12]


def _enhance_cults(data: PageMetadata, soup: BeautifulSoup, final_url: str) -> None:
    table_values: dict[str, Tag] = {}
    for row in soup.find_all("tr"):
        heading = row.find("th")
        value = row.find("td")
        if isinstance(heading, Tag) and isinstance(value, Tag):
            table_values[clean_text(heading.get_text(" ")).casefold()] = value

    author_cell = table_values.get("design author")
    if author_cell:
        data.creator = clean_text(author_cell.get_text(" ")) or data.creator
    if data.creator:
        creator_anchor = soup.find("a", href=re.compile(rf"/users/{re.escape(data.creator)}(?:/|$)", re.I))
        if isinstance(creator_anchor, Tag):
            data.creator_url = urljoin(final_url, str(creator_anchor.get("href") or ""))

    for key, attribute in (("publication date", "published"), ("last update", "updated")):
        cell = table_values.get(key)
        time_tag = cell.find("time") if cell else None
        if isinstance(time_tag, Tag):
            setattr(data, attribute, str(time_tag.get("datetime") or clean_text(time_tag.get_text(" "))))

    license_cell = table_values.get("license")
    if license_cell:
        license_anchor = license_cell.find("a", href=True)
        if isinstance(license_anchor, Tag):
            license_label = license_anchor.select_one(".link--strong")
            data.license_name = clean_text(
                (license_label or license_anchor).get_text(" ")
            )
            data.license_url = urljoin(final_url, str(license_anchor.get("href") or ""))

    format_cell = table_values.get("3d design format")
    if format_cell:
        data.model_files = unique_strings(
            re.findall(r"[^\n<>]+?\.(?:stl|3mf|obj|step|stp|zip)\b", format_cell.get_text("\n"), re.I)
        )

    for section in soup.select(".creation-page__tab-section"):
        heading = section.find(re.compile(r"^h[1-6]$"))
        if not isinstance(heading, Tag):
            continue
        label = clean_text(heading.get_text(" ")).casefold()
        body = clean_text("\n".join(value for value in section.stripped_strings if value))
        body = re.sub(rf"^{re.escape(clean_text(heading.get_text(' ')))}\s*", "", body, flags=re.I)
        if label == "3d model description" and body:
            data.description = body
        elif "printing settings" in label and body:
            data.print_instructions = body
        elif label == "categories" and body:
            data.category = body.replace("›", "/")
        elif label == "tags":
            data.tags = unique_strings(clean_text(anchor.get_text(" ")) for anchor in section.find_all("a"))

    gallery_images: list[str] = []
    for image in soup.find_all("img", src=True):
        src = urljoin(final_url, str(image.get("src") or ""))
        lowered = src.lower()
        if "cults3d.com" in lowered and ("illustration-file" in lowered or "/illustrations/" in lowered):
            gallery_images.append(src)
    data.images = unique_strings(data.images + gallery_images)[:12]


def _extract_result_urls(html_text: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    urls: list[str] = []
    for selector in ("li.b_algo h2 a", "a.result__a", "a[href]"):
        for anchor in soup.select(selector):
            href = str(anchor.get("href") or "")
            if not href:
                continue
            href = urljoin(base_url, href)
            parsed = urlparse(href)
            if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
                continue
            if "duckduckgo.com" in parsed.netloc:
                target = parse_qs(parsed.query).get("uddg", [""])[0]
                href = unquote(target) or href
            if site_for_url(href) in {"Printables", "MakerWorld", "Thingiverse", "Thangs", "Creality Cloud", "Cults3D"}:
                urls.append(href)
        if urls:
            break
    return unique_strings(urls)


def parse_makerworld_api(data: dict[str, Any], source_url: str) -> PageMetadata:
    model_id = str(data.get("id") or "")
    slug = str(data.get("slug") or "")
    canonical = f"https://makerworld.com/en/models/{model_id}"
    if slug:
        canonical += f"-{slug}"
    page = PageMetadata(
        url=canonical if model_id else source_url,
        site="MakerWorld",
        title=clean_text(str(data.get("title") or "")),
        description=clean_text(str(data.get("summary") or "")),
        license_name=clean_text(str(data.get("license") or "")),
        published=str(data.get("createTime") or ""),
        updated=str(data.get("updateTime") or ""),
        tags=[clean_text(str(value)) for value in data.get("tags") or []],
    )
    creator = data.get("designCreator") or {}
    if isinstance(creator, dict):
        page.creator = clean_text(str(creator.get("name") or creator.get("handle") or ""))
        handle = str(creator.get("handle") or "")
        if handle:
            page.creator_url = f"https://makerworld.com/en/@{quote_plus(handle)}"
    categories = data.get("categories") or []
    if categories and isinstance(categories[0], dict):
        page.category = clean_text(str(categories[0].get("name") or ""))
    images = [str(data.get("coverUrl") or "")]
    summary_soup = BeautifulSoup(str(data.get("summary") or ""), "html.parser")
    images.extend(str(image.get("src") or "") for image in summary_soup.find_all("img", src=True))
    for instance in data.get("instances") or []:
        if not isinstance(instance, dict):
            continue
        images.append(str(instance.get("cover") or ""))
        images.extend(
            str(picture.get("url") or "")
            for picture in instance.get("pictures") or []
            if isinstance(picture, dict)
        )
    page.images = unique_strings([image for image in images if image])
    instruction_match = re.search(
        r"(?:🧰\s*)?(?:Print(?:ing)? (?:settings|instructions)|Consigli per l[’']assemblaggio)\b",
        page.description,
        re.I,
    )
    if instruction_match:
        page.print_instructions = page.description[instruction_match.start() :].strip()
        page.description = page.description[: instruction_match.start()].strip()
    return page


class SourceService:
    def __init__(self, web: CachedWebClient) -> None:
        self.web = web

    def enrich(self, record: ProjectRecord, allow_search: bool = True) -> ProjectRecord:
        if record.site in {"Yeggi", "3Drop"} and record.source_url:
            resolved = self.resolve_aggregator(record.source_url)
            if resolved:
                record.discovery_url = record.source_url
                record.source_url = resolved
                record.site = site_for_url(resolved)
                record.evidence.append(f"Resolved {site_for_url(record.discovery_url)} to original listing")
                record.confidence = max(record.confidence, 0.96)

        if (not record.source_url or not _looks_like_model_page(record.source_url)) and allow_search:
            match = self.search_for_record(record)
            if match:
                record.candidates.insert(0, match)
                record.select_candidate(match)

        if record.source_url:
            record.warnings = [
                warning
                for warning in record.warnings
                if "No embedded source URL" not in warning
                and "filename search is needed" not in warning
            ]

        if record.source_url and record.site == "MakerWorld":
            model_match = re.search(r"makerworld\.com/(?:[a-z]{2}/)?models/(\d+)", record.source_url, re.I)
            if model_match:
                api_url = f"https://makerworld.com/api/v1/design-service/design/{model_match.group(1)}"
                try:
                    api_text, _ = self.web.get_text(api_url)
                    page = parse_makerworld_api(json.loads(api_text), record.source_url)
                    self.apply_page(record, page)
                    return record
                except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
                    record.warnings.append(f"Could not read MakerWorld metadata API: {exc}")

        if record.source_url:
            try:
                html_text, final_url = self.web.get_text(record.source_url)
                page = parse_page_metadata(html_text, final_url)
                self.apply_page(record, page)
            except (httpx.HTTPError, OSError, ValueError) as exc:
                detail = str(exc)
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = f"HTTP {exc.response.status_code} {exc.response.reason_phrase}"
                record.warnings.append(f"Could not read {record.site or 'source'} page: {detail}")
        record.warnings = unique_strings(record.warnings)
        return record

    def resolve_aggregator(self, url: str) -> str:
        parsed = urlparse(url)
        if "three-drop.com" in parsed.netloc:
            match = re.search(r"/model/(printables|makerworld|thingiverse|crealitycloud|thangs)/(\d+)", parsed.path, re.I)
            if match:
                site, model_id = match.groups()
                patterns = {
                    "printables": f"https://www.printables.com/model/{model_id}",
                    "makerworld": f"https://makerworld.com/en/models/{model_id}",
                    "thingiverse": f"https://www.thingiverse.com/thing:{model_id}",
                    "crealitycloud": f"https://www.crealitycloud.com/model-detail/{model_id}",
                }
                if site.lower() in patterns:
                    return patterns[site.lower()]
        try:
            html_text, final_url = self.web.get_text(url)
        except httpx.HTTPError:
            return ""
        soup = BeautifulSoup(html_text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = urljoin(final_url, str(anchor["href"]))
            if site_for_url(href) not in {"Yeggi", "3Drop", "Website"} and _looks_like_model_page(href):
                return href
        return ""

    def search_for_record(self, record: ProjectRecord) -> ProvenanceCandidate | None:
        query_options = [record.title, *record.model_files]
        query_source = max(query_options, key=lambda value: len(re.findall(r"[a-z0-9]", value.lower())), default=record.title)
        query_source = Path(query_source).stem
        query_source = re.sub(r"[+_-]+", " ", query_source)
        query_source = re.sub(r"\b(stl|3mf|obj|step|download|files?)\b", " ", query_source, flags=re.I)
        query_source = re.sub(r"\s+", " ", query_source).strip()
        site_hint = record.site if record.site not in {"", "Website"} else ""
        domains = {
            "Printables": "printables.com/model",
            "MakerWorld": "makerworld.com/en/models",
            "Thingiverse": "thingiverse.com/thing",
            "Thangs": "thangs.com",
            "Creality Cloud": "crealitycloud.com/model-detail",
        }
        if site_hint == "Printables":
            printables_match = self._search_printables(query_source)
            if printables_match:
                return printables_match

        query = query_source
        if site_hint in domains:
            query = f"site:{domains[site_hint]} {query}"
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            html_text, final_url = self.web.get_text(search_url, max_age=3600)
        except httpx.HTTPError:
            search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
            try:
                html_text, final_url = self.web.get_text(search_url, max_age=3600)
            except httpx.HTTPError:
                return None
        candidates = _extract_result_urls(html_text, final_url)
        if not candidates:
            return None
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", query_source.lower())
            if len(token) > 2 or token.isdigit()
        }
        scored: list[tuple[float, str]] = []
        for url in candidates:
            url_tokens = set(re.findall(r"[a-z0-9]+", unquote(url).lower()))
            overlap = len(tokens & url_tokens) / max(1, len(tokens))
            site_bonus = 0.1 if not site_hint or site_for_url(url) == site_hint else -0.15
            scored.append((min(0.9, 0.62 + overlap * 0.25 + site_bonus), url))
        confidence, best_url = max(scored)
        return ProvenanceCandidate(
            url=best_url,
            site=site_for_url(best_url),
            confidence=confidence,
            evidence=[f"Exact filename/title web search: {query_source}"],
        )

    def _search_printables(self, query_source: str) -> ProvenanceCandidate | None:
        url = f"https://www.printables.com/search/models?q={quote_plus(query_source)}"
        try:
            html_text, final_url = self.web.get_text(url, max_age=3600)
        except httpx.HTTPError:
            return None
        soup = BeautifulSoup(html_text, "html.parser")
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", query_source.lower())
            if len(token) > 2 or token.isdigit()
        }
        scored: list[tuple[float, str, str]] = []
        for anchor in soup.find_all("a", href=re.compile(r"^/model/\d+")):
            href = urljoin(final_url, str(anchor.get("href") or ""))
            text = clean_text(anchor.get_text(" "))
            haystack = f"{href} {text}".lower()
            matched = sum(1 for token in tokens if token in haystack)
            overlap = matched / max(1, len(tokens))
            scored.append((overlap, href, text))
        if not scored:
            return None
        overlap, href, text = max(scored, key=lambda item: item[0])
        if overlap < 0.45:
            return None
        return ProvenanceCandidate(
            url=href,
            site="Printables",
            confidence=min(0.98, 0.72 + overlap * 0.26),
            evidence=[f"Printables filename/title search: {query_source}"],
            title=text,
        )

    @staticmethod
    def apply_page(record: ProjectRecord, page: PageMetadata) -> None:
        record.source_url = page.url or record.source_url
        record.site = page.site or record.site
        record.title = page.title or record.title
        record.creator = page.creator or record.creator
        record.creator_url = page.creator_url or record.creator_url
        record.description = page.description or record.description
        record.print_instructions = page.print_instructions or record.print_instructions
        record.license_name = page.license_name or record.license_name
        record.license_url = page.license_url or record.license_url
        record.published = page.published or record.published
        record.updated = page.updated or record.updated
        record.category = page.category or record.category
        record.tags = unique_strings(record.tags + page.tags)
        record.images = unique_strings(record.images + page.images)
        record.model_files = unique_strings(record.model_files + page.model_files)


def _looks_like_model_page(url: str) -> bool:
    lowered = url.lower()
    host = (urlparse(url).hostname or "").lower()
    if host.startswith(("files.", "media.")) or host.endswith("bblmw.com"):
        return False
    if Path(urlparse(url).path).suffix.lower() in {".stl", ".3mf", ".obj", ".step", ".stp", ".png", ".jpg", ".jpeg", ".webp"}:
        return False
    return any(
        token in lowered
        for token in ("/model/", "/models/", "/thing:", "/3d-model/", "/model-detail/")
    )


def enrich_records(
    records: Iterable[ProjectRecord],
    cache_dir: Path | None = None,
    allow_search: bool = True,
) -> list[ProjectRecord]:
    web = CachedWebClient(cache_dir=cache_dir)
    service = SourceService(web)
    try:
        return [service.enrich(record, allow_search=allow_search) for record in records]
    finally:
        web.close()
