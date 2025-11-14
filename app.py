import streamlit as st
import pandas as pd
import numpy as np
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

st.set_page_config(page_title="YouTube Outlier Video Hunter", page_icon="🎬", layout="wide", initial_sidebar_state="collapsed")

# --- Custom CSS for Dark Theme, Red Accents, and Custom Layouts ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }
    
    /* DEFINITIVE FIX: Force the entire app background to be dark */
    [data-testid="stAppViewContainer"] > .main {
        background-color: #0E1117;
    }
    
    body { background-color: #0E1117; }
    
    .main .block-container { padding: 2rem 3rem; }
    
    h1 { font-weight: 700; color: #FFFFFF !important; }
    h2, h3 { font-weight: 700; color: #FFFFFF; }
    
    a { color: #FF4B4B; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .config-box { background-color: #161A25; border: 1px solid #303742; border-radius: 12px; padding: 2rem; margin-bottom: 2rem; }
    
    .metric-card { background-color: #161A25; border: 1px solid #303742; border-radius: 12px; padding: 1.5rem; text-align: center; }
    .metric-card .metric-label { font-size: 1rem; color: #A0AEC0; }
    .metric-card .metric-value { font-size: 2.25rem; font-weight: 700; color: #FFFFFF; }
    
    .stButton>button { border-radius: 8px; background-color: #FF4B4B; color: white; font-weight: 600; border: none; }
    .stButton>button:hover { background-color: #E03C3C; color: white; }
    
    .video-result-card { display: flex; align-items: flex-start; gap: 20px; padding: 1rem; background-color: #161A25; border: 1px solid #303742; border-radius: 12px; margin-bottom: 1rem; }
    .video-result-card.outlier { border-color: #FFD700; background-color: #2c2a22; }
    .video-thumbnail img { width: 160px; height: 90px; border-radius: 8px; object-fit: cover; }
    .video-details { flex: 1; }
    .video-title a { font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; color: #FFFFFF !important; }
    .video-stats { display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9rem; color: #A0AEC0; }
    .video-stats strong { color: #FAFAFA; }
    .footer { text-align: center; padding: 2rem 0; color: #A0AEC0; }
</style>
""", unsafe_allow_html=True)


# --- API & UTILITY FUNCTIONS ---
@st.cache_resource
def get_youtube_service(api_key: str):
    try:
        service = build("youtube", "v3", developerKey=api_key)
        service.channels().list(part="id", id="UC_x5XG1OV2P6uZZ5FSM9Ttw").execute(); return service
    except: return None

@st.cache_data(ttl=3600)
def get_channel_id_from_input(_youtube_service, user_input: str):
    user_input = user_input.strip()
    id_match = re.search(r"(UC[a-zA-Z0-9_-]{22})", user_input)
    if id_match: return id_match.group(1)
    handle_match = re.search(r"(@[a-zA-Z0-9_.-]+)", user_input)
    handle = handle_match.group(1) if handle_match else f"@{user_input.split('/')[-1]}"
    try:
        req = _youtube_service.search().list(part="id", q=handle, type="channel", maxResults=1); res = req.execute()
        return res["items"][0]["id"]["channelId"] if res.get("items") else None
    except: return None

@st.cache_data(ttl=3600)
def get_channel_stats(_youtube_service, channel_ids):
    stats_dict = {}
    try:
        for i in range(0, len(channel_ids), 50):
            req = _youtube_service.channels().list(part="statistics", id=",".join(channel_ids[i:i+50])); channels = req.execute().get("items", [])
            for ch in channels:
                stats = ch.get("statistics", {})
                stats_dict[ch["id"]] = {"subscribers": int(stats.get("subscriberCount", 0)), "average_views": int(stats.get("viewCount", 0)) / max(1, int(stats.get("videoCount", 1)))}
        return stats_dict
    except: return stats_dict

# --- CORE ANALYSIS ENGINE ---
def analyze_videos(youtube_service, search_type, query_input, view_multiplier, min_views, avg_multiplier):
    try:
        resolved_channel_id = get_channel_id_from_input(youtube_service, query_input) if "channel" in search_type else None
        if "channel" in search_type and not resolved_channel_id: return None, None, f"❌ Could not find channel for '{query_input}'."

        order = "date" if search_type == "channel_avg_self" else "viewCount"
        params = {"part": "snippet", "maxResults": 50, "type": "video", "order": order}
        if "channel" in search_type: params["channelId"] = resolved_channel_id
        else: params["q"] = query_input
        
        search_results = youtube_service.search().list(**params).execute().get("items", [])
        if not search_results: return None, None, "No videos found."

        video_ids = [item["id"]["videoId"] for item in search_results]
        video_details = youtube_service.videos().list(part="snippet,statistics", id=",".join(video_ids)).execute().get("items", [])
        channel_ids = list(set(item["snippet"]["channelId"] for item in video_details))
        all_channel_stats = get_channel_stats(youtube_service, channel_ids)
        
        rows = []
        for v in video_details:
            stats, snip, video_id = v.get("statistics", {}), v.get("snippet", {}), v.get("id")
            pub_date = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            rows.append({
                "video_id": video_id, "published": pub_date.date(), "title": snip.get("title", "N/A"),
                "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url") or f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                "views": int(stats.get("viewCount", 0)), "likes": int(stats.get("likeCount", 0)), "comments": int(stats.get("commentCount", 0)),
                "velocity": int(stats.get("viewCount", 0)) / max(1, (datetime.now(timezone.utc) - pub_date).days),
                "subscribers": all_channel_stats.get(snip.get("channelId", ""), {}).get("subscribers", 0),
                "channel_avg_views": all_channel_stats.get(snip.get("channelId", ""), {}).get("average_views", 0),
            })
        df = pd.DataFrame(rows)
        if df.empty: return None, None, "No data processed."

        df['z_score'] = ((df['views'] - df['views'].mean()) / df['views'].std()).fillna(0)
        if "avg" in search_type:
            avg_source = df['views'].mean() if search_type == "channel_avg_self" else df['channel_avg_views']
            df['outlier_score'] = df['views'] / np.maximum(1, avg_source); df['is_outlier'] = df['outlier_score'] > avg_multiplier
        else:
            df = df[df['views'] >= min_views].copy(); 
            if df.empty: return df, df, None
            df['outlier_score'] = df['views'] / np.maximum(1, df['subscribers']); df['is_outlier'] = df['outlier_score'] > view_multiplier
        
        return df.sort_values("outlier_score", ascending=False), df[df["is_outlier"]], None
    except HttpError as e: return None, None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e: return None, None, f"An unexpected error occurred: {str(e)}"

# --- UI & APP FLOW ---

st.markdown("<h1>🎬 YouTube Outlier Video Hunter</h1>", unsafe_allow_html=True)
st.markdown("A free tool by [Write Wing Media](https://writewing.in) to discover viral videos and analyze performance.")

if "api_key_valid" not in st.session_state: st.session_state.api_key_valid = False

st.markdown('<div class="config-box">', unsafe_allow_html=True)
if not st.session_state.api_key_valid:
    st.header("1. Enter API Key")
    api_key = st.text_input("YouTube Data API Key", type="password", placeholder="AIza...")
    if st.button("✅ Validate & Save Key"):
        if api_key and (yt_service := get_youtube_service(api_key)):
            st.session_state.api_key_valid = True; st.session_state.yt = yt_service; st.rerun()
        else: st.error("Invalid API Key.")
else:
    st.header("2. Analysis Configuration")
    
    stype_option = st.radio(
        "Select an Analysis Mode:",
        ("Search Term (vs Subs)", "Search Term (vs Channel Avg)", "By Channel (vs Subs)", "By Channel (vs Channel Avg)"),
        key="analysis_mode"
    )
    stype_val = {"Search Term (vs Subs)": "search_vs_subs", "Search Term (vs Channel Avg)": "search_vs_avg", "By Channel (vs Subs)": "channel_vs_subs", "By Channel (vs Channel Avg)": "channel_avg_self"}[stype_option]
    
    c1, c2 = st.columns(2)
    query = c1.text_input("Enter Channel URL/Handle or Search Term", placeholder="@mkbhd or 'AI product demos'")
    
    with c2:
        if "avg" in stype_val:
            avg_multiplier = st.slider("Outlier Multiplier", 2, 50, 10, help="Flags videos with views > (Multiplier * Avg. Views)")
            view_multiplier, min_views = 100, 50000
        else:
            view_multiplier = st.slider("View-to-Sub Multiplier", 10, 1000, 100)
            min_views = st.select_slider("Min. Views", options=[k * 10000 for k in range(1, 10)] + [100000, 250000, 500000, 1000000], value=50000)
            avg_multiplier = 10

    if st.button("🔍 Find Outliers", use_container_width=True, type="primary"):
        st.session_state.query_params = (stype_val, query, view_multiplier, min_views, avg_multiplier)
st.markdown('</div>', unsafe_allow_html=True)

# --- RESULTS DISPLAY ---
if 'query_params' in st.session_state and st.session_state.query_params[1].strip():
    with st.spinner("🔄 Analyzing videos..."):
        df, outliers_df, err = analyze_videos(st.session_state.yt, *st.session_state.query_params)
        if err: st.error(err)
        elif df is None or df.empty: st.warning("No videos found matching your criteria.")
        else:
            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.markdown(f'<div class="metric-card"><div class="metric-label">Total Views</div><div class="metric-value">{df["views"].sum():,}</div></div>', unsafe_allow_html=True)
            m2.markdown(f'<div class="metric-card"><div class="metric-label">Avg. Views/Day</div><div class="metric-value">{df["velocity"].mean():,.0f}</div></div>', unsafe_allow_html=True)
            m3.markdown(f'<div class="metric-card"><div class="metric-label">Total Likes</div><div class="metric-value">{df["likes"].sum():,}</div></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            st.header("📊 Visualizations")
            v1, v2 = st.columns(2)
            v1.subheader("View Velocity Over Time"); v1.line_chart(df.sort_values("published")[["published", "velocity"]].set_index("published"))
            v2.subheader("Top 10 Outliers by Velocity")
            if not outliers_df.empty: v2.bar_chart(outliers_df.nlargest(10, "velocity")[["title", "velocity"]].set_index("title"))
            else: v2.info("No outliers found to visualize.")
            st.header("📹 Analyzed Videos")
            for _, row in df.iterrows():
                st.markdown(f"""
                <div class="video-result-card {'outlier' if row['is_outlier'] else ''}">
                    <div class="video-thumbnail"><a href="https://www.youtube.com/watch?v={row['video_id']}" target="_blank"><img src="{row['thumbnail']}" alt="Thumbnail"></a></div>
                    <div class="video-details">
                        <div class="video-title"><a href="https://www.youtube.com/watch?v={row['video_id']}" target="_blank">{row['title']}</a></div>
                        <div class="video-stats">
                            <span>Published: <strong>{row['published']}</strong></span><span>Views: <strong>{row['views']:,}</strong></span>
                            <span>Likes: <strong>{row['likes']:,}</strong></span><span>Views/Day: <strong>{row['velocity']:,.0f}</strong></span>
                            <span>Z-Score: <strong>{row['z_score']:.2f}</strong></span>
                        </div>
                    </div>
                </div>""", unsafe_allow_html=True)

# --- FOOTER ---
st.markdown("---")
st.markdown(
    '<div class="footer">Built by <a href="https://writewing.in" target="_blank">Write Wing Media</a> | <a href="https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com" target="_blank">Get your free YouTube API key</a></div>',
    unsafe_allow_html=True
)
