import streamlit as st
import pandas as pd
import numpy as np
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timezone

# --- Page Configuration ---
st.set_page_config(
    page_title="YouTube Outlier Finder",
    page_icon="📊",
    layout="wide"
)

# --- App Header ---
st.title("📊 YouTube Outlier Finder")
st.markdown("A free tool to detect outlier videos from a YouTube channel or search query, inspired by 1of10.com.")

# --- API & Data Functions ---
@st.cache_resource
def get_youtube_service(api_key):
    """Builds and validates the YouTube API service object."""
    try:
        service = build('youtube', 'v3', developerKey=api_key)
        # Validate key with a simple, low-quota call
        service.channels().list(part='id', id='UC_x5XG1OV2P6uZZ5FSM9Ttw').execute()
        return service
    except HttpError as e:
        st.error(f"API Key validation failed. Reason: {e.reason}. Please ensure the key is correct and the YouTube Data API v3 is enabled.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during API key validation: {e}")
        return None

def fetch_video_ids(youtube, search_type, query):
    """Fetches up to 50 video IDs based on channel ID or search query."""
    if search_type == 'channel':
        request = youtube.search().list(
            part='id',
            channelId=query,
            maxResults=50,
            order='date',
            type='video'
        )
    else: # search query
        request = youtube.search().list(
            part='id',
            q=query,
            maxResults=50,
            type='video'
        )
    response = request.execute()
    return [item['id']['videoId'] for item in response.get('items', [])]

def get_video_details(youtube, video_ids):
    """Fetches details and statistics for a list of video IDs."""
    # YouTube API allows fetching details for up to 50 videos at once
    request = youtube.videos().list(
        part='snippet,statistics',
        id=','.join(video_ids)
    )
    response = request.execute()
    return response.get('items', [])

def analyze_video_data(videos):
    """Processes raw video data into a DataFrame with outlier analysis."""
    if not videos:
        return pd.DataFrame()

    records = []
    for video in videos:
        stats = video.get('statistics', {})
        snippet = video.get('snippet', {})
        
        # Skip videos with missing critical data
        if not all(k in stats for k in ['viewCount']) or not snippet.get('publishedAt'):
            continue

        published_at = datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00'))
        age_days = max(1, (datetime.now(timezone.utc) - published_at).days)
        views = int(stats.get('viewCount', 0))
        likes = int(stats.get('likeCount', 0))
        comments = int(stats.get('commentCount', 0))

        records.append({
            'title': snippet.get('title', 'N/A'),
            'publish_date': published_at.date(),
            'views': views,
            'likes': likes,
            'comments': comments,
            'age_days': age_days,
            'velocity': views / age_days,
            'engagement_rate': (likes + comments) / views if views > 0 else 0,
            'video_id': video['id']
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    
    # Z-score calculation for velocity
    velocities = df['velocity']
    if len(velocities) > 1 and velocities.std() > 0:
        df['z_score'] = (velocities - velocities.mean()) / velocities.std()
    else:
        df['z_score'] = 0

    # Outlier detection
    velocity_top_10_percentile = df['velocity'].quantile(0.90)
    df['is_outlier'] = (df['z_score'] > 2) | (df['velocity'] >= velocity_top_10_percentile)
    
    return df

# --- UI Flow ---

# 1. API Key Input
if 'api_key_valid' not in st.session_state:
    st.session_state.api_key_valid = False

if not st.session_state.api_key_valid:
    st.warning("A YouTube Data API v3 key is required to use this tool.")
    api_key = st.text_input("Enter your YouTube API Key", type="password")
    if st.button("Validate Key"):
        if api_key:
            youtube_service = get_youtube_service(api_key)
            if youtube_service:
                st.session_state.api_key = api_key
                st.session_state.youtube_service = youtube_service
                st.session_state.api_key_valid = True
                st.success("API Key is valid! You can now search for videos.")
                st.rerun()
        else:
            st.error("Please enter an API key.")
else:
    # 2. Search Form
    with st.form("search_form"):
        st.success("API Key validated. Ready to analyze.")
        search_type = st.radio("Search by:", ('Channel ID', 'Search Query'), horizontal=True)
        query_placeholder = "e.g., UCsT0YIqwnpJCM-mx7-gSA4Q" if search_type == 'Channel ID' else "e.g., 'streamlit tutorial'"
        query = st.text_input(f"Enter {search_type}", placeholder=query_placeholder)
        submitted = st.form_submit_button("Analyze Videos")

    # 3. Data Fetching and Analysis on Submit
    if submitted:
        if not query:
            st.warning("Please enter a search term or channel ID.")
        else:
            with st.spinner("Fetching and analyzing videos... this may take a moment."):
                try:
                    search_type_val = 'channel' if search_type == 'Channel ID' else 'search'
                    video_ids = fetch_video_ids(st.session_state.youtube_service, search_type_val, query)

                    if not video_ids:
                        st.warning("No videos found for the given query. Please try another.")
                    else:
                        video_details = get_video_details(st.session_state.youtube_service, video_ids)
                        df = analyze_video_data(video_details)

                        if df.empty:
                            st.warning("Could not process video data. The videos may have stats disabled or be inaccessible.")
                        else:
                            st.session_state.results_df = df

                except HttpError as e:
                    if e.resp.status == 403:
                        st.error("Quota Exceeded: Your API key has run out of quota for today. Please try again tomorrow or use a different key.")
                    else:
                        st.error(f"An API error occurred: {e.reason}. Please check the Channel ID or search query.")
                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

# 4. Display Results
if 'results_df' in st.session_state:
    df = st.session_state.results_df
    st.subheader("Analysis Results")
    
    outliers = df[df['is_outlier']]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Videos Analyzed", len(df))
    col2.metric("Outliers Detected", len(outliers))
    col3.metric("Outlier Percentage", f"{len(outliers) / len(df):.1%}" if len(df) > 0 else "0%")
    
    st.markdown("---")

    # Charts
    st.subheader("Charts")
    
    # Velocity over time
    st.write("#### View Velocity Over Time")
    chart_data = df.sort_values('publish_date')[['publish_date', 'velocity']].set_index('publish_date')
    st.line_chart(chart_data)
    
    # Top outliers bar chart
    if not outliers.empty:
        st.write("#### Top Outliers by View Velocity")
        outlier_chart_data = outliers.sort_values('velocity', ascending=False).head(15)[['title', 'velocity']].set_index('title')
        st.bar_chart(outlier_chart_data)

    st.markdown("---")
    
    # Dataframe
    st.subheader("Detailed Video Data")
    st.dataframe(df[[
        'title',
        'publish_date',
        'views',
        'velocity',
        'engagement_rate',
        'z_score',
        'is_outlier'
    ]].style.format({
        'views': '{:,.0f}',
        'velocity': '{:,.1f}',
        'engagement_rate': '{:.2%}',
        'z_score': '{:.2f}'
    }), use_container_width=True)

# --- Footer ---
st.markdown("---")
st.markdown("Free tool by [WriteWing.in](https://writewing.in) – Need an API key? [Get one here](https://console.cloud.google.com/apis/library/youtubedata-api.googleapis.com).")