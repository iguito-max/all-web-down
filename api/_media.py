import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL


ALLOWED_HOSTS = {
    "bsky.app",
    "dailymotion.com",
    "dai.ly",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "instagr.am",
    "kw.ai",
    "kwai.com",
    "kuaishou.com",
    "loom.com",
    "newgrounds.com",
    "ok.ru",
    "pinterest.com",
    "pin.it",
    "reddit.com",
    "redd.it",
    "rutube.ru",
    "snapchat.com",
    "soundcloud.com",
    "streamable.com",
    "tiktok.com",
    "tumblr.com",
    "twitch.tv",
    "twitter.com",
    "x.com",
    "vimeo.com",
    "vk.com",
    "youtube.com",
    "youtu.be",
}

PLATFORM_NAMES = {
    "bsky.app": "Bluesky",
    "dailymotion.com": "Dailymotion",
    "dai.ly": "Dailymotion",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "instagram.com": "Instagram",
    "instagr.am": "Instagram",
    "kw.ai": "Kwai",
    "kwai.com": "Kwai",
    "kuaishou.com": "Kwai",
    "pinterest.com": "Pinterest",
    "pin.it": "Pinterest",
    "reddit.com": "Reddit",
    "redd.it": "Reddit",
    "soundcloud.com": "SoundCloud",
    "tiktok.com": "TikTok",
    "twitter.com": "X / Twitter",
    "x.com": "X / Twitter",
    "vimeo.com": "Vimeo",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
}


def matching_host(hostname):
    hostname = (hostname or "").lower().rstrip(".")
    return next(
        (host for host in ALLOWED_HOSTS if hostname == host or hostname.endswith(f".{host}")),
        None,
    )


def validate_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Cole um link público válido.")

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Cole um link público válido.")

    host = matching_host(parsed.hostname)
    if not host:
        raise ValueError("Essa plataforma ainda não é compatível.")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Não foi possível localizar essa plataforma.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_reserved, ip.is_multicast)):
            raise ValueError("Esse endereço não é público.")

    return value.strip(), host


def ydl_options(extra=None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "cachedir": False,
        "socket_timeout": 22,
        "retries": 1,
        "fragment_retries": 1,
        "extract_flat": False,
        "http_headers": {
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        },
    }
    if extra:
        options.update(extra)
    return options


def primary_media(info):
    if not isinstance(info, dict):
        return {}
    if info.get("formats") or info.get("url"):
        return info
    for entry in info.get("entries") or []:
        media = primary_media(entry)
        if media:
            return media
    return info


def extract_media(url):
    with YoutubeDL(ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(primary_media(info))


def number(value):
    return value if isinstance(value, (int, float)) else 0


def human_size(value):
    size = number(value)
    if not size:
        return "tamanho variável"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit != "GB" else f"{size:.1f} {unit}"
        size /= 1024
    return "tamanho variável"


def safe_filename(value, fallback="all-web-down"):
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(value or "")).strip(" .-")
    return (cleaned[:120] or fallback).strip()


def downloaded_file(directory):
    files = [
        path
        for path in Path(directory).iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl", ".json"))
    ]
    return max(files, key=lambda path: path.stat().st_size) if files else None


def friendly_error(error):
    message = str(error).lower()
    if any(token in message for token in ("unsupported url", "no suitable extractor")):
        return "Esse tipo de link ainda não é compatível."
    if any(token in message for token in ("private", "login required", "sign in", "cookies")):
        return "Esse conteúdo não está público ou exige login."
    if any(token in message for token in ("drm", "protected")):
        return "Conteúdo protegido por DRM não pode ser baixado."
    if any(token in message for token in ("geo", "country", "region")):
        return "Esse conteúdo não está disponível nesta região."
    if any(token in message for token in ("429", "too many requests", "rate limit")):
        return "A plataforma limitou as tentativas. Aguarde um pouco e tente novamente."
    if any(token in message for token in ("timed out", "timeout")):
        return "A plataforma demorou demais para responder. Tente novamente."
    return "Não foi possível processar esse link público agora."


def platform_name(host, info=None):
    if host in PLATFORM_NAMES:
        return PLATFORM_NAMES[host]
    extractor = str((info or {}).get("extractor_key") or (info or {}).get("extractor") or "Mídia")
    return extractor.replace("IE", "").replace("_", " ").strip().title()

