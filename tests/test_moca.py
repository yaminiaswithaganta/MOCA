"""
Automated tests for the MoCA auto-scoring.

    cd "Moca"            # the project folder
    python -m unittest tests/test_moca.py -v

Uses synthetic drawings (tests/synth.py) so it runs without a camera or mic.
The speech end-to-end test runs only if the optional TTS/ASR test models are
present (see tests/speech_harness.py); the rest has no extra dependencies
(Task 3's handwritten-digit test cases use mlxtend's bundled MNIST sample
when installed, otherwise printed-style digits).
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import matplotlib  # noqa: E402
matplotlib.use("Agg")

from moca_common import (MAX_TOTAL_SCORE, SECTIONS, build_final_report,  # noqa: E402
                         make_task_result, prepare_drawing)

VISUO = ["task1_trail_making", "task2_cube_copy", "task3_clock_draw"]


# --------------------------------------------------------------------------
class TestScoreStructure(unittest.TestCase):
    def test_maxima(self):
        self.assertEqual(SECTIONS["visuospatial_executive"]["max"], 5)
        self.assertEqual(SECTIONS["naming"]["max"], 3)
        self.assertEqual(SECTIONS["memory"]["max"], 0)
        self.assertEqual(SECTIONS["attention"]["max"], 6)
        # full MoCA: 5 + 3 + 0 + 6 + 3 + 2 + 5 + 6 = 30 (memory not scored)
        self.assertEqual(MAX_TOTAL_SCORE, 30)

    def _report(self, t1, t2, c, n, h, tasks=VISUO, extra=None):
        res = {
            "task1_trail_making": make_task_result("task1_trail_making", t1),
            "task2_cube_copy": make_task_result("task2_cube_copy", t2),
            "task3_clock_draw": make_task_result("task3_clock_draw", c + n + h,
                                                 criteria={"contour": c, "numbers": n, "hands": h}),
        }
        res.update(extra or {})
        return build_final_report(res, tasks=tasks)

    def test_examples_from_brief(self):
        r = self._report(1, 1, 1, 0, 1)
        self.assertEqual((r["total"], r["max_total"]), (4, 5))      # 1 + 1 + 2/3 = 4/5
        self.assertEqual(self._report(0, 0, 1, 1, 1)["total"], 3)   # 0 + 0 + 3/3 = 3/5
        self.assertEqual(self._report(1, 1, 1, 1, 1)["total"], 5)
        self.assertEqual(self._report(0, 0, 0, 0, 0)["total"], 0)

    def test_summary_format(self):
        s = self._report(1, 0, 1, 0, 1)["summary"]
        self.assertEqual(s, {"task1_trail_making": 1, "task2_cube_copy": 0,
                             "task3_clock_draw": {"contour": 1, "numbers": 0, "hands": 1},
                             "total": 3, "max_total": 5})

    def test_full_session_with_naming_and_memory(self):
        extra = {
            "task4_naming": make_task_result("task4_naming", 2,
                                             criteria={"lion": 1, "rhino": 0, "camel": 1}),
            "task5_memory": make_task_result("task5_memory", 0, details={"trials": [
                {"trial": 1, "recalled": ["FACE", "RED"]},
                {"trial": 2, "recalled": ["FACE", "VELVET", "RED"]}]}),
        }
        r = self._report(1, 1, 1, 1, 0, tasks=VISUO + ["task4_naming", "task5_memory"], extra=extra)
        self.assertEqual((r["total"], r["max_total"]), (6, 8))
        self.assertEqual(r["sections"]["visuospatial_executive"], {"score": 4, "max": 5})
        self.assertEqual(r["sections"]["naming"], {"score": 2, "max": 3})
        self.assertEqual(r["summary"]["task5_memory"],
                         {"trial1": ["FACE", "RED"], "trial2": ["FACE", "VELVET", "RED"]})

    def test_memory_is_never_scored(self):
        with self.assertRaises(ValueError):
            make_task_result("task5_memory", 1)

    def test_no_partial_or_out_of_range_scores(self):
        with self.assertRaises(ValueError):
            make_task_result("task1_trail_making", 2)
        with self.assertRaises(ValueError):
            make_task_result("task2_cube_copy", -1)
        with self.assertRaises(ValueError):   # criteria must add up
            make_task_result("task3_clock_draw", 3, criteria={"contour": 1, "numbers": 0, "hands": 1})
        with self.assertRaises(ValueError):
            make_task_result("task3_clock_draw", 1, criteria={"contour": 0.5, "numbers": 0.5, "hands": 0})

    def test_missing_task_counts_zero(self):
        rep = build_final_report({"task2_cube_copy": make_task_result("task2_cube_copy", 1)})
        self.assertEqual(rep["total"], 1)
        self.assertFalse(rep["tasks"]["task1_trail_making"]["completed"])
        self.assertEqual(rep["summary"]["task4_naming"], {"lion": 0, "rhino": 0, "camel": 0})


# --------------------------------------------------------------------------
def _res(text, prob=0.9):
    return {"text": text, "words": [{"word": " " + w, "prob": prob} for w in text.split()]}


class TestTask4Naming(unittest.TestCase):
    def setUp(self):
        import task4_naming as t4
        self.t4 = t4

    def score(self, target, text, live=None, prob=0.9):
        live = [_res(t, prob) for t in (live if live is not None else [text])] if text else []
        return self.t4.judge_answer(target, live, _res(text, prob) if text else None)[0]

    def test_correct_answers_and_variants(self):
        cases = {
            "lion": ["Lion.", "It's a lion", "a lion!", "lions", "Lyon", "lie on", "I think it's a lion",
                     "a tiger, no, a lion"],
            "rhino": ["Rhino", "rhinoceros", "It is a rhinoceros.", "Rhinocerous", "rino", "Ryno",
                      "rhino ceros", "rhinoceroses", "hippo... no, rhino"],
            "camel": ["Camel.", "a camel", "Dromedary", "Cammel", "kamel", "camels"],
        }
        for target, texts in cases.items():
            for t in texts:
                self.assertEqual(self.score(target, t), 1, (target, t))

    def test_wrong_answers(self):
        cases = {
            "lion": ["tiger", "a cat", "line", "it's a dog", "lion... no, tiger", "I don't know",
                     "leopard", ""],
            "rhino": ["hippo", "an elephant", "a cow", "rhine", "buffalo", "lion"],
            "camel": ["horse", "llama", "camera", "cameo", "a giraffe", "cancel", "caramel", "rhino"],
        }
        for target, texts in cases.items():
            for t in texts:
                self.assertEqual(self.score(target, t), 0, (target, t))

    def test_unreliable_is_zero(self):
        # heard only once (no agreement) with very low confidence -> 0
        self.assertEqual(self.score("lion", "lion", live=[], prob=0.05), 0)
        # low-scored first word but live + final agree -> accepted
        self.assertEqual(self.score("lion", "Lion.", prob=0.05), 1)
        # near-zero confidence is rejected even when both agree
        self.assertEqual(self.score("lion", "Lion.", prob=0.005), 0)

    def test_pictures_exist(self):
        for a in self.t4.ANIMALS:
            self.assertTrue((self.t4.IMAGE_DIR / a["image"]).exists(), a["image"])


class TestTask5Memory(unittest.TestCase):
    def test_recall_matching(self):
        from task5_memory import recalled_words
        cases = [
            ("Face, velvet, church, daisy, red.", ["FACE", "VELVET", "CHURCH", "DAISY", "RED"], []),
            ("red daisy face", ["FACE", "DAISY", "RED"], []),
            ("um face and welvet and I think church", ["FACE", "VELVET", "CHURCH"], []),
            ("daisies, churches, read", ["CHURCH", "DAISY", "RED"], []),
            ("face, blue, church, flower", ["FACE", "CHURCH"], ["blue", "flower"]),
            ("I don't remember", [], ["remember"] if False else []),
            ("", [], []),
            ("fact, lazy, crutch", [], ["fact", "lazy", "crutch"]),
        ]
        for text, rec, intr in cases:
            got_rec, got_intr = recalled_words(text)
            self.assertEqual(got_rec, rec, text)
            self.assertEqual(got_intr, intr, text)


# --------------------------------------------------------------------------
class TestTask1Parsing(unittest.TestCase):
    def setUp(self):
        import task1_trail_making as t1
        self.t1 = t1

    def score(self, text, prob=0.9):
        steps = self.t1.parse_word_list([{"word": w, "prob": prob} for w in text.split()])
        return self.t1.evaluate_path(steps)[0]

    def test_correct_variants(self):
        for text in ["1, A, 2, B, 3, C, 4, D, 5, E.",
                     "One. A. Two. B. Three. C. Four. D. Five. E.",
                     "one to A to two to B to three to C to four to D to five to E",
                     "1A 2B 3C 4D 5E", "1A2B3C4D5E",
                     "one A two bee three see four dee five e",
                     "um one then A then two and B, three, C, four, D, five and then E",
                     "1 A A 2 B 3 C 4 D 5 E"]:            # repeated step = one step
            self.assertEqual(self.score(text), 1, text)

    def test_incorrect_variants(self):
        for text in ["1 A 2 B 3 D 4 C 5 E", "1 A 2 B 3 C 4 5 E", "1 2 3 4 5 A B C D E",
                     "1 A 2 B 3", "1 A 2 B 3 C 4 D 5 F", "1 A 2 B 3 C 4 D 5 6 E",
                     "A 1 B 2 C 3 D 4 E 5", "", "hello there", "E",
                     "1 A 2 B 3 C 4 D 5 E 1"]:
            self.assertEqual(self.score(text), 0, text)

    def test_low_confidence_gives_zero(self):
        self.assertEqual(self.score("1 A 2 B 3 C 4 D 5 E", prob=0.2), 0)

    def test_the_is_not_d(self):
        self.assertEqual(self.score("one A two B three C four the five E"), 0)


# --------------------------------------------------------------------------
class TestTask2Cube(unittest.TestCase):
    def test_reference_is_the_projects_cube(self):
        from task2_cube_copy import make_reference_cube_image, reference_cube_geometry
        g = reference_cube_geometry()
        self.assertEqual(len(g["vertices"]), 8)
        self.assertEqual(len(g["edges"]), 12)
        img = make_reference_cube_image()
        for x, y in g["vertices"].astype(int):   # every corner is drawn on the reference
            self.assertLess(img[y, x].mean(), 128)

    def test_cases(self):
        from cube_cases import cube_cases
        from task2_cube_copy import score_cube_image
        wrong = []
        for seed in (0, 1, 2):
            for name, expected, img in cube_cases(seed):
                r = score_cube_image(img)
                self.assertIn(r["score"], (0, 1))
                if r["score"] != expected:
                    wrong.append((seed, name, expected, r["score"], r["reason"]))
        false_pass = [w for w in wrong if w[3] == 1]
        self.assertEqual(false_pass, [], "a non-matching drawing was scored 1")
        self.assertEqual(wrong, [])


# --------------------------------------------------------------------------
class TestPatientAndScoreSheet(unittest.TestCase):
    GOOD = {"name": "Test Patient", "education": "12", "sex": "Female",
            "dob": "25/03/1950", "test_date": "19/10/2026"}

    def test_score_sheet_matches_paper_form(self):
        import run_moca  # noqa: F401  (imports must work)
        from moca_common import TASK_MAX_SCORES, build_final_report
        from moca_score_sheet import PAPER_SECTIONS, build_sheet, sheet_text
        from moca_common import make_task_result
        full = {
            "task1_trail_making": make_task_result("task1_trail_making", 1),
            "task2_cube_copy": make_task_result("task2_cube_copy", 1),
            "task3_clock_draw": make_task_result("task3_clock_draw", 2,
                criteria={"contour": 1, "numbers": 1, "hands": 0}),
            "task4_naming": make_task_result("task4_naming", 2,
                criteria={"lion": 1, "rhino": 0, "camel": 1}),
            "task5_memory": make_task_result("task5_memory", 0),
            "task6_digit_span": make_task_result("task6_digit_span", 2,
                criteria={"digits_forward": 1, "digits_backward": 1}),
            "task7_letters": make_task_result("task7_letters", 1, criteria={"letters_a": 1}),
            "task8_serial7s": make_task_result("task8_serial7s", 3, criteria={"serial7": 3}),
            "task9_sentence_repetition": make_task_result("task9_sentence_repetition", 1,
                criteria={"sentence_1": 1, "sentence_2": 0}),
            "task10_fluency": make_task_result("task10_fluency", 1, criteria={"fluency": 1}),
            "task11_abstraction": make_task_result("task11_abstraction", 1,
                criteria={"train_bicycle": 1, "watch_ruler": 0}),
            "task12_delayed_recall": make_task_result("task12_delayed_recall", 3,
                criteria={"face": 1, "velvet": 1, "church": 0, "daisy": 1, "red": 0}),
            "task13_orientation": make_task_result("task13_orientation", 6,
                criteria={"date": 1, "month": 1, "year": 1, "day": 1, "place": 1, "city": 1}),
        }
        report = build_final_report(full, tasks=list(TASK_MAX_SCORES))
        sheet = build_sheet(report, {"education_years": 12})
        by_key = {s["key"]: s for s in sheet["sections"]}
        self.assertEqual((by_key["visuospatial_executive"]["score"], by_key["visuospatial_executive"]["max"]), (4, 5))
        self.assertEqual(by_key["naming"]["score"], 2)
        self.assertEqual(by_key["abstraction"]["score"], 1)
        self.assertEqual(by_key["delayed_recall"]["score"], 3)
        # visuospatial 4 + naming 2 + attention 6 + language 2 + abstraction 1 + recall 3 + orientation 6
        self.assertEqual(sheet["total"], 24)
        self.assertEqual(sheet["max_total"], 30)
        self.assertEqual(sheet["education_bonus"], 1)                  # 12 years or less
        self.assertEqual(sheet["adjusted_total"], sheet["total"] + 1)
        text = sheet_text(sheet)
        self.assertIn("VISUOSPATIAL / EXECUTIVE", text)
        self.assertIn("4 / 5", text)
        self.assertEqual(len(PAPER_SECTIONS), 7)
        self.assertEqual(sum(s["max"] for s in sheet["sections"]), 30)

    def test_missing_tasks_count_as_zero(self):
        from moca_common import build_final_report
        from moca_score_sheet import build_sheet
        report = build_final_report({}, tasks=["task1_trail_making", "task2_cube_copy"])
        sheet = build_sheet(report, None)
        self.assertEqual(sheet["total"], 0)
        self.assertEqual(sheet["education_bonus"], 0)


class TestRealPhotos(unittest.TestCase):
    """Photos taken with the webcam during testing (tests/real_photos)."""
    DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_photos")

    def _load(self, name):
        import cv2
        img = cv2.imread(os.path.join(self.DIR, name))
        self.assertIsNotNone(img, name)
        return img

    def test_cube_photos(self):
        from task2_cube_copy import score_cube_image
        for name in ("cube_pass_1.png", "cube_pass_2.png", "cube_pass_3.png"):
            r = score_cube_image(self._load(name))
            self.assertEqual(r["score"], 1, f"{name}: {r['reason']}")
        r = score_cube_image(self._load("cube_cut_off.png"))
        self.assertEqual(r["score"], 0)
        self.assertIn("runs off the edge", r["reason"])

    def test_clock_photos(self):
        from task3_clock_draw import score_clock_image
        for name in ("clock_pass_1.png", "clock_pass_2.png"):
            r = score_clock_image(self._load(name))
            self.assertEqual(r["criteria"]["contour"], 1, name)
            self.assertEqual(r["criteria"]["numbers"], 1, f"{name}: {r['numbers']['reason']}")
        r = score_clock_image(self._load("clock_cut_off.png"))
        self.assertEqual(r["criteria"]["contour"], 0)


class TestTask3Clock(unittest.TestCase):
    def test_required_time(self):
        from task3_clock_draw import required_hand_angles
        self.assertEqual(required_hand_angles(11, 10), (335.0, 60.0))

    def test_cases(self):
        from clock_cases import clock_cases
        from task3_clock_draw import score_clock_image
        false_pass, wrong, total = [], [], 0
        numbers_ok = numbers_total = 0
        for seed in (0, 1, 2):
            for name, exp, img in clock_cases(seed):
                r = score_clock_image(img)
                got = r["criteria"]
                self.assertEqual(r["score"], sum(got.values()))
                for k in ("contour", "numbers", "hands"):
                    total += 1
                    self.assertIn(got[k], (0, 1))
                    if got[k] != exp[k]:
                        wrong.append((seed, name, k, exp[k], got[k]))
                        if got[k] == 1:
                            false_pass.append((seed, name, k, r[k].get("reason")))
                if exp["numbers"] == 1:
                    numbers_total += 1
                    numbers_ok += got["numbers"] == 1
        # never award a criterion that was not met
        self.assertEqual(false_pass, [])
        # contour and hands must be exactly right on every synthetic case
        self.assertEqual([w for w in wrong if w[2] != "numbers"], [])
        # reading handwritten numbers is the hardest part: allow a few false 0s
        self.assertGreaterEqual(numbers_ok / numbers_total, 0.85, wrong)

    def test_sideways_and_upside_down_paper_scores_the_same(self):
        # the patient holds the paper turned: the score must not change
        import cv2
        from clock_cases import clock_cases
        from task3_clock_draw import score_clock_image
        exp, img = next((e, im) for n, e, im in clock_cases(0) if n == "ex1 all correct")
        for code in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
            r = score_clock_image(cv2.rotate(img, code))
            self.assertEqual(r["criteria"], exp, f"rotation {code}")

    def test_fair_human_judgement_cases(self):
        # arrow head touching a number, and one stray speck: a person still gives full marks
        from clock_cases import clock_cases
        from task3_clock_draw import score_clock_image
        for name in ("hands with arrowheads", "camera photo correct #0"):
            exp, img = next((e, im) for n, e, im in clock_cases(0) if n == name)
            self.assertEqual(score_clock_image(img)["criteria"], exp, name)

    def test_examples_from_brief(self):
        from clock_cases import clock_cases
        from task3_clock_draw import score_clock_image
        for name, exp, img in clock_cases(0)[:5]:
            r = score_clock_image(img)
            self.assertEqual(r["criteria"], exp, name)


# --------------------------------------------------------------------------
class TestTask1SpeechEndToEnd(unittest.TestCase):
    """Synthesised voices through the real Task 1 pipeline (needs test models)."""

    def test_voices(self):
        try:
            import speech_harness as sh
            if not os.path.isdir(sh.TTS_DIR) or not os.path.isdir(sh.SHERPA_WHISPER_DIR):
                raise ImportError
            import faster_whisper  # noqa: F401  (VAD)
        except ImportError:
            self.skipTest("speech test models not installed")
        res = sh.run_all(voice_names=["en_GB-alan-medium"], verbose=False)
        false_pos = [r[:4] for r in res if r[3] == 1 and r[2] == 0]
        self.assertEqual(false_pos, [], "an incorrect spoken path was scored 1")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# --------------------------------------------------------------------------
class TestTask6Attention(unittest.TestCase):
    """Tests for Task 6 (Digit Span), Task 7 (Letters), Task 8 (Serial 7s)"""
    def setUp(self):
        import task6_attention as t6
        self.t6 = t6

    def test_digit_span(self):
        """Task 6: Digit Span (forward + backward)"""
        j = self.t6.judge_digits
        fwd, bwd = [2, 1, 8, 5, 4], [2, 4, 7]
        for text in ["2 1 8 5 4", "21854", "Two, one, eight, five, four.", "2-1-8-5-4"]:
            self.assertEqual(j(fwd, [], _res(text))[0], 1, text)
        for text in ["2 1 8 4 5", "2 1 8 5", "1 2 8 5 4", "2 1 8 5 4 4", "", "I don't know"]:
            self.assertEqual(j(fwd, [], _res(text) if text else None)[0], 0, text)
        for text in ["2 4 7", "two four seven", "247"]:
            self.assertEqual(j(bwd, [], _res(text))[0], 1, text)
        for text in ["7 4 2", "2 7 4", "4 2 7"]:
            self.assertEqual(j(bwd, [], _res(text))[0], 0, text)

    def test_serial7_parsing_and_rule(self):
        """Task 8: Serial 7s (3 points max)"""
        a = self.t6.serial7_answers
        # the task asks for SERIAL_ANSWERS (4) subtractions, so only the first 4 are read
        self.assertEqual(a("93, 86, 79, 72, 65"), [93, 86, 79, 72])
        self.assertEqual(a("100 minus 7 is 93, minus 7 is 86, 79, 72, 65"), [93, 86, 79, 72])
        self.assertEqual(a("ninety-three, eighty six, seventy nine, seventy-two, sixty five"),
                         [93, 86, 79, 72])
        sc = lambda ans: self.t6.score_serial7(ans)[0]
        self.assertEqual(sc([93, 86, 79, 72, 65]), 3)    # 5 correct
        self.assertEqual(sc([93, 85, 78, 71, 64]), 2)    # 3 of the 4 read are correct (85 is wrong)
        self.assertEqual(sc([93, 86, 80, 72, 65]), 2)    # 3 correct (80 and 72 wrong)
        self.assertEqual(sc([93, 88, 80, 72, 60]), 1)    # 1 correct
        self.assertEqual(sc([90, 80, 70, 60, 50]), 0)
        self.assertEqual(sc([]), 0)
        self.assertEqual(sc([93, 86]), 2)                # stopped early: 2 correct

    def test_letter_scoring_hand_kept_up(self):
        # a detector stuck "up" must not give full marks: every other letter is an error
        L = self.t6.LETTERS
        times = [i * 2.0 for i in range(len(L))]
        always_up = [(t, True) for t in np.arange(0, times[-1] + 2, 0.1)]
        score, errors, _ = self.t6.score_letter_responses(L, times, [], always_up, 2.0)
        self.assertEqual(score, 0)
        self.assertGreater(errors, 2)
        always_down = [(t, False) for t in np.arange(0, times[-1] + 2, 0.1)]
        self.assertEqual(self.t6.score_letter_responses(L, times, [], always_down, 2.0)[0], 0)

    def test_fluency_needs_eleven_words(self):
        import task10_fluency as t10
        self.assertEqual(t10.fluency_points(["f%d" % i for i in range(10)]), 0)
        self.assertEqual(t10.fluency_points(["f%d" % i for i in range(11)]), 1)
        self.assertEqual(t10.f_words("fish fork fox for from fire fan"), ["fish", "fork", "fox", "fire", "fan"])

    def test_letter_scoring(self):
        L = self.t6.LETTERS
        times = [i * 2.0 for i in range(len(L))]
        perfect = [t + 0.8 for t, x in zip(times, L) if x == "A"]
        self.assertEqual(self.t6.score_letter_responses(L, times, perfect, [], 2.0)[:2], (1, 0))
        one_miss = perfect[1:]
        self.assertEqual(self.t6.score_letter_responses(L, times, one_miss, [], 2.0)[:2], (1, 1))
        two_miss = perfect[2:]
        self.assertEqual(self.t6.score_letter_responses(L, times, two_miss, [], 2.0)[:2], (0, 2))
        wrong = perfect + [times[0] + 0.8]                # raised at "F"
        self.assertEqual(self.t6.score_letter_responses(L, times, wrong, [], 2.0)[:2], (1, 1))
        wrong2 = perfect + [times[0] + 0.8, times[1] + 0.8]
        self.assertEqual(self.t6.score_letter_responses(L, times, wrong2, [], 2.0)[:2], (0, 2))
        every = [t + 0.8 for t in times]                  # raised at every letter
        self.assertEqual(self.t6.score_letter_responses(L, times, every, [], 2.0)[0], 0)
        self.assertEqual(self.t6.score_letter_responses(L, times, [], [], 2.0)[0], 0)

    def test_hand_raise_detector_on_synthetic_video(self):
        """Hands down, a practice raise, then the hand going up and down again."""
        import cv2
        import task7_letters as t7
        rng = np.random.default_rng(0)
        h, w = 360, 640

        def frame(hand_up):
            img = np.full((h, w, 3), (150, 160, 150), np.uint8)              # grey-green wall
            cv2.rectangle(img, (0, 220), (w, h), (60, 50, 50), -1)            # body / lap
            cv2.ellipse(img, (320, 150), (55, 70), 0, 0, 360, (120, 150, 200), -1)  # face (skin)
            if hand_up:
                cv2.rectangle(img, (110, 40), (190, 200), (120, 150, 200), -1)  # raised hand
            noise = rng.normal(0, 3, img.shape)
            return np.clip(img + noise, 0, 255).astype(np.uint8)

        class FakeCap:
            def __init__(self):
                self.t0 = time.time()
                self.up_during = (2.6, 5.5)          # practice raise during calibration
            def isOpened(self):
                return True
            def read(self):
                t = time.time() - self.t0
                time.sleep(0.02)
                return True, frame(self.up_during[0] <= t <= self.up_during[1])
            def release(self):
                pass

        import time
        old_say = t7.say
        t7.say = lambda *a, **k: None
        try:
            det = t7.HandRaiseDetector()
            det.cap = FakeCap()
            ok, info = det.calibrate(lambda *a: None)
        finally:
            t7.say = old_say
        self.assertTrue(ok, info)
        self.assertEqual(info["signal"], "skin", info)
        # now check up/down tracking on frames fed through read()-style features
        states = []
        for up in [False] * 5 + [True] * 5 + [False] * 5:
            fr = frame(up)
            small = cv2.GaussianBlur(cv2.resize(cv2.flip(fr, 1), (320, 180)), (5, 5), 0)
            det.last_bgr = small
            g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
            states.append(det.update(g)[0])
        self.assertEqual(states[:5], [False] * 5)
        self.assertTrue(all(states[7:10]))
        self.assertFalse(any(states[12:]))




class TestScoringRules2026(unittest.TestCase):
    def test_task7_one_error_still_scores_one(self):
        from task7_letters import score_letter_responses
        letters = list("AFABA")
        times = [0.0, 2.0, 4.0, 6.0, 8.0]
        interval = 2.0

        def ups_for(raises):
            # hand held up for 0.3 s from each raise moment
            return [(t / 10, any(r <= t / 10 < r + 0.3 for r in raises)) for t in range(0, 110)]

        # correct raises for the three A's; the B (t=6) gets one raise -> one error
        raises = [0.5, 4.5, 6.5, 8.5]
        score, errors, _ = score_letter_responses(letters, times, raises, ups_for(raises), interval)
        self.assertEqual(errors, 1)
        self.assertEqual(score, 1)
        # add a second wrong raise during the F -> two errors -> 0
        raises = [0.5, 2.5, 4.5, 6.5, 8.5]
        score, errors, _ = score_letter_responses(letters, times, raises, ups_for(raises), interval)
        self.assertEqual(errors, 2)
        self.assertEqual(score, 0)

    def test_task11_transport_and_measure_words(self):
        from task11_abstraction import ITEMS, judge_item
        tb, wr = ITEMS
        for text in ["they are both means of transport", "they both have wheels",
                     "public transport", "a measuring instrument"]:
            self.assertEqual(judge_item(tb, text, ""), 1 if "instrument" not in text else 0, text)
        for text in ["they both measure things", "they are both precision tools", "they measure length"]:
            self.assertEqual(judge_item(wr, text, ""), 1, text)
        self.assertEqual(judge_item(wr, "they are both long", ""), 0)
        self.assertEqual(judge_item(tb, "they both have legs", ""), 0)
