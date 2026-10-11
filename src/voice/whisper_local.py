"""
Local Whisper transcription via mlx-whisper (Apple Silicon optimized).
Model: whisper-large-v3-turbo (cached after first download).

mlx-whisper only installs on Apple Silicon. If it is missing the rest of
the backend still runs; voice commands return a clear error instead of the
server failing to start.
"""
import os

try:
    import mlx_whisper
except ImportError:  # not Apple Silicon, or voice extras not installed
    mlx_whisper = None

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

    if mlx_whisper is None:
        raise RuntimeError(
            "Voice input needs mlx-whisper (Apple Silicon only): pip install mlx-whisper"
        )

    try:
        result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=MODEL)
        return result["text"].strip()
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}") from e
