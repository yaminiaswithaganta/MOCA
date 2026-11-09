"""
The 13 MoCA tasks for the web app.

The browser shows the screens, speaks the instructions and streams the
microphone / camera. Everything that decides a score stays in the original
task modules -- this file only calls them:

  * LISTEN_STEPS  -- for every spoken answer: Whisper prompt, timing, file name,
                     and when an answer is complete (same values as the
                     command-line tasks use)
  * finish_task() -- turns the recorded answers of one task into the standard
                     result dict, with the task module's own judge functions
  * score_photo() -- Task 2 / Task 3 photo scoring
  * score_letters() -- Task 7 from the hand-raise times the browser measured
  * client_config() -- the texts, words and pictures the browser needs
"""

import datetime
import os
import threading
from contextlib import contextmanager

os.environ.setdefault("MPLBACKEND", "Agg")      # task modules import pyplot; no windows here

from moca_common import TASK_MAX_SCORES, make_task_result, save_task_result  # noqa: E402
from moca_speech import digits_of, find_mentions, words_of  # noqa: E402
from moca_tasks import SECTION_OF, TASK_IDS, TASK_INFO  # noqa: E402

import task1_trail_making as t1  # noqa: E402
import task4_naming as t4  # noqa: E402
import task5_memory as t5  # noqa: E402
import task6_attention as t6  # noqa: E402
import task7_letters as t7  # noqa: E402
import task8_serial7s as t8  # noqa: E402
import task9_sentence_repetition as t9  # noqa: E402
import task10_fluency as t10  # noqa: E402
import task11_abstraction as t11  # noqa: E402
import task12_delayed_recall as t12  # noqa: E402
import task13_orientation as t13  # noqa: E402

# get_session_dir() reads MOCA_SESSION_DIR; Task 2/3 scoring uses it for the
# annotated picture. One task is scored at a time, under this lock.
_session_env_lock = threading.Lock()


@contextmanager
def session_env(folder):
    with _session_env_lock:
        old = os.environ.get("MOCA_SESSION_DIR")
        os.environ["MOCA_SESSION_DIR"] = str(folder)
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("MOCA_SESSION_DIR", None)
            else:
                os.environ["MOCA_SESSION_DIR"] = old


# --------------------------------------------------------------------------
# Spoken answers: one entry per (task, step)
# --------------------------------------------------------------------------
def _step(prompt, wav, max_seconds, end_silence=2.0, no_speech_timeout=12.0, is_done=None,
          grace=1.5, reminder="Please answer out loud."):
    return {"prompt": prompt, "wav": wav, "max_seconds": max_seconds, "end_silence": end_silence,
            "no_speech_timeout": no_speech_timeout, "is_done": is_done, "grace": grace,
            "reminder": reminder}


def _naming_done(texts):
    return any(find_mentions(words_of(t), t4.ALL_VOCAB) for t in texts)


LISTEN_STEPS = {}
for _a in t4.ANIMALS:
    LISTEN_STEPS[(4, _a["key"])] = _step(
        t4.PROMPT, f"task4_naming_{_a['key']}.wav", t4.MAX_ANSWER_S,
        no_speech_timeout=t4.ANSWER_TIMEOUT_S, is_done=_naming_done,
        reminder="Please say the name of the animal out loud.")
for _tr in range(1, t5.N_TRIALS + 1):
    LISTEN_STEPS[(5, f"trial{_tr}")] = _step(
        t5.PROMPT, f"task5_memory_trial{_tr}.wav", 30.0, end_silence=3.0, no_speech_timeout=15.0,
        reminder="Please say the words you remember, out loud.")
LISTEN_STEPS[(6, "forward")] = _step(
    t6.DIGIT_PROMPT, "task6_digits_forward.wav", 25, end_silence=3.0, no_speech_timeout=10.0,
    is_done=lambda texts: len(digits_of(" ".join(texts))) >= len(t6.FORWARD))
LISTEN_STEPS[(6, "backward")] = _step(
    t6.DIGIT_PROMPT, "task6_digits_backward.wav", 25, end_silence=3.0, no_speech_timeout=10.0,
    is_done=lambda texts: len(digits_of(" ".join(texts))) >= len(t6.BACKWARD))
LISTEN_STEPS[(8, "serial7")] = _step(
    t8.NUMBER_PROMPT, "task8_serial7.wav", 90, end_silence=8.0, no_speech_timeout=15.0,
    is_done=lambda texts: len(t8.serial7_answers(" ".join(texts))) >= t8.SERIAL_ANSWERS)
