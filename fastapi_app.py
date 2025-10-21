import os
import sys
import io
import tempfile
from typing import Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from PIL import Image
import requests

# Ensure project root is on path to import table_cropper
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from table_cropper import AdvancedTableCropper  # type: ignore


app = FastAPI(title="DKN Table Cropper API (FastAPI)", version="1.0.0")

# CORS for local dev and deployments (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "DKN Table Cropper API (FastAPI)", "version": "1.0.0"}


def _validate_image_content_type(upload: UploadFile) -> None:
    content_type = (upload.content_type or "").lower()
    if not any(content_type.endswith(ext) for ext in ["jpeg", "jpg", "png", "bmp", "tiff"]):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PNG/JPG/JPEG/BMP/TIFF.")


def _pil_to_png_bytes(pil_img: Image.Image) -> bytes:
    buf = io.BytesIO()
    save_img = pil_img
    if pil_img.mode not in ("RGB", "RGBA"):
        save_img = pil_img.convert("RGB")
    save_img.save(buf, format="PNG")
    return buf.getvalue()


async def _process_with_cropper(file_bytes: bytes) -> Tuple[dict, str]:
    # Save to a temporary path for AdvancedTableCropper

    original_name = getattr(_process_with_cropper, "_last_name", "uploaded.png")

    with tempfile.TemporaryDirectory() as work_dir:
        input_path = os.path.join(work_dir, original_name)
        with open(input_path, "wb") as f:
            f.write(file_bytes)

        cropper = AdvancedTableCropper()
        result = cropper.process_image(input_path, output_dir=None, return_images=True)

        base_name, _ = os.path.splitext(os.path.basename(original_name))
        return result, base_name


def upload_to_tmpfiles(image_bytes: bytes, filename: str) -> str:
    """Upload image to tmpfiles.org and return the public URL"""
    try:
        files = {"file": (filename, image_bytes, "image/png")}
        response = requests.post("https://tmpfiles.org/api/v1/upload", files=files)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                file_url = data.get("data", {}).get("url", "")
                if file_url:
                    if file_url.startswith("http://"):
                        file_url = file_url.replace("http://", "https://")
                    if "/dl/" not in file_url:
                        file_url = file_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    return file_url
        raise Exception(f"Upload failed: {response.text}")
    except Exception as e:
        raise Exception(f"Failed to upload to tmpfiles.org: {str(e)}")


@app.post("/api/crop-preview")
async def crop_and_perspective_correction(image: UploadFile = File(...)):
    """
    API 1: Accept an image, detect corners, apply perspective correction and cropping,
    and upload the corrected image to tmpfiles.org, returning a public URL as JSON.
    """
    try:
        _validate_image_content_type(image)
        # Store filename for naming consistency
        setattr(_process_with_cropper, "_last_name", image.filename or "uploaded.png")

        file_bytes = await image.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        result, base_name = await _process_with_cropper(file_bytes)

        # Prefer perspective-corrected; fallback to cropped_table
        out_img: Image.Image = result.get("perspective_corrected") or result.get("cropped_table") or result.get("original")
        if out_img is None:
            raise HTTPException(status_code=500, detail="Processing failed to produce an output image")

        # Additional crop: remove ~27% from left and ~12% from bottom
        width, height = out_img.size
        left_trim = int(0.27 * width)
        bottom_trim = int(0.12 * height)
        new_right = max(left_trim + 1, width)
        new_bottom = max(1, height - bottom_trim)
        out_img = out_img.crop((left_trim, 0, new_right, new_bottom))

        png_bytes = _pil_to_png_bytes(out_img)
        name_base = os.path.splitext(os.path.basename(image.filename or "uploaded"))[0]
        filename = f"{name_base}_preview.png"
        url = upload_to_tmpfiles(png_bytes, filename)
        return JSONResponse({"status": "success", "filename": filename, "url": url})

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(exc)}")


@app.post("/api/split-halves")
async def split_image_halves(
    image: UploadFile | None = File(None),
    image_url: str | None = Form(None),
):
    """
    API 2: Accept an image and split into two equal horizontal halves. Each half is uploaded
    to tmpfiles.org and their public URLs are returned as JSON.
    """
    try:
        file_bytes: bytes | None = None

        # Accept either an uploaded file or a URL to download
        if image is not None:
            _validate_image_content_type(image)
            file_bytes = await image.read()
            if not file_bytes:
                raise HTTPException(status_code=400, detail="Empty file uploaded")
            original_name = image.filename or "uploaded.png"
        elif image_url:
            try:
                # Ensure tmpfiles links are direct download
                url = image_url
                if url.startswith("http://"):
                    url = url.replace("http://", "https://")
                if "tmpfiles.org" in url and "/dl/" not in url:
                    url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Failed to download image: HTTP {resp.status_code}")
                file_bytes = resp.content
                # Derive a name from the URL
                original_name = os.path.basename(url.split("?")[0] or "downloaded.png")
                if not original_name:
                    original_name = "downloaded.png"
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Failed to download image from URL: {str(exc)}")
        else:
            raise HTTPException(status_code=400, detail="Provide either 'image' file or 'image_url' form field")

        pil_img = Image.open(io.BytesIO(file_bytes))
        pil_img = pil_img.convert("RGB")
        width, height = pil_img.size
        mid = height // 2

        top_half = pil_img.crop((0, 0, width, mid))
        bottom_half = pil_img.crop((0, mid, width, height))

        top_bytes = _pil_to_png_bytes(top_half)
        bottom_bytes = _pil_to_png_bytes(bottom_half)

        # File naming based on original name
        # original_name already set above depending on source
        name_base, _ = os.path.splitext(os.path.basename(original_name))
        top_name = f"{name_base}_top_half.png"
        bottom_name = f"{name_base}_bottom_half.png"

        top_url = upload_to_tmpfiles(top_bytes, top_name)
        bottom_url = upload_to_tmpfiles(bottom_bytes, bottom_name)

        return JSONResponse({
            "status": "success",
            "top_half": {"filename": top_name, "url": top_url},
            "bottom_half": {"filename": bottom_name, "url": bottom_url}
        })

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Split failed: {str(exc)}")


# For local running: `uvicorn fastapi_app:app --host 127.0.0.1 --port 8000 --reload`

