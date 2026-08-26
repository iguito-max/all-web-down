import mimetypes
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import imageio_ffmpeg
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from yt_dlp import YoutubeDL

from api._media import (
    MAX_DOWNLOAD_BYTES,
    downloaded_file,
    extract_media,
    friendly_error,
    platform_name,
    safe_filename,
    validate_url,
    ydl_options,
)
from api.analyze import build_options
from api.download import ALLOWED_OUTPUTS, progress_guard


SUPABASE_EDGE_URL = "https://nnfppxftbtvuvgphzfwj.supabase.co/functions/v1/all-web-down-storage"


app = FastAPI(
    title="All Web Down",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def api_error(status, message):
    return JSONResponse({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})


def storage_request(action, **payload):
    oidc_token = os.environ.get("VERCEL_OIDC_TOKEN", "")
    edge_secret = os.environ.get("AWD_EDGE_SECRET", "")
    if not oidc_token and not edge_secret:
        raise RuntimeError("A identidade segura do deployment não está disponível.")

    auth_headers = (
        {"Authorization": f"Bearer {oidc_token}"}
        if oidc_token
        else {"x-all-web-down-key": edge_secret}
    )

    response = requests.post(
        SUPABASE_EDGE_URL,
        headers={
            **auth_headers,
            "Content-Type": "application/json",
        },
        json={"action": action, **payload},
        timeout=25,
    )
    if not response.ok:
        raise RuntimeError("O armazenamento temporário não respondeu.")
    data = response.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "storage": bool(
            os.environ.get("VERCEL_OIDC_TOKEN") or os.environ.get("AWD_EDGE_SECRET")
        ),
        "maxBytes": MAX_DOWNLOAD_BYTES,
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/favicon.svg", status_code=307)


@app.post("/api/analyze")
async def analyze(request: Request):
    try:
        raw = await request.body()
        if len(raw) < 2 or len(raw) > 16384:
            raise ValueError("Cole um link público válido.")
        payload = await request.json()
        url, host = validate_url(payload.get("url"))
        info = extract_media(url)
        options = build_options(info)
        if not options:
            raise ValueError("Nenhum formato compatível de até 50 MB foi encontrado.")
        return JSONResponse(
            {
                "platform": platform_name(host, info),
                "title": info.get("title") or "Conteúdo identificado",
                "duration": info.get("duration"),
                "options": options,
            },
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as error:
        return api_error(400, str(error))
    except Exception as error:
        return api_error(422, friendly_error(error))


@app.post("/api/download")
async def download(request: Request):
    temp_dir = None
    try:
        raw = await request.body()
        if len(raw) < 2 or len(raw) > 32768:
            raise ValueError("Solicitação de download inválida.")
        fields = await request.json()

        url, _ = validate_url(fields.get("url"))
        selection = str(fields.get("selection") or "")
        mode = str(fields.get("mode") or "source")
        ext = str(fields.get("ext") or "").lower()
        quality = str(fields.get("quality") or "")

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
        if media_file.stat().st_size > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("O arquivo ultrapassa o limite de 50 MB deste serviço.")

        actual_ext = media_file.suffix.lstrip(".").lower() or ext
        title = safe_filename((result or {}).get("title") if isinstance(result, dict) else media_file.stem)
        filename = f"{title}.{actual_ext}"
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        object_path = f"temp/{uuid.uuid4().hex}.{actual_ext}"

        upload = storage_request(
            "upload",
            path=object_path,
            filename=filename,
            contentType=content_type,
        )
        with media_file.open("rb") as source:
            response = requests.put(
                upload["signedUrl"],
                data=source,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "max-age=600",
                    "x-upsert": "false",
                },
                timeout=180,
            )
        if not response.ok:
            raise RuntimeError("Não foi possível guardar o arquivo temporário.")

        signed = storage_request("download", path=object_path, filename=filename)
        return JSONResponse(
            {"downloadUrl": signed["signedUrl"], "filename": filename},
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as error:
        return api_error(400, str(error))
    except Exception as error:
        return api_error(422, friendly_error(error))
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
