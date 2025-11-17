import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build

# --- Page Configuration and Secrets ---
st.set_page_config(page_title="YouTube Outlier Video Hunter & Analyst", page_icon="🚀", layout="wide")

# Try to get API keys from Streamlit secrets
try:
    YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]
    GEMINI_API_KEY = st.secrets["google_ai"]["gemini_api_key"]
except (FileNotFoundError, KeyError):
    st.warning("API keys not found in st.secrets. Please enter them manually below.")
    YOUTUBE_API_KEY = ""
    GEMINI_API_KEY = ""

# --- Custom CSS ---
st.markdown("""
<style>
   @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
   html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }
   .main .block-container { padding: 2rem 3rem; }
   [data-testid="stAppViewContainer"] > .main { background-color: #FFFFFF; }
   h1, h2, h3, p, span, div, label { color: #000000 !important; }
   a { color: #0072b1; text-decoration: none; }
   a:hover { text-decoration: underline; }
   .hero-section {
        background-color: #F0F2F6;
        border: 1px solid #E0E0E0;
        border-radius: 16px;
        padding: 2.5rem 3rem;
        margin-bottom: 2rem;
   }
   .hero-section h1, .hero-section h2 { color: #000000 !important; }
    .hero-section .description {
        color: #333333 !important;
        font-size: 1.1rem;
        max-width: 800px;
   }
    .metric-card { background-color: #F0F2F6; border: 1px solid #E0E0E0; border-radius: 12px; padding: 1.5rem; text-align: center; }
    .metric-card .metric-label { font-size: 1rem; color: #555555 !important; }
    .metric-card .metric-value { font-size: 2.25rem; font-weight: 700; color: #000000 !important; }
    .video-result-card { display: flex; align-items: flex-start; gap: 20px; padding: 1rem; background-color: #FFFFFF; border: 1px solid #E0E0E0; border-radius: 12px; margin-bottom: 1rem; }
    .outlier-card { background-color: #FFFBEB; border: 1px solid #FFC700; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
    .video-thumbnail img { width: 160px; height: 90px; border-radius: 8px; object-fit: cover; }
    .video-details { flex: 1; }
    .video-title a { font-size: 1.1rem; font-weight: 600; margin-bottom: 8px; color: #000000 !important; }
    .video-stats { display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9rem; color: #555555 !important; }
    .video-stats strong { color: #000000 !important; }
    .footer { text-align: center; padding: 2rem 0; color: #555555 !important; }
    .footer a { color: #0072b1 !important; }
</style>
""", unsafe_allow_html=True)

# --- State Management ---
for key in ['api_key_valid', 'analysis_loading', 'analysis_result', 'analysis_target_video', 'videos', 'avg_views']:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'api_key_valid' else False

# --- Core Functions ---
def get_transcript(video_id):
    try:
        return " ".join([item['text'] for item in YouTubeTranscriptApi.get_transcript(video_id)])
    except Exception as e:
        st.warning(f"Could not retrieve transcript for video ID {video_id}: {e}")
        return None

def get_video_details(youtube_service, video_id):
    try:
        request = youtube_service.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if response['items']:
            snippet = response['items'][0]['snippet']
            return snippet['title'], snippet['description']
    except Exception as e:
        st.error(f"Could not retrieve video details: {e}")
    return None, None

def get_ai_analysis(video_id, youtube_service):
    st.session_state.analysis_loading = True
    st.session_state.analysis_result = None
    transcript = get_transcript(video_id)
    if not transcript:
        st.session_state.analysis_loading = False
        return
    title, description = get_video_details(youtube_service, video_id)
    if not title:
        st.session_state.analysis_loading = False
        return
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"""
        As an expert YouTube strategist, analyze this 'outlier' video and provide a blueprint to create a better one.

        **Video Analysis:**
        - **Original Title:** {title}
        - **Original Transcript:**\n'''{transcript}'''

        **Your Mission:**
        1. **Content Gap Analysis:** Identify 3-5 specific weaknesses or missed opportunities in the original script.
        2. **Generate a Better Title:** Create one new, clickable, SEO-optimized title (under 70 characters).
        3. **Generate a Better Script:** Write a new, complete video script designed for higher retention, including a strong hook, clear structure, visual cues (e.g., "[Visual: B-roll]"), and a call-to-action.

        Format your response clearly with Markdown headings for "Content Gaps," "New Title," and "New Script".
        """
        response = model.generate_content(prompt)
        st.session_state.analysis_result = response.text
    except Exception as e:
        st.error(f"Error during AI analysis: {e}")
    finally:
        st.session_state.analysis_loading = False

