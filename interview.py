#interview.py - OpenAI (Saving to Google Drive)

import streamlit as st
import time
import re
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
    save_interview_data_to_drive,
)
import os
import config
import pytz

from datetime import datetime
from urllib.parse import urlparse, parse_qs
from openai import OpenAI

api = "openai"

# Set page title and icon
st.set_page_config(page_title="Interview - OpenAI", page_icon=config.AVATAR_INTERVIEWER)

# Define Central Time (CT) timezone
central_tz = pytz.timezone("America/Chicago")

# Extract UID from URL query parameters
uid = None
try:
    query_params = st.experimental_get_query_params()
    for key in ['uid', 'UID', 'user_id', 'userId', 'participant_id']:
        if key in query_params:
            uid = query_params[key][0]
            break
except:
    pass

# Get current date and time in CT
current_datetime = datetime.now(central_tz).strftime("%Y-%m-%d_%H-%M-%S")

# Create username with model and UID (format: ChatGPT_UID_DateTimeStamp)
if "username" not in st.session_state or st.session_state.username is None:
    if uid:
        st.session_state.username = f"ChatGPT_{uid}_{current_datetime}"
    else:
        st.session_state.username = f"ChatGPT_NoUID_{current_datetime}"

# Store UID in session state for later use
if uid:
    st.session_state.uid = uid
    
# Create directories if they do not already exist
for directory in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
    os.makedirs(directory, exist_ok=True)

# Initialise session state
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])


# Check if interview previously completed
interview_previously_completed = check_if_interview_completed(
    config.TRANSCRIPTS_DIRECTORY, st.session_state.username
    )

# If app started but interview was previously completed
if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    completed_message = "Interview already completed."
    

# Add 'Quit' button to dashboard
col1, col2 = st.columns([0.85, 0.15])
with col2:
    if st.session_state.interview_active and st.button("Quit", help="End the interview."):
        st.session_state.interview_active = False
        st.session_state.messages.append({"role": "assistant", "content": "You have cancelled the interview."})
        try:
            transcript_path = save_interview_data(st.session_state.username, config.TRANSCRIPTS_DIRECTORY)
            if transcript_path:
                save_interview_data_to_drive(transcript_path)
        except Exception as e:
            st.error(f"Error saving data: {str(e)}")

# Display previous conversation (except system prompt)
for message in st.session_state.messages[1:]:
    avatar = config.AVATAR_INTERVIEWER if message["role"] == "assistant" else config.AVATAR_RESPONDENT
    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# Load API client
client = OpenAI(api_key=st.secrets["API_KEY"])
api_kwargs = {"stream": True}

# API kwargs
api_kwargs.update({
    "messages": st.session_state.messages,
    "model": config.MODEL,
    "max_tokens": config.MAX_OUTPUT_TOKENS,
})
if config.TEMPERATURE is not None:
    api_kwargs["temperature"] = config.TEMPERATURE

# Initialize first system message if history is empty
if not st.session_state.messages:
    st.session_state.messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
    with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
        try:
            stream = client.chat.completions.create(**api_kwargs)
            message_interviewer = st.write_stream(stream)
        except Exception as e:
            st.error(f"API Error: {str(e)}")
            message_interviewer = "Sorry, there was an error connecting to the interview service. Please try again later."

    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

    # Store initial backup - no need to save or upload yet as there's no conversation
    try:
        save_interview_data(
            username=st.session_state.username,
            transcripts_directory=config.BACKUPS_DIRECTORY,
        )
    except Exception as e:
        st.error(f"Error saving backup: {str(e)}")
        
# Main chat if interview is active
if st.session_state.interview_active:
    if message_respondent := st.chat_input("Your message here"):
        st.session_state.messages.append({"role": "user", "content": message_respondent})

        with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
            st.markdown(message_respondent)

        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            message_placeholder = st.empty()
            message_interviewer = ""

            try:
                stream = client.chat.completions.create(**api_kwargs)
                for message in stream:
                    text_delta = message.choices[0].delta.content
                    if text_delta:
                        message_interviewer += text_delta
                    if len(message_interviewer) > 5:
                        message_placeholder.markdown(message_interviewer + "▌")
                    if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                        message_placeholder.empty()
                        break
            except Exception as e:
                st.error(f"API Error: {str(e)}")
                message_interviewer = "Sorry, there was an error. Your response was saved, but we couldn't generate a reply."
                
            if not any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                message_placeholder.markdown(message_interviewer)
                st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

                try:
                    # Save a backup after each message
                    save_interview_data(
                        username=st.session_state.username,
                        transcripts_directory=config.BACKUPS_DIRECTORY,
                    )
                except Exception as e:
                    st.warning(f"Failed to save backup: {str(e)}")

            for code in config.CLOSING_MESSAGES.keys():
                if code in message_interviewer:
                    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})
                    st.session_state.interview_active = False
                    st.markdown(config.CLOSING_MESSAGES[code])

                    final_transcript_stored = False
                    retries = 0
                    max_retries = 10
                    transcript_path = None
                    
                    while not final_transcript_stored and retries < max_retries:
                        try:
                            transcript_path = save_interview_data(
                                username=st.session_state.username,
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                            )
                            # Double check the transcript was actually written
                            if transcript_path and os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 0:
                                final_transcript_stored = True
                            else:
                                final_transcript_stored = False
                        except Exception as e:
                            st.warning(f"Retry {retries+1}/{max_retries}: Error saving transcript - {str(e)}")
                        
                        time.sleep(0.1)
                        retries += 1

                    if retries == max_retries and not final_transcript_stored:
                        st.error("Error: Interview transcript could not be saved properly after multiple attempts!")
                        # Create emergency local transcript
                        emergency_file = f"emergency_transcript_{st.session_state.username}.txt"
                        try:
                            with open(emergency_file, "w") as t:
                                # Skip the system prompt when saving
                                for message in st.session_state.messages[1:]:
                                    t.write(f"{message['role']}: {message['content']}\n\n")
                            transcript_path = emergency_file
                            st.success(f"Created emergency transcript: {emergency_file}")
                        except Exception as e:
                            st.error(f"Failed to create emergency transcript: {str(e)}")

                    if transcript_path:
                        try:
                            # Save to Google Drive without displaying any ID information
                            save_interview_data_to_drive(transcript_path)
                        except Exception as e:
                            st.error(f"Failed to upload to Google Drive: {str(e)}")
