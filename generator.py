import os
import json
import asyncio
import httpx
from google import genai
from google.genai import types
import replicate
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, VideoFileClip

load_dotenv()

# Configure GenAI Client
client = None
if os.getenv("GEMINI_API_KEY"):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Configure Replicate
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if REPLICATE_API_TOKEN:
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

async def generate_script(thought: str, duration_seconds: int = 60, visual_style: str = "Cinematic Photo") -> dict:
    """
    Sends the user's thought to Gemini to generate a script and YouTube SEO metadata.
    Returns a dictionary containing:
      - title: YouTube title
      - description: SEO description with timestamps
      - tags: comma-separated hashtags and tags
      - segments: list of segments with text_to_speak and visual_prompt
    """
    style_guidelines = {
        "Cinematic Photo": "cinematic, dramatic lighting, detailed 8k photography, realistic, depth of field",
        "Dark Sci-Fi / Fantasy": "epic scale dark fantasy/sci-fi, moody, mysterious atmosphere, digital art, high contrast, atmospheric fog",
        "Cyberpunk": "cyberpunk style, neon glow, futuristic technology, dark rainy city, hyper-detailed, synthwave color palette",
        "Retro Anime": "90s retro anime style, hand-drawn aesthetic, Studio Ghibli inspired, vibrant colors, detailed cel shading",
        "Steampunk Oil Painting": "steampunk aesthetic, textured oil painting style, visible brush strokes, brass and copper mechanisms, warm historical tones"
    }
    chosen_style = style_guidelines.get(visual_style, style_guidelines["Cinematic Photo"])

    prompt = f"""
    You are an expert director, visual storyteller, and YouTube growth marketer.
    Break down the following thought/topic into a sequence of short video segments for a video around {duration_seconds} seconds long.
    Each segment must last approximately 5 to 10 seconds (roughly 15 to 25 words of spoken narration per segment).
    The narration should flow naturally as a single continuous script.
    
    CRITICAL ENGAGEMENT AND STRUCTURE REQUIREMENTS:
    1. Hook (Segment 1): Must begin with an immediate, high-retention hook (an intriguing, polarising, or curiosity-inducing question that stops the scroll).
    2. Close (Final Segment): Must end with a compelling, open-ended question that drives comments, paired with a call to action asking the viewer to share/tag a friend.
    3. Language: Write the spoken narration (`text_to_speak`) in very simple, clear, and easy-to-understand English (approx. 5th-grade reading level). Keep sentences short and direct.
    
    Provide highly detailed, specific visual prompts for each segment that will be fed into an AI visual generator.

    Thought/Topic: {thought}

    Respond strictly in JSON format. The response must be a JSON object with exactly these keys:
      "title": "a catchy, click-worthy, algorithm-friendly YouTube title based on the topic",
      "description": "an SEO-optimized YouTube description containing a compelling summary, call to action, and timestamp chapters (e.g. 00:00 - Introduction, etc.)",
      "tags": "a comma-separated string of relevant hashtags and search tags",
      "segments": [
         {{
           "text_to_speak": "spoken narration text for this segment, written in simple and clear English",
           "visual_prompt": "highly detailed visual prompt describing the scene, style, lighting, composition, and dynamic motion (e.g. slow-motion camera sweep, steam rising, wind blowing, debris drifting, subtle character gestures). Explicitly describe the motion or camera movement to enable high-quality AI video generation."
         }}
      ]

    Ensure the visuals strictly adhere to the following style: {chosen_style}. Make sure the prompt itself is descriptive rather than just stating the style name and always include active, cinematic camera movements or environmental motion instructions.
    """

    global client
    if not client:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            break
        except Exception as e:
            error_msg = str(e)
            is_429 = "429" in error_msg or "quota" in error_msg.lower() or "ResourceExhausted" in error_msg
            if is_429 and attempt < max_retries - 1:
                wait_time = 15 + attempt * 15
                print(f"Gemini API rate limit hit. Waiting {wait_time}s before retry (Attempt {attempt+1}/{max_retries})...")
                await asyncio.sleep(wait_time)
            else:
                raise e
    
    try:
        data = json.loads(response.text)
        if not isinstance(data, dict):
            raise ValueError("Root element is not a JSON object")
            
        # Ensure fallback keys exist
        if "segments" not in data:
            if isinstance(data, list):
                data = {"segments": data}
            else:
                data = {"segments": []}
                
        if "title" not in data:
            data["title"] = f"Imagine If: {thought[:40]}..."
        if "description" not in data:
            data["description"] = "A short story exploring a fascinating 'Imagine If' scenario. Subscribe for more speculative concepts!"
        if "tags" not in data:
            data["tags"] = "#ImagineIf, #SciFi, #Speculative"
            
        return data
    except Exception as e:
        print(f"Error parsing JSON from Gemini: {e}. Raw response: {response.text}")
        raise e

async def generate_voiceover(text: str, output_path: str, voice: str = "en-US-GuyNeural"):
    """
    Generates a voiceover .mp3 file for the given text using edge-tts.
    Also captures word timings and saves them as a JSON file.
    """
    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    words = []
    
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10000000.0
                duration = chunk["duration"] / 10000000.0
                words.append({
                    "word": chunk["text"],
                    "start": start,
                    "end": start + duration
                })
                
    # Save word timings to a JSON file alongside the audio
    json_path = output_path.replace(".mp3", ".json")
    with open(json_path, "w", encoding="utf-8") as fj:
        json.dump(words, fj, indent=2)
        
    return output_path

import urllib.parse
import time

def generate_image_pollinations(prompt: str, output_path: str, aspect_ratio: str = "16:9") -> str:
    print(f"Generating image via Pollinations.ai (Free Option) for: {prompt[:60]}...")
    encoded_prompt = urllib.parse.quote(prompt)
    
    # Set dimensions based on aspect ratio
    width, height = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)
    url = f"https://image.pollinations.ai/p/{encoded_prompt}?width={width}&height={height}&nologo=true"
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = httpx.get(url, timeout=30.0)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                break
            elif response.status_code == 429:
                wait_time = 3 + attempt * 3
                print(f"Pollinations.ai returned 429 (Rate Limit). Waiting {wait_time}s and retrying (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"Pollinations.ai failed with status code {response.status_code}")
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = 3 + attempt * 3
            print(f"Error calling Pollinations.ai: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
    else:
        raise RuntimeError("Failed to generate image from Pollinations.ai after multiple retries due to rate limiting.")
    
    try:
        with Image.open(output_path) as img:
            jpg_path = os.path.splitext(output_path)[0] + ".jpg"
            img.convert("RGB").save(jpg_path, "JPEG")
            if output_path != jpg_path:
                os.remove(output_path)
            return jpg_path
    except Exception as e:
        print(f"Warning converting fallback image: {e}")
        return output_path

def generate_image_replicate(prompt: str, output_path: str, aspect_ratio: str = "16:9", image_model: str = "schnell") -> str:
    """
    Generates an image from a prompt using Replicate (black-forest-labs/flux-schnell or flux-dev).
    Falls back to Pollinations.ai if Replicate is not configured, has no credit, or fails.
    """
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token or "your_" in token.lower():
        print("Replicate token not configured. Falling back to Pollinations.ai...")
        return generate_image_pollinations(prompt, output_path, aspect_ratio)
    
    model_name = "black-forest-labs/flux-dev" if image_model == "dev" else "black-forest-labs/flux-schnell"
    
    max_retries = 4
    output = None
    for attempt in range(max_retries):
        try:
            output = replicate.run(
                model_name,
                input={
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "output_format": "webp",
                    "output_quality": 90
                }
            )
            break
        except Exception as e:
            error_msg = str(e)
            is_429 = "429" in error_msg or "throttled" in error_msg.lower()
            if is_429 and attempt < max_retries - 1:
                wait_time = 10 + attempt * 5
                print(f"Replicate rate limit (429) hit. Waiting {wait_time}s before retry (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"Replicate image generation failed ({e}). Falling back to Pollinations.ai...")
                return generate_image_pollinations(prompt, output_path, aspect_ratio)
                
    if not output or len(output) == 0:
        print("Replicate did not return any output URLs. Falling back to Pollinations.ai...")
        return generate_image_pollinations(prompt, output_path, aspect_ratio)
        
    try:
        image_url = output[0]
        
        # Download and save the image content, supporting both file-like objects and URLs
        if hasattr(image_url, "read"):
            content = image_url.read()
        else:
            url_str = image_url.url if hasattr(image_url, "url") else str(image_url)
            response = httpx.get(url_str, timeout=30.0)
            if response.status_code != 200:
                raise RuntimeError(f"Failed to download image from {url_str}")
            content = response.content
            
        with open(output_path, "wb") as f:
            f.write(content)
            
        # Convert WebP to JPG/PNG to ensure moviepy compatibility
        with Image.open(output_path) as img:
            jpg_path = os.path.splitext(output_path)[0] + ".jpg"
            img.convert("RGB").save(jpg_path, "JPEG")
            os.remove(output_path)  # remove old WebP
            return jpg_path
    except Exception as e:
        print(f"Replicate download/processing failed ({e}). Falling back to Pollinations.ai...")
        return generate_image_pollinations(prompt, output_path, aspect_ratio)

def generate_video_replicate(prompt: str, output_path: str, aspect_ratio: str = "16:9") -> str:
    """
    Generates a 4-second video clip using Replicate (thudm/cogvideox-t2v).
    Falls back to a static image if it fails or Replicate is not configured.
    """
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token or "your_" in token.lower():
        print("Replicate token not configured for video. Falling back to static image...")
        return generate_image_replicate(prompt, output_path, aspect_ratio)
        
    max_retries = 3
    output = None
    for attempt in range(max_retries):
        try:
            # Fetch latest version of Lightricks LTX-Video model dynamically
            model = replicate.models.get("lightricks/ltx-video")
            prediction = replicate.predictions.create(
                version=model.latest_version,
                input={
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "negative_prompt": "low quality, blurry, watermark"
                }
            )
            
            # Poll status up to 3 minutes (180s)
            import time
            start_poll = time.time()
            while prediction.status not in ["succeeded", "failed", "canceled"]:
                if time.time() - start_poll > 180:
                    raise TimeoutError("CogVideoX prediction timed out after 3 minutes.")
                time.sleep(3)
                prediction.reload()
                
            if prediction.status == "succeeded":
                output = prediction.output
                break
            else:
                raise RuntimeError(f"Prediction failed with status: {prediction.status}")
        except Exception as e:
            error_msg = str(e)
            is_429 = "429" in error_msg or "throttled" in error_msg.lower()
            if is_429 and attempt < max_retries - 1:
                wait_time = 15 + attempt * 5
                print(f"Replicate rate limit hit. Waiting {wait_time}s before retry (Attempt {attempt+1}/{max_retries})...")
                import time
                time.sleep(wait_time)
            else:
                print(f"Replicate video generation failed ({e}). Falling back to static image...")
                return generate_image_replicate(prompt, output_path, aspect_ratio)
                
    if not output:
        print("Replicate video returned no output. Falling back to static image...")
        return generate_image_replicate(prompt, output_path, aspect_ratio)
        
    try:
        video_url = output
        if isinstance(output, list):
            video_url = output[0]
            
        if hasattr(video_url, "read"):
            content = video_url.read()
        else:
            url_str = video_url.url if hasattr(video_url, "url") else str(video_url)
            import httpx
            response = httpx.get(url_str, timeout=45.0)
            if response.status_code != 200:
                raise RuntimeError(f"Failed to download video from {url_str}")
            content = response.content
            
        mp4_path = os.path.splitext(output_path)[0] + ".mp4"
        with open(mp4_path, "wb") as f:
            f.write(content)
        return mp4_path
    except Exception as e:
        print(f"Replicate video processing failed ({e}). Falling back to static image...")
        return generate_image_replicate(prompt, output_path, aspect_ratio)

def create_ken_burns_clip(image_path: str, duration: float, target_size=(1920, 1080), motion_type: str = "zoom_in") -> ImageClip:
    """
    Creates an ImageClip with varied Ken Burns animations: zoom_in, zoom_out, pan_left, pan_right.
    """
    with Image.open(image_path) as img:
        img_w, img_h = img.size
    
    clip = ImageClip(image_path).with_duration(duration)
    
    # Base scale factor to cover the canvas completely
    base_scale = max(target_size[0]/img_w, target_size[1]/img_h)
    
    if motion_type == "zoom_in":
        base_w, base_h = int(img_w * base_scale), int(img_h * base_scale)
        clip = clip.resized((base_w, base_h))
        zoom_speed = 0.08 / duration
        animated_clip = clip.resized(lambda t: 1.0 + zoom_speed * t)
        pos_func = "center"
        
    elif motion_type == "zoom_out":
        base_w, base_h = int(img_w * base_scale), int(img_h * base_scale)
        clip = clip.resized((base_w, base_h))
        zoom_speed = 0.08 / duration
        # Start at 1.08 and scale down to 1.0
        animated_clip = clip.resized(lambda t: 1.08 - zoom_speed * t)
        pos_func = "center"
        
    elif motion_type == "pan_left":
        # Scale slightly larger (1.12x) to allow horizontal panning room
        scale_factor = base_scale * 1.12
        base_w, base_h = int(img_w * scale_factor), int(img_h * scale_factor)
        clip = clip.resized((base_w, base_h))
        
        max_pan_x = base_w - target_size[0]
        # Panning function: start on right side (max_pan_x) and translate left to 0
        pos_func = lambda t: (int(max_pan_x - (max_pan_x / duration) * t), "center")
        animated_clip = clip
        
    elif motion_type == "pan_right":
        scale_factor = base_scale * 1.12
        base_w, base_h = int(img_w * scale_factor), int(img_h * scale_factor)
        clip = clip.resized((base_w, base_h))
        
        max_pan_x = base_w - target_size[0]
        # Panning function: start on left side (0) and translate right to max_pan_x
        pos_func = lambda t: (int((max_pan_x / duration) * t), "center")
        animated_clip = clip
        
    else:
        # Fallback to standard center crop
        base_w, base_h = int(img_w * base_scale), int(img_h * base_scale)
        clip = clip.resized((base_w, base_h))
        animated_clip = clip
        pos_func = "center"
        
    canvas = CompositeVideoClip([animated_clip.with_position(pos_func)], size=target_size).with_duration(duration)
    return canvas


def draw_text_on_frame(frame, t, words, target_size, font_name="Arial Bold", highlight_color_name="Yellow", position_name="Bottom", add_watermark=False, is_last_segment=False):
    """
    Draws custom styled highlighted subtitles, an optional brand watermark, and engagement overlays on a numpy video frame using PIL.
    """
    # Convert numpy frame (RGB) to Pillow Image
    pil_img = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil_img)
    
    # 1. Draw Watermark if selected
    if add_watermark:
        watermark_text = "@ImagineIfOfficial"
        # Use a small simple font size
        watermark_font_path = "C:\\Windows\\Fonts\\arial.ttf"
        try:
            watermark_font = ImageFont.truetype(watermark_font_path, 28 if target_size[0] < 1200 else 24)
        except Exception:
            watermark_font = ImageFont.load_default()
        
        # Position: Top Right corner
        w_w = draw.textlength(watermark_text, font=watermark_font)
        x_watermark = target_size[0] - w_w - 30
        y_watermark = 30
        
        # Draw watermark with transparency by writing semi-transparent text
        # Draw light gray text with thin stroke
        draw.text(
            (x_watermark, y_watermark), 
            watermark_text, 
            fill=(255, 255, 255, 120),  # semi-transparent white
            font=watermark_font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 100)
        )
        
    # 2. Draw Visual CTA Badge if it's the last segment (YouTube Friendly engagement card)
    if is_last_segment:
        card_w, card_h = 420, 65
        card_x = (target_size[0] - card_w) / 2
        card_y = 90
        
        # Draw semi-transparent card container with rounded corners and glowing indigo border
        draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=16,
            fill=(0, 0, 0, 160),
            outline=(99, 102, 241, 200),
            width=2
        )
        
        cta_text = "🔔 Share & Comment below!"
        cta_font_path = "C:\\Windows\\Fonts\\arialbd.ttf"
        try:
            cta_font = ImageFont.truetype(cta_font_path, 26)
        except Exception:
            cta_font = ImageFont.load_default()
            
        txt_w = draw.textlength(cta_text, font=cta_font)
        txt_x = card_x + (card_w - txt_w) / 2
        txt_y = card_y + (card_h - 30) / 2
        
        # Text shadow and drawing
        draw.text((txt_x + 2, txt_y + 2), cta_text, fill=(0, 0, 0, 200), font=cta_font)
        draw.text((txt_x, txt_y), cta_text, fill=(255, 255, 255), font=cta_font)
        
    if not words:
        return np.array(pil_img)
        
    # Find active word index
    active_word_idx = -1
    for idx, w in enumerate(words):
        if w['start'] <= t <= w['end']:
            active_word_idx = idx
            break
            
    # Fallback to closest word if none active
    if active_word_idx == -1:
        if t < words[0]['start']:
            active_word_idx = 0
        else:
            for idx, w in enumerate(words):
                if w['end'] <= t:
                    active_word_idx = idx

    # Slice word group to display (window of 5 words around active word)
    start_idx = max(0, active_word_idx - 2)
    end_idx = min(len(words), active_word_idx + 3)
    display_words = words[start_idx:end_idx]
    
    # Map font name to Windows Font Path
    font_paths = {
        "Arial Bold": "C:\\Windows\\Fonts\\arialbd.ttf",
        "Impact": "C:\\Windows\\Fonts\\impact.ttf",
        "Courier Bold": "C:\\Windows\\Fonts\\courbd.ttf",
        "Times Bold": "C:\\Windows\\Fonts\\timesbd.ttf"
    }
    font_file = font_paths.get(font_name, font_paths["Arial Bold"])
    
    # Scale font size slightly larger for Shorts (9:16)
    font_size = 64 if target_size[0] < 1200 else 52
    try:
        font = ImageFont.truetype(font_file, font_size)
    except Exception:
        font = ImageFont.load_default()
        
    # Map highlight color name to RGB
    color_map = {
        "Yellow": (255, 255, 0),
        "Neon Green": (57, 255, 20),
        "Cyan": (0, 255, 255),
        "Magenta": (255, 0, 255),
        "White": (255, 255, 255)
    }
    highlight_rgb = color_map.get(highlight_color_name, color_map["Yellow"])
    
    # Map position to vertical height multiplier
    pos_map = {
        "Top": 0.18,
        "Center": 0.50,
        "Bottom": 0.70
    }
    y_multiplier = pos_map.get(position_name, pos_map["Bottom"])
    y_pos = target_size[1] * y_multiplier
    
    # Calculate word positions dynamically
    words_metadata = []
    total_w = 0
    space_w = draw.textlength(" ", font=font)
    
    for w in display_words:
        w_text = w['word']
        is_active = (w == words[active_word_idx])
        
        # Check for pause after this word
        has_pause = False
        try:
            abs_idx = words.index(w)
            if abs_idx < len(words) - 1:
                gap = words[abs_idx + 1]['start'] - w['end']
                if gap > 0.4:
                    has_pause = True
        except ValueError:
            pass

        # Determine font size scale and styling based on punctuation/pauses
        scale = 1.0
        if is_active:
            scale = 1.18  # Pop active word slightly
            if "!" in w_text:
                scale = 1.35  # Excitement gets a massive pop
            elif "?" in w_text:
                scale = 1.25  # Question gets a medium pop
                
            # Dynamic bounce/pop animation curve based on active timing
            w_start = w.get('start', t)
            w_end = w.get('end', t + 0.1)
            w_dur = max(w_end - w_start, 0.05)
            progress = (t - w_start) / w_dur
            if progress < 0.25:
                bounce_factor = 1.0 + (0.25 * (progress / 0.25))
            else:
                decay_progress = min((progress - 0.25) / 0.75, 1.0)
                bounce_factor = 1.25 - (0.15 * decay_progress)
            scale = scale * bounce_factor
        
        # Load scaled font for this word if necessary
        word_font = font
        if scale != 1.0:
            try:
                word_font = ImageFont.truetype(font_file, int(font_size * scale))
            except Exception:
                word_font = font
                
        # Transform text based on context
        display_text = w_text
        if is_active and "!" in w_text:
            display_text = w_text.upper()
        if has_pause and is_active:
            display_text = w_text + "..."
            
        w_width = draw.textlength(display_text, font=word_font)
        
        # Determine Color based on spoken expression
        word_color = (255, 255, 255)
        if is_active:
            if "!" in w_text:
                word_color = (255, 69, 0)  # Red-Orange for high excitement!
            elif "?" in w_text:
                word_color = (0, 255, 255)  # Cyan for questions?
            elif has_pause:
                word_color = (219, 112, 147)  # Pink-Violet for pauses...
            else:
                word_color = highlight_rgb
                
        words_metadata.append({
            "text": display_text,
            "width": w_width,
            "font": word_font,
            "color": word_color,
            "scale": scale
        })
        total_w += w_width + space_w
        
    total_w -= space_w
    
    start_x = (target_size[0] - total_w) / 2
    
    curr_x = start_x
    for w_meta in words_metadata:
        text = w_meta["text"]
        w_w = w_meta["width"]
        word_font = w_meta["font"]
        word_color = w_meta["color"]
        scale = w_meta["scale"]
        
        # Center vertically around standard baseline
        y_offset = 0
        if scale > 1.0:
            y_offset = -int((font_size * (scale - 1.0)) / 2)
            
        # Draw 3D Drop Shadow first
        shadow_offset = int(3 * scale)
        draw.text(
            (curr_x + shadow_offset, y_pos + y_offset + shadow_offset), 
            text, 
            fill=(0, 0, 0, 180),
            font=word_font, 
            stroke_width=int(4 * scale), 
            stroke_fill=(0, 0, 0)
        )
            
        # Draw Main Highlighted Text
        draw.text(
            (curr_x, y_pos + y_offset), 
            text, 
            fill=word_color, 
            font=word_font, 
            stroke_width=int(4 * scale), 
            stroke_fill=(0, 0, 0)
        )
        curr_x += w_w + space_w
        
    return np.array(pil_img)

