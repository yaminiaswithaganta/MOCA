"""
MoCA Task 9 -- Language (3 points)
==================================

    Sentence repetition   2 points   1 point per sentence repeated correctly
    Letter fluency        1 point    at least 11 different words starting with F
                                     in one minute

How it works
-------------
1. Sentence repetition: each sentence is read aloud (Mac voice) and the
   patient repeats it. The answer is transcribed offline (Whisper) and
   compared word by word with the sentence. A sentence counts as repeated
   when at least REPEAT_MIN_RATIO of its words were said, in order (a word
   spelled one letter differently still counts). Set REPEAT_MIN_RATIO = 1.0
   for strict MoCA scoring.
2. Letter fluency: "Say as many words as you can that begin with the letter
   F. You have one minute." Recording runs for up to 60 s (or stops after
   10 s of silence). Each DIFFERENT word beginning with F counts once; repeats
   are ignored. Proper names cannot be detected automatically -- the saved
   transcript lets the examiner check the list.

Run
---
    python task9_language.py
"""

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import damerau, get_engine, listen_for_answer, save_wav, speak, words_of

TASK_ID = "task9_language"
SENTENCES = [
    "I only know that John is the one to help today.",
    "The cat always hid under the couch when dogs were in the room.",
]
REPEAT_MIN_RATIO = 0.9
FLUENCY_SECONDS = 60.0
FLUENCY_END_SILENCE = 10.0
FLUENCY_MIN_WORDS = 11
FLUENCY_IGNORE = {"for", "from"}
REPEAT_PROMPT = "The person repeats a sentence that was read to them."
FLUENCY_PROMPT = "The person says English words that begin with the letter F."
FLUENCY_INSTRUCTION = ("Now say as many words as you can that begin with the letter F. "
                       "You have one minute. Go.")


def _same_word(a, b):
    return a == b or (len(a) >= 4 and damerau(a, b) <= 1)


def repetition_ratio(target, said):
    """Share of the target's words that were said, in order (fuzzy longest common subsequence)."""
    t, s = words_of(target), words_of(said)
    if not t:
        return 0.0
    prev = [0] * (len(s) + 1)
    for tw in t:
        cur = [0]
        for j, sw in enumerate(s, 1):
            best = max(prev[j], cur[j - 1])
            if _same_word(tw, sw):
                best = max(best, prev[j - 1] + 1)
            cur.append(best)
        prev = cur
    return prev[-1] / len(t)


def f_words(text):
    """Different words beginning with F, in the order they were said."""
    out = []
    for w in words_of(text):
        if w.startswith("f") and len(w) >= 2 and w not in FLUENCY_IGNORE and w not in out:
            out.append(w)
    return out


class LanguageWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.ax.axis("off")

    def show(self, title, big="", small="", color="white"):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(title, fontsize=15)
        self.ax.text(0.5, 0.55, big, ha="center", va="center", fontsize=30, weight="bold",
                     transform=self.ax.transAxes)
        self.ax.text(0.5, 0.15, small, ha="center", va="center", fontsize=14,
                     transform=self.ax.transAxes, wrap=True)
        self.fig.patch.set_facecolor(color)
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def pump(self):
        plt.pause(0.03)

    def wait(self, seconds):
        import time
        t = time.time() + seconds
        while time.time() < t:
            self.pump()


def run_sentences(win, engine, session_dir, evidence):
    results = []
    for i, sentence in enumerate(SENTENCES, 1):
        title = f"Language - repeat sentence {i} of {len(SENTENCES)}"
        win.show(title, "", "Listen carefully. Then repeat the sentence exactly as you heard it.")
        speak(sentence)
        win.show(title, "", "Now repeat the sentence out loud.", color="#eef6ee")
        ans = listen_for_answer(
            engine, REPEAT_PROMPT, pump=win.pump,
            status=lambda t, ti=title: win.show(ti, "", t),
            max_seconds=30.0, end_silence=2.5, no_speech_timeout=15.0,
            reminder=lambda ti=title: win.show(ti, "", "Please repeat the sentence out loud.",
                                               color="#ffe9c6"))
        said = (ans["final"] or {}).get("text") or " ".join(p["text"] for p in ans["phrases"])
        ratio = repetition_ratio(sentence, said)
        ok = ratio >= REPEAT_MIN_RATIO
        wav = session_dir / f"task9_language_sentence{i}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        results.append({"sentence": sentence, "heard": said, "ratio": round(ratio, 3),
                        "score": int(ok), "end_reason": ans["end_reason"]})
        print(f"[sentence {i}] {int(ok)}/1  match {ratio:.2f}  heard \"{said}\"")
        win.show(title, "", f"Recorded: \"{said or '(nothing)'}\"", color="lightgray")
        win.wait(2.0)
    return results


def run_fluency(win, engine, session_dir, evidence):
    title = "Language - letter F fluency"
    win.show(title, "", FLUENCY_INSTRUCTION)
    speak(FLUENCY_INSTRUCTION)
    win.show(title, "", "Say as many F words as you can...", color="#eef6ee")
    ans = listen_for_answer(
        engine, FLUENCY_PROMPT, pump=win.pump,
        status=lambda t: win.show(title, "", t),
        max_seconds=FLUENCY_SECONDS, end_silence=FLUENCY_END_SILENCE, no_speech_timeout=15.0,
        reminder=lambda: win.show(title, "", "Please say words that begin with F.",
                                  color="#ffe9c6"))
    said = (ans["final"] or {}).get("text") or " ".join(p["text"] for p in ans["phrases"])
    words = f_words(said)
    ok = len(words) >= FLUENCY_MIN_WORDS
    wav = session_dir / "task9_language_fluency.wav"
    save_wav(wav, ans["audio"])
    evidence.append(wav)
    print(f"[fluency] {int(ok)}/1  {len(words)} F-words: {', '.join(words)}")
    win.show(title, "", f"{len(words)} F-words recorded", color="lightgray")
    win.wait(2.0)
    return {"heard": said, "words": words, "words_counted": len(words),
            "score": int(ok), "end_reason": ans["end_reason"]}


def run_task9(show_result=True):
    print("=" * 60)
    print("MoCA Task 9: Language (sentence repetition + letter F fluency)")
    print("=" * 60)
    win = LanguageWindow()
    win.show("Language", "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()
    evidence = []

    sentences = run_sentences(win, engine, session_dir, evidence)
    fluency = run_fluency(win, engine, session_dir, evidence)

    criteria = {"sentence_repetition": sum(s["score"] for s in sentences),
                "fluency": fluency["score"]}
    score = sum(criteria.values())
    reason = (f"sentence repetition {criteria['sentence_repetition']}/2; "
              f"fluency {fluency['words_counted']} F-words -> {criteria['fluency']}/1")
    win.show("Language - finished", "", f"LANGUAGE SCORE: {score} / 3", color="#eef6ee")

    std = make_task_result(TASK_ID, score, criteria=criteria, reason=reason,
                           details={"sentences": sentences, "fluency": fluency},
                           evidence_files=evidence)
    print(f"\n--- RESULT ---\n{reason}\nSCORE: {score} / 3")
    print(f"Result saved to: {save_task_result(std)}")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(3)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task9()
