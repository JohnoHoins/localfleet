"""
Local Whisper transcription via mlx-whisper (Apple Silicon optimized).
Model: whisper-small (~500MB, cached after first download).
"""
import os

import mlx_whisper

MODEL = "mlx-community/whisper-large-v3-turbo"


def transcribe_audio(audio_path: str) -> str:
    """Transcribe a WAV/audio file to text using local Whisper model.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Transcribed text string.

    Raises:
        FileNotFoundError: If audio_path does not exist.
        RuntimeError: If transcription fails.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    try:
        result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=MODEL)
        return result["text"].strip()
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}") from e
