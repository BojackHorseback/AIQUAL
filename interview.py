import streamlit as st
import time
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)
import json
from boxsdk import JWTAuth, Client
from pathlib import Path
import os
import config

# Fetch the JWT configuration from environment variables or a file
jwt_config_json = os.getenv("BOX_JWT_CONFIG")

if jwt_config_json is None:
    # Try loading from file if environment variable isn't set
    if not os.path.exists(config.BOX_JWT_CONFIG_PATH):
        raise ValueError(f"Box JWT configuration file not found at {config.BOX_JWT_CONFIG_PATH}")
    with open(config.BOX_JWT_CONFIG_PATH, 'r') as f:
        jwt_config_json = f.read()

# Convert the JSON string into a Python dictionary
jwt_config = json.loads(jwt_config_json)

# Use JWTAuth to authenticate with Box using the config dictionary
auth = JWTAuth.from_settings_dict(jwt_config)

# Load API library
if "gpt" in config.MODEL.lower():
    api = "openai"
    from openai import OpenAI
elif "claude" in config.MODEL.lower():
    api = "anthropic"
    import anthropic
else:
    raise ValueError("Model does not contain 'gpt' or 'claude'; unable to determine API.")

# Set page title and icon
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

# Check if usernames and logins are enabled
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    else:
        st.session_state.username = username
else:
    st.session_state.username = "testaccount"

# Create directories if they do not already exist
os.makedirs(config.TRANSCRIPTS_DIRECTORY, exist_ok=True)
os.makedirs(config.TIMES_DIRECTORY, exist_ok=True)
os.makedirs(config.BACKUPS_DIRECTORY, exist_ok=True)

# Initialize session state
if "interview_active" not in st.session_state:
    st.session_state.interview_active = True

if "messages" not in st.session_state:
    st.session_state.messages = []

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time))

# Check if interview previously completed
interview_previously_completed = check_if_interview_completed(config.TIMES_DIRECTORY, st.session_state.username)

# If app started but interview was previously completed
if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    completed_message = "Interview already completed."
    st.markdown(completed_message)

# Add 'Quit' button to dashboard
col1, col2 = st.columns([0.85, 0.15])
with col2:
    if st.session_state.interview_active and st.button("Quit", help="End the interview."):
        st.session_state.interview_active = False
        quit_message = "You have cancelled the interview."
        st.session_state.messages.append({"role": "assistant", "content": quit_message})
        save_interview_data(st.session_state.username, config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY)

# Display previous conversation
for message in st.session_state.messages[1:]:
    avatar = config.AVATAR_INTERVIEWER if message["role"] == "assistant" else config.AVATAR_RESPONDENT
    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# Initialize API client
if api == "openai":
    client = OpenAI(api_key=st.secrets["API_KEY"])
    api_kwargs = {"stream": True}
elif api == "anthropic":
    client = anthropic.Anthropic(api_key=st.secrets["API_KEY"])
    api_kwargs = {"system": config.SYSTEM_PROMPT}

api_kwargs["messages"] = st.session_state.messages
api_kwargs["model"] = config.MODEL
api_kwargs["max_tokens"] = config.MAX_OUTPUT_TOKENS
if config.TEMPERATURE is not None:
    api_kwargs["temperature"] = config.TEMPERATURE

# Generate first message if no conversation
if not st.session_state.messages:
    if api == "openai":
        st.session_state.messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            stream = client.chat.completions.create(**api_kwargs)
            message_interviewer = st.write_stream(stream)
    elif api == "anthropic":
        st.session_state.messages.append({"role": "user", "content": "Hi"})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            message_placeholder = st.empty()
            message_interviewer = ""
            with client.messages.stream(**api_kwargs) as stream:
                for text_delta in stream.text_stream:
                    if text_delta:
                        message_interviewer += text_delta
                    message_placeholder.markdown(message_interviewer + "▌")
            message_placeholder.markdown(message_interviewer)

    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

    # Store first backup files
    save_interview_data(
        username=st.session_state.username,
        transcripts_directory=config.BACKUPS_DIRECTORY,
        times_directory=config.BACKUPS_DIRECTORY,
        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
    )

# Main chat if interview is active
if st.session_state.interview_active:
    if message_respondent := st.chat_input("Your message here"):
        st.session_state.messages.append({"role": "user", "content": message_respondent})

        # Display respondent message
        with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
            st.markdown(message_respondent)

        # Generate and display interviewer message
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            message_placeholder = st.empty()
            message_interviewer = ""

            if api == "openai":
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
            elif api == "anthropic":
                with client.messages.stream(**api_kwargs) as stream:
                    for text_delta in stream.text_stream:
                        if text_delta:
                            message_interviewer += text_delta
                        if len(message_interviewer) > 5:
                            message_placeholder.markdown(message_interviewer + "▌")
                        if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                            message_placeholder.empty()
                            break

            if not any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                message_placeholder.markdown(message_interviewer)
                st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

                # Store backup periodically
                try:
                    save_interview_data(
                        username=st.session_state.username,
                        transcripts_directory=config.BACKUPS_DIRECTORY,
                        times_directory=config.BACKUPS_DIRECTORY,
                        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
                        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
                    )
                except Exception as e:
                    st.warning(f"Error saving data: {e}")

            # Handle closing message codes
            for code in config.CLOSING_MESSAGES.keys():
                if code in message_interviewer:
                    st.session_state.interview_active = False
                    closing_message = config.CLOSING_MESSAGES[code]
                    st.markdown(closing_message)
                    st.session_state.messages.append({"role": "assistant", "content": closing_message})

                    # Save final transcript and time
                    final_transcript_stored = False
                    while not final_transcript_stored:
                        try:
                            save_interview_data(
                                username=st.session_state.username,
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                                times_directory=config.TIMES_DIRECTORY,
                                file_name_addition_transcript=f"_final_transcript_{st.session_state.start_time_file_names}",
                                file_name_addition_time=f"_final_time_{st.session_state.start_time_file_names}",
                            )
                            final_transcript_stored = True
                        except Exception as e:
                            st.warning(f"Error saving final data: {e}")
                    break  # Exit loop if interview ends

        # Save transcript to Box
        if not st.session_state.interview_active:
            try:
                # Initialize Box API client with JWT authentication
                client = Client(auth)

                # Define folder and file path
                folder = client.folder(config.BOX_FOLDER_ID).get()
                file_path = Path(config.TRANSCRIPTS_DIRECTORY) / f"{st.session_state.username}_interview_transcript.txt"

                # Upload interview transcript to Box
                file = folder.upload(file_path)
                st.markdown(f"Interview transcript saved to Box: {file.name}")

            except Exception as e:
                st.warning(f"Error uploading file to Box: {e}")

        # End of the interview
        if not st.session_state.interview_active:
            st.stop()

# Streamlit UI
if st.session_state.interview_active:
    st.title("Interview in Progress")
    st.markdown("Please answer the following questions.")
else:
    st.title("Interview Completed")
    st.markdown("Thank you for completing the interview!")
    st.markdown(f"Transcript saved for {st.session_state.username}.")
