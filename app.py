import streamlit as st
import pandas as pd
import numpy as np
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
st.markdown("Discover viral videos from any search query or channel using three powerful analysis modes.")

# --- API Service ---
@st.cache_resource
def get_youtube_service(api_key: str):
    """Build and validate YouTube API service."""
    try:
        service = build("youtube", "v3", developerKey=api_key)
        # A simple, low-quota call to validate the key
        service.channels().list(part="id", id="UC_x5XG1OV2P6uZZ5FSM9Ttw").execute()
        return service
    except HttpError as e:
        st.error(f"API key validation failed: {getattr(e, 'reason', str(e))}")
        return None
    except Exception as e:
        st.error(f"Unexpected validation error: {e}")
        return None

# --- Fetch Channel Stats (Batch) ---
@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_channel_stats(_youtube_service, channel_ids):
    """Batch fetch subscriber counts for channels."""
    if not channel_ids:
        return {}
    try:
        req = _youtube_service.channels().list(part="statistics", id=",".join(channel_ids))
        channels = req.execute().get("items", [])
        return {ch["id"]: int(ch.get("statistics", {}).get("subscriberCount", 0)) for ch in channels}
    except HttpError as e:
        st.warning(f"Channel stats fetch error: {getattr(e, 'reason', str(e))}")
        return {}
    except Exception as e:
        st.error(f"Unexpected channel stats error: {e}")
        return {}

# --- Outlier Analysis Engine ---
def analyze_videos(youtube_service, search_type, query, view_multiplier=100, min_views=100000, avg_multiplier=5):
    """
    Fetch 50 videos and analyze for outliers based on one of three methods:
    1. Search Term (vs. Subs): High views, low subs for a keyword.
    2. By Channel (vs. Subs): High views, low subs for a specific channel.
    3. By Channel (vs. Channel Average): Views are high compared to the channel's own average.
    """
    try:
        # --- Step 1: Fetch 50 videos based on search type ---
        if search_type == "channel_avg":
            # For channel average, we need the most RECENT videos to establish a baseline
            req = youtube_service.search().list(part="snippet", channelId=query, maxResults=50, order="date", type="video")
        elif search_type == "channel":
            # **FIXED**: Order by viewCount to find a channel's most popular videos
            req = youtube_service.search().list(part="snippet", channelId=query, maxResults=50, order="viewCount", type="video")
        else: # search_type == "search"
            # For keyword search, order by viewCount to find popular videos
            req = youtube_service.search().list(part="snippet", q=query, maxResults=50, type="video", order="viewCount")
        
        search_results = req.execute().get("items", [])
        if not search_results:
            return None, None, "No videos found for this query."

        video_ids = [item["id"]["videoId"] for item in search_results]
        search_thumbnails = {item["id"]["videoId"]: item.get("snippet", {}).get("thumbnails", {}).get("medium", {}).get("url", "") for item in search_results}

        # --- Step 2: Fetch detailed stats for all videos and channels ---
        channel_ids = list(set(item["snippet"]["channelId"] for item in search_results))
        channel_subs = get_channel_stats(youtube_service, channel_ids)
        video_details = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute().get("items", [])

        # --- Step 3: Pre-process and build the analysis DataFrame ---
        rows = []
        for v in video_details:
            stats = v.get("statistics", {}) or {}
            snip = v.get("snippet", {}) or {}
            if "viewCount" not in stats or not snip.get("publishedAt"):
                continue
            
            pub_date = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            age_days = max(1, (datetime.now(timezone.utc) - pub_date).days)
            views = int(stats.get("viewCount", 0))
            
            # Filter by minimum views threshold early
            if search_type != "channel_avg" and views < min_views:
                continue

            rows.append({
                "video_id": v.get("id"), "title": snip.get("title", "N/A"), "publish_date": pub_date.date(),
                "views": views, "likes": int(stats.get("likeCount", 0)), "comments": int(stats.get("commentCount", 0)),
                "age_days": age_days, "velocity": views / age_days,
                "channel_id": snip.get("channelId", ""), "subscribers": channel_subs.get(snip.get("channelId", ""), 0),
                "thumbnail": search_thumbnails.get(v.get("id"), snip.get("thumbnails", {}).get("medium", {}).get("url", f"https://img.youtube.com/vi/{v.get('id')}/mqdefault.jpg")),
                "engagement_rate": (int(stats.get("likeCount", 0)) + int(stats.get("commentCount", 0))) / views if views > 0 else 0
            })
        
        if not rows:
            return None, None, "No videos meet the minimum view criteria."
        df = pd.DataFrame(rows)

        # --- Step 4: Apply the selected outlier logic ---
        if search_type == "channel_avg":
            # New Method: Outlier based on channel's own average
            average_views = df['views'].mean()
            st.session_state.average_views = average_views # Store for display
            df['is_outlier'] = df['views'] > (average_views * avg_multiplier)
            df['outlier_score'] = df['views'] / max(1, average_views)
            df['multiplier_ratio'] = df['outlier_score'] # Use the same column for sorting
        else:
            # Original Method: Outlier based on views vs. subscriber count
            df['multiplier_ratio'] = df['views'] / df['subscribers'].apply(lambda x: max(x, 1))
            df['is_outlier'] = (df['multiplier_ratio'] > view_multiplier) & (df['views'] >= min_views)
            df['outlier_score'] = df['multiplier_ratio']

        outliers_df = df[df["is_outlier"]].sort_values("outlier_score", ascending=False)
        return df, outliers_df, None

    except HttpError as e:
        if getattr(e, "resp", None) and getattr(e.resp, "status", None) == 403:
            return None, None, "❌ Quota exceeded. Please try again tomorrow or use a different API key."
        return None, None, f"An API error occurred: {getattr(e, 'reason', str(e))}"
    except Exception as e:
        return None, None, f"An unexpected error occurred: {str(e)}"

