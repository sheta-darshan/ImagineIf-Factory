import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_youtube_client(secrets_path="client_secrets.json", token_path="client_token.json"):
    """
    Checks local tokens and starts OAuth2 flow if needed.
    """
    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"Warning: Failed to load existing YouTube tokens ({e}). Re-authenticating...")
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as re:
                print(f"Warning: Failed to refresh YouTube credentials token ({re}). Re-authenticating...")
                creds = None
                
        if not creds or not creds.valid:
            if not os.path.exists(secrets_path):
                raise FileNotFoundError(
                    f"Credentials file '{secrets_path}' not found.\n"
                    "Please download it from Google Cloud Console (OAuth 2.0 Desktop Client credentials) "
                    "and place it in the project root as 'client_secrets.json'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(token_path, "w") as token:
            token.write(creds.to_json())
            
    return build("youtube", "v3", credentials=creds)

def upload_video_to_youtube(video_path, title, description, tags="", secrets_path="client_secrets.json", token_path="client_token.json"):
    """
    Performs chunked resumable upload of video_path to the authenticated channel.
    """
    youtube = get_youtube_client(secrets_path, token_path)
    
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    
    body = {
        "snippet": {
            "title": title[:100],  # Title limit is 100 chars
            "description": description[:5000],  # Desc limit is 5000 chars
            "tags": tags_list,
            "categoryId": "22"  # Category 22 is 'People & Blogs' (standard category)
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(
        video_path,
        chunksize=1024 * 1024,  # 1MB chunks
        resumable=True,
        mimetype="video/mp4"
    )
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading video... {int(status.progress() * 100)}% complete")
            
    print(f"Video uploaded successfully! ID: {response.get('id')}")
    return response.get("id")
