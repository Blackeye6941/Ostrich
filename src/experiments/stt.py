"""Real-time streaming speech-to-text (audio note transcription).

Transcribes microphone audio word-by-word with low latency using Needle Whistle,
similar to Claude's audio note transcription.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import queue
import shutil
import sys
import threading
import time
import wave
from typing import Generator

import needle
import numpy as np
import pyaudio


RATE = 16000
CHUNK = 1024
CHANNELS = 1
FORMAT = pyaudio.paInt16

# Stream chunking: 0.5s provides optimal balance of low latency and recognition accuracy
STREAM_CHUNK_SECONDS = 0.5
STREAM_CHUNK_SAMPLES = int(RATE * STREAM_CHUNK_SECONDS)

# ANSI terminal colors
DIM = "\033[90m"
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K\r"


@contextlib.contextmanager
def suppress_c_stderr():
    """Suppress C-level stderr messages (e.g., ALSA / JACK initialization warnings)."""
    try:
        stderr_fd = sys.stderr.fileno()
        with open(os.devnull, "w") as devnull:
            old_stderr = os.dup(stderr_fd)
            try:
                os.dup2(devnull.fileno(), stderr_fd)
                yield
            finally:
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stderr)
    except Exception:
        yield


class RealtimeTranscriber:
    """Manages real-time word-by-word streaming audio transcription."""

    def __init__(
        self,
        language: str | None = None,
        keywords: list[str] | None = None,
        chunk_seconds: float = STREAM_CHUNK_SECONDS,
    ):
        self.language = language
        self.keywords = keywords
        self.chunk_samples = max(1600, int(RATE * chunk_seconds))
        self.stt = needle.Whistle()

        self.audio_queue: queue.Queue[bytes | None] = queue.Queue()
        self.stop_event = threading.Event()
        self.committed_text: str = ""
        self.last_drawn_rows: int = 0
        self.is_tty = sys.stdout.isatty()

    def _audio_capture_worker(self, stream: pyaudio.Stream):
        """Dedicated thread to continuously capture audio without buffer overflow."""
        while not self.stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                if data:
                    self.audio_queue.put(data)
            except Exception:
                break
        self.audio_queue.put(None)

    def _chunk_stream(self) -> Generator[np.ndarray, None, None]:
        """Convert incoming raw audio bytes into normalized float32 chunks for Whistle."""
        buffer: list[np.ndarray] = []
        buffered_samples = 0

        while True:
            try:
                # Use a small timeout so we can periodically check stop_event
                data = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                if self.stop_event.is_set():
                    break
                continue

            if data is None:
                break

            # Convert 16-bit PCM to float32 in [-1.0, 1.0]
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            buffer.append(samples)
            buffered_samples += len(samples)

            if buffered_samples >= self.chunk_samples:
                yield np.concatenate(buffer)
                buffer = []
                buffered_samples = 0

        if buffer:
            yield np.concatenate(buffer)

    def _render_display(self, committed: str, pending: str, status: str = "Recording"):
        """Render the audio note word-by-word in real time (Claude-style)."""
        if not self.is_tty:
            # For non-interactive output, we only emit newly committed text
            return

        cols = max(shutil.get_terminal_size((80, 24)).columns, 40)

        status_badge = f"{GREEN}● {status}{RESET}" if status == "Recording" else f"{YELLOW}◌ {status}{RESET}"
        header = f"{status_badge} {DIM}(Press Enter or Ctrl+C to finish note){RESET}\n"

        committed_clean = committed.strip()
        pending_clean = pending.strip()

        if committed_clean and pending_clean:
            text_flow = f"{committed_clean} {DIM}{pending_clean}{RESET}"
            plain_len = len(committed_clean) + 1 + len(pending_clean)
        elif committed_clean:
            text_flow = committed_clean
            plain_len = len(committed_clean)
        elif pending_clean:
            text_flow = f"{DIM}{pending_clean}{RESET}"
            plain_len = len(pending_clean)
        else:
            text_flow = f"{DIM}[Listening... speak into your microphone]{RESET}"
            plain_len = 45

        body = f"📝 {BOLD}Note:{RESET} {text_flow}"

        # Estimate row count for multiline cursor rewinding
        prefix_len = 8  # "📝 Note: "
        total_len = prefix_len + plain_len
        body_rows = max(1, (total_len + cols - 1) // cols)
        total_rows = 1 + body_rows  # header line + body rows

        # Clear previously drawn lines
        if self.last_drawn_rows > 0:
            sys.stdout.write(f"\r\033[{self.last_drawn_rows}A\033[J")

        sys.stdout.write(header + body + "\n")
        sys.stdout.flush()
        self.last_drawn_rows = total_rows

    def transcribe_mic(self) -> str:
        """Start live microphone audio note transcription."""
        with suppress_c_stderr():
            audio = pyaudio.PyAudio()

        stream = None
        capture_thread = None

        try:
            with suppress_c_stderr():
                stream = audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                )

            # Start audio capture thread
            capture_thread = threading.Thread(
                target=self._audio_capture_worker,
                args=(stream,),
                daemon=True,
            )
            capture_thread.start()

            # Background thread to allow user to press Enter to finish recording
            def check_stdin():
                try:
                    if sys.stdin.isatty():
                        sys.stdin.readline()
                        self.stop_event.set()
                except (EOFError, KeyboardInterrupt, Exception):
                    self.stop_event.set()

            stdin_thread = threading.Thread(target=check_stdin, daemon=True)
            stdin_thread.start()

            self._render_display("", "", status="Recording")

            # Stream through Whistle
            for step in self.stt.stream(
                self._chunk_stream(),
                language=self.language,
                keywords=self.keywords,
            ):
                new_text = step.get("text", "")
                pending = step.get("pending", "")

                if new_text:
                    if (
                        self.committed_text
                        and not self.committed_text.endswith(" ")
                        and not new_text.startswith(" ")
                        and not new_text.startswith((".", ",", "!", "?", ":", ";"))
                    ):
                        self.committed_text += " " + new_text
                    elif self.committed_text and self.committed_text.endswith(" ") and new_text.startswith(" "):
                        self.committed_text += new_text.lstrip()
                    else:
                        self.committed_text += new_text

                    if not self.is_tty:
                        sys.stdout.write(new_text + " ")
                        sys.stdout.flush()

                self._render_display(
                    self.committed_text,
                    pending,
                    status="Stopping..." if self.stop_event.is_set() else "Recording",
                )

                if self.stop_event.is_set() and not pending:
                    break

        except KeyboardInterrupt:
            self.stop_event.set()
        finally:
            self.stop_event.set()

            if capture_thread and capture_thread.is_alive():
                capture_thread.join(timeout=1.0)

            if stream is not None:
                try:
                    if stream.is_active():
                        stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

            audio.terminate()

        # Clean final output
        final_transcript = self.committed_text.strip()
        if self.is_tty:
            if self.last_drawn_rows > 0:
                sys.stdout.write(f"\r\033[{self.last_drawn_rows}A\033[J")
            print(f"\n{GREEN}{BOLD}✓ Final Transcript:{RESET}")
            print(final_transcript if final_transcript else f"{DIM}(No speech detected){RESET}")
            print()
        else:
            print()

        return final_transcript

    def transcribe_file(self, wav_path: str) -> str:
        """Transcribe a WAV file with simulated real-time word-by-word streaming."""
        with wave.open(wav_path, "rb") as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        # Extract 16-bit PCM mono
        raw = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            raw = raw[::channels]

        if rate != RATE:
            # Simple linear resampling if not 16000 Hz
            num_samples = int(len(raw) * RATE / rate)
            raw = np.interp(
                np.linspace(0, len(raw), num_samples, endpoint=False),
                np.arange(len(raw)),
                raw,
            ).astype(np.int16)

        audio_samples = raw.astype(np.float32) / 32768.0

        def file_chunks():
            for i in range(0, len(audio_samples), self.chunk_samples):
                yield audio_samples[i : i + self.chunk_samples]

        self._render_display("", "", status="Transcribing File")

        for step in self.stt.stream(
            file_chunks(),
            language=self.language,
            keywords=self.keywords,
        ):
            new_text = step.get("text", "")
            pending = step.get("pending", "")

            if new_text:
                if (
                    self.committed_text
                    and not self.committed_text.endswith(" ")
                    and not new_text.startswith(" ")
                    and not new_text.startswith((".", ",", "!", "?", ":", ";"))
                ):
                    self.committed_text += " " + new_text
                else:
                    self.committed_text += new_text

                if not self.is_tty:
                    sys.stdout.write(new_text + " ")
                    sys.stdout.flush()

            self._render_display(self.committed_text, pending, status="Transcribing File")

        final_transcript = self.committed_text.strip()
        if self.is_tty:
            if self.last_drawn_rows > 0:
                sys.stdout.write(f"\r\033[{self.last_drawn_rows}A\033[J")
            print(f"\n{GREEN}{BOLD}✓ Final Transcript:{RESET}")
            print(final_transcript if final_transcript else f"{DIM}(No speech detected){RESET}")
            print()
        else:
            print()

        return final_transcript


def main():
    parser = argparse.ArgumentParser(
        description="Real-time word-by-word audio note transcription using Needle Whistle."
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Path to an existing WAV audio file to transcribe in real-time.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=None,
        choices=["en", "de", "fr", "es", "it", "nl", "pl"],
        help="Force a specific language (default: auto-detect).",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        default=None,
        help="Comma-separated keywords for recognition biasing (e.g. 'Claude,Needle,Python').",
    )
    parser.add_argument(
        "--chunk-size",
        type=float,
        default=STREAM_CHUNK_SECONDS,
        help=f"Chunk duration in seconds for streaming inference (default: {STREAM_CHUNK_SECONDS}s).",
    )

    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else None

    print(f"\n{CYAN}{BOLD}🎙️  Audio Note Transcriber (Real-Time Word-by-Word){RESET}")
    print(f"{DIM}Model: Needle Whistle | Chunk Size: {args.chunk_size}s | Language: {args.language or 'auto-detect'}{RESET}\n")

    transcriber = RealtimeTranscriber(
        language=args.language,
        keywords=keywords,
        chunk_seconds=args.chunk_size,
    )

    if args.file:
        transcriber.transcribe_file(args.file)
    else:
        transcriber.transcribe_mic()


if __name__ == "__main__":
    main()
