"""Turn what happened in a client meeting into a structured written record.

Nothing here can attend the meeting, so the input is always something a human
produced: rough notes typed during the call, or an audio recording. Meet will
not record on a free Google account, so notes are the path that always works
and audio is the upgrade when a recording happens to exist.

Every function returns {"status": "success", ...} or {"status": "error",
"message": ...}, matching api_integrations.py so callers can treat both the
same way.
"""
import os

from groq import Groq

# An unbounded call here freezes the portal, same reasoning as HTTP_TIMEOUT in
# api_integrations.py. Transcription is slower than chat, so it gets more room.
SUMMARY_TIMEOUT = 60.0
TRANSCRIBE_TIMEOUT = 180.0

# Not the llama-3.1-8b-instant the AI assistant runs on. This writes a record a
# client may read, where a weak model's failure mode is inventing an agreement
# nobody made.
SUMMARY_MODEL = "llama-3.3-70b-versatile"
TRANSCRIBE_MODEL = "whisper-large-v3"

# Groq rejects uploads over 25MB. Catch it here with a sentence the user can act
# on rather than letting the API return a raw 413.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

AUDIO_TYPES = ["mp3", "mp4", "m4a", "wav", "webm", "ogg", "flac"]

SUMMARY_PROMPT = """You are minuting a meeting between an agency and its client.

Write the record under exactly these three headings, as markdown:

**Purpose** — why the meeting happened, in one or two sentences.
**Agreements** — what was actually agreed, as bullets.
**Disagreements / Open Items** — what was disputed, declined, or left unresolved, as bullets.

Rules:
- Use ONLY what is in the source below. Never add detail that is not there.
- If a heading has nothing to report, write "Not discussed" under it. Do not pad it.
- Do not invent names, dates, figures, or commitments.
- Keep it terse and factual. This may be shown to the client.
"""


def _client(timeout):
    """A Groq client, or an error dict if the key is missing."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None, {"status": "error", "message": "Missing GROQ_API_KEY. Add it to your .env file."}
    return Groq(api_key=api_key, timeout=timeout), None


def summarize_meeting(raw_notes: str = None, transcript: str = None):
    """Summarize a meeting into Purpose / Agreements / Disagreements.

    Prefers the transcript when there is one: it is what was actually said,
    where notes are only what someone remembered to write down.
    """
    source = (transcript or "").strip() or (raw_notes or "").strip()
    if not source:
        return {"status": "error", "message": "Nothing to summarize -- add notes or a recording first."}

    client, err = _client(SUMMARY_TIMEOUT)
    if err:
        return err

    origin = "TRANSCRIPT" if (transcript or "").strip() else "ROUGH NOTES"

    try:
        response = client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"{origin} OF THE MEETING:\n\n{source}"},
            ],
            temperature=0.2,
        )
        return {"status": "success", "summary": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"status": "error", "message": f"Groq summary failed: {str(e)}"}


def transcribe_recording(file_bytes: bytes, filename: str):
    """Transcribe a meeting recording via Whisper."""
    if not file_bytes:
        return {"status": "error", "message": "The recording is empty."}

    if len(file_bytes) > MAX_AUDIO_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        return {
            "status": "error",
            "message": f"Recording is {size_mb:.0f}MB. Groq's limit is 25MB -- "
                       f"re-export it as mono audio at a lower bitrate, or summarize from notes instead.",
        }

    client, err = _client(TRANSCRIBE_TIMEOUT)
    if err:
        return err

    try:
        response = client.audio.transcriptions.create(
            file=(filename, file_bytes),
            model=TRANSCRIBE_MODEL,
        )
        return {"status": "success", "transcript": response.text.strip()}
    except Exception as e:
        return {"status": "error", "message": f"Transcription failed: {str(e)}"}
