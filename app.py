import streamlit as st
import pandas as pd
import numpy as np
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

st.set_page_config(page_title="YouTube Outlier Finder", layout="wide", initial_sidebar_state="collapsed")

# --- Custom CSS for Dark Theme & Professional UI ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Base dark theme colors */
    body {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* Main container */
    .main .block-container {
        padding: 2rem 3rem;
    }

    /* Titles and headers */
    h1, h2, h3 {
        font-weight: 700;
        color: #FFFFFF;
    }

    /* Configuration Box */
    .config-box {
        background-color: #161A25;
        border: 1px solid #303742;
        border-radius: 12px;
        padding: 2rem;
        margin-bottom: 2rem;
    }
    
    /* Metric Cards */
    .metric-card {
        background-color: #161A25;
        border: 1px solid #303742;
        border-radius: 12px;
        padding: 1.5rem;
        text-align: center;
    }
    .metric-card .metric-label {
        font-size: 1rem;
        color: #A0AEC0;
    }
    .metric-card .metric-value {
        font-size: 2.25rem;
        font-weight: 700;
        color: #FFFFFF;
    }
    
    /* Dataframe styling */
    .stDataFrame {
        border: 1px solid #303742;
        border-radius: 8px;
    }
    
    /* Primary button style */
    .stButton>button {
        border-radius: 8px;
        background-color: #D6336C;
        color: white;
        font-weight: 600;
        border: none;
    }
    .stButton>button:hover {
        background-color: #C2255C;
        color: white;
    }

</style>
""", unsafe_allow_html=True)


# --- API & UTILITY FUNCTIONS ---
@st.cache_resource
def get_youtube_service(api_key: str):
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
    user_input = user_input.strip()
    id_match = re.search(r"(UC[a-zA-Z0-9_-]{22})", user_input)
    if id_match: return id_match.group(1)
    
    handle_match = re.search(r"(@[a-zA-Z0-9_.-]+)", user_input)
    handle = handle_match.group(1) if handle_match else f"@{user_input.split('/')[-1]}"
    
    try:
        req = _youtube_service.search().list(part="id", q=handle, type="channel", maxResults=1)
        res = req.execute()
        return res["items"][0]["id"]["channelId"] if res.get("items") else None
    except:
        return None

@st.cache_data(ttl=3600)
def get_channel_stats(_youtube_service, channel_ids):
    stats_dict = {}
    try:
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
    except:
        return stats_dict

# --- CORE ANALYSIS ENGINE (ENHANCED) ---
def analyze_videos(youtube_service, search_type, query_input, view_multiplier=100, min_views=50000, avg_multiplier=10):
    try:
        resolved_channel_id = None
        if "channel" in search_type:
            resolved_channel_id = get_channel_id_from_input(youtube_service, query_input)
            if not resolved_channel_id:
                return None, None, f"❌ Could not find a valid YouTube channel for '{query_input}'."

        order = "date" if search_type == "channel_avg_self" else "viewCount"
        params = {"part": "snippet", "maxResults": 50, "type": "video", "order": order}
        if "channel" in search_type:
            params["channelId"] = resolved_channel_id
        else:
            params["q"] = query_input
        
        search_results = youtube_service.search().list(**params).execute().get("items", [])
        if not search_results: return None, None, "No videos found."

        video_ids = [item["id"]["videoId"] for item in search_results]
        video_details = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute().get("items", [])
        
        channel_ids = list(set(item["snippet"]["channelId"] for item in video_details))
        all_channel_stats = get_channel_stats(youtube_service, channel_ids)
        
        rows = []
        for v in video_details:
            stats, snip = v.get("statistics", {}), v.get("snippet", {})
            channel_id = snip.get("channelId", "")
            channel_info = all_channel_stats.get(channel_id, {"subscribers": 0, "average_views": 0})
            pub_date = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            
            rows.append({
                "video_id": v.get("id"),
                "published": pub_date.date(),
                "title": snip.get("title", "N/A"),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "velocity": int(stats.get("viewCount", 0)) / max(1, (datetime.now(timezone.utc) - pub_date).days),
                "subscribers": channel_info["subscribers"],
                "channel_avg_views": channel_info["average_views"],
                "channel_id": channel_id,
            })
        df = pd.DataFrame(rows)
        if df.empty: return None, None, "No video data could be processed."

        # Z-Score Calculation
        df['z_score'] = ((df['views'] - df['views'].mean()) / df['views'].std()).fillna(0)

        # Outlier Logic
        if search_type == "search_vs_avg":
            df = df[df["channel_avg_views"] > 0]
            df['outlier_score'] = df['views'] / df['channel_avg_views']
            df['is_outlier'] = df['outlier_score'] > avg_multiplier
        elif search_type == "channel_avg_self":
            self_avg = df['views'].mean()
            df['outlier_score'] = df['views'] / max(1, self_avg)
            df['is_outlier'] = df['outlier_score'] > avg_multiplier
        else:
            df = df[df['views'] >= min_views]
            df['outlier_score'] = df['views'] / df['subscribers'].apply(lambda x: max(x, 1))
            df['is_outlier'] = df['outlier_score'] > view_multiplier

        outliers_df = df[df["is_outlier"]].sort_values("outlier_score", ascending=False)
        return df.sort_values("outlier_score", ascending=False), outliers_df, None
    except HttpError as e: return None, None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e: return None, None, f"An error occurred: {str(e)}"

# --- MAIN APP UI ---

st.title("🎬 YouTube Outlier Finder")

if "api_key_valid" not in st.session_state:
    st.session_state.api_key_valid = False

# --- Configuration Section ---
st.markdown('<div class="config-box">', unsafe_allow_html=True)
if not st.session_state.api_key_valid:
    st.header("1. API Key")
    api_key = st.text_input("Enter your YouTube Data API Key", type="password", placeholder="AIza...")
    if st.button("✅ Validate & Save Key"):
        if api_key and (yt_service := get_youtube_service(api_key)):
            st.session_state.api_key_valid = True
            st.session_state.yt = yt_service
            st.rerun()
else:
    st.success("✅ API key validated.")
    st.header("Analysis Configuration")
    
    stype_option = st.radio("Select Analysis Mode:", (
        "Search Term (vs. Subs)", "Search Term (vs. Channel Average)", 
        "By Channel (vs. Subs)", "By Channel (vs. Channel Average)"
    ))
    
    stype_map = {
        "Search Term (vs. Subs)": "search_vs_subs", "Search Term (vs. Channel Average)": "search_vs_avg",
        "By Channel (vs. Subs)": "channel_vs_subs", "By Channel (vs. Channel Average)": "channel_avg_self"
    }
    stype_val = stype_map[stype_option]

    c1, c2 = st.columns(2)
    with c1:
        query_label = "Enter Channel URL or Handle" if "channel" in stype_val else "Search Term"
        query = st.text_input(query_label, placeholder="e.g., @mkbhd or 'AI product demos'")
    with c2:
        if "avg" in stype_val:
            avg_multiplier = st.slider("Outlier Multiplier (x Average)", 2, 50, 10)
            view_multiplier, min_views_threshold = 100, 50000
        else:
            view_multiplier = st.slider("View-to-Subscriber Multiplier", 10, 1000, 100)
            min_views_threshold = st.select_slider("Minimum Views", [10000, 25000, 50000, 100000, 250000, 500000, 1000000], value=50000)
            avg_multiplier = 10

    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        st.session_state.query_params = (stype_val, query, view_multiplier, min_views_threshold, avg_multiplier)

st.markdown('</div>', unsafe_allow_html=True)


# --- Results Section ---
if 'query_params' in st.session_state:
    with st.spinner("🔄 Fetching & analyzing videos..."):
        df, outliers_df, err = analyze_videos(st.session_state.yt, *st.session_state.query_params)
        
        if err: st.error(err)
        elif df is None or df.empty: st.warning("No videos found matching your criteria.")
        else:
            st.markdown("---")
            # --- Top Metrics ---
            m1, m2, m3 = st.columns(3)
            with m1:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Total Views</div><div class="metric-value">{df["views"].sum():,}</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Avg. Views/Day</div><div class="metric-value">{df["velocity"].mean():,.0f}</div></div>', unsafe_allow_html=True)
            with m3:
                st.markdown(f'<div class="metric-card"><div class="metric-label">Total Likes</div><div class="metric-value">{df["likes"].sum():,}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            
            # --- Visualizations ---
            st.header("📊 Visualizations")
            v1, v2 = st.columns(2)
            with v1:
                st.subheader("View Velocity Over Time")
                chart_data = df.sort_values("published")[["published", "velocity"]].set_index("published")
                st.line_chart(chart_data)
            with v2:
                st.subheader("Top 10 Outliers by Velocity")
                top_outliers = outliers_df.nlargest(10, "velocity")[["title", "velocity"]].set_index("title")
                st.bar_chart(top_outliers)

            # --- Data Table ---
            st.header("📹 All Analyzed Videos")
            
            df_display = df.copy()
            df_display['Outlier'] = df_display['is_outlier'].apply(lambda x: '🔥' if x else '')
            df_display['URL'] = 'https://www.youtube.com/watch?v=' + df_display['video_id']
            df_display['Views/Day'] = df_display['velocity'].map('{:,.0f}'.format)
            df_display['Z-Score'] = df_display['z_score'].map('{:.2f}'.format)

            st.dataframe(
                df_display[['Outlier', 'title', 'published', 'views', 'likes', 'comments', 'Views/Day', 'Z-Score', 'URL']],
                column_config={
                    "title": st.column_config.TextColumn("Title", width="large"),
                    "views": st.column_config.NumberColumn("Views", format="%d"),
                    "URL": st.column_config.LinkColumn("Watch", display_text="▶️"),
                },
                use_container_width=True
            )

