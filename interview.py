#interview.py - OpenAI (Saving to Google Drive) - Updated Version

import streamlit as st
import time
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
from openai import OpenAI

# Set page title and icon
st.set_page_config(page_title="Interview - OpenAI", page_icon=config.AVATAR_INTERVIEWER)

# Define Central Time (CT) timezone
central_tz = pytz.timezone("America/Chicago")

# Get current date and time in CT
current_datetime = datetime.now(central_tz).strftime("%Y-%m-%d_%H-%M-%S")

# Create unique username with model identifier
if "username" not in st.session_state or st.session_state.username is None:
    st.session_state.username = f"User-{current_datetime}"

# Create directories if they do not already exist
for directory in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
    os.makedirs(directory, exist_ok=True)

# Initialize session state
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

# Check if interview previously completed
interview_previously_completed = check_if_interview_completed(
    config.TRANSCRIPTS_DIRECTORY, st.session_state.username, model=config.MODEL
    )

# If app started but interview was previously completed
if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    st.write("Interview already completed.")

# Add 'Quit' button to dashboard
col1, col2 = st.columns([0.85, 0.15])
with col2:
    if st.session_state.interview_active and st.button("Quit", help="End the interview."):
        st.session_state.interview_active = False
        st.session_state.messages.append({"role": "assistant", "content": "You have cancelled the interview."})
        try:
            transcript_path = save_interview_data(
                username=st.session_state.username, 
                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                model=config.MODEL,
                file_name_addition_transcript="_cancelled"
            )
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

# API kwargs
api_kwargs = {
    "stream": True,
    "messages": st.session_state.messages,
    "model": config.MODEL,
    "max_tokens": config.MAX_OUTPUT_TOKENS,
}
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

    # Store initial backup
    try:
        save_interview_data(
            username=st.session_state.username,
            transcripts_directory=config.BACKUPS_DIRECTORY,
            model=config.MODEL,
            file_name_addition_transcript="_initial_backup"
        )
    except Exception as e:
        st.error(f"Error saving initial backup: {str(e)}")
        
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

                # Save backup after each message
                try:
                    save_interview_data(
                        username=st.session_state.username,
                        transcripts_directory=config.BACKUPS_DIRECTORY,
                        model=config.MODEL,
                        file_name_addition_transcript="_backup"
                    )
                except Exception as e:
                    st.warning(f"Failed to save backup: {str(e)}")

            # Check for interview completion codes
            for code in config.CLOSING_MESSAGES.keys():
                if code in message_interviewer:
                    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})
                    st.session_state.interview_active = False
                    st.markdown(config.CLOSING_MESSAGES[code])

                    # Save final transcript with proper naming
                    final_transcript_stored = False
                    retries = 0
                    max_retries = 10
                    transcript_path = None
                    
                    while not final_transcript_stored and retries < max_retries:
                        try:
                            transcript_path = save_interview_data(
                                username=st.session_state.username,
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                                model=config.MODEL,
                                file_name_addition_transcript="_final"
                            )
                            # Verify the file was written successfully
                            if os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 0:
                                final_transcript_stored = True
                            else:
                                final_transcript_stored = False
                        except Exception as e:
                            st.warning(f"Retry {retries+1}/{max_retries}: Error saving transcript - {str(e)}")
                        
                        time.sleep(0.1)
                        retries += 1

                    if not final_transcript_stored:
                        st.error("Error: Interview transcript could not be saved properly after multiple attempts!")
                        # Create emergency local transcript
                        emergency_file = f"emergency_transcript_{config.MODEL}-{current_datetime}-{st.session_state.username}.txt"
                        try:
                            with open(emergency_file, "w") as t:
                                # Skip the system prompt when saving
                                for message in st.session_state.messages[1:]:
                                    t.write(f"{message['role']}: {message['content']}\n\n")
                            transcript_path = emergency_file
                            st.success(f"Created emergency transcript: {emergency_file}")
                        except Exception as e:
                            st.error(f"Failed to create emergency transcript: {str(e)}")

                    # Upload to Google Drive
                    if transcript_path:
                        try:
                            # Verify file content before upload
                            with open(transcript_path, "r") as f:
                                file_content = f.read()
                                if len(file_content.strip()) < 10:
                                    st.warning(f"Warning: Transcript file appears to be nearly empty before upload!")
                                    
                                    # Re-write the file with full content
                                    with open(transcript_path, "w") as t:
                                        for message in st.session_state.messages[1:]:
                                            t.write(f"{message['role']}: {message['content']}\n\n")
                            
                            save_interview_data_to_drive(transcript_path)
                        except Exception as e:
                            st.error(f"Failed to upload to Google Drive: {str(e)}")
