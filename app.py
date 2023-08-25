import streamlit as st
from yt_dlp import YoutubeDL
import os
import re
from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel
from clarifai_grpc.grpc.api import resources_pb2, service_pb2, service_pb2_grpc
from clarifai_grpc.grpc.api.status import status_code_pb2

format_prompt = '''Below is the transcript of a video. Please correct the capitalization and punctuation, including making separate paragraphs, without changing any of the text. If a word is misspelled, correct the word, and if a word does not exist take your best guess as to the correct word. Only return the corrected text without commentary:'''
video_prompt = '[INST] Write a YouTube video title and video description for the following video script. [/INST]'

# Model configurations
models = {
    'Llama2-7b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'Llama2-7b-chat',
        'MODEL_VERSION_ID': 'e52af5d6bc22445aa7a6761f327f7129'
    },
    'Llama2-13b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'llama2-13b-chat',
        'MODEL_VERSION_ID': '79a1af31aa8249a99602fc05687e8f40'
    },
    'Llama2-13b-alternative': {
        'USER_ID': 'clarifai',
        'APP_ID': 'ml',
        'MODEL_ID': 'llama2-13b-alternative',
        'MODEL_VERSION_ID': 'f5ef18073bdc4875ae9caa970f614eb3'
    },
    'Llama2-70b-chat': {
        'USER_ID': 'meta',
        'APP_ID': 'Llama-2',
        'MODEL_ID': 'llama2-70b-chat',
        'MODEL_VERSION_ID': '6c27e86364ba461d98de95cddc559cb3'
    },
    'Llama2-70b-alternative': {
        'USER_ID': 'clarifai',
        'APP_ID': 'ml',
        'MODEL_ID': 'llama2-70b-alternative',
        'MODEL_VERSION_ID': '75a64576ad664768b828f1047acdae30'
    },
    'GPT-3': {
        'USER_ID': 'openai',
        'APP_ID': 'chat-completion',
        'MODEL_ID': 'GPT-3_5-turbo',
        'MODEL_VERSION_ID': '8ea3880d08a74dc0b39500b99dfaa376'
    },
    'GPT-4': {
        'USER_ID': 'openai',
        'APP_ID': 'chat-completion',
        'MODEL_ID': 'GPT-4',
        'MODEL_VERSION_ID': 'ad16eda6ac054796bf9f348ab6733c72'
    }
}

def filter_subtitles(subtitle_str):
    lines = subtitle_str.strip().split("\n")
    
    past_header = False
    content_lines = []
    capture_next = False

    for line in lines:
        line = line.strip()

        if "-->" in line:
            past_header = True
            capture_next = True
            continue
        
        if not past_header:
            continue
        
        # If line has no tags and we are set to capture, add to content
        if capture_next and line and "<" not in line and ">" not in line:
            if not content_lines or (content_lines and content_lines[-1] != line):
                content_lines.append(line)
            capture_next = False

    return "\n".join(content_lines)

def extract_video_id(url_or_id):
    """
    Extracts the YouTube video ID from a URL or returns the ID if it's already just an ID.
    """
    match = re.search(r"(?<=v=)[\w-]+", url_or_id)
    return match.group(0) if match else url_or_id

def download_subtitles(video_id):
    """
    Downloads subtitles for a given video ID and returns the content.
    """
    temp_file_path = "/tmp/temp_subtitle_file"
    full_temp_file_path = temp_file_path + ".en.vtt"
    ydl_opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "sleep_interval_subtitles": 1,
        "outtmpl": temp_file_path,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_id])
    
    with open(full_temp_file_path, "r", encoding="utf-8") as file:
        content = file.read()
    
    # Clean up the temporary file
    os.remove(full_temp_file_path)

    return filter_subtitles(content).replace('\n', ' ').replace('\r', '')

def format_with_clarifai_api(raw_text, prompt):

    full_prompt = prompt + '\n' + raw_text + '\n'
    PAT = os.environ.get('CLARIFAI_PAT') 

    if not PAT:  # If PAT is not set via environment variable
        try:
            PAT = st.secrets['CLARIFAI_PAT']
        except KeyError:
            st.error("Failed to retrieve the Clarifai Personal Access Token!")
            PAT = None

    channel = ClarifaiChannel.get_grpc_channel()
    stub = service_pb2_grpc.V2Stub(channel)

    metadata = (('authorization', 'Key ' + PAT),)

    userDataObject = resources_pb2.UserAppIDSet(
        user_id=selected_model['USER_ID'], 
        app_id=selected_model['APP_ID']
    )

    post_model_outputs_response = stub.PostModelOutputs(
        service_pb2.PostModelOutputsRequest(
            user_app_id=userDataObject,
            model_id=selected_model['MODEL_ID'],
            version_id=selected_model['MODEL_VERSION_ID'],
            inputs=[
                resources_pb2.Input(
                    data=resources_pb2.Data(
                        text=resources_pb2.Text(
                            raw=full_prompt  # Send the raw text here
                        )
                    )
                )
            ]
        ),
        metadata=metadata
    )

    if post_model_outputs_response.status.code != status_code_pb2.SUCCESS:
        st.error(f"Error from Clarifai API: {post_model_outputs_response.status.description}")
        return None

    output = post_model_outputs_response.outputs[0]
    # Check if output is not None and then strip it
    return output.data.text.raw.strip() if output.data.text.raw else None

