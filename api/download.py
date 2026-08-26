import html
import json
import mimetypes
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote

import imageio_ffmpeg
from yt_dlp import YoutubeDL

from api._media import MAX_DOWNLOAD_BYTES, downloaded_file, friendly_error, safe_filename, validate_url, ydl_options


ALLOWED_OUTPUTS = {"aac", "m4a", "mkv", "mov", "mp3", "mp4", "ogg", "opus", "wav", "webm"}
def progress_guard(data):
    downloaded = data.get("downloaded_bytes") or 0
    total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
    if max(downloaded, total) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError("O arquivo ultrapassa o limite de 50 MB deste serviço.")


class handler(BaseHTTPRequestHandler):
    def send_error_frame(self, status, message):
        safe_message = json.dumps(message, ensure_ascii=False).replace("</", "<\\/")
        page = (
            "<!doctype html><meta charset='utf-8'><title>Download</title>"
            f"<p>{html.escape(message)}</p>"
            f"<script>parent.postMessage({{type:'download-error',message:{safe_message}}},location.origin)</script>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        temp_dir = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 32768:
                raise ValueError("Solicitação de download inválida.")
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            url, _ = validate_url(fields.get("url", [""])[0])
            selection = fields.get("selection", [""])[0]
            mode = fields.get("mode", ["source"])[0]
            ext = fields.get("ext", [""])[0].lower()
            quality = fields.get("quality", [""])[0]

            if mode not in {"source", "convert"} or ext not in ALLOWED_OUTPUTS:
                raise ValueError("Formato de download inválido.")
            if not selection or len(selection) > 160:
                raise ValueError("Formato de download inválido.")
            if mode == "convert" and (ext not in {"mp3", "wav"} or quality not in {"0", "128", "192", "320"}):
                raise ValueError("Conversão de áudio inválida.")

            temp_dir = tempfile.mkdtemp(prefix="all-web-down-")
            output_template = str(Path(temp_dir) / "%(title).120s [%(id)s].%(ext)s")
            options = {
                "format": selection,
                "outtmpl": output_template,
                "overwrites": True,
                "progress_hooks": [progress_guard],
                "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
            }

            if mode == "convert":
                options["format"] = "bestaudio/best"
                options["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": ext,
                        "preferredquality": quality if quality != "0" else None,
                    }
                ]
            elif "+" in selection:
                options["merge_output_format"] = "mp4" if ext in {"mp4", "mov"} else ext

            with YoutubeDL(ydl_options(options)) as ydl:
                result = ydl.extract_info(url, download=True)

            media_file = downloaded_file(temp_dir)
            if not media_file or media_file.stat().st_size == 0:
                raise RuntimeError("O arquivo retornado pela plataforma está vazio.")

            actual_ext = media_file.suffix.lstrip(".").lower() or ext
            title = safe_filename((result or {}).get("title") if isinstance(result, dict) else media_file.stem)
            filename = f"{title}.{actual_ext}"
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            size = media_file.stat().st_size

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            with media_file.open("rb") as source:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as error:
            self.send_error_frame(400, str(error))
        except Exception as error:
            self.send_error_frame(422, friendly_error(error))
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