# --- Initialize Session State ---
if "api_key_valid" not in st.session_state:
    st.session_state.api_key_valid = False
if "average_views" not in st.session_state:
    st.session_state.average_views = 0

# --- Main App Flow ---
if not st.session_state.api_key_valid:
    st.warning("🔑 A YouTube API v3 key is required to use this tool.")
    api_key = st.text_input("Enter your YouTube API Key", type="password", placeholder="AIza...")
    if st.button("✅ Validate Key", use_container_width=True):
        if api_key:
            with st.spinner("Validating API key..."):
                yt_service = get_youtube_service(api_key)
                if yt_service:
                    st.session_state.api_key_valid = True
                    st.session_state.yt = yt_service
                    st.success("API key validated! The app is now ready.")
                    st.rerun()
        else:
            st.error("Please enter a valid API key.")
else:
    st.success("✅ API key validated. Configure your analysis below.")
    
    st.markdown("### 1. Choose Analysis Mode")
    stype_option = st.radio(
        "Search by:",
        ("🔴 Search Term (vs. Subs)", "⚪ By Channel (vs. Subs)", "📈 By Channel (vs. Channel Average)"),
        horizontal=True, help="""
        - **Search Term (vs. Subs):** Finds high-view videos from channels with low subscribers for a search query.
        - **By Channel (vs. Subs):** Finds high-view videos relative to subscriber count for a specific channel.
        - **By Channel (vs. Channel Avg):** Finds videos with views significantly above the channel's recent average.
        """
    )
    
    stype_map = {
        "🔴 Search Term (vs. Subs)": "search",
        "⚪ By Channel (vs. Subs)": "channel",
        "📈 By Channel (vs. Channel Average)": "channel_avg"
    }
    stype_val = stype_map[stype_option]

    st.markdown("### 2. Set Parameters")
    col1, col2 = st.columns(2)
    with col1:
        if stype_val in ["channel", "channel_avg"]:
            query = st.text_input("Channel ID", placeholder="e.g., UCsT0YIqwnpJCM-mx7-gSA4Q")
        else:
            query = st.text_input("Search Term", placeholder="e.g., ai tutorial for beginners")
    
    # Conditional sliders based on analysis mode
    with col2:
        if stype_val == "channel_avg":
            avg_multiplier = st.slider("Average View Multiplier (x Avg)", min_value=2, max_value=50, value=5, help="Outlier if views > this number x channel's average views.")
            view_multiplier, min_views_threshold = 100, 100000 # Set default values for other params
        else:
            view_multiplier = st.slider("View-to-Subscriber Multiplier (x Subs)", min_value=10, max_value=1000, value=100, help="Outlier if views > this number x channel subscribers.")
            min_views_threshold = st.slider("Minimum View Threshold", min_value=10000, max_value=1000000, value=100000, step=10000, help="Videos with fewer views than this will be ignored.")
            avg_multiplier = 5 # Set default

    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        if not query or not query.strip():
            st.error("❌ Please enter a search term or channel ID.")
        else:
            with st.spinner("🔄 Fetching videos, channel stats, and analyzing... This may take a moment."):
                df, outliers_df, err = analyze_videos(st.session_state.yt, stype_val, query.strip(), view_multiplier, min_views_threshold, avg_multiplier)
                
                if err:
                    st.error(err)
                elif df is None or df.empty:
                    st.warning("No videos were found or processed based on your criteria.")
                else:
                    st.markdown("---")
                    st.markdown("### 📊 Analysis Results")
                    
                    # Display metrics based on analysis type
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Videos Analyzed", len(df))
                    c2.metric("True Outliers Found", len(outliers_df))
                    c3.metric("Outlier Percentage", f"{len(outliers_df)/len(df)*100:.1f}%" if len(df) > 0 else "0%")
                    if stype_val == 'channel_avg':
                        c4.metric("Channel Avg Views", f"{st.session_state.average_views:,.0f}")
                    else:
                        c4.metric("Avg. View/Sub Ratio", f"{df['multiplier_ratio'].mean():.0f}x")

                    if not outliers_df.empty:
                        st.markdown("### ⭐ True Outlier Videos")
                        for _, row in outliers_df.iterrows():
                            youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                            score_label = "vs. Avg" if stype_val == 'channel_avg' else "vs. Subs"
                            st.markdown(f"""
                            <div class="video-card outlier">
                                <div style="display: flex; gap: 15px;">
                                    <a href="{youtube_url}" target="_blank"><img src="{row['thumbnail']}" style="width: 120px; height: 90px; border-radius: 8px; object-fit: cover;"></a>
                                    <div style="flex: 1;">
                                        <h4 style="margin: 0 0 5px 0;"><a href="{youtube_url}" target="_blank" class="watch-link">{row['title'][:70]}...</a></h4>
                                        <p style="font-size:14px; margin:0;">
                                            <b>Views:</b> {int(row['views']):,} | <b>Subs:</b> {int(row['subscribers']):,} | <b>Score ({score_label}):</b> {row['outlier_score']:.0f}x
                                            <br><b>Velocity:</b> {row['velocity']:.0f} views/day | <b>Published:</b> {row['publish_date']}
                                        </p>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No true outliers found with the current settings. Try adjusting the multipliers or view thresholds.")
                    
                    st.markdown("---")
                    
                    # --- All Fetched Videos Display ---
                    st.markdown("### 📹 All Videos Fetched (Sorted by Outlier Score)")
                    for _, row in df.sort_values("outlier_score", ascending=False).iterrows():
                        youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                        is_outlier_class = "outlier" if row["is_outlier"] else ""
                        st.markdown(f"""
                        <div class="video-card {is_outlier_class}" style="font-size: 14px;">
                            <strong><a href="{youtube_url}" target="_blank">{row['title'][:80]}...</a></strong>
                            <a href="{youtube_url}" target="_blank" class="watch-link" style="float: right;">▶ Watch</a><br>
                            Views: {int(row['views']):,} | Subs: {int(row['subscribers']):,} | Score: {row['outlier_score']:.1f}x | 
                            {'<span style="color:green; font-weight:bold;">▲ OUTLIER</span>' if row['is_outlier'] else 'Normal'}
                        </div>
                        """, unsafe_allow_html=True)

# --- Footer ---
st.markdown("---")
st.markdown(
    "🚀 **Free tool by [WriteWing.in](https://writewing.in)** | "
    "[Get your free YouTube API key](https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com) | "
    "Built with Streamlit & Python"
)
