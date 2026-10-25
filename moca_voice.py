"""
One voice for every MoCA task.

Every instruction the patient hears goes through speak_instruction(). It:
  * prints the text in the console (so the examiner can see what was said),
  * reads it aloud with the macOS voice ("say"),
  * reports clearly if the voice could not run, instead of failing silently.

Run this file directly to test the voice on this computer:
    python moca_voice.py
"""

import shutil
import subprocess
import sys

VOICE_RATE = 150
HAS_MAC_VOICE = sys.platform == "darwin" and shutil.which("say") is not None
_warned = False


def voice_available():
    return HAS_MAC_VOICE


def speak_instruction(text, wait=True, rate=VOICE_RATE):
    """Read `text` aloud. wait=True returns after the sentence is finished.

    Returns True if the macOS voice ran successfully, False otherwise.
    """
    global _warned
    print(f"[voice] {text}")
    if not HAS_MAC_VOICE:
        if not _warned:
            print("[voice] No macOS voice on this computer - the instructions are shown "
                  "on screen and printed here only.")
            _warned = True
        return False
    try:
        if wait:
            result = subprocess.run(["say", "-r", str(rate), text], timeout=180)
            if result.returncode != 0:
                print(f"[voice] 'say' returned error code {result.returncode}")
                return False
            return True
        subprocess.Popen(["say", "-r", str(rate), text])
        return True
    except subprocess.TimeoutExpired:
        print("[voice] Speaking took too long and was stopped.")
        return False
    except Exception as exc:  # never let speech stop the test
        print(f"[voice] Could not speak: {exc}")
        return False


if __name__ == "__main__":
    print(f"Mac voice available: {HAS_MAC_VOICE}")
    ok = speak_instruction("This is the MoCA voice test. If you can hear this, the voice works.")
    print("Voice worked" if ok else "Voice did NOT work")
