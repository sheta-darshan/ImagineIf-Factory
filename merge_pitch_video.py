import os
import sys
from moviepy import VideoFileClip, AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip

def merge_pitch_video(video_path, output_path="final_pitch_submission.mp4"):
    voiceover_path = r"C:\Users\sheta\.gemini\antigravity-ide\brain\aee98736-edd7-474d-a428-7af079615d93\pitch_voiceover.mp3"
    bgm_path = r"static/music/ambient_space.mp3"
    
    if not os.path.exists(video_path):
        print(f"Error: Input video not found at {video_path}")
        return
        
    print("Loading video and audio clips...")
    video_clip = VideoFileClip(video_path)
    voice_clip = AudioFileClip(voiceover_path)
    
    # Calculate duration
    duration = voice_clip.duration
    video_clip = video_clip.subclipped(0, duration) # trim video to match voiceover
    
    if os.path.exists(bgm_path):
        print("Mixing background music...")
        bg_clip = AudioFileClip(bgm_path)
        
        # Loop using MoviePy 2.x AudioLoop effect
        try:
            from moviepy.audio.fx.AudioLoop import AudioLoop
            bg_clip_looped = bg_clip.with_effects([AudioLoop(duration=duration)])
        except Exception as e:
            print(f"Warning: AudioLoop failed ({e}), using raw clip.")
            bg_clip_looped = bg_clip
            
        bg_clip_ducked = bg_clip_looped.with_volume_scaled(0.12)
        
        # Merge voiceover with BGM
        final_audio = CompositeAudioClip([voice_clip, bg_clip_ducked])
    else:
        print("BGM not found, using voiceover only.")
        final_audio = voice_clip
        
    print("Stitching audio to video track...")
    final_video = video_clip.with_audio(final_audio)
    
    print(f"Exporting final video to {output_path}...")
    final_video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-pitch-audio.m4a",
        remove_temp=True
    )
    
    # Close clips to release resources
    video_clip.close()
    voice_clip.close()
    if os.path.exists(bgm_path):
        bg_clip.close()
    print("Successfully exported final pitch submission video!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python merge_pitch_video.py <path_to_your_converted_mp4>")
    else:
        merge_pitch_video(sys.argv[1])
