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
    .outlier-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 20px;
        color: white;
        margin: 15px 0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .outlier-card.outlier-highlight {
        background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
        color: #333;
    }
    .outlier-title {
        font-size: 18px;
        font-weight: bold;
        margin-bottom: 10px;
        line-height: 1.4;
    }
    .outlier-stats {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr 1fr;
        gap: 15px;
        margin-top: 15px;
        font-size: 14px;
    }
    .stat-box {
        background: rgba(255,255,255,0.2);
        padding: 10px;
        border-radius: 8px;
        text-align: center;
    }
    .stat-value {
        font-size: 18px;
        font-weight: bold;
    }
    .stat-label {
        font-size: 12px;
        opacity: 0.9;
    }
    .video-card {
        border: 1px solid #ddd;
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
        background: #f9f9f9;
    }
    .video-card.outlier {
        border-color: #ffd700;
        background: #fff9e6;
        box-shadow: 0 2px 8px rgba(255,215,0,0.3);
    }
    .thumbnail-link {
        text-decoration: none;
        color: inherit;
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
st.markdown("Discover viral outlier videos from small channels (low subs, high views) for any search query or channel, inspired by 1of10.com.")

# --- API Service ---

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

# --- Fetch Channel Stats (Batch) ---

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_channel_stats(youtube_service, channel_ids):
    """Batch fetch subscriber counts for channels."""
    if not channel_ids:
        return {}
    try:
        # Batch up to 50 channel IDs
        req = youtube_service.channels().list(part="statistics", id=",".join(channel_ids))
        channels = req.execute().get("items", [])
        return {ch["id"]: int(ch.get("statistics", {}).get("subscriberCount", 0)) for ch in channels}
    except HttpError as e:
        st.warning(f"Channel stats fetch error: {getattr(e, 'reason', str(e))}")
        return {}
    except Exception as e:
        st.error(f"Unexpected channel stats error: {e}")
        return {}

# --- Outlier Analysis (New Criteria: High Views vs Low Subs) ---

def analyze_videos(youtube_service, search_type, query, view_multiplier=100, min_views=100000):
    """Fetch 50 videos, analyze for outliers: views > multiplier * subs, min views threshold."""
    try:
        # Fetch video IDs with snippets
        if search_type == "channel":
            req = youtube_service.search().list(
                part="snippet",
                channelId=query,
                maxResults=50,
                order="date",
                type="video"
            )
        else:
            req = youtube_service.search().list(
                part="snippet",
                q=query,
                maxResults=50,
                type="video",
                order="viewCount"  # Order by views descending for better outlier potential
            )
        search_results = req.execute().get("items", [])
        
        if not search_results:
            return None, None, "No videos found."
        
        # Extract unique channel IDs and video details
        channel_ids = list(set(item["snippet"]["channelId"] for item in search_results))
        video_ids = [item["id"]["videoId"] for item in search_results]
        search_thumbnails = {item["id"]["videoId"]: item.get("snippet", {}).get("thumbnails", {}).get("medium", {}).get("url", "") for item in search_results}
        
        # Fetch channel subscriber counts
        channel_subs = get_channel_stats(youtube_service, channel_ids)
        
        # Fetch detailed video stats
        req = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids))
        videos = req.execute().get("items", [])
        
        # Analyze
        rows = []
        for v in videos:
            stats = v.get("statistics", {}) or {}
            snip = v.get("snippet", {}) or {}
            if "viewCount" not in stats or not snip.get("publishedAt"):
                continue
            
            pub_date = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            age_days = max(1, (datetime.now(timezone.utc) - pub_date).days)
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            channel_id = snip.get("channelId", "")
            subs = channel_subs.get(channel_id, 0)  # 0 if hidden/unavailable
            
            # Filter: Minimum views threshold
            if views < min_views:
                continue
            
            engagement_rate = (likes + comments) / views if views > 0 else 0
            vid_id = v.get("id")
            # Thumbnail fallback
            thumbnail = search_thumbnails.get(vid_id, snip.get("thumbnails", {}).get("medium", {}).get("url", ""))
            if not thumbnail:
                thumbnail = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"  # Medium quality for speed
            
            # Outlier score: Views multiplier vs subs
            multiplier_ratio = views / max(subs, 1)  # Avoid division by zero
            is_outlier = multiplier_ratio > view_multiplier
            outlier_score = multiplier_ratio  # For sorting
            
            rows.append({
                "title": snip.get("title", "N/A"),
                "publish_date": pub_date.date(),
                "views": views,
                "velocity": views / age_days,
                "engagement_rate": engagement_rate,
                "subscribers": subs,
                "multiplier_ratio": multiplier_ratio,
                "outlier_score": outlier_score,
                "is_outlier": is_outlier,
                "video_id": vid_id,
                "thumbnail": thumbnail,
                "channel_id": channel_id,
                "likes": likes,
                "comments": comments,
                "age_days": age_days,
            })
        
        if not rows:
            return None, None, "No videos meet the criteria (high views from small channels)."
        
        df = pd.DataFrame(rows)
        outliers_df = df[df["is_outlier"]].sort_values("outlier_score", ascending=False)
        
        return df, outliers_df, None
    except HttpError as e:
        if getattr(e, "resp", None) and getattr(e.resp, "status", None) == 403:
            return None, None, "❌ Quota exceeded. Try tomorrow."
        return None, None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e:
        return None, None, f"Error: {str(e)}"

