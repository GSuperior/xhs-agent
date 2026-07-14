"""网页抓取工具，带安全防护（Prompt Injection 防护 + SSRF 防护 + 来源快照）。

安全要点:
- URL 限制：只允许 http/https，阻止内网 IP（10.x / 172.16-31.x / 192.168.x / 127.x / localhost）。
- 网页内容视为不可信数据：只返回 BeautifulSoup 提取的纯文本与元数据，
  不返回原始 HTML 中的指令（防 Prompt Injection）。
- 来源快照：保存到 sources/{source_id}.txt，供 Evidence Reviewer 核对原文。
- content_hash：sha256(text)，用于后续完整性校验。
"""

import hashlib
import ipaddress
import re
import socket
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel


class FetchResult(BaseModel):
    """单次抓取结果。text 为不可信数据，仅含纯文本与元数据。"""

    source_id: str
    url: str
    text: str
    title: Optional[str] = None
    published_at: Optional[str] = None
    accessed_at: str
    snapshot_ref: str
    content_hash: str
    source_type: str = "media"


class FetchError(Exception):
    """抓取过程中的安全/网络错误。"""


# 内网/保留 IP 段判定由 ipaddress 模块完成（is_private / is_loopback /
# is_link_local / is_reserved / is_multicast），覆盖：
#   10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、127.0.0.0/8、169.254.0.0/16、
#   IPv6 的 ::1 / fc00::/7 / fe80::/10 等。
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def _is_blocked_ip(ip_str: str) -> bool:
    """判断 IP 是否属于内网/保留/环回等不可达地址。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无法解析为合法 IP，按阻断处理
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _check_url_safe(url: str) -> None:
    """校验 URL 协议与目标 IP，阻止 SSRF。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"不允许的协议: {parsed.scheme!r}（仅允许 http/https）")
    hostname = parsed.hostname
    if not hostname:
        raise FetchError(f"URL 缺少 hostname: {url!r}")
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise FetchError(f"被阻断的 hostname: {hostname!r}")

    # 如果 hostname 本身是 IP 字面量，直接校验
    try:
        ipaddress.ip_address(hostname)
        if _is_blocked_ip(hostname):
            raise FetchError(f"目标 IP 属于内网/保留段: {hostname}")
        return
    except ValueError:
        pass  # 不是 IP 字面量，走 DNS 解析

    # DNS 解析并逐一校验，任一解析结果落在内网即阻断
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise FetchError(f"DNS 解析失败: {hostname!r}: {e}")
    for info in infos:
        ip_str = info[4][0]
        # getaddrinfo 对 IPv6 可能返回带 scope 的形式，取 % 前
        ip_str = ip_str.split("%")[0]
        if _is_blocked_ip(ip_str):
            raise FetchError(
                f"hostname {hostname!r} 解析到内网/保留 IP: {ip_str}"
            )


def _extract_text(html: str) -> tuple[str, Optional[str], Optional[str]]:
    """从 HTML 提取 (纯文本, title, published_at)。

    只返回可见纯文本，丢弃 script/style/noscript/template 标签内容，
    避免把 HTML 中的指令泄漏给下游 LLM（Prompt Injection 防护）。
    """
    soup = BeautifulSoup(html, "lxml")

    # 移除所有非内容标签
    for tag in soup(
        ["script", "style", "noscript", "template", "svg", "iframe"]
    ):
        tag.decompose()

    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    # og:title 优先级更高
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    # 提取发布时间
    published_at = None
    for meta_name in (
        "article:published_time",
        "og:published_time",
        "datePublished",
        "publishdate",
        "publish_date",
        "date",
    ):
        meta = soup.find("meta", attrs={"property": meta_name}) or soup.find(
            "meta", attrs={"name": meta_name}
        )
        if meta and meta.get("content"):
            published_at = meta["content"].strip()
            break
    # <time datetime="..."> 兜底
    if not published_at:
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            published_at = time_tag["datetime"].strip()

    text = soup.get_text(separator="\n", strip=True)
    # 压缩连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, title, published_at


class Fetcher:
    """网页抓取器，集成 SSRF 防护与来源快照。"""

    def __init__(
        self,
        snapshot_dir: str = "./sources",
        timeout: float = 15.0,
        max_content_length: int = 2 * 1024 * 1024,
        user_agent: str = "xhs-agent-research/1.0",
    ):
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.user_agent = user_agent

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search_web(self, query: str, max_results: int = 8) -> List[dict]:
        """网页搜索。Phase 1A 用 DuckDuckGo HTML 搜索，失败时返回空列表。

        返回 [{"url", "title", "snippet"}]。
        """
        if not query or not query.strip():
            return []
        try:
            return self._ddg_html_search(query, max_results)
        except Exception:
            # Phase 1A：任何异常都不阻断流程，返回空列表由上游决定下一步
            return []

    def _ddg_html_search(self, query: str, max_results: int) -> List[dict]:
        """DuckDuckGo HTML 搜索（无官方 API 依赖）。"""
        url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": self.user_agent}
        params = {"q": query}
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.post(url, data=params, headers=headers)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: List[dict] = []
        for item in soup.select(".result"):
            a = item.select_one(".result__a")
            if not a:
                continue
            href = a.get("href", "")
            # DuckDuckGo 的跳转链接形如 //duckduckgo.com/l/?uddg=<encoded>
            uddg = re.search(r"uddg=([^&]+)", href)
            link = (
                _safe_unquote(uddg.group(1)) if uddg else href
            )
            snippet_tag = item.select_one(".result__snippet")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            results.append(
                {"url": link, "title": a.get_text(strip=True), "snippet": snippet}
            )
            if len(results) >= max_results:
                break
        return results

    # ------------------------------------------------------------------
    # 抓取
    # ------------------------------------------------------------------
    def fetch_url(self, url: str, source_type: str = "media") -> FetchResult:
        """抓取单个 URL，返回纯文本 + 元数据 + 来源快照引用。

        - source_type: 由调用方（Agent）根据 URL 性质指定，默认 media。
        """
        _check_url_safe(url)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, max_redirects=5
        ) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            if len(resp.content) > self.max_content_length:
                raise FetchError(
                    f"内容过大({len(resp.content)} bytes)，"
                    f"超过上限 {self.max_content_length}"
                )
            # 优先用响应声明的编码，兜底用 resp.encoding
            resp.encoding = resp.encoding or resp.charset_encoding or "utf-8"
            html = resp.text

        text, title, published_at = _extract_text(html)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source_id = "src_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        accessed_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        snapshot_path = self.snapshot_dir / f"{source_id}.txt"
        snapshot_path.write_text(
            f"URL: {url}\n"
            f"ACCESSED_AT: {accessed_at}\n"
            f"TITLE: {title or ''}\n"
            f"CONTENT_HASH: {content_hash}\n"
            f"---\n"
            f"{text}",
            encoding="utf-8",
        )

        return FetchResult(
            source_id=source_id,
            url=url,
            text=text,
            title=title,
            published_at=published_at,
            accessed_at=accessed_at,
            snapshot_ref=str(snapshot_path),
            content_hash=content_hash,
            source_type=source_type,
        )


def _safe_unquote(s: str) -> str:
    from urllib.parse import unquote

    try:
        return unquote(s)
    except Exception:
        return s