for _i in range(1, len(t9.SENTENCES) + 1):
    LISTEN_STEPS[(9, f"sentence{_i}")] = _step(
        t9.REPEAT_PROMPT, f"task9_sentence{_i}.wav", t9.ANSWER_SECONDS,
        end_silence=t9.ANSWER_END_SILENCE, no_speech_timeout=t9.NO_SPEECH_TIMEOUT,
        reminder="Please repeat the sentence out loud.")
LISTEN_STEPS[(10, "fluency")] = _step(
    t10.FLUENCY_PROMPT, "task10_fluency.wav", t10.FLUENCY_SECONDS,
    end_silence=t10.FLUENCY_END_SILENCE, no_speech_timeout=15.0,
    reminder="Please say words that begin with F.")
for _it in t11.ITEMS:
    LISTEN_STEPS[(11, _it["key"])] = _step(
        t11.PROMPT, f"task11_abstraction_{_it['key']}.wav", t11.ANSWER_SECONDS,
        end_silence=t11.ANSWER_END_SILENCE, no_speech_timeout=t11.NO_SPEECH_TIMEOUT)
LISTEN_STEPS[(12, "recall")] = _step(
    t12.PROMPT, "task12_delayed_recall.wav", t12.ANSWER_SECONDS,
    end_silence=t12.ANSWER_END_SILENCE, no_speech_timeout=t12.NO_SPEECH_TIMEOUT,
    reminder="Please say the words you remember.")
for _it in t13.build_items(datetime.datetime.now()):
    LISTEN_STEPS[(13, _it["key"])] = _step(
        t13.PROMPT, f"task13_orientation_{_it['key']}.wav", t13.ANSWER_SECONDS,
        end_silence=2.0, no_speech_timeout=t13.NO_SPEECH_TIMEOUT)


def heard_text(answer):
    """What the patient said: the final whole-answer transcript, else the live phrases."""
    return (answer["final"] or {}).get("text") or " ".join(p["text"] for p in answer["phrases"])


def _live_text(answer):
    return " ".join(p["text"] for p in answer["phrases"])


def _final_text(answer):
    return (answer["final"] or {}).get("text", "")


# --------------------------------------------------------------------------
# Scoring a finished task from its recorded answers
# --------------------------------------------------------------------------
class MissingAnswers(Exception):
    pass


def _need(answers, steps):
    missing = [s for s in steps if s not in answers]
    if missing:
        raise MissingAnswers(f"answers missing for: {', '.join(missing)}")


def finish_task(number, answers, folder, started_at=None):
    """
    answers: {step: {"phrases", "final", "end_reason", "wav"}} for the spoken tasks,
             {"result": (score, reason, details), "wav", "transcript"} for Task 1.
    Saves <folder>/<task>.json and returns the standard result dict.
    """
    task_id = TASK_IDS[number]
    builder = {1: _finish1, 4: _finish4, 5: _finish5, 6: _finish6, 8: _finish8, 9: _finish9,
               10: _finish10, 11: _finish11, 12: _finish12, 13: _finish13}.get(number)
    if builder is None:
        raise ValueError(f"task {number} is not scored from spoken answers")
    std = builder(answers, started_at)
    assert std["task"] == task_id
    save_task_result(std, folder)
    return std


def _finish1(answers, _):
    _need(answers, ["path"])
    a = answers["path"]
    score, reason, details = a["result"]
    std = make_task_result(t1.TASK_ID, score, reason=reason, details=details,
                           evidence_files=[a["wav"], a["transcript"]])
    std.update({"spoken_sequence": details["spoken_sequence"],
                "expected_sequence": t1.CORRECT_SEQUENCE})
    return std


def _finish4(answers, _):
    _need(answers, [a["key"] for a in t4.ANIMALS])
    criteria, per_animal, evidence = {}, {}, []
    for animal in t4.ANIMALS:
        key = animal["key"]
        ans = answers[key]
        score, reason, details = t4.judge_answer(key, ans["phrases"], ans["final"])
        details["end_reason"] = ans["end_reason"]
        criteria[key] = score
        per_animal[key] = {"score": score, "reason": reason, **details}
        evidence.append(ans["wav"])
    total = sum(criteria.values())
    return make_task_result(t4.TASK_ID, total, criteria=criteria,
                            reason="; ".join(f"{k}: {v['reason']}" for k, v in per_animal.items()),
                            details=per_animal, evidence_files=evidence)