# --- Initialize Session State ---

if "api_key_valid" not in st.session_state:
    st.session_state.api_key_valid = False

# --- API Key Validation Flow ---

if not st.session_state.api_key_valid:
    st.warning("🔑 YouTube API v3 key required to use this tool.")
    api_key = st.text_input("Enter your YouTube API Key", type="password", placeholder="AIza...")
    if st.button("✅ Validate Key", use_container_width=True):
        if api_key:
            with st.spinner("Validating..."):
                yt = get_youtube_service(api_key)
                if yt:
                    st.session_state.api_key_valid = True
                    st.session_state.yt = yt
                    st.success("API key validated!")
                    st.rerun()
        else:
            st.error("Please enter an API key.")
else:
    st.success("✅ API key validated. Ready to analyze.")
    
    # --- Analysis Configuration ---
    st.markdown("### Analysis Configuration")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        stype = st.radio("Search by:", ("🔴 Search Term", "⚪ By Channel"), horizontal=False)
        stype_val = "search" if stype == "🔴 Search Term" else "channel"
    
    with col2:
        if stype == "🔴 Search Term":
            query = st.text_input("Search Term", placeholder="e.g., physiotherapy, tech reviews")
        else:
            query = st.text_input("Channel ID", placeholder="e.g., UCsT0YIqwnpJCM-mx7-gSA4Q")
        
        view_multiplier = st.slider("View Multiplier (x Subs)", min_value=10, max_value=1000, value=100, help="Outlier if views > this x channel subs")
        min_views_threshold = st.slider("Min Views", min_value=10000, max_value=1000000, value=100000, help="Absolute min views for consideration")
    
    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        if not query or not query.strip():
            st.error("❌ Please enter a search term or channel ID.")
        else:
            with st.spinner("🔄 Fetching 50 videos, channel stats, and analyzing..."):
                df, outliers_df, err = analyze_videos(st.session_state.yt, stype_val, query.strip(), view_multiplier, min_views_threshold)
                if err:
                    st.error(err)
                else:
                    # --- Top Stats ---
                    st.markdown("### 📊 Analysis Results")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Videos (50 fetched)", len(df), delta=None)
                    c2.metric("True Outliers", len(outliers_df), delta=None)
                    c3.metric("Outlier %", f"{len(outliers_df)/len(df)*100:.1f}%", delta=None)
                    c4.metric("Avg Multiplier", f"{df['multiplier_ratio'].mean():.0f}x", delta=None)
                    
                    st.markdown("---")
                    
                    # --- All Outlier Videos (Highlighted Cards) ---
                    if not outliers_df.empty:
                        st.markdown("### ⭐ True Outlier Videos (Small Channels, High Views)")
                        for _, row in outliers_df.iterrows():
                            youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                            is_outlier_class = "outlier" if row["is_outlier"] else ""
                            st.markdown(f"""
                            <div class="video-card {is_outlier_class}">
                                <div style="display: flex; gap: 15px;">
                                    <a href="{youtube_url}" target="_blank" class="thumbnail-link">
                                        <img src="{row['thumbnail']}" style="width: 120px; height: 90px; border-radius: 8px; object-fit: cover;">
                                    </a>
                                    <div style="flex: 1;">
                                        <h4 style="margin: 0 0 5px 0;">
                                            <a href="{youtube_url}" target="_blank" style="color: #1da1f2; text-decoration: none; font-weight: bold;">{row['title'][:60]}...</a>
                                        </h4>
                                        <p><strong>Views:</strong> {int(row['views']):,} | <strong>Subs:</strong> {row['subscribers']:,} | <strong>Multiplier:</strong> {row['multiplier_ratio']:.0f}x</p>
                                        <p><strong>Velocity:</strong> {row['velocity']:.0f}/day | <strong>Engagement:</strong> {row['engagement_rate']*100:.1f}%</p>
                                        <a href="{youtube_url}" target="_blank" class="watch-link">▶ Watch on YouTube →</a>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No true outliers found (videos with views 100x+ channel subs and >100k views). Try adjusting thresholds.")
                    
                    st.markdown("---")
                    
                    # --- All 50 Videos (with Hyperlinks) ---
                    st.markdown("### 📹 All 50 Videos Fetched")
                    st.markdown(f"**Showing all videos sorted by outlier score.** Non-outliers are from larger channels or below thresholds.")
                    for _, row in df.sort_values("outlier_score", ascending=False).iterrows():
                        youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                        is_outlier_class = "outlier" if row["is_outlier"] else ""
                        st.markdown(f"""
                        <div class="video-card {is_outlier_class}" style="font-size: 14px;">
                            <strong>{row['title'][:80]}...</strong> 
                            <a href="{youtube_url}" target="_blank" class="watch-link" style="float: right;">▶ Watch</a><br>
                            Views: {int(row['views']):,} | Subs: {row['subscribers']:,} | Multiplier: {row['multiplier_ratio']:.0f}x | 
                            {'🟡 OUTLIER' if row['is_outlier'] else '⚪ Normal'}
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    # --- Charts ---
                    st.markdown("### 📈 Visualizations")
                    c1, c2 = st.columns(2)
                    
                    with c1:
                        st.write("**Views vs Subscriber Multiplier**")
                        chart_data = df[["views", "multiplier_ratio"]].head(20)  # Top 20 for clarity
                        st.scatter_chart(chart_data, x="multiplier_ratio", y="views")
                    
                    with c2:
                        st.write("**Outlier Scores (Top Videos)**")
                        if not outliers_df.empty:
                            top_outliers = outliers_df.head(10)[["title", "outlier_score"]].copy()
                            top_outliers["title"] = top_outliers["title"].str[:30] + "..."
                            st.bar_chart(top_outliers.set_index("title")["outlier_score"])
                    
                    st.markdown("---")
                    
                    # --- Detailed Table (with Hyperlinked Titles) ---
                    st.markdown("### 📋 Detailed Data")
                    display_df = df[["title", "publish_date", "views", "subscribers", "multiplier_ratio", "velocity", "engagement_rate", "is_outlier"]].copy()
                    display_df["velocity"] = display_df["velocity"].round(2)
                    display_df["engagement_rate"] = (display_df["engagement_rate"] * 100).round(2).astype(str) + "%"
                    display_df["multiplier_ratio"] = display_df["multiplier_ratio"].round(1)
                    display_df = display_df.sort_values("outlier_score", ascending=False)
                    
                    # Render table with hyperlinked titles
                    for _, row in display_df.iterrows():
                        youtube_url = f"https://www.youtube.com/watch?v={row['video_id']}"
                        outlier_badge = "🟡 OUTLIER" if row["is_outlier"] else "⚪ Normal"
                        st.markdown(f"""
                        <div style="border: 1px solid #eee; padding: 10px; margin: 5px 0; border-radius: 5px;">
                            <strong><a href="{youtube_url}" target="_blank" style="color: #1da1f2;">{row['title'][:60]}...</a></strong> | 
                            {outlier_badge} | Views: {int(row['views']):,} | Subs: {int(row['subscribers']):,} | 
                            Multiplier: {row['multiplier_ratio']}x | Velocity: {row['velocity']}
                        </div>
                        """, unsafe_allow_html=True)

# --- Footer ---
st.markdown("---")
st.markdown(
    "🚀 **Free tool by [WriteWing.in](https://writewing.in)** | "
    "[Get your free YouTube API key](https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com) | "
    "[Learn SEO & content strategy](https://writewing.in)"
)