def extract_string(s):
    # Search for content inside triple quotes
    match = re.search(r'\"\"\"(.*?)\"\"\"', s, re.DOTALL)
    return match.group(1) if match else None

st.title("YouTube Script, Title, and Description Generator")

# Callout text
st.markdown('''
**This app is designed to automate some of the steps in creating a YouTube video.**
When you upload a video, YouTube will automatically create English subtitled word-by-word. Sometimes it does a great job, sometimes a poor one, but it's usually a great starting place for creating proper subtitles for your video. Ideally this should work with videos about ~5 minutes long at most, since longer videos will have longer scripts that may exceed the context of the LLM used.

To use this app as intended, do the following:

- Upload an English language YouTube video and wait for YouTube to create the automatically generated subtitles.
- Once YouTube has generated the subtitles, use this app. Enter either the full URL or just the video code (for example, either `https://www.youtube.com/watch?v=HbuOu9zq2UE` or `HbuOu9zq2UE`)
- The app will pull the auto-generated subtitles. Choose a model to try. The choices are `Llama-2-7b`, `Llama-2-13b`, and `Llama-2-13b`, as well as OpenAI's `GPT-3` and `GPT-4`.
- The app will create a formatted version of the script. You may need to copy it to another document and review it for errors and corrections, as the speech-to-text from YouTube and the punctuating from the LLM may have left a few problems.
- Click the "Generate title and description" to have the model propose a title and description for the video.

This way, the steps of formatting the script for subtitles, the video title, and the video description, can all be automated!
''')

# Input for YouTube URL or video ID
url_or_id = st.text_input("Enter YouTube URL or Video ID:")

# Check if 'previous_url_or_id' exists in session_state, if not initialize it
if 'previous_url_or_id' not in st.session_state:
    st.session_state.previous_url_or_id = None

# Detect if the entered url_or_id has changed
if st.session_state.previous_url_or_id != url_or_id:
    st.session_state.previous_url_or_id = url_or_id
    st.session_state.subtitles = None
    st.session_state.formatted_text = None

# Create containers for the video and subtitles to prevent their disappearance upon model change
video_container = st.empty()
subtitles_container = st.empty()

# Add the model selection dropdown
selected_model_name = st.selectbox("Select Model:", list(models.keys()))
selected_model = models[selected_model_name]

# Check if 'subtitles' exist in session_state, if not initialize it
if 'subtitles' not in st.session_state:
    st.session_state.subtitles = None

# If URL or ID is provided and subtitles haven't been fetched yet, process it
if url_or_id and not st.session_state.subtitles:
    video_id = extract_video_id(url_or_id)
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"  # Construct the full YouTube URL
    
    # Display the YouTube video embedded on the page within the container
    video_container.video(youtube_url)

    try:
        st.session_state.subtitles = download_subtitles(video_id)
        subtitles_container.text_area("Subtitles:", value=st.session_state.subtitles, height=400)
    except Exception as e:
        st.error(f"An error occurred: {e}")
else:
    # If a URL or ID had been previously provided and is still in the input box, then re-display the video and subtitles
    if url_or_id:
        video_id = extract_video_id(url_or_id)
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        video_container.video(youtube_url)

        # Check if subtitles have been fetched already and display them
        if st.session_state.subtitles:
            subtitles_container.text_area("Subtitles:", value=st.session_state.subtitles, height=400)

if 'formatted_text' not in st.session_state:
    st.session_state.formatted_text = None

if st.session_state.subtitles:  # If raw subtitles are available in the session state
    if st.button("Punctuate Script"):
        st.session_state.formatted_text = format_with_clarifai_api(st.session_state.subtitles, format_prompt)

    # Only show the formatted text if it exists
    if st.session_state.formatted_text:
        st.text_area("Formatted Subtitles:", value=st.session_state.formatted_text, height=400)
        
        # Check for the st.session_state.formatted_text before showing the "Generate title and description" button
        if st.button("Generate title and description"):
            # Generate title and description
            video_description = format_with_clarifai_api(st.session_state.formatted_text, video_prompt)
            st.text_area("Generated Title and Description:", value=video_description, height=400)

st.write("""
**Note**: Please ensure the video has available subtitles. 
Also, be aware of YouTube's terms of service when downloading and using content.
""")
