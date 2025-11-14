import streamlit as st
import pandas as pd
import numpy as np
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

st.set_page_config(page_title="YouTube Outlier Finder", page_icon="📊", layout="wide")

# --- Custom CSS for Better UI ---
st.markdown("""
<style>
    .video-card {
        border: 1px solid #ddd;
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
        background: #f9f9f9;
        transition: box-shadow 0.3s ease;
    }
    .video-card.outlier {
        border-color: #ffd700;
        background: #fffbeb;
        box-shadow: 0 4px 12px rgba(255,215,0,0.4);
    }
    .watch-link {
        color: #1da1f2;
        text-decoration: none;
        font-weight: bold;
    }
    .watch-link:hover {
        text-decoration: underline;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎬 YouTube Outlier Finder")
st.markdown("Discover viral videos from any search query or channel using four powerful analysis modes.")

# --- API & Channel ID Utilities ---

@st.cache_resource
def get_youtube_service(api_key: str):
    """Build and validate YouTube API service."""
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

@st.cache_data(ttl=3600)
def get_channel_id_from_input(_youtube_service, user_input: str):
    """Resolves a channel ID from a URL, handle, or direct ID."""
    user_input = user_input.strip()
    
    # Regex to find UC, HC, or KC channel IDs
    id_match = re.search(r"(UC[a-zA-Z0-9_-]{22})", user_input)
    if id_match:
        return id_match.group(1)

    # Regex to find a handle from a URL or direct input
    handle_match = re.search(r"(@[a-zA-Z0-9_.-]+)", user_input)
    handle = handle_match.group(1) if handle_match else user_input
    
    try:
        # Search for the channel using the handle
        req = _youtube_service.search().list(part="id", q=handle, type="channel", maxResults=1)
        res = req.execute()
        if res.get("items"):
            return res["items"][0]["id"]["channelId"]
        else:
            return None
    except HttpError as e:
        st.error(f"Failed to resolve channel handle '{handle}': {e.reason}")
        return None
    except Exception as e:
        st.error(f"An error occurred while resolving handle '{handle}': {e}")
        return None


@st.cache_data(ttl=3600)
def get_channel_stats(_youtube_service, channel_ids):
    """Batch fetch statistics (subs, total views, video count) for channels."""
    if not channel_ids:
        return {}
    stats_dict = {}
    try:
        # Process in chunks of 50
        for i in range(0, len(channel_ids), 50):
            chunk = channel_ids[i:i+50]
            req = _youtube_service.channels().list(part="statistics", id=",".join(chunk))
            channels = req.execute().get("items", [])
            for ch in channels:
                stats = ch.get("statistics", {})
                stats_dict[ch["id"]] = {
                    "subscribers": int(stats.get("subscriberCount", 0)),
                    "average_views": int(stats.get("viewCount", 0)) / max(1, int(stats.get("videoCount", 1)))
                }
        return stats_dict
    except HttpError as e:
        st.warning(f"Could not fetch some channel stats: {getattr(e, 'reason', str(e))}")
        return stats_dict
    except Exception as e:
        st.error(f"An unexpected error occurred during channel stat fetching: {e}")
        return stats_dict

# --- Main Analysis Engine ---

def analyze_videos(youtube_service, search_type, query_input, view_multiplier=100, min_views=100000, avg_multiplier=5):
    try:
        resolved_channel_id = None
        if "channel" in search_type:
            resolved_channel_id = get_channel_id_from_input(youtube_service, query_input)
            if not resolved_channel_id:
                return None, None, f"❌ Could not find a valid YouTube channel for '{query_input}'. Please check the handle or URL."

        # --- Step 1: Fetch 50 videos ---
        if search_type == "channel_avg_self": # Analyze a channel against its own recent videos
            req = youtube_service.search().list(part="snippet", channelId=resolved_channel_id, maxResults=50, order="date", type="video")
        elif search_type == "channel_vs_subs": # Find a channel's most popular videos
            req = youtube_service.search().list(part="snippet", channelId=resolved_channel_id, maxResults=50, order="viewCount", type="video")
        else: # "search_vs_subs" or "search_vs_avg"
            req = youtube_service.search().list(part="snippet", q=query_input, maxResults=50, type="video", order="viewCount")
        
        search_results = req.execute().get("items", [])
        if not search_results: return None, None, "No videos found for this query."

        video_ids = [item["id"]["videoId"] for item in search_results]
        video_details = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute().get("items", [])

        # --- Step 2: Fetch all required channel stats in batches ---
        channel_ids = list(set(item["snippet"]["channelId"] for item in video_details))
        all_channel_stats = get_channel_stats(youtube_service, channel_ids)
        
        # --- Step 3: Build DataFrame ---
        rows = []
        for v in video_details:
            stats, snip = v.get("statistics", {}), v.get("snippet", {})
            channel_id = snip.get("channelId", "")
            channel_info = all_channel_stats.get(channel_id, {"subscribers": 0, "average_views": 0})
            
            rows.append({
                "video_id": v.get("id"), "title": snip.get("title", "N/A"),
                "views": int(stats.get("viewCount", 0)),
                "subscribers": channel_info["subscribers"],
                "channel_avg_views": channel_info["average_views"],
                "channel_id": channel_id,
                 "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url", f"https://img.youtube.com/vi/{v.get('id')}/mqdefault.jpg"),
            })
        df = pd.DataFrame(rows)

        # --- Step 4: Apply Outlier Logic ---
        if search_type == "search_vs_avg": # NEW: Search term vs channel average
            df = df[df["channel_avg_views"] > 0] # Filter out channels where avg couldn't be calculated
            df['outlier_score'] = df['views'] / df['channel_avg_views']
            df['is_outlier'] = df['outlier_score'] > avg_multiplier
        elif search_type == "channel_avg_self": # Channel vs its own recent average
            self_average_views = df['views'].mean()
            st.session_state.average_views = self_average_views
            df['outlier_score'] = df['views'] / max(1, self_average_views)
            df['is_outlier'] = df['outlier_score'] > avg_multiplier
        else: # Default: Views vs. Subscribers
            df = df[df['views'] >= min_views]
            df['outlier_score'] = df['views'] / df['subscribers'].apply(lambda x: max(x, 1))
            df['is_outlier'] = df['outlier_score'] > view_multiplier

        outliers_df = df[df["is_outlier"]].sort_values("outlier_score", ascending=False)
        return df, outliers_df, None

    except HttpError as e:
        return None, None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e:
        return None, None, f"An error occurred: {str(e)}"

# --- Main App UI ---
if "api_key_valid" not in st.session_state:
    st.session_state.api_key_valid = False

if not st.session_state.api_key_valid:
    # API Key input flow
    st.warning("🔑 A YouTube API v3 key is required.")
    api_key = st.text_input("Enter your YouTube API Key", type="password")
    if st.button("✅ Validate Key", use_container_width=True):
        if api_key and (yt_service := get_youtube_service(api_key)):
            st.session_state.api_key_valid = True
            st.session_state.yt = yt_service
            st.rerun()
else:
    st.success("✅ API key validated.")
    
    st.markdown("### 1. Choose Analysis Mode")
    stype_option = st.radio("Search by:", (
        "Search Term (vs. Subs)", "Search Term (vs. Channel Average)", 
        "By Channel (vs. Subs)", "By Channel (vs. Channel Average)"
    ))
    
    stype_map = {
        "Search Term (vs. Subs)": "search_vs_subs",
        "Search Term (vs. Channel Average)": "search_vs_avg",
        "By Channel (vs. Subs)": "channel_vs_subs",
        "By Channel (vs. Channel Average)": "channel_avg_self"
    }
    stype_val = stype_map[stype_option]

    st.markdown("### 2. Set Parameters")
    col1, col2 = st.columns(2)
    
    with col1:
        if "channel" in stype_val:
            query = st.text_input("Enter Channel URL or Handle", placeholder="e.g., @mkbhd or https://youtube.com/@mkbhd")
        else:
            query = st.text_input("Search Term", placeholder="e.g., beginner guitar lesson")
    
    with col2:
        if "avg" in stype_val:
            avg_multiplier = st.slider("Outlier Multiplier (x Average)", 2, 50, 10, help="Flags videos with views > (Multiplier * Average Views).")
            view_multiplier, min_views_threshold = 100, 100000 # Defaults
        else:
            view_multiplier = st.slider("View-to-Subscriber Multiplier", 10, 1000, 100, help="Flags videos with views > (Multiplier * Subscribers).")
            min_views_threshold = st.slider("Minimum Views", 10000, 1000000, 50000, 10000)
            avg_multiplier = 10 # Default

    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        if not query.strip():
            st.error("❌ Please enter a value.")
        else:
            with st.spinner("🔄 Analyzing..."):
                df, outliers_df, err = analyze_videos(st.session_state.yt, stype_val, query, view_multiplier, min_views_threshold, avg_multiplier)
                
                if err: st.error(err)
                elif df is None or df.empty: st.warning("No videos found matching your criteria.")
                else:
                    st.markdown("---")
                    st.markdown("### 📊 Analysis Results")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Videos Analyzed", len(df))
                    c2.metric("Outliers Found", len(outliers_df))
                    c3.metric("Outlier %", f"{(len(outliers_df)/len(df)*100):.1f}%" if not df.empty else "0%")

                    if not outliers_df.empty:
                        st.markdown("### ⭐ True Outlier Videos")
                        for _, row in outliers_df.iterrows():
                            youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                            score_label = "vs Chan. Avg" if "avg" in stype_val else "vs Subs"
                            st.markdown(f"""
                            <div class="video-card outlier">
                                <div style="display: flex; gap: 15px;">
                                    <a href="{youtube_url}" target="_blank"><img src="{row['thumbnail']}" style="width: 120px; height: 90px; border-radius: 8px; object-fit: cover;"></a>
                                    <div style="flex: 1;">
                                        <h4 style="margin: 0 0 5px 0;"><a href="{youtube_url}" target="_blank" class="watch-link">{row['title'][:70]}...</a></h4>
                                        <p style="font-size:14px; margin:0;">
                                            <b>Views:</b> {int(row['views']):,} | <b>Score ({score_label}):</b> {row['outlier_score']:.0f}x
                                        </p>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No true outliers found with the current settings.")

# --- Footer ---
st.markdown("---")
st.markdown("🚀 **Free tool by [WriteWing.in](https://writewing.in)**")

