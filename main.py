import os
import json
import time
import shutil
import asyncio
from typing import List
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

# Import our generator engine
import generator

load_dotenv()

app = FastAPI(title="ImagineIf Factory")

# Ensure required directories exist
os.makedirs("outputs", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("static/music", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount outputs for static file serving
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

class ScriptRequest(BaseModel):
    thought: str
    duration: int = 60
    visual_style: str = "Cinematic Photo"

class Segment(BaseModel):
    text_to_speak: str
    visual_prompt: str
    audio_path: str = ""
    image_path: str = ""

class AssetRequest(BaseModel):
    projectId: str
    segments: List[Segment]
    aspectRatio: str = "16:9"
    imageModel: str = "schnell"

class RenderRequest(BaseModel):
    projectId: str
    segments: List[Segment]
    aspectRatio: str = "16:9"
    musicTrack: str = ""
    fontName: str = "Arial Bold"
    highlightColor: str = "Yellow"
    captionPosition: str = "Bottom"
    addWatermark: bool = False
    captionPreset: str = "default"

class RegenerateSegmentRequest(BaseModel):
    projectId: str
    segmentIndex: int
    textToSpeak: str
    visualPrompt: str
    aspectRatio: str = "16:9"
    regenerateAudio: bool = True
    regenerateImage: bool = True
    imageModel: str = "schnell"

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.get("/api/list-music")
async def api_list_music():
    """
    List available background music files in static/music/
    """
    music_dir = "static/music"
    files = [f for f in os.listdir(music_dir) if f.lower().endswith(('.mp3', '.wav', '.m4a'))]
    return files

@app.get("/api/list-projects")
async def api_list_projects():
    """
    List all generated projects by reading metadata.json from outputs/ subdirectories.
    """
    projects = []
    outputs_dir = "outputs"
    if not os.path.exists(outputs_dir):
        return []
        
    for item in os.listdir(outputs_dir):
        item_path = os.path.join(outputs_dir, item)
        if os.path.isdir(item_path):
            meta_path = os.path.join(item_path, "metadata.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    projects.append(meta)
                except Exception as e:
                    print(f"Error reading metadata for {item}: {e}")
                    
    projects.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return projects

@app.get("/api/daily-topic")
async def api_daily_topic():
    """
    Scans content_calendar_365.md and pulls a random speculative topic not marked as Done.
    """
    calendar_path = "content_calendar_365.md"
    if not os.path.exists(calendar_path):
        return {"topic": "Imagine if human cities were built inside giant trees."}
        
    try:
        import re
        import random
        unused_topics = []
        with open(calendar_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Matches Day headings: **Day X:** Imagine if...
                match = re.search(r"\*\*Day \d+:\*\*\s*(.*)", line)
                if match:
                    topic_text = match.group(1).strip()
                    if not topic_text.endswith("-Done"):
                        unused_topics.append(topic_text)
                        
        if unused_topics:
            selected = random.choice(unused_topics)
            return {"topic": selected}
        else:
            return {"topic": "Imagine if gravity on Earth randomly turned off for five seconds every day."}
    except Exception as e:
        print(f"Error parsing calendar: {e}")
        return {"topic": "Imagine if space travel was as cheap as buying a bus ticket."}

@app.delete("/api/delete-project/{projectId}")
async def api_delete_project(projectId: str):
    """
    Delete a project folder and all its assets from outputs/
    """
    project_dir = f"outputs/{projectId}"
    if not os.path.exists(project_dir):
        raise HTTPException(status_code=404, detail="Project not found")
        
    try:
        shutil.rmtree(project_dir)
        return {"status": "success", "message": f"Project {projectId} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")

@app.post("/api/generate-script")
async def api_generate_script(req: ScriptRequest):
    """
    Step 1: Generate JSON script and SEO metadata from a thought.
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY is not configured in .env")
    try:
        data = await generator.generate_script(req.thought, req.duration, req.visual_style)
        project_id = f"project_{int(time.time())}"
        # Ensure project output directory exists
        os.makedirs(f"outputs/{project_id}", exist_ok=True)
        
        # Save project metadata
        metadata = {
            "projectId": project_id,
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "tags": data.get("tags", ""),
            "timestamp": int(time.time()),
            "status": "script_generated",
            "aspectRatio": "",
            "videoUrl": "",
            "thought": req.thought,
            "duration": req.duration,
            "visualStyle": req.visual_style
        }
        with open(f"outputs/{project_id}/metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        return {
            "projectId": project_id,
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "tags": data.get("tags", ""),
            "segments": data.get("segments", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-assets")
async def api_generate_assets(req: AssetRequest):
    """
    Step 2: Generate all audio (edge-tts) and images (Replicate/Flux) concurrently.
    """
    project_id = req.projectId
    project_dir = f"outputs/{project_id}"
    os.makedirs(project_dir, exist_ok=True)
    
    # Update project metadata
    meta_path = f"{project_dir}/metadata.json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["aspectRatio"] = req.aspectRatio
            meta["status"] = "assets_generated"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            print(f"Error updating metadata during assets gen: {e}")
            
    # Use a Semaphore of 1 to ensure images are generated sequentially
    image_semaphore = asyncio.Semaphore(1)
    
    async def process_segment(index: int, seg: Segment):
        audio_filename = f"audio_{index}.mp3"
        audio_path = f"{project_dir}/{audio_filename}"
        
        image_filename = f"image_{index}" # extension added later
        image_path_raw = f"{project_dir}/{image_filename}.webp"
        
        # 1. Generate Voiceover (async, completely parallel)
        voiceover_task = generator.generate_voiceover(seg.text_to_speak, audio_path)
        
        # 2. Generate Visual Asset (queued sequentially using Semaphore)
        async def run_image_task():
            async with image_semaphore:
                # Add a 10.0 second pause between generations to stay within Replicate's 6/min rate limit
                await asyncio.sleep(10.0)
                if req.imageModel == "video":
                    return await asyncio.to_thread(
                        generator.generate_video_replicate, 
                        seg.visual_prompt, 
                        image_path_raw,
                        req.aspectRatio
                    )
                else:
                    return await asyncio.to_thread(
                        generator.generate_image_replicate, 
                        seg.visual_prompt, 
                        image_path_raw,
                        req.aspectRatio,
                        req.imageModel
                    )
        
        # Run concurrently
        try:
            actual_audio_path, actual_image_path = await asyncio.gather(voiceover_task, run_image_task())
            return {
                "text_to_speak": seg.text_to_speak,
                "visual_prompt": seg.visual_prompt,
                "audio_path": f"outputs/{project_id}/{os.path.basename(actual_audio_path)}",
                "image_path": f"outputs/{project_id}/{os.path.basename(actual_image_path)}"
            }
        except Exception as e:
            print(f"Error generating assets for segment {index}: {e}")
            raise e

    try:
        tasks = [process_segment(i, seg) for i, seg in enumerate(req.segments)]
        results = await asyncio.gather(*tasks)
        return {
            "projectId": project_id,
            "segments": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate assets: {str(e)}")

@app.post("/api/regenerate-segment")
async def api_regenerate_segment(req: RegenerateSegmentRequest):
    """
    Regenerates only a single segment's voiceover and/or image.
    """
    project_id = req.projectId
    project_dir = f"outputs/{project_id}"
    os.makedirs(project_dir, exist_ok=True)
    
    audio_filename = f"audio_{req.segmentIndex}.mp3"
    audio_path = f"{project_dir}/{audio_filename}"
    
    image_filename = f"image_{req.segmentIndex}" # extension added later
    image_path_raw = f"{project_dir}/{image_filename}.webp"
    
    actual_audio_path = f"outputs/{project_id}/{audio_filename}"
    actual_image_path = ""
    
    try:
        tasks = []
        
        # 1. Regenerate voiceover if requested
        if req.regenerateAudio:
            tasks.append(generator.generate_voiceover(req.textToSpeak, audio_path))
        else:
            # Dummy awaitable to match unpack count
            async def dummy_voice():
                return audio_path
            tasks.append(dummy_voice())
            
        # 2. Regenerate visual asset if requested
        if req.regenerateImage:
            async def run_image():
                if req.imageModel == "video":
                    return await asyncio.to_thread(
                        generator.generate_video_replicate,
                        req.visualPrompt,
                        image_path_raw,
                        req.aspectRatio
                    )
                else:
                    return await asyncio.to_thread(
                        generator.generate_image_replicate,
                        req.visualPrompt,
                        image_path_raw,
                        req.aspectRatio,
                        req.imageModel
                    )
            tasks.append(run_image())
        else:
            async def dummy_image():
                # Search for existing file with mp4 or jpg extension
                for ext in [".mp4", ".jpg"]:
                    test_file = f"{project_dir}/image_{req.segmentIndex}{ext}"
                    if os.path.exists(test_file):
                        return test_file
                return f"{project_dir}/image_{req.segmentIndex}.jpg"
            tasks.append(dummy_image())
            
        res_audio, res_image = await asyncio.gather(*tasks)
        
        if req.regenerateAudio:
            actual_audio_path = f"outputs/{project_id}/{os.path.basename(res_audio)}"
        else:
            actual_audio_path = f"outputs/{project_id}/{audio_filename}"
            
        actual_image_path = f"outputs/{project_id}/{os.path.basename(res_image)}"
            
        return {
            "text_to_speak": req.textToSpeak,
            "visual_prompt": req.visualPrompt,
            "audio_path": actual_audio_path,
            "image_path": actual_image_path
        }
    except Exception as e:
        print(f"Error regenerating segment {req.segmentIndex}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/render-video")
async def api_render_video(req: RenderRequest):
    """
    Step 3: Stitches all generated segment images and voice tracks into a final MP4 video.
    """
    project_id = req.projectId
    project_dir = f"outputs/{project_id}"
    output_video_path = f"{project_dir}/final_video.mp4"
    
    # Map the relative URLs back to absolute local paths
    processed_segments = []
    for seg in req.segments:
        local_img = seg.image_path.replace("outputs/", f"outputs/")
        local_audio = seg.audio_path.replace("outputs/", f"outputs/")
        
        processed_segments.append({
            "image_path": local_img,
            "audio_path": local_audio
        })
        
    bg_music_path = None
    if req.musicTrack:
        if req.musicTrack in ["Auto-Select", "auto", "Auto"]:
            # Auto-detect visual style from metadata
            visual_style = "Cinematic Photo"
            meta_path = f"{project_dir}/metadata.json"
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    visual_style = meta.get("visualStyle", "Cinematic Photo")
                except Exception:
                    pass
            # Map visual style to corresponding BGM
            style_music_mapping = {
                "Cyberpunk": "synthwave_beat.mp3",
                "Retro Anime": "ambient_dream.mp3",
                "Dark Sci-Fi / Fantasy": "ambient_space.mp3",
                "Steampunk Oil Painting": "ambient_dream.mp3",
                "Cinematic Photo": "ambient_dream.mp3"
            }
            mapped_track = style_music_mapping.get(visual_style, "ambient_dream.mp3")
            bg_music_path = f"static/music/{mapped_track}"
            print(f"Auto-selected BGM '{mapped_track}' for style '{visual_style}'")
        else:
            bg_music_path = f"static/music/{req.musicTrack}"
        
    try:
        # Assemble using moviepy
        video_path = await asyncio.to_thread(
            generator.assemble_video,
            processed_segments,
            output_video_path,
            req.aspectRatio,
            bg_music_path,
            req.fontName,
            req.highlightColor,
            req.captionPosition,
            req.addWatermark,
            req.captionPreset
        )
        
        # Update project metadata
        meta_path = f"{project_dir}/metadata.json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["status"] = "rendered"
                meta["videoUrl"] = f"outputs/{project_id}/final_video.mp4"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception as e:
                print(f"Error updating metadata during render: {e}")
                
        return {
            "projectId": project_id,
            "video_url": f"outputs/{project_id}/final_video.mp4"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render video: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
