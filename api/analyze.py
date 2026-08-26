import json
from http.server import BaseHTTPRequestHandler

from api._media import (
    extract_media,
    friendly_error,
    human_size,
    number,
    platform_name,
    validate_url,
)


VIDEO_EXTENSIONS = {"mp4", "webm", "mkv", "mov"}
AUDIO_EXTENSIONS = {"m4a", "mp3", "ogg", "opus", "webm", "wav", "aac"}


def format_score(item):
    return (
        number(item.get("height")),
        number(item.get("fps")),
        number(item.get("tbr")),
        number(item.get("filesize")) or number(item.get("filesize_approx")),
    )


def audio_score(item):
    return (
        number(item.get("abr")),
        number(item.get("asr")),
        number(item.get("tbr")),
        number(item.get("filesize")) or number(item.get("filesize_approx")),
    )


def build_options(info):
    source_formats = [item for item in info.get("formats") or [] if item.get("format_id")]
    progressive = []
    video_only = []
    audio_only = []

    for item in source_formats:
        ext = str(item.get("ext") or "").lower()
        has_video = item.get("vcodec") not in {None, "none"}
        has_audio = item.get("acodec") not in {None, "none"}
        if has_video and has_audio and ext in VIDEO_EXTENSIONS:
            progressive.append(item)
        elif has_video and not has_audio and ext in VIDEO_EXTENSIONS:
            video_only.append(item)
        elif has_audio and not has_video and ext in AUDIO_EXTENSIONS:
            audio_only.append(item)

    best_audio_by_family = {}
    for item in audio_only:
        ext = str(item.get("ext") or "").lower()
        family = "mp4" if ext in {"m4a", "mp4", "aac"} else "webm"
        current = best_audio_by_family.get(family)
        if not current or audio_score(item) > audio_score(current):
            best_audio_by_family[family] = item

    video_choices = {}
    for item in progressive:
        ext = str(item.get("ext") or "mp4").lower()
        height = int(number(item.get("height")))
        key = (ext, height or -1)
        current = video_choices.get(key)
        if not current or format_score(item) > format_score(current["format"]):
            video_choices[key] = {"format": item, "selection": str(item["format_id"]), "merged": False}

    for item in video_only:
        ext = str(item.get("ext") or "mp4").lower()
        height = int(number(item.get("height")))
        family = "mp4" if ext in {"mp4", "mov"} else "webm"
        audio = best_audio_by_family.get(family) or max(audio_only, key=audio_score, default=None)
        if not audio:
            continue
        key = (ext, height or -1)
        current = video_choices.get(key)
        if not current or format_score(item) > format_score(current["format"]):
            video_choices[key] = {
                "format": item,
                "selection": f"{item['format_id']}+{audio['format_id']}",
                "merged": True,
            }

    options = []
    ordered_video = sorted(video_choices.values(), key=lambda choice: format_score(choice["format"]), reverse=True)
    for index, choice in enumerate(ordered_video[:24]):
        item = choice["format"]
        ext = str(item.get("ext") or "mp4").lower()
        height = int(number(item.get("height")))
        fps = int(number(item.get("fps")))
        size = item.get("filesize") or item.get("filesize_approx")
        quality = f"{height}p" if height else "original"
        details = [f"{fps} fps" if fps else "vídeo + áudio", human_size(size)]
        options.append(
            {
                "key": f"video-{index}",
                "label": f"{ext.upper()} · {quality}",
                "detail": " · ".join(details),
                "selection": choice["selection"],
                "mode": "source",
                "ext": "mp4" if choice["merged"] and ext in {"mp4", "mov"} else ext,
                "quality": "",
                "recommended": ext == "mp4" and (height == 1080 or (height <= 1080 and index == 0)),
            }
        )

    best_source_audio = {}
    for item in audio_only:
        ext = str(item.get("ext") or "").lower()
        current = best_source_audio.get(ext)
        if not current or audio_score(item) > audio_score(current):
            best_source_audio[ext] = item

    for ext, item in sorted(best_source_audio.items(), key=lambda pair: audio_score(pair[1]), reverse=True):
        bitrate = int(number(item.get("abr")) or number(item.get("tbr")))
        options.append(
            {
                "key": f"audio-source-{ext}",
                "label": f"{ext.upper()} · áudio",
                "detail": f"{bitrate} kbps" if bitrate else "qualidade original",
                "selection": str(item["format_id"]),
                "mode": "source",
                "ext": ext,
                "quality": "",
                "recommended": False,
            }
        )

    if audio_only or any(item.get("acodec") not in {None, "none"} for item in progressive):
        for ext, quality, detail in (
            ("mp3", "320", "320 kbps"),
            ("mp3", "192", "192 kbps"),
            ("mp3", "128", "128 kbps"),
            ("wav", "0", "sem compressão"),
        ):
            options.append(
                {
                    "key": f"audio-{ext}-{quality}",
                    "label": f"{ext.upper()} · áudio",
                    "detail": detail,
                    "selection": "bestaudio/best",
                    "mode": "convert",
                    "ext": ext,
                    "quality": quality,
                    "recommended": False,
                }
            )

    if not options and info.get("url"):
        ext = str(info.get("ext") or "mp4").lower()
        options.append(
            {
                "key": "direct-original",
                "label": f"{ext.upper()} · original",
                "detail": "melhor formato disponível",
                "selection": "best",
                "mode": "source",
                "ext": ext,
                "quality": "",
                "recommended": True,
            }
        )

    if options and not any(option["recommended"] for option in options):
        options[0]["recommended"] = True
    return options


class handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384:
                raise ValueError("Cole um link público válido.")
            payload = json.loads(self.rfile.read(length))
            url, host = validate_url(payload.get("url"))
            info = extract_media(url)
            options = build_options(info)
            if not options:
                raise ValueError("Nenhum formato compatível foi encontrado.")
            self.send_json(
                200,
                {
                    "platform": platform_name(host, info),
                    "title": info.get("title") or "Conteúdo identificado",
                    "duration": info.get("duration"),
                    "options": options,
                },
            )
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(422, {"error": friendly_error(error)})