def analyze_videos(youtube_service, search_type, query_input, view_multiplier, max_results):
    st.info("Displaying sample data. Replace `analyze_videos` with your own logic.")
    sample_videos = [
        {'videoId': 'jNQXAC9IVRw', 'title': 'Sample Outlier 1: How to Go Viral', 'thumbnail': 'https://i.ytimg.com/vi/jNQXAC9IVRw/hqdefault.jpg', 'views': 500000, 'channel': 'Channel B', 'is_outlier': True, 'days_since_published': 30, 'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw'},
        {'videoId': 'L_LUpnjgPso', 'title': 'Sample Outlier 2: Another Viral Hit', 'thumbnail': 'https://i.ytimg.com/vi/L_LUpnjgPso/hqdefault.jpg', 'views': 800000, 'channel': 'Channel D', 'is_outlier': True, 'days_since_published': 45, 'url': 'https://www.youtube.com/watch?v=L_LUpnjgPso'},
        {'videoId': 'dQw4w9WgXcQ', 'title': 'Sample Video: Not an Outlier', 'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', 'views': 15000, 'channel': 'Channel A', 'is_outlier': False, 'days_since_published': 100, 'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'},
        {'videoId': 'o-YBDTqX_ZU', 'title': 'Sample Video: A Standard Upload', 'thumbnail': 'https://i.ytimg.com/vi/o-YBDTqX_ZU/hqdefault.jpg', 'views': 25000, 'channel': 'Channel C', 'is_outlier': False, 'days_since_published': 60, 'url': 'https://www.youtube.com/watch?v=o-YBDTqX_ZU'}
    ]
    avg_views = 20000
    return sample_videos, avg_views

# --- STREAMLIT UI ---
st.markdown('<div class="hero-section"><h1>🚀 YouTube Outlier Hunter & Analyst</h1><p class="description">A free tool by <a href="https://writewing.in" target="_blank">Write Wing Media</a> to discover viral videos and generate superior, AI-powered content strategies to outrank them.</p></div>', unsafe_allow_html=True)

if not st.session_state.api_key_valid:
    st.header("1. Enter API Keys")
    if not YOUTUBE_API_KEY: YOUTUBE_API_KEY = st.text_input("YouTube Data API v3 Key", type="password")
    if not GEMINI_API_KEY: GEMINI_API_KEY = st.text_input("Google AI Studio (Gemini) API Key", type="password")
    if st.button("Validate Keys"):
        if len(YOUTUBE_API_KEY) > 10 and len(GEMINI_API_KEY) > 10:
            st.session_state.api_key_valid = True
            st.rerun()
        else: st.error("Please enter valid API keys.")
else:
    youtube_service = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    st.header("2. Find Outlier Videos")
    search_type = st.radio("Search by:", ("Keyword", "Channel URL"), horizontal=True)
    query_input = st.text_input("Enter Keyword or Channel URL", "")
    col1, col2 = st.columns(2)
    with col1: view_multiplier = st.slider("Outlier Threshold (Views Multiplier)", 2, 20, 10)
    with col2: max_results = st.slider("Videos to Analyze", 10, 50, 25)

    if st.button("Hunt for Outliers", type="primary"):
        if query_input:
            with st.spinner("Analyzing YouTube..."):
                videos, avg_views = analyze_videos(youtube_service, search_type, query_input, view_multiplier, max_results)
                st.session_state.videos = videos
                st.session_state.avg_views = avg_views
                st.session_state.analysis_result = None # Clear previous analysis
                st.session_state.analysis_target_video = None
        else: st.warning("Please enter a search query.")

    if st.session_state.videos:
        st.header("3. Analysis Results")
        outlier_videos = [v for v in st.session_state.videos if v.get('is_outlier')]
        other_videos = [v for v in st.session_state.videos if not v.get('is_outlier')]

        if outlier_videos:
            st.subheader("🏆 Outlier Videos Found")
            for video in outlier_videos:
                with st.container():
                    st.markdown(f'<div class="outlier-card">', unsafe_allow_html=True)
                    col1, col2 = st.columns([1, 4])
                    with col1: st.image(video['thumbnail'], use_column_width=True)
                    with col2:
                        st.markdown(f"<h5><a href='{video['url']}' target='_blank'>{video['title']}</a></h5>", unsafe_allow_html=True)
                        st.markdown(f"**Views:** {video['views']:,} | **Channel:** {video['channel']}")
                        st.markdown(f"<span style='color:green;'>This video is an outlier, significantly outperforming the average.</span>", unsafe_allow_html=True)
                        if st.button("🤖 Analyze & Generate Better Script", key=f"analyze_{video['videoId']}"):
                            st.session_state.analysis_target_video = video
                            get_ai_analysis(video['videoId'], youtube_service)
                            st.rerun()
                    st.markdown(f'</div>', unsafe_allow_html=True)

        if st.session_state.analysis_loading: st.info("AI is analyzing, please wait...")
        if st.session_state.analysis_result:
            st.subheader("💡 AI Strategy Blueprint")
            if st.session_state.analysis_target_video:
                st.markdown(f"**Analysis for:** *{st.session_state.analysis_target_video['title']}*")
            st.markdown(st.session_state.analysis_result, unsafe_allow_html=True)
            if st.button("Clear Analysis"):
                st.session_state.analysis_result = None
                st.session_state.analysis_target_video = None
                st.rerun()

        if other_videos:
            st.subheader("Other Videos Analyzed")
            for video in other_videos:
                st.markdown(f"""
                <div class="video-result-card">
                    <div class="video-thumbnail"><img src="{video['thumbnail']}"></div>
                    <div class="video-details">
                        <div class="video-title"><a href="{video['url']}" target="_blank">{video['title']}</a></div>
                        <div class="video-stats">
                            <span><strong>{video['views']:,}</strong> views</span>
                            <span><strong>{video['days_since_published']}</strong> days ago</span>
                            <span>by <strong>{video['channel']}</strong></span>
                        </div>
                    </div>
                </div>""", unsafe_allow_html=True)

st.markdown("<div class='footer'>Made with ❤️ by <a href='https://writewing.in' target='_blank'>Write Wing Media</a></div>", unsafe_allow_html=True)
