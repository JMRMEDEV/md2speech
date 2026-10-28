"""md2speech - Markdown study materials to natural-sounding speech.

A lightweight CLI that converts Markdown into narration-ready text and
synthesizes it into audio using the ``kokoro-tts`` command-line backend.

Architecture (deliberately layered so pieces can be swapped independently):

1. ``parser``   - Markdown parsing + narration normalization (markdown-it-py).
2. ``chunking`` - Splitting narration into speech chunks + pause metadata.
3. ``tts``      - Kokoro synthesis backend wrapper (subprocess + caching).
4. ``audio``    - Silence/pause generation, concat, format conversion (ffmpeg).
5. ``playback`` - Configurable playback backend (default: paplay / WSLg).
6. ``cli``      - Command-line entry point tying everything together.
"""

__version__ = "0.1.0"