def _finish5(answers, _):
    steps = [f"trial{t}" for t in range(1, t5.N_TRIALS + 1)]
    _need(answers, steps)
    trials, evidence = [], []
    for trial, step in enumerate(steps, 1):
        ans = answers[step]
        final_text = heard_text(ans)
        rec_final, intr = t5.recalled_words(final_text)
        rec_live, _ = t5.recalled_words(_live_text(ans))
        recalled = [w for w in t5.WORDS if w in rec_final or w in rec_live]
        trials.append({"trial": trial, "recalled": recalled, "n_recalled": len(recalled),
                       "intrusions": intr, "transcript": final_text,
                       "live_transcripts": [p["text"] for p in ans["phrases"]],
                       "end_reason": ans["end_reason"]})
        evidence.append(ans["wav"])
    return make_task_result(
        t5.TASK_ID, 0,
        reason="learning trials recorded (not scored); " +
               "; ".join(f"trial {t['trial']}: {t['n_recalled']}/5" for t in trials),
        details={"words": t5.WORDS, "trials": trials, "scored": False},
        evidence_files=evidence)


def _finish6(answers, _):
    _need(answers, ["forward", "backward"])
    criteria, parts = {}, {}
    for step, key, expected in (("forward", "digits_forward", t6.FORWARD),
                                ("backward", "digits_backward", list(reversed(t6.BACKWARD)))):
        ans = answers[step]
        s, r, d = t6.judge_digits(expected, ans["phrases"], ans["final"])
        criteria[key] = s
        parts[key] = {"score": s, "reason": r, **d}
    total = sum(criteria.values())
    return make_task_result("task6_digit_span", total, criteria=criteria,
                            reason="; ".join(f"{k}: {v['reason']}" for k, v in parts.items()),
                            details=parts,
                            evidence_files=[answers["forward"]["wav"], answers["backward"]["wav"]])


def _finish8(answers, _):
    _need(answers, ["serial7"])
    ans = answers["serial7"]
    final_ans = t8.serial7_answers(_final_text(ans))
    live_ans = t8.serial7_answers(_live_text(ans))
    given = final_ans if len(final_ans) >= len(live_ans) else live_ans
    points, correct, per = t8.score_serial7(given)
    reason = (f"{correct} of 4 correct subtractions ({', '.join(map(str, given)) or 'no answers'}) "
              f"-> {points} point(s)")
    d = {"answers": given, "correct_subtractions": correct, "per_step": per,
         "transcript": _final_text(ans), "live_transcripts": [p["text"] for p in ans["phrases"]]}
    return make_task_result("task8_serial7s", points, criteria={"serial7": points}, reason=reason,
                            details={"serial7": {"score": points, "reason": reason, **d}},
                            evidence_files=[ans["wav"]])


def _finish9(answers, _):
    steps = [f"sentence{i}" for i in range(1, len(t9.SENTENCES) + 1)]
    _need(answers, steps)
    results, evidence = [], []
    for sentence, step in zip(t9.SENTENCES, steps):
        ans = answers[step]
        said = heard_text(ans)
        ratio = t9.repetition_ratio(sentence, said)
        ok = int(ratio >= t9.REPEAT_MIN_RATIO)
        results.append({"sentence": sentence, "heard": said, "match": round(ratio, 3),
                        "score": ok, "end_reason": ans["end_reason"]})
        evidence.append(ans["wav"])
    criteria = {f"sentence_{i}": r["score"] for i, r in enumerate(results, 1)}
    reason = "; ".join(f"sentence {i}: {r['score']}/1" for i, r in enumerate(results, 1))
    return make_task_result(t9.TASK_ID, sum(criteria.values()), criteria=criteria, reason=reason,
                            details={"sentences": results}, evidence_files=evidence)


def _finish10(answers, _):
    _need(answers, ["fluency"])
    ans = answers["fluency"]
    said = heard_text(ans)
    words = t10.f_words(said)
    ok = t10.fluency_points(words)
    reason = (f"{len(words)} different F-words (need {t10.FLUENCY_MIN_WORDS}) -> {ok}/1: "
              + ", ".join(words))
    return make_task_result(t10.TASK_ID, ok, criteria={"fluency": ok}, reason=reason,
                            details={"heard": said, "words": words, "words_counted": len(words),
                                     "end_reason": ans["end_reason"]},
                            evidence_files=[ans["wav"]])


