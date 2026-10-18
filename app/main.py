import os, uuid, json, shutil, subprocess, threading, time
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
UPLOADS = DATA_DIR / "uploads"
JOBS = DATA_DIR / "jobs"
OUTPUTS = DATA_DIR / "outputs"
for p in (UPLOADS, JOBS, OUTPUTS):
    p.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1500"))
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
app = FastAPI(title="ClipForge AI", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()

def run_cmd(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-3000:] or "Command failed")
    return result.stdout.strip()

def probe_duration(path: Path) -> float:
    out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return max(0.1, float(out))

def transcribe(path: Path):
    from faster_whisper import WhisperModel
    model_name = os.getenv("WHISPER_MODEL", "base")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute = os.getenv("WHISPER_COMPUTE_TYPE", "int8" if device == "cpu" else "float16")
    model = WhisperModel(model_name, device=device, compute_type=compute,
                         download_root=str(DATA_DIR / "models"))
    segments, info = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    result = []
    for seg in segments:
        words = []
        for w in (seg.words or []):
            words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})
        result.append({"start": float(seg.start), "end": float(seg.end),
                       "text": seg.text.strip(), "words": words})
    return result, getattr(info, "language", "unknown")

def rank_segments(segments, duration, clip_seconds=35):
    """Transcript-only baseline: score windows for emphasis and concise, self-contained speech."""
    all_words = []
    for s in segments:
        all_words.extend(s["text"].lower().split())
    emphasis = {"secret","mistake","never","always","best","worst","why","how","truth",
                "actually","important","shocking","remember","learned","problem","solution",
                "amazing","incredible","because","first","finally","imagine","tip","trick"}
    candidates = []
    step = max(8, clip_seconds * 0.45)
    start = 0.0
    while start < duration:
        end = min(duration, start + clip_seconds)
        if end - start >= 8:
            selected = [s for s in segments if s["end"] > start and s["start"] < end]
            text = " ".join(s["text"] for s in selected).strip()
            words = text.lower().split()
            if len(words) >= 12:
                punch = sum(1 for w in words if w.strip(".,!?;:'\"()[]") in emphasis)
                sentence_end = sum(1 for s in selected if s["text"].rstrip().endswith((".", "?", "!")))
                density = min(len(words) / 65, 1.5)
                duration_factor = 1.0 if end - start >= 18 else 0.65
                score = (punch * 1.6 + sentence_end * 0.7 + density * 2.0) * duration_factor
                candidates.append({"start": start, "end": end, "text": text, "score": score})
        start += step
    candidates.sort(key=lambda x: x["score"], reverse=True)
    chosen = []
    for c in candidates:
        if all(abs(c["start"] - x["start"]) > clip_seconds * 0.65 for x in chosen):
            chosen.append(c)
        if len(chosen) >= 5:
            break
    if not chosen:
        chosen = [{"start": 0.0, "end": min(duration, clip_seconds), "text": "", "score": 0.0}]
    return sorted(chosen, key=lambda x: x["start"])

def ass_time(seconds):
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"

def ass_escape(text):
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", " ")

def make_ass(segments, clip_start, clip_end, path):
    # ASS colors are &HAABBGGRR. White base, yellow active word, dark outline.
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,64,&H00FFFFFF,&H0000D7FF,&H00101010,&H90000000,-1,0,1,5,2,2,80,80,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            if w["end"] >= clip_start and w["start"] <= clip_end:
                words.append(w)
    # Show small groups of up to 5 words; each word gets a karaoke timing tag.
    for i in range(0, len(words), 5):
        group = words[i:i+5]
        if not group: continue
        start = max(clip_start, group[0]["start"])
        end = min(clip_end, group[-1]["end"] + 0.18)
        if end <= start: continue
        text = " ".join(r"{\k" + str(max(1, int((w["end"]-w["start"])*100))) + "}" + ass_escape(w["word"].strip()) for w in group)
        lines.append(f"Dialogue: 0,{ass_time(start-clip_start)},{ass_time(end-clip_start)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines), encoding="utf-8")

def make_clip(source: Path, out: Path, segments, start, end):
    ass = out.with_suffix(".ass")
    make_ass(segments, start, end, ass)
    # Fill a vertical frame with a blurred background and overlay a centered, aspect-fit foreground.
    ass_filter = str(ass).replace("\\", "/").replace(":", r"\:")
    vf = ("split=2[bg][fg];"
          "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=24:8,eq=brightness=-0.22[blur];"
          "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
          "[blur][front]overlay=(W-w)/2:(H-h)/2,"
          f"subtitles='{ass_filter}':fontsdir=/usr/share/fonts/truetype/dejavu")
    run_cmd(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{end-start:.3f}",
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
    try: ass.unlink()
    except OSError: pass

def update_job(job_id, **kwargs):
    with _lock:
        _jobs[job_id].update(kwargs)
        (JOBS / f"{job_id}.json").write_text(json.dumps(_jobs[job_id], indent=2))

def process_job(job_id, source: Path):
    try:
        update_job(job_id, status="transcribing", progress=10, message="Transcribing speech with Whisper…")
        duration = probe_duration(source)
        segments, language = transcribe(source)
        update_job(job_id, status="selecting", progress=38, message="Finding promising moments…", language=language)
        clips = rank_segments(segments, duration)
        results = []
        for idx, clip in enumerate(clips, start=1):
            update_job(job_id, status="rendering", progress=40 + int(55*(idx-1)/len(clips)),
                       message=f"Rendering clip {idx} of {len(clips)}…")
            name = f"{job_id}_clip_{idx}.mp4"
            out = OUTPUTS / name
            make_clip(source, out, segments, clip["start"], clip["end"])
            results.append({"id": name, "filename": name, "start": round(clip["start"], 2),
                            "end": round(clip["end"], 2), "duration": round(clip["end"]-clip["start"], 2),
                            "text": clip["text"][:500], "download_url": f"/api/clips/{name}"})
            update_job(job_id, clips=results)
        update_job(job_id, status="completed", progress=100, message="Your clips are ready.", clips=results)
    except Exception as e:
        update_job(job_id, status="failed", progress=0, message="Processing failed.", error=str(e))
    finally:
        # Keep source files for reprocessing/debugging; production deployments should clean up.
        pass

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"status": "ok", "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, "Unsupported file type. Upload MP4, MOV, MKV, WebM, or M4V.")
    job_id = uuid.uuid4().hex[:12]
    source = UPLOADS / f"{job_id}{suffix}"
    size = 0
    try:
        with source.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk: break
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    f.close()
                    source.unlink(missing_ok=True)
                    raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")
                f.write(chunk)
    finally:
        await file.close()
    record = {"id": job_id, "status": "queued", "progress": 2, "message": "Upload complete. Starting AI processing…",
              "filename": file.filename, "clips": [], "created_at": time.time()}
    with _lock:
        _jobs[job_id] = record
        (JOBS / f"{job_id}.json").write_text(json.dumps(record, indent=2))
    threading.Thread(target=process_job, args=(job_id, source), daemon=True).start()
    return record

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        path = JOBS / f"{job_id}.json"
        if path.exists(): _jobs[job_id] = json.loads(path.read_text())
        else: raise HTTPException(404, "Job not found.")
    return _jobs[job_id]

@app.get("/api/clips/{filename}")
def download_clip(filename: str):
    if Path(filename).name != filename or not filename.endswith(".mp4"):
        raise HTTPException(400, "Invalid filename.")
    path = OUTPUTS / filename
    if not path.exists(): raise HTTPException(404, "Clip not found.")
    return FileResponse(path, media_type="video/mp4", filename=filename)
