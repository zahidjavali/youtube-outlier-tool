import streamlit as st
import pandas as pd
import numpy as np
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

st.setpageconfig(pagetitle="YouTube Outlier Video Hunter", pageicon="🎬", layout="wide", initialsidebarstate="collapsed")

# --- CSS for a Clean, Professional LIGHT THEME ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class="st-"] { font-family: 'Inter', sans-serif; }
    
    / Set main background to white /
    [data-testid="stAppViewContainer"] > .main { background-color: #FFFFFF; }
    
    .main .block-container { padding: 2rem 3rem; }
    
    / Set all text to black */
    h1, h2, h3, p, span, div, label {
        color: #000000 !important;
    }
    
    a { color: #0072b1; text-decoration: none; }
    a:hover { text-decoration: underline; }

    / Redesigned Light "Hero" Section /
    .hero-section {
        background-color: #F0F2F6; / Light grey for pop /
        border: 1px solid #E0E0E0;
        border-radius: 16px;
        padding: 2.5rem 3rem;
        margin-bottom: 2rem;
    }
    .hero-section h1, .hero-section h2 { color: #000000 !important; }
    .hero-section .description {
        color: #333333 !important; / Slightly softer black for description /
        font-size: 1.1rem;
        max-width: 800px;
    }

    / Standard Light Theme Elements /
    .metric-card { background-color: #F0F2F6; border: 1px solid #E0E0E0; border-radius: 12px; padding: 1.5rem; text-align: center; }
    .metric-card .metric-label { font-size: 1rem; color: #555555 !important; }
    .metric-card .metric-value { font-size: 2.25rem; font-weight: 700; color: #000000 !important; }
    
    .video-result-card { display: flex; align-items: flex-start; gap: 20px; padding: 1rem; background-color: #FFFFFF; border: 1px solid #E0E0E0; border-radius: 12px; margin-bottom: 1rem; }
    .video-result-card.outlier { border-color: #FFC700; background-color: #FFFBEB; }
    .video-thumbnail img { width: 160px; height: 90px; border-radius: 8px; object-fit: cover; }
    .video-details { flex: 1; }
    .video-title a { font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; color: #000000 !important; }
    .video-stats { display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9rem; color: #555555 !important; }
    .video-stats strong { color: #000000 !important; }
    
    .footer { text-align: center; padding: 2rem 0; color: #555555 !important; }
    .footer a { color: #0072b1 !important; }
</style>
""", unsafeallowhtml=True)


# --- API & UTILITY FUNCTIONS ---
@st.cacheresource
def getyoutubeservice(apikey: str):
    try:
        service = build("youtube", "v3", developerKey=apikey)
        service.channels().list(part="id", id="UCx5XG1OV2P6uZZ5FSM9Ttw").execute(); return service
    except: return None

@st.cachedata(ttl=3600)
def getchannelidfrominput(youtubeservice, userinput: str):
    userinput = userinput.strip()
    idmatch = re.search(r"(UC[a-zA-Z0-9-]{22})", userinput)
    if idmatch: return idmatch.group(1)
    handlematch = re.search(r"(@[a-zA-Z0-9.-]+)", userinput)
    handle = handlematch.group(1) if handlematch else f"@{userinput.split('/')[-1]}"
    try:
        req = youtube_service.search().list(part="id", q=handle, type="channel", maxResults=1); res = req.execute()
        return res["items"][0]["id"]["channelId"] if res.get("items") else None
    except: return None

@st.cachedata(ttl=3600)
def getchannelstats(youtubeservice, channelids):
    statsdict = {}
    try:
        for i in range(0, len(channelids), 50):
            req = youtubeservice.channels().list(part="statistics", id=",".join(channelids[i:i+50])); channels = req.execute().get("items", [])
            for ch in channels:
                stats = ch.get("statistics", {})
                statsdict[ch["id"]] = {"subscribers": int(stats.get("subscriberCount", 0)), "averageviews": int(stats.get("viewCount", 0)) / max(1, int(stats.get("videoCount", 1)))}
        return statsdict
    except: return stats_dict

# --- CORE ANALYSIS ENGINE ---
def analyzevideos(youtubeservice, searchtype, queryinput, viewmultiplier, minviews, avgmultiplier):
    try:
        resolvedchannelid = getchannelidfrominput(youtubeservice, queryinput) if "channel" in searchtype else None
        if "channel" in searchtype and not resolvedchannelid: return None, None, f"❌ Could not find channel for '{queryinput}'."

        order = "date" if searchtype == "channelavgself" else "viewCount"
        params = {"part": "snippet", "maxResults": 50, "type": "video", "order": order}
        if "channel" in searchtype: params["channelId"] = resolvedchannelid
        else: params["q"] = queryinput
        
        searchresults = youtubeservice.search().list(**params).execute().get("items", [])
        if not searchresults: return None, None, "No videos found."

        videoids = [item["id"]["videoId"] for item in searchresults]
        videodetails = youtubeservice.videos().list(part="snippet,statistics", id=",".join(videoids)).execute().get("items", [])
        channelids = list(set(item["snippet"]["channelId"] for item in videodetails))
        allchannelstats = getchannelstats(youtubeservice, channelids)
        
        rows = []
        for v in videodetails:
            stats, snip, videoid = v.get("statistics", {}), v.get("snippet", {}), v.get("id")
            pubdate = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            rows.append({
                "videoid": videoid, "published": pubdate.date(), "title": snip.get("title", "N/A"),
                "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url") or f"https://img.youtube.com/vi/{videoid}/mqdefault.jpg",
                "views": int(stats.get("viewCount", 0)), "likes": int(stats.get("likeCount", 0)), "comments": int(stats.get("commentCount", 0)),
                "velocity": int(stats.get("viewCount", 0)) / max(1, (datetime.now(timezone.utc) - pubdate).days),
                "subscribers": allchannelstats.get(snip.get("channelId", ""), {}).get("subscribers", 0),
                "channelavgviews": allchannelstats.get(snip.get("channelId", ""), {}).get("averageviews", 0),
            })
        df = pd.DataFrame(rows)
        if df.empty: return None, None, "No data processed."

        df['zscore'] = ((df['views'] - df['views'].mean()) / df['views'].std()).fillna(0)
        if "avg" in searchtype:
            avgsource = df['views'].mean() if searchtype == "channelavgself" else df['channelavgviews']
            df['outlierscore'] = df['views'] / np.maximum(1, avgsource); df['isoutlier'] = df['outlierscore'] > avgmultiplier
        else:
            df = df[df['views'] >= minviews].copy(); 
            if df.empty: return df, df, None
            df['outlierscore'] = df['views'] / np.maximum(1, df['subscribers']); df['isoutlier'] = df['outlierscore'] > viewmultiplier
        
        return df.sortvalues("outlierscore", ascending=False), df[df["is_outlier"]], None
    except HttpError as e: return None, None, f"API error: {getattr(e, 'reason', str(e))}"
    except Exception as e: return None, None, f"An unexpected error occurred: {str(e)}"

# --- UI & APP FLOW ---

if "apikeyvalid" not in st.sessionstate: st.sessionstate.apikeyvalid = False

st.markdown('<div class="hero-section">', unsafeallowhtml=True)
st.markdown("<h1>🎬 YouTube Outlier Video Hunter</h1>", unsafeallowhtml=True)
st.markdown("<p class='description'>A free tool by <a href='https://writewing.in' target='blank'>Write Wing Media</a> to discover viral videos and analyze performance.</p>", unsafeallowhtml=True)
st.markdown("<br>", unsafeallowhtml=True)
if not st.sessionstate.apikeyvalid:
    st.header("1. Enter API Key")
    apikey = st.textinput("YouTube Data API Key", type="password", placeholder="AIza...")
    if st.button("✅ Validate & Save Key"):
        if apikey and (ytservice := getyoutubeservice(apikey)):
            st.sessionstate.apikeyvalid = True; st.sessionstate.yt = ytservice; st.rerun()
        else: st.error("Invalid API Key.")
else:
    st.header("2. Analysis Configuration")
    stypeoption = st.radio("Select an Analysis Mode:", ("Search Term (vs Subs)", "Search Term (vs Channel Avg)", "By Channel (vs Subs)", "By Channel (vs Channel Avg)"), key="analysismode")
    stypeval = {"Search Term (vs Subs)": "searchvssubs", "Search Term (vs Channel Avg)": "searchvsavg", "By Channel (vs Subs)": "channelvssubs", "By Channel (vs Channel Avg)": "channelavgself"}[stypeoption]
    c1, c2 = st.columns(2)
    query = c1.textinput("Enter Channel URL/Handle or Search Term", placeholder="@mkbhd or 'AI product demos'")
    with c2:
        if "avg" in stypeval:
            avgmultiplier = st.slider("Outlier Multiplier", 2, 50, 10, help="Flags videos with views > (Multiplier * Avg. Views)")
            viewmultiplier, minviews = 100, 50000
        else:
            viewmultiplier = st.slider("View-to-Sub Multiplier", 10, 1000, 100)
            minviews = st.selectslider("Min. Views", options=[k * 10000 for k in range(1, 10)] + [100000, 250000, 500000, 1000000], value=50000)
            avgmultiplier = 10
    if st.button("🔍 Find Outliers", usecontainerwidth=True, type="primary"):
        st.sessionstate.queryparams = (stypeval, query, viewmultiplier, minviews, avgmultiplier)
st.markdown('</div>', unsafeallow_html=True)

# --- RESULTS DISPLAY ---
if 'queryparams' in st.sessionstate and st.sessionstate.queryparams[1].strip():
    with st.spinner("🔄 Analyzing videos..."):
        df, outliersdf, err = analyzevideos(st.sessionstate.yt, *st.sessionstate.queryparams)
        if err: st.error(err)
        elif df is None or df.empty: st.warning("No videos found matching your criteria.")
        else:
            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.markdown(f'<div class="metric-card"><div class="metric-label">Total Views</div><div class="metric-value">{df["views"].sum():,}</div></div>', unsafeallowhtml=True)
            m2.markdown(f'<div class="metric-card"><div class="metric-label">Avg. Views/Day</div><div class="metric-value">{df["velocity"].mean():,.0f}</div></div>', unsafeallowhtml=True)
            m3.markdown(f'<div class="metric-card"><div class="metric-label">Total Likes</div><div class="metric-value">{df["likes"].sum():,}</div></div>', unsafeallowhtml=True)
            st.markdown("<br>", unsafeallowhtml=True)
            st.header("📊 Visualizations")
            v1, v2 = st.columns(2)
            v1.subheader("View Velocity Over Time"); v1.linechart(df.sortvalues("published")[["published", "velocity"]].setindex("published"))
            v2.subheader("Top 10 Outliers by Velocity")
            if not outliersdf.empty: v2.barchart(outliersdf.nlargest(10, "velocity")[["title", "velocity"]].setindex("title"))
            else: v2.info("No outliers found to visualize.")
            st.header("📹 Analyzed Videos")
            for , row in df.iterrows():
                st.markdown(f"""<div class="video-result-card {'outlier' if row['isoutlier'] else ''}"><div class="video-thumbnail"><a href="https://www.youtube.com/watch?v={row['videoid']}" target="blank"><img src="{row['thumbnail']}" alt="Thumbnail"></a></div><div class="video-details"><div class="video-title"><a href="https://www.youtube.com/watch?v={row['videoid']}" target="blank">{row['title']}</a></div><div class="video-stats"><span>Published: <strong>{row['published']}</strong></span><span>Views: <strong>{row['views']:,}</strong></span><span>Likes: <strong>{row['likes']:,}</strong></span><span>Views/Day: <strong>{row['velocity']:,.0f}</strong></span><span>Z-Score: <strong>{row['zscore']:.2f}</strong></span></div></div></div>""", unsafeallow_html=True)

# --- FOOTER ---
st.markdown("---")
st.markdown('<div class="footer">Built by <a href="https://writewing.in" target="blank">Write Wing Media</a> | <a href="https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com" target="blank">Get your free YouTube API key</a></div>', unsafeallowhtml=True)