def _finish11(answers, _):
    _need(answers, [it["key"] for it in t11.ITEMS])
    criteria, details, evidence = {}, {}, []
    for item in t11.ITEMS:
        ans = answers[item["key"]]
        final_text, live_text = _final_text(ans), _live_text(ans)
        score = t11.judge_item(item, final_text, live_text)
        criteria[item["key"]] = score
        details[item["key"]] = {"question": item["question"], "heard": final_text or live_text,
                                "accepted_category": item["category"], "score": score,
                                "end_reason": ans["end_reason"]}
        evidence.append(ans["wav"])
    reason = "; ".join(f"{it['label']}: {criteria[it['key']]}/1" for it in t11.ITEMS)
    return make_task_result(t11.TASK_ID, sum(criteria.values()), criteria=criteria, reason=reason,
                            details=details, evidence_files=evidence)


def _finish12(answers, _):
    _need(answers, ["recall"])
    ans = answers["recall"]
    final_text, live_text = _final_text(ans), _live_text(ans)
    rec_final, intrusions = t5.recalled_words(final_text)
    rec_live, _ = t5.recalled_words(live_text)
    recalled = [w for w in t12.WORDS if w in rec_final or w in rec_live]
    criteria = {w.lower(): int(w in recalled) for w in t12.WORDS}
    score = sum(criteria.values())
    missed = [w for w in t12.WORDS if w not in recalled]
    reason = f"recalled {score} of {len(t12.WORDS)}: {', '.join(recalled) or 'none'}"
    if missed:
        reason += f" (missed: {', '.join(missed)})"
    return make_task_result(
        t12.TASK_ID, score, criteria=criteria, reason=reason,
        details={"recalled": recalled, "missed": missed, "intrusions": intrusions,
                 "transcript": final_text or live_text,
                 "live_transcripts": [p["text"] for p in ans["phrases"]],
                 "end_reason": ans["end_reason"]},
        evidence_files=[ans["wav"]])


def _finish13(answers, started_at):
    now = started_at or datetime.datetime.now()
    items = t13.build_items(now)
    _need(answers, [it["key"] for it in items])
    criteria, details, evidence = {}, {}, []
    for item in items:
        ans = answers[item["key"]]
        final_text, live_text = _final_text(ans), _live_text(ans)
        ok = int(bool(item["judge"](final_text) or item["judge"](live_text)))
        criteria[item["key"]] = ok
        details[item["key"]] = {"question": item["question"], "heard": final_text or live_text,
                                "expected": item["expected"], "score": ok,
                                "end_reason": ans["end_reason"]}
        evidence.append(ans["wav"])
    score = sum(criteria.values())
    missed = [k for k, v in criteria.items() if not v]
    reason = f"{score} of 6 correct" + (f" (missed: {', '.join(missed)})" if missed else "")
    return make_task_result(t13.TASK_ID, score, criteria=criteria, reason=reason,
                            details={"clock": now.isoformat(timespec="seconds"), "items": details},
                            evidence_files=evidence)


# --------------------------------------------------------------------------
# Task 2 / 3: photo
# --------------------------------------------------------------------------
def score_photo(number, photo_path, folder):
    """Score a cube (2) or clock (3) photo with the task's own score_and_report()."""
    with session_env(folder):
        if number == 2:
            import task2_cube_copy as t2
            return t2.score_and_report(str(photo_path), show_result=False)
        if number == 3:
            import task3_clock_draw as t3
            return t3.score_and_report(str(photo_path), show_result=False)
    raise ValueError(f"task {number} is not a photo task")


def photo_name(number):
    return {2: "cube_capture.png", 3: "clock_capture.png"}[number]


