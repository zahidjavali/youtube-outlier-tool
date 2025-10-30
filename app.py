import streamlit as st
import pandas as pd
import numpy as np
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

# --- Page Configuration ---
st.set_page_config(page_title="YouTube Outlier Finder", page_icon="📊", layout="wide")

# --- App Header ---
st.title("📊 YouTube Outlier Finder")
st.markdown("A free tool to detect outlier videos from a YouTube channel or search query, inspired by 1of10.com.")

# --- API & Data Functions ---

@st.cache_resource
def get_youtube_service(api_key: str):
    """Build and validate the YouTube API service object."""
    try:
        service = build("youtube", "v3", developerKey=api_key)
        service.channels().list(part="id", id="UC_x5XG1OV2P6uZZ5FSM9Ttw").execute()
        return service
    except HttpError as e:
        st.error(f"API key validation failed: {getattr(e, 'reason', str(e))}")
        return None
    except Exception as e:
        st.error(f"Unexpected validation error: {e}")
        return None

@st.cache_data(show_spinner=False)
def fetch_video_ids(_youtube, search_type: str, query: str):
    """Fetch up to 50 video IDs by channel ID or search query."""
    if search_type == "channel":
        req = _youtube.search().list(
            part="id",
            channelId=query,
            maxResults=50,
            order="date",
            type="video",
        )
    else:
        req = _youtube.search().list(
            part="id",
            q=query,
            maxResults=50,
            type="video",
            order="date",
        )
    resp = req.execute()
    return [item["id"]["videoId"] for item in resp.get("items", [])]

@st.cache_data(show_spinner=False)
def get_video_details(_youtube, video_ids):
    """Fetch snippet and statistics for a list of up to 50 videos."""
    if not video_ids:
        return []
    req = _youtube.videos().list(part="snippet,statistics", id=",".join(video_ids))
    resp = req.execute()
    return resp.get("items", [])

def analyze_video_data(videos):
    """Convert raw items to DataFrame and compute outlier flags."""
    if not videos:
        return pd.DataFrame()

    rows = []
    for v in videos:
        stats = v.get("statistics", {}) or {}
        snip = v.get("snippet", {}) or {}
        pub = snip.get("publishedAt")
        vid = v.get("id")
        if not pub or not vid or "viewCount" not in stats:
            continue

        published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        age_days = max(1, (datetime.now(timezone.utc) - published_at).days)
        views = int(stats.get("viewCount") or 0)
        likes = int(stats.get("likeCount") or 0)
        comments = int(stats.get("commentCount") or 0)

        rows.append(
            {
                "title": snip.get("title", "N/A"),
                "publish_date": published_at.date(),
                "views": views,
                "likes": likes,
                "comments": comments,
                "age_days": age_days,
                "velocity": views / age_days,
                "engagement_rate": (likes + comments) / views if views > 0 else 0.0,
                "video_id": vid,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("publish_date")
    vel = df["velocity"]
    if len(vel) > 1 and vel.std() > 0:
        df["z_score"] = (vel - vel.mean()) / vel.std()
    else:
        df["z_score"] = 0.0

    p90 = df["velocity"].quantile(0.90)
    df["is_outlier"] = (df["z_score"] > 2) | (df["velocity"] >= p90)
    return df

# --- Initialize Session State ---
if "api_key_valid" not in st.session_state:
    st.session_state.api_key_valid = False

# --- API Key Validation Flow ---

if not st.session_state.api_key_valid:
    st.warning("A YouTube Data API v3 key is required to use this tool.")
    api_key = st.text_input("Enter your YouTube API Key", type="password")
    
    if st.button("Validate Key"):
        if api_key and len(api_key) > 10:
            with st.spinner("Validating API key..."):
                yt = get_youtube_service(api_key)
                if yt:
                    st.session_state.api_key_valid = True
                    st.session_state.youtube_service = yt
                    st.success("API key is valid!")
                    st.rerun()
        else:
            st.error("Please enter a valid API key.")

# --- Main App (After Key Validation) ---

if st.session_state.api_key_valid:
    st.success("✅ API key validated. Ready to analyze videos.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        search_type_label = st.radio("Search by:", ("Channel ID", "Search Query"))
    
    with col2:
        placeholder = "e.g., UCsT0YIqwnpJCM-mx7-gSA4Q" if search_type_label == "Channel ID" else "e.g., physiotherapy tips"
        user_input = st.text_input("Enter your search:", placeholder=placeholder)
    
    if st.button("🔍 Analyze Videos", use_container_width=True):
        user_input_clean = user_input.strip() if user_input else ""
        
        if not user_input_clean:
            st.error("❌ Please enter a search term or channel ID.")
        else:
            with st.spinner("🔄 Fetching and analyzing videos..."):
                try:
                    search_type = "channel" if search_type_label == "Channel ID" else "search"
                    
                    # Fetch video IDs
                    video_ids = fetch_video_ids(st.session_state.youtube_service, search_type, user_input_clean)
                    
                    if not video_ids:
                        st.warning("⚠️ No videos found for your search. Try a different query.")
                    else:
                        # Fetch video details
                        video_items = get_video_details(st.session_state.youtube_service, video_ids)
                        
                        # Analyze
                        results_df = analyze_video_data(video_items)
                        
                        if results_df.empty:
                            st.warning("⚠️ Could not process video data. Some videos may have disabled stats.")
                        else:
                            # Display results
                            outliers = results_df[results_df["is_outlier"]]
                            
                            st.success(f"✅ Analysis complete! Found {len(results_df)} videos with {len(outliers)} outliers.")
                            
                            st.markdown("---")
                            st.subheader("📊 Analysis Results")
                            
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Videos Analyzed", len(results_df))
                            c2.metric("Outliers Detected", len(outliers))
                            c3.metric("Outlier %", f"{(len(outliers) / len(results_df) * 100):.1f}%")
                            
                            st.markdown("---")
                            st.subheader("📈 Charts")
                            
                            st.write("**View Velocity Over Time**")
                            st.line_chart(results_df.set_index("publish_date")["velocity"])
                            
                            if not outliers.empty:
                                st.write("**Top 15 Outliers by View Velocity**")
                                top_outliers = outliers.sort_values("velocity", ascending=False).head(15)
                                st.bar_chart(top_outliers.set_index("title")["velocity"])
                            
                            st.markdown("---")
                            st.subheader("📋 Detailed Video Data")
                            st.dataframe(
                                results_df[["title", "publish_date", "views", "velocity", "engagement_rate", "z_score", "is_outlier"]],
                                use_container_width=True,
                                hide_index=True
                            )
                
                except HttpError as e:
                    if getattr(e, "resp", None) and getattr(e.resp, "status", None) == 403:
                        st.error("❌ API Quota Exceeded: Your key has used its daily quota. Try again tomorrow or use a different key.")
                    else:
                        reason = getattr(e, "reason", str(e))
                        st.error(f"❌ API Error: {reason}")
                except Exception as e:
                    st.error(f"❌ Unexpected error: {str(e)}")

# --- Footer ---
st.markdown("---")
st.markdown(
    "🚀 Free tool by [**WriteWing.in**](https://writewing.in) | "
    "[Get your free YouTube API key](https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com)"
)
