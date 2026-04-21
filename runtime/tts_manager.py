import queue
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TTSRequest:
    """
    One queued text-to-speech request.
    """
    text: str
    voice_name: str | None
    volume: float


class TTSManager:
    """
    Lightweight queued TTS manager.

    Supports:
    - "male"
    - "female"
    - exact system voice names
    - partial name fallback
    - default fallback

    Design:
    - requests are queued
    - one background worker speaks them sequentially
    - pyttsx3 engine is created per request for stability
    """

    FEMALE_KEYWORDS = [
        "female", "woman", "zira", "hazel", "susan", "sophie", "eva", "hedda", "katja",
    ]
    MALE_KEYWORDS = [
        "male", "man", "david", "mark", "george", "james", "daniel", "alex",
    ]

    def __init__(self):
        self._queue: queue.Queue[TTSRequest] = queue.Queue()
        self._running = True

        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="TTSManagerWorker",
        )
        self._thread.start()

    # ============================================================
    # PUBLIC API
    # ============================================================

    def speak_async(
        self,
        text: str,
        voice_name: str | None = None,
        volume: float = 1.0,
    ):
        """
        Queue one speech request.

        Empty text is ignored.
        Volume is normalized to [0.0 .. 1.0].
        """
        text = str(text or "").strip()
        if not text:
            return

        self._queue.put(
            TTSRequest(
                text=text,
                voice_name=voice_name,
                volume=self._normalize_volume(volume),
            )
        )

    def list_voices(self) -> list[str]:
        """
        Return available system voice names.

        Best-effort only:
        - returns [] if pyttsx3 or voice discovery fails
        """
        engine = None
        try:
            import pyttsx3

            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            return [
                str(voice.name)
                for voice in voices
                if getattr(voice, "name", None)
            ]
        except Exception:
            return []
        finally:
            self._safe_stop_engine(engine)

    def stop(self):
        """
        Stop the background worker.

        Uporabimo prazen request kot wake-up sentinel,
        da worker ne ostane blokiran na queue.get().
        """
        self._running = False
        self._queue.put(TTSRequest(text="", voice_name=None, volume=1.0))

    # ============================================================
    # WORKER
    # ============================================================

    def _worker_loop(self):
        while self._running:
            request = self._queue.get()

            if not self._running:
                break

            if not request.text:
                continue

            self._speak_once(request)

    def _speak_once(self, request: TTSRequest):
        """
        Speak one queued request.

        Engine ustvarimo za vsak request posebej.
        To je malo manj optimalno kot persistent engine,
        ampak je običajno stabilnejše pri pyttsx3.
        """
        engine = None
        try:
            import pyttsx3

            engine = pyttsx3.init()
            self._apply_voice(engine, request.voice_name)
            engine.setProperty("volume", request.volume)
            engine.say(request.text)
            engine.runAndWait()
        except Exception as ex:
            print(f"TTS error: {ex}")
        finally:
            self._safe_stop_engine(engine)

    # ============================================================
    # VOICE SELECTION
    # ============================================================

    def _apply_voice(self, engine: Any, voice_name: str | None):
        """
        Apply requested voice to pyttsx3 engine.

        Order:
        1. exact full name match
        2. semantic male/female mapping
        3. partial substring match
        4. leave engine default voice unchanged
        """
        if not voice_name:
            return

        requested = str(voice_name).strip().lower()
        if not requested or requested == "default":
            return

        try:
            voices = engine.getProperty("voices") or []
            if not voices:
                return

            selected = self._find_exact_voice(voices, requested)
            if selected is not None:
                engine.setProperty("voice", selected.id)
                return

            if requested in {"male", "female"}:
                selected = self._find_gender_voice(voices, requested)
                if selected is not None:
                    engine.setProperty("voice", selected.id)
                    return

            selected = self._find_partial_voice(voices, requested)
            if selected is not None:
                engine.setProperty("voice", selected.id)
                return

        except Exception as ex:
            print(f"Failed to apply voice '{voice_name}': {ex}")

    def _find_exact_voice(self, voices, requested: str):
        for voice in voices:
            name = str(getattr(voice, "name", "")).strip().lower()
            if name == requested:
                return voice
        return None

    def _find_partial_voice(self, voices, requested: str):
        for voice in voices:
            name = str(getattr(voice, "name", "")).strip().lower()
            if requested in name:
                return voice
        return None

    def _find_gender_voice(self, voices, gender: str):
        """
        Best-effort male/female mapping using voice name/id heuristics.

        To ni popolna znanost:
        pyttsx3 običajno ne ponuja zanesljivega 'gender' fielda,
        zato uporabimo keyword scoring.
        """
        gender = str(gender).strip().lower()

        preferred_keywords = (
            self.FEMALE_KEYWORDS if gender == "female" else self.MALE_KEYWORDS
        )
        opposite_keywords = (
            self.MALE_KEYWORDS if gender == "female" else self.FEMALE_KEYWORDS
        )

        scored: list[tuple[int, Any]] = []

        for voice in voices:
            blob = self._voice_blob(voice)
            score = self._score_voice_blob(blob, preferred_keywords, opposite_keywords)
            scored.append((score, voice))

        scored.sort(key=lambda item: item[0], reverse=True)

        if not scored:
            return None

        best_score, best_voice = scored[0]

        # Če nismo našli nič pametnega, uporabimo preprost fallback.
        if best_score <= 0:
            return self._fallback_gender_voice(voices, gender)

        return best_voice

    def _voice_blob(self, voice: Any) -> str:
        name = str(getattr(voice, "name", "")).strip().lower()
        voice_id = str(getattr(voice, "id", "")).strip().lower()
        return f"{name} {voice_id}"

    def _score_voice_blob(
        self,
        blob: str,
        preferred_keywords: list[str],
        opposite_keywords: list[str],
    ) -> int:
        score = 0

        for keyword in preferred_keywords:
            if keyword in blob:
                score += 10

        for keyword in opposite_keywords:
            if keyword in blob:
                score -= 10

        # Malo preferiraj Microsoft voice-e na Windows.
        if "microsoft" in blob:
            score += 2

        return score

    def _fallback_gender_voice(self, voices, gender: str):
        """
        Final fallback when scoring found nothing useful.

        Namenoma ohranja trenutno obnašanje:
        - female -> first voice if available
        - male   -> second voice if available, else first
        """
        if not voices:
            return None

        if gender == "female":
            return voices[0]

        if gender == "male":
            if len(voices) >= 2:
                return voices[1]
            return voices[0]

        return voices[0]

    # ============================================================
    # SMALL HELPERS
    # ============================================================

    @staticmethod
    def _normalize_volume(volume: float) -> float:
        return max(0.0, min(1.0, float(volume)))

    @staticmethod
    def _safe_stop_engine(engine):
        if engine is None:
            return

        try:
            engine.stop()
        except Exception:
            pass