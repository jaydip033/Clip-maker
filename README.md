# ClipForge AI — Auto Clip Maker

A runnable starter project for turning long videos into vertical short clips with word-timed animated captions.

## Features
- Browser UI for uploading MP4/MOV/WebM files
- FastAPI backend with background processing and job status
- Audio transcription with Faster-Whisper (word timestamps)
- Heuristic highlight ranking from transcript segments (a practical baseline, not a trained viral-moment model)
- Vertical 9:16 MP4 output using FFmpeg
- Animated karaoke-style captions with active-word highlighting (ASS subtitles)
- Download links for generated clips

## Requirements
- Python 3.10+
- FFmpeg and FFprobe installed and available on PATH
- For GPU acceleration, install a compatible CTranslate2/CUDA setup; CPU works but is slower.
- Internet may be needed the first time Faster-Whisper downloads its model.

## Run locally
```bash
# Install FFmpeg first:
# macOS: brew install ffmpeg
# Ubuntu/Debian: sudo apt update && sudo apt install ffmpeg
# Windows: install FFmpeg and add its bin folder to PATH

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000

The first transcription may take a while because the Whisper model is downloaded. Use `WHISPER_MODEL= tiny` for a quick test or `base` for a better baseline. Environment variable should be `WHISPER_MODEL=tiny` (no space).

## Docker
```bash
docker compose up --build
```
Then open http://localhost:8000. The model cache is stored in a Docker volume.

## Important notes
- This is a working starter, not a production SaaS deployment. Files are stored on the server and there is no login, payment system, or multi-tenant isolation yet.
- Highlight detection is transcript-based heuristic ranking. It favors punchy phrases and emphasis words; it cannot guarantee viral clips. Replace `rank_segments()` with an LLM/classifier or learned highlight detector for production.
- Do not upload copyrighted or private videos unless you have the rights and permission to process them.
- Set upload limits and add authentication, rate limits, cleanup jobs, and cloud storage before public deployment.
