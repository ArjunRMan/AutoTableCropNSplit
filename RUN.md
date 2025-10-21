## Run the FastAPI app locally

1) Activate the virtual environment and run (recommended):
```bash
cd "/Users/arjun/Desktop/final table cropper tool"
source .venv/bin/activate
python -m uvicorn fastapi_app:app --host 127.0.0.1 --port 8000 --reload
```

2) Or run without activating the venv (direct binary):
```bash
cd "/Users/arjun/Desktop/final table cropper tool"
./.venv/bin/uvicorn fastapi_app:app --host 127.0.0.1 --port 8000 --reload
```

3) Stop the server:
```bash
pkill -f "uvicorn fastapi_app:app"
```

## Test with curl (macOS Terminal)

Health check:
```bash
curl -s http://127.0.0.1:8000/api/health | jq .
```

Crop & perspective correction preview (returns JSON with tmpfiles URL):
```bash
curl -s -X POST \
  -F "image=@/path/to/your/image.jpg" \
  http://127.0.0.1:8000/api/crop-preview | jq .
# {
#   "status": "success",
#   "filename": "image_preview.png",
#   "url": "https://tmpfiles.org/dl/..."
# }
```

Example with a path containing spaces and a colon (works on macOS):
```bash
curl -sS -X POST \
  -F "image=@/Users/arjun/Downloads/dkn images Y:N/3.jpeg" \
  http://127.0.0.1:8000/api/crop-preview | jq .
```

Split image into two halves (returns JSON with tmpfiles URLs):
```bash
curl -s -X POST \
  -F "image=@/path/to/your/image.jpg" \
  http://127.0.0.1:8000/api/split-halves | jq .
# {
#   "status": "success",
#   "top_half": {"filename": "example_top_half.png", "url": "https://tmpfiles.org/dl/..."},
#   "bottom_half": {"filename": "example_bottom_half.png", "url": "https://tmpfiles.org/dl/..."}
# }
```

Example with a path containing spaces and a colon:
```bash
curl -sS -X POST \
  -F "image=@/Users/arjun/Downloads/dkn images Y:N/3.jpeg" \
  http://127.0.0.1:8000/api/split-halves | jq .
```

Notes:
- Replace `/path/to/your/image.jpg` with your local image path.
- If you deploy behind a different host/port, update the URL accordingly.

