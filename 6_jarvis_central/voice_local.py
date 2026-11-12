"""Hands-free voice, 100% on this PC: speech segments -> local Whisper -> «Jarvis …» detection.

The browser only cuts speech segments (energy detection) and sends them to this
PC. Transcription runs on the CPU with faster-whisper, so the GPU stays free for
the Qwen model. Audio and text are never stored or written to the logs.
"""
from __future__ import annotations
import io
import re
import threading
import time
import unicodedata
import wave

# Spellings Whisper produces for «Jarvis» in Portuguese speech.
WAKE = re.compile(r'^\W*(?:(?:ok|ola|ei|hey|oi|o)\s+)?(?:jarvis|jarves|jarviz|jarvi|jarbas|jarvas|djarvis|dj?arvis|charvis|xarvis|garvis|jervis|jarvys|harvis)\b[\s,.!?:;-]*', re.I)
# Lenient first-pass check on the start of a segment (small model): anything that sounds like the name.
NAME_HINT = re.compile(r'(?:[dj]?jarv|jarb|jarr?v|charv|xarv|harv|jerv|gerv|garv|chav|jav[ie]s)')
STOP = re.compile(r'^(?:para|parar|pare|chega|silencio|cala-te|desliga|para de falar|para de ouvir)\b')


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def split_wake(text):
    """('jarvis, o que tenho amanhã?') -> (True, 'o que tenho amanhã?'). Text without the name -> (False, text)."""
    folded = fold(text.strip())
    match = WAKE.match(folded)
    if not match: return False, text.strip()
    # fold() keeps one character per character for normal Portuguese text, so the cut maps to the original.
    return True, text.strip()[match.end():].strip(' ,.!?:;-')


def is_stop(command):
    return bool(STOP.match(fold(command).strip(' ,.!?')))


def wav_to_float(data, max_seconds=15):
    """Mono/stereo 16-bit PCM WAV -> 16 kHz float samples (numpy array)."""
    import numpy as np
    try:
        with wave.open(io.BytesIO(data)) as source:
            channels, width, rate, frames = source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()
            if width != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000:
                raise ValueError('Formato de áudio não suportado: usa WAV PCM de 16 bits.')
            if frames/rate > max_seconds: raise ValueError('O excerto de voz é demasiado longo.')
            raw = source.readframes(frames)
    except (wave.Error, EOFError) as error:
        raise ValueError('O áudio recebido não é um WAV válido.') from error
    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)/32768.0
    if channels == 2: samples = samples.reshape(-1, 2).mean(axis=1)
    if rate != 16000 and len(samples):
        positions = np.linspace(0, len(samples)-1, int(len(samples)*16000/rate))
        samples = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)
    return samples


def cpu_threads(settings):
    import os
    return int(settings.get('stt_threads') or max(2, min(8, (os.cpu_count() or 4)-2)))


class LocalTranscriber:
    """Lazy-loaded faster-whisper on the CPU (int8). One transcription at a time.

    Two models: a tiny one checks only the first ~1.6 s of each segment for the
    name; the larger one transcribes the request only when the name was heard.
    """
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.quick = None
        self.error = None
        self.lock = threading.Lock()

    def model_name(self):
        return self.settings.get('stt_model', 'small')

    def quick_name(self):
        return self.settings.get('stt_wake_model', 'tiny')

    def status(self):
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return {'disponivel': False, 'motivo': 'O reconhecimento de voz local ainda não está instalado. Volta a correr INSTALAR_JARVIS.cmd.'}
        return {'disponivel': self.error is None, 'carregado': self.model is not None, 'modelo': self.model_name(),
                'modelo_rapido': self.quick_name(), 'motivo': self.error}

    def load(self, quick=False):
        name = self.quick_name() if quick else self.model_name()
        if (self.quick if quick else self.model) is None:
            from faster_whisper import WhisperModel
            try:
                model = WhisperModel(name, device='cpu', compute_type='int8', cpu_threads=cpu_threads(self.settings))
            except Exception as error:  # missing download, broken install
                self.error = 'Não consegui carregar o modelo de voz local: '+type(error).__name__
                raise RuntimeError(self.error) from error
            if quick: self.quick = model
            else: self.model = model
        return self.quick if quick else self.model

    def transcribe(self, data, quick=False, seconds=None):
        samples = wav_to_float(data)
        if seconds: samples = samples[:int(16000*seconds)]
        if len(samples) < 16000*0.3: return ''
        with self.lock:
            model = self.load(quick)
            segments, _ = model.transcribe(samples, language='pt', beam_size=1, vad_filter=False, without_timestamps=True,
                                           condition_on_previous_text=False, initial_prompt='Jarvis,')
            return ' '.join(segment.text.strip() for segment in segments).strip()

    def heard_name(self, data):
        """Fast first pass: does the start of the segment sound like «Jarvis»?"""
        return bool(NAME_HINT.search(fold(self.transcribe(data, quick=True, seconds=1.6))))


def listen(transcriber, data, mode):
    """mode='wake': only answer if the segment starts with «Jarvis». mode='comando': already awake."""
    started = time.monotonic()
    if mode == 'wake' and hasattr(transcriber, 'heard_name') and not transcriber.heard_name(data):
        # Speech not starting with the name is dropped after the quick check (no full transcription).
        return {'ativado': False, 'comando': '', 'parar': False, 'ms': round((time.monotonic()-started)*1000), 'rapido': True}
    text = transcriber.transcribe(data)
    if mode == 'comando':
        awake, command = True, split_wake(text)[1] if split_wake(text)[0] else text.strip()
    else:
        awake, command = split_wake(text)
    if not awake: text = command = ''  # speech not addressed to Jarvis is discarded and never returned
    return {'ativado': awake, 'comando': command, 'parar': bool(command) and is_stop(command),
            'ms': round((time.monotonic()-started)*1000)}