def assemble_video(segments: list, output_path: str, aspect_ratio: str = "16:9", bg_music_path: str = None, font_name: str = "Arial Bold", highlight_color: str = "Yellow", caption_position: str = "Bottom", add_watermark: bool = False) -> str:
    """
    Stitches generated audio and visual assets (images or CogVideoX videos) together into a final MP4 video.
    """
    import random
    target_size = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
    clips = []
    
    # Track speaking intervals for dynamic audio ducking
    speaking_intervals = []
    clip_start_times = []
    curr_start = 0.0
    
    motion_types = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
    
    for i, seg in enumerate(segments):
        img_path = seg.get("image_path")
        audio_path = seg.get("audio_path")
        
        if not img_path or not os.path.exists(img_path):
            print(f"Skipping segment {i} due to missing visual asset: {img_path}")
            continue
            
        if not audio_path or not os.path.exists(audio_path):
            print(f"Skipping segment {i} due to missing audio: {audio_path}")
            continue
            
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration
        clip_start_times.append(curr_start)
        
        is_video_asset = img_path.lower().endswith(".mp4")
        if is_video_asset:
            try:
                # Load, scale, and center-crop video clip to target size
                video_segment = VideoFileClip(img_path)
                seg_w, seg_h = video_segment.size
                scale_factor = max(target_size[0] / seg_w, target_size[1] / seg_h)
                resized_video = video_segment.resized((int(seg_w * scale_factor), int(seg_h * scale_factor)))
                
                cropped_video = resized_video.cropped(
                    x_center=resized_video.w / 2,
                    y_center=resized_video.h / 2,
                    width=target_size[0],
                    height=target_size[1]
                )
                
                # Loop or trim to fit speech duration
                if cropped_video.duration < duration:
                    try:
                        from moviepy.video.fx.Loop import Loop
                        img_clip = cropped_video.with_effects([Loop(duration=duration)])
                    except Exception:
                        img_clip = cropped_video.loop(duration=duration)
                else:
                    img_clip = cropped_video.subclipped(0, duration)
            except Exception as ve:
                print(f"Warning: Failed to load video asset {img_path} ({ve}). Falling back to blank canvas.")
                img_clip = create_ken_burns_clip(None, duration, target_size=target_size)
        else:
            # Fallback to panning static image clip
            motion_style = random.choice(motion_types)
            img_clip = create_ken_burns_clip(img_path, duration, target_size=target_size, motion_type=motion_style)
        
        # Integrate customized auto-captions word overlay
        json_path = audio_path.replace(".mp3", ".json")
        word_timings = None
        try:
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as fj:
                    word_timings = json.load(fj)
            
            # Dynamic subtitle & watermark frame processor function
            is_last = (i == len(segments) - 1)
            def make_subtitle_filter(timings, size, font, color, pos, watermark, is_last_seg):
                def filter_func(get_frame, t):
                    frame = get_frame(t)
                    return draw_text_on_frame(frame, t, timings, size, font, color, pos, watermark, is_last_seg)
                return filter_func
            
            filter_to_apply = make_subtitle_filter(
                word_timings, 
                target_size, 
                font_name, 
                highlight_color, 
                caption_position, 
                add_watermark,
                is_last
            )
            
            if hasattr(img_clip, "transform"):
                img_clip = img_clip.transform(filter_to_apply)
            else:
                img_clip = img_clip.fl(filter_to_apply)
        except Exception as se:
            print(f"Warning: Failed to apply subtitle/watermark overlay: {se}")
            
        # Collect word timestamps relative to the final merged timeline
        if word_timings:
            for w in word_timings:
                word_start = curr_start + w.get("start", 0)
                word_end = curr_start + w.get("end", 0)
                # Pad slightly for natural decay
                speaking_intervals.append((word_start - 0.15, word_end + 0.15))
                
        img_clip = img_clip.with_audio(audio_clip)
        clips.append(img_clip)
        
        # Shift start offset for the next clip (adjusting for crossfade overlap)
        curr_start += duration - 0.5
        
    if not clips:
        raise ValueError("No valid video segments to assemble")
        
    # Use padding=-0.5 to overlap clips by 0.5s and automatically cross-dissolve them
    if len(clips) > 1:
        final_clip = concatenate_videoclips(clips, method="compose", padding=-0.5)
    else:
        final_clip = clips[0]
        
    final_duration = final_clip.duration
    
    # Background Music Integration
    if bg_music_path and os.path.exists(bg_music_path):
        try:
            from moviepy.audio.AudioClip import CompositeAudioClip
            bg_clip = AudioFileClip(bg_music_path)
            
            # Loop audio using helper fallbacks
            try:
                from moviepy.audio.fx.all import audio_loop
                bg_clip_looped = bg_clip.fx(audio_loop, duration=final_duration)
            except Exception:
                bg_clip_looped = bg_clip.loop(duration=final_duration)
                
            # Duck music volume to 8% during speech, boost to 22% during silence/breaks
            if speaking_intervals:
                def volume_duck_filter(t):
                    import numpy as np
                    if isinstance(t, np.ndarray):
                        res = np.ones(t.shape) * 0.22
                        for idx_t, time_val in enumerate(t):
                            for start, end in speaking_intervals:
                                if start <= time_val <= end:
                                    res[idx_t] = 0.08
                                    break
                        return res
                    else:
                        for start, end in speaking_intervals:
                            if start <= t <= end:
                                return 0.08
                        return 0.22
                
                try:
                    bg_clip_ducked = bg_clip_looped.transform_volume(volume_duck_filter)
                except Exception as ve:
                    print(f"Warning: Ducking transform failed ({ve}), using fallback.")
                    bg_clip_ducked = bg_clip_looped.with_volume_scaled(0.12)
            else:
                bg_clip_ducked = bg_clip_looped.with_volume_scaled(0.12)
                
            # Mix music with narration audio
            mixed_audio = CompositeAudioClip([final_clip.audio, bg_clip_ducked])
            final_clip = final_clip.with_audio(mixed_audio)
            print(f"Successfully mixed background music: {bg_music_path}")
        except Exception as e:
            print(f"Warning: Failed to mix background music: {e}")
            
    # Transition Whoosh Sound Effects mixing
    whoosh_sfx_path = "static/music/whoosh_transition.wav"
    whoosh_audio_clips = []
    if os.path.exists(whoosh_sfx_path) and len(clips) > 1:
        try:
            whoosh_sfx = AudioFileClip(whoosh_sfx_path)
            half_dur = whoosh_sfx.duration / 2
            # Add a transition whoosh centered around each transition point
            for t_trans in clip_start_times[1:]:
                whoosh_audio_clips.append(whoosh_sfx.with_start(max(0.0, t_trans - half_dur)))
                
            if whoosh_audio_clips:
                from moviepy.audio.AudioClip import CompositeAudioClip
                mixed_audio = CompositeAudioClip([final_clip.audio] + whoosh_audio_clips)
                final_clip = final_clip.with_audio(mixed_audio)
                print("Successfully mixed transition whoosh sound effects!")
        except Exception as we:
            print(f"Warning: Failed to mix transition whoosh sound effects: {we}")
            
    # Engagement Chime Notification SFX mixing for the final segment CTA
    chime_sfx_path = "static/music/chime_notification.wav"
    if os.path.exists(chime_sfx_path) and len(clip_start_times) > 0:
        try:
            chime_sfx = AudioFileClip(chime_sfx_path)
            # Start chime exactly at the beginning of the last segment (CTA hook)
            chime_start_t = clip_start_times[-1]
            chime_clip = chime_sfx.with_start(chime_start_t)
            
            from moviepy.audio.AudioClip import CompositeAudioClip
            mixed_audio = CompositeAudioClip([final_clip.audio, chime_clip])
            final_clip = final_clip.with_audio(mixed_audio)
            print("Successfully mixed final segment chime notification sound effect!")
        except Exception as ce:
            print(f"Warning: Failed to mix chime sound effect: {ce}")
            
    final_clip.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True
    )
    
    final_clip.close()
    for c in clips:
        c.close()
        
    return output_path