# --------------------------------------------------------------------------
# Task 7: letters -- the browser measured the times, the task module scores them
# --------------------------------------------------------------------------
def score_letters(data, folder):
    """
    data: {"letter_times": [s], "raise_times": [s], "up_samples": [[s, 0/1]], "mode",
           "calibration": {...}, "trace": [...]} -- seconds from the start of the list.
    """
    letter_times = [float(t) for t in data.get("letter_times", [])]
    raise_times = [float(t) for t in data.get("raise_times", [])]
    up_samples = [(float(t), bool(u)) for t, u in data.get("up_samples", [])]
    letters = t7.LETTERS[:len(letter_times)]
    if len(letters) < len(t7.LETTERS):
        raise ValueError(f"only {len(letters)} of {len(t7.LETTERS)} letters were read")
    s, errors, per = t7.score_letter_responses(letters, letter_times, raise_times, up_samples,
                                               t7.LETTER_INTERVAL_S)
    missed = [k for k, p in enumerate(per) if p["letter"] == "A" and not p["ok"]]
    wrong = [f"{p['letter']}#{k + 1}" for k, p in enumerate(per) if p["letter"] != "A" and not p["ok"]]
    reason = (f"{errors} error(s): {len(missed)} missed A, {len(wrong)} raise(s) on other letters"
              + ("" if s else " (2 or more errors = 0)"))
    d = {"mode": data.get("mode", "camera"), "errors": errors,
         "missed_A_positions": [m + 1 for m in missed], "wrong_raises": wrong, "per_letter": per,
         "calibration": data.get("calibration") or {}, "letter_interval_s": t7.LETTER_INTERVAL_S,
         "letter_times_s": [round(t, 2) for t in letter_times],
         "raise_times_s": [round(t, 2) for t in raise_times], "trace": data.get("trace") or []}
    std = make_task_result("task7_letters", s, criteria={"letters_a": s}, reason=reason,
                           details={"letters_a": {"score": s, "reason": reason, **d}})
    save_task_result(std, folder)
    return std


# --------------------------------------------------------------------------
# What the browser needs to show and say
# --------------------------------------------------------------------------
SPEECH = {
    1: ("I will show you a diagram with circles labeled with numbers and letters. "
        "Your task is to connect them by saying the path out loud, alternating between "
        "numbers and letters: one, A, two, B, three, C, and so on, all the way to E. "
        "Start at one, and keep alternating."),
    2: ("Look at the cube shown on the screen. Draw a matching three-dimensional cube on paper. "
        "Include all edges and make it look like the picture. Then hold your drawing up to the camera, "
        "with the whole cube in view."),
    3: ("Draw a clock. First, draw a large circle. Then write all 12 numbers in their correct positions "
        "around the circle. Finally, draw two hands to show the time ten past eleven. "
        "Then hold the clock up to the camera. Hold it straight, not tilted, and not upside down, "
        "with the whole clock in view."),
    4: ("I will show you three pictures of animals, one at a time. For each picture, "
        "look carefully and say the name of the animal out loud as clearly as you can."),
    6: {"forward": ("I am going to say some numbers, and when I am through, repeat them to me "
                    "exactly as I said them."),
        "backward": ("Now I am going to say some more numbers, but when I am through, you must "
                     "repeat them to me in the backwards order.")},
    7: {"sit": ("Please sit facing the camera, put your hands down on your lap, "
                "and keep still for a moment."),
        "raise": "Now raise your hand, and hold it up.",
        "lower": "Thank you. Put your hand down.",
        "retry": ("I could not see your hand clearly. Please raise your hand higher, "
                  "to the side of your head, so the camera can see it."),
        "task": ("I am going to read a list of letters. Every time I say the letter A, raise your "
                 "hand, and then put it down again. If I say a different letter, do not raise your hand.")},
    8: ("Now I will ask you to count by subtracting seven from one hundred, and then keep "
        "subtracting seven from your answer. Please begin now."),
}


def client_config():
    now = datetime.datetime.now()
    tasks = [{"number": n, "id": TASK_IDS[n], "title": TASK_INFO[n][0],
              "description": TASK_INFO[n][1], "camera": TASK_INFO[n][2],
              "section": SECTION_OF[n], "max": TASK_MAX_SCORES[TASK_IDS[n]]} for n in TASK_IDS]
    return {
        "tasks": tasks,
        "speech": SPEECH,
        "t1": {"nodes": t1.NODE_POSITIONS, "correct": t1.CORRECT_SEQUENCE},
        "t4": {"animals": t4.ANIMALS},
        "t5": {"words": t5.WORDS, "trials": t5.N_TRIALS, "seconds_per_word": t5.SECONDS_PER_WORD},
        "t6": {"forward": t6.FORWARD, "backward": t6.BACKWARD},
        "t7": {"letters": t7.LETTERS, "interval_s": t7.LETTER_INTERVAL_S},
        "t9": {"intro": t9.INTRO, "sentences": t9.SENTENCES},
        "t10": {"instruction": t10.INSTRUCTION, "seconds": t10.FLUENCY_SECONDS},
        "t11": {"items": t11.ITEMS},
        "t12": {"question": t12.QUESTION},
        "t13": {"items": [{"key": it["key"], "question": it["question"]}
                          for it in t13.build_items(now)]},
    }
