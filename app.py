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
    .outlier-title {
        font-size: 18px;
        font-weight: bold;
        margin-bottom: 10px;
        line-height: 1.4;
    }
    .outlier-stats {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
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
        font-size: 20px;
        font-weight: bold;
    }
    .stat-label {
        font-size: 12px;
        opacity: 0.9;
    }
    .thumbnail-container {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 20px;
        margin: 20px 0;
    }
    .thumbnail-card {
        text-align: center;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        transition: transform 0.3s;
    }
    .thumbnail-card:hover {
        transform: scale(1.05);
    }
    .thumbnail-img {
        width: 100%;
        aspect-ratio: 16/9;
        object-fit: cover;
    }
    .thumbnail-info {
        padding: 12px;
        background: #f0f2f6;
    }
    .z-score-badge {
        display: inline-block;
        background: #ff6b6b;
        color: white;
        padding: 6px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 14px;
        margin-top: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎬 YouTube Outlier Finder")
st.markdown("Discover viral outlier videos from any YouTube channel or search query, inspired by 1of10.com.")

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

# --- Outlier Analysis (Strict Filtering) ---

def analyze_videos(youtube_service, search_type, query):
    """Fetch, analyze with stricter outlier detection."""
    try:
        # Fetch video IDs
        if search_type == "channel":
            req = youtube_service.search().list(
                part="id",
                channelId=query,
                maxResults=50,
                order="date",
                type="video"
            )
        else:
            req = youtube_service.search().list(
                part="id",
                q=query,
                maxResults=50,
                type="video",
                order="date"
            )
        video_ids = [item["id"]["videoId"] for item in req.execute().get("items", [])]
        
        if not video_ids:
            return None, "No videos found."
        
        # Fetch details
        req = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids))
        videos = req.execute().get("items", [])
        
        # Analyze with minimum thresholds
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
            
            # SKIP videos with insufficient data (filters noise)
            if views < 50 or age_days < 1:
                continue
            
            engagement_rate = (likes + comments) / views if views > 0 else 0
            thumbnail = snip.get("thumbnails", {}).get("high", {}).get("url", "")
            
            rows.append({
                "title": snip.get("title", "N/A"),
                "publish_date": pub_date.date(),
                "views": views,
                "velocity": views / age_days,
                "engagement_rate": engagement_rate,
                "video_id": v.get("id"),
                "thumbnail": thumbnail,
                "likes": likes,
                "comments": comments,
                "age_days": age_days,
            })
        
        if not rows:
            return None, "No analyzable data (require min 50 views)."
        
        df = pd.DataFrame(rows).sort_values("publish_date")
        vel = df["velocity"]
        
        # Z-score calculation
        if len(vel) > 1 and vel.std() > 0:
            df["z_score"] = (vel - vel.mean()) / vel.std()
        else:
            df["z_score"] = 0
        
        # STRICTER outlier detection:
        # - z_score > 2.5 (strict deviation)
        # - OR velocity in top 5% (selective)
        # - AND engagement_rate > 0.5% (meaningful interaction)
        velocity_top_5_percentile = df["velocity"].quantile(0.95)
        df["is_outlier"] = (
            (df["z_score"] > 2.5) & (df["engagement_rate"] > 0.005)
        ) | (
            (df["velocity"] >= velocity_top_5_percentile) & (df["engagement_rate"] > 0.005)
        )
        
        return df, None
    except HttpError as e:
        if getattr(e, "resp", None) and getattr(e.resp, "status", None) == 403:
            return None, "❌ Quota exceeded. Try tomorrow."
        return None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e:
        return None, f"Error: {str(e)}"

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
    col1, col2 = st.columns(2)
    
    with col1:
        stype = st.radio("Search by:", ("🔴 Search Term", "⚪ By Channel"), horizontal=False)
        stype_val = "search" if stype == "🔴 Search Term" else "channel"
    
    with col2:
        if stype == "🔴 Search Term":
            query = st.text_input("Search Term", placeholder="e.g., physiotherapy, tech reviews, cooking...")
        else:
            query = st.text_input("Channel ID", placeholder="e.g., UCsT0YIqwnpJCM-mx7-gSA4Q")
    
    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        if not query or not query.strip():
            st.error("❌ Please enter a search term or channel ID.")
        else:
            with st.spinner("🔄 Fetching and analyzing videos..."):
                df, err = analyze_videos(st.session_state.yt, stype_val, query.strip())
                if err:
                    st.error(err)
                else:
                    outliers = df[df["is_outlier"]].sort_values("z_score", ascending=False)
                    
                    # --- Top Stats ---
                    st.markdown("### 📊 Analysis Results")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Videos", len(df), delta=None)
                    c2.metric("Outliers Found", len(outliers), delta=None)
                    c3.metric("Outlier %", f"{len(outliers)/len(df)*100:.1f}%", delta=None)
                    c4.metric("Avg Velocity", f"{df['velocity'].mean():.0f}", delta=None)
                    
                    st.markdown("---")
                    
                    # --- Top Outliers Thumbnails ---
                    if not outliers.empty:
                        st.markdown("### ⭐ Top 3 Outlier Videos")
                        top3 = outliers.head(3)
                        
                        cols = st.columns(3)
                        for idx, (_, row) in enumerate(top3.iterrows()):
                            with cols[idx]:
                                if row["thumbnail"]:
                                    st.image(row["thumbnail"], use_container_width=True)
                                st.markdown(f"""
                                <div class="outlier-card">
                                    <div class="outlier-title">{row['title'][:50]}...</div>
                                    <div class="outlier-stats">
                                        <div class="stat-box">
                                            <div class="stat-value">{int(row['views']):,}</div>
                                            <div class="stat-label">Views</div>
                                        </div>
                                        <div class="stat-box">
                                            <div class="stat-value">{row['velocity']:.0f}</div>
                                            <div class="stat-label">Velocity</div>
                                        </div>
                                        <div class="stat-box">
                                            <div class="stat-value">{row['z_score']:.2f}</div>
                                            <div class="stat-label">Z-Score</div>
                                        </div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                    else:
                        st.info("No outliers detected with strict filtering criteria.")
                    
                    st.markdown("---")
                    
                    # --- Charts ---
                    st.markdown("### 📈 Visualizations")
                    c1, c2 = st.columns(2)
                    
                    with c1:
                        st.write("**View Velocity Over Time**")
                        st.line_chart(df.set_index("publish_date")["velocity"])
                    
                    with c2:
                        if not outliers.empty:
                            st.write("**Top 10 Outliers by Z-Score**")
                            top_10 = outliers.head(10)[["title", "z_score"]].copy()
                            top_10["title"] = top_10["title"].str[:30] + "..."
                            st.bar_chart(top_10.set_index("title")["z_score"])
                    
                    st.markdown("---")
                    
                    # --- Detailed Table ---
                    st.markdown("### 📋 Detailed Video Data")
                    display_df = df[["title", "publish_date", "views", "velocity", "engagement_rate", "z_score", "is_outlier"]].copy()
                    display_df["velocity"] = display_df["velocity"].round(2)
                    display_df["engagement_rate"] = (display_df["engagement_rate"] * 100).round(2).astype(str) + "%"
                    display_df["z_score"] = display_df["z_score"].round(2)
                    display_df = display_df.sort_values("z_score", ascending=False)
                    
                    st.dataframe(display_df, use_container_width=True, hide_index=True)

# --- Footer ---
st.markdown("---")
st.markdown(
    "🚀 **Free tool by [WriteWing.in](https://writewing.in)** | "
    "[Get your free YouTube API key](https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com) | "
    "[Learn SEO & content strategy](https://writewing.in)"
)
