"""Tests for voice transcription module and /api/voice-command endpoint."""
import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.schemas import (
    FleetCommand, MissionType, DomainType, AssetCommand, Waypoint,
)
from src.fleet.fleet_commander import FleetCommander
from src.api.server import create_app


@pytest.fixture
def commander():
    return FleetCommander()


@pytest.fixture
def client(commander):
    app = create_app(commander)
    return TestClient(app)


# ===== whisper_local.transcribe_audio =====

class TestTranscribeAudio:
    def test_returns_string(self):
        """transcribe_audio returns a stripped string."""
        mock_result = {"text": "  patrol the harbor  "}
        with patch("src.voice.whisper_local.mlx_whisper") as mock_whisper:
            mock_whisper.transcribe.return_value = mock_result
            from src.voice.whisper_local import transcribe_audio
            with patch("os.path.exists", return_value=True):
                text = transcribe_audio("/tmp/test.wav")
        assert isinstance(text, str)
        assert text == "patrol the harbor"

    def test_file_not_found(self):
        from src.voice.whisper_local import transcribe_audio
        with pytest.raises(FileNotFoundError):
            transcribe_audio("/nonexistent/path.wav")

    def test_transcription_failure(self):
        with patch("src.voice.whisper_local.mlx_whisper") as mock_whisper:
            mock_whisper.transcribe.side_effect = Exception("model error")
            from src.voice.whisper_local import transcribe_audio
            with patch("os.path.exists", return_value=True):
                with pytest.raises(RuntimeError, match="Transcription failed"):
                    transcribe_audio("/tmp/test.wav")


# ===== POST /api/voice-command =====

class TestVoiceCommandEndpoint:
    def test_voice_command_success(self, client):
        """Upload audio → transcribe → LLM parse → CommandResponse."""
        fake_cmd = FleetCommand(
            mission_type=MissionType.PATROL,
            assets=[
                AssetCommand(
                    asset_id="alpha",
                    domain=DomainType.SURFACE,
                    waypoints=[Waypoint(x=100, y=200)],
                    speed=5.0,
                ),
            ],
        )
        with patch("src.api.routes.transcribe_audio", return_value="patrol the harbor"), \
             patch("src.fleet.fleet_commander.parse_fleet_command", return_value=fake_cmd):
            resp = client.post(
                "/api/voice-command",
                files={"audio": ("test.wav", io.BytesIO(b"fake-audio-data"), "audio/wav")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["fleet_command"]["mission_type"] == "patrol"

    def test_voice_command_transcription_error(self, client):
        """If transcription fails, return error response."""
        with patch("src.api.routes.transcribe_audio", side_effect=RuntimeError("bad audio")):
            resp = client.post(
                "/api/voice-command",
                files={"audio": ("test.wav", io.BytesIO(b"bad"), "audio/wav")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "bad audio" in data["error"]

    def test_voice_command_no_file(self, client):
        """Missing audio field returns 422."""
        resp = client.post("/api/voice-command")
        assert resp.status_code == 422
