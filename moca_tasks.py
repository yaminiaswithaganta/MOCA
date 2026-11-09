"""
The 13 MoCA tasks: their ids, what the examiner sees for each one, and how to run one.

Used by the command-line run (run_moca.py).
"""

TASK_IDS = {1: "task1_trail_making", 2: "task2_cube_copy", 3: "task3_clock_draw",
            4: "task4_naming", 5: "task5_memory", 6: "task6_digit_span",
            7: "task7_letters", 8: "task8_serial7s", 9: "task9_sentence_repetition",
            10: "task10_fluency", 11: "task11_abstraction", 12: "task12_delayed_recall",
            13: "task13_orientation"}
ALL_TASKS = list(TASK_IDS)

# number -> (short title, what the patient does, uses the camera?)
TASK_INFO = {
    1: ("Trail making", "Connect the numbers and letters in order: 1 - A - 2 - B - 3 - C - 4 - D - 5 - E.", False),
    2: ("Cube copy", "Hold the drawing up to the camera. Copy the cube exactly, keeping the whole cube in view.", True),
    3: ("Clock drawing", "Draw a clock face with all the numbers, then draw the hands to show ten past eleven.", True),
    4: ("Naming", "Name the three animals shown: lion, rhinoceros, camel.", False),
    5: ("Memory (learning)", "Learn the five words FACE, VELVET, CHURCH, DAISY, RED over two rounds. Not scored; used again in task 12.", False),
    6: ("Digit span", "Repeat the digits forward, then backward.", False),
    7: ("Letters (A)", "Raise a hand each time the letter A is heard. Camera watches the hand.", True),
    8: ("Serial 7s", "Start at 100 and subtract 7 each time, as far as you can.", False),
    9: ("Sentence repetition", "Repeat the two sentences exactly after the voice.", False),
    10: ("F-word fluency", "Say as many different words starting with F as possible in one minute. 11 or more scores 1.", False),
    11: ("Abstraction", "Say how a train and a bicycle are alike, then how a watch and a ruler are alike.", False),
    12: ("Delayed recall", "Say back the five words from task 5, with no clues.", False),
    13: ("Orientation", "Say today's date, month, year, day, the place and the city.", False),
}

SECTION_OF = {1: "Visuospatial / Executive", 2: "Visuospatial / Executive", 3: "Visuospatial / Executive",
              4: "Naming", 5: "Memory", 6: "Attention", 7: "Attention", 8: "Attention",
              9: "Language", 10: "Language", 11: "Abstraction", 12: "Delayed recall",
              13: "Orientation"}


def run_single_task(number, cam_index=0, show_result=False):
    """Run one task (1-13). Returns its result dict, or None. Each task saves its own JSON."""
    if number == 1:
        from task1_trail_making import run_task1
        return run_task1(show_result=show_result)
    if number == 2:
        from task2_cube_copy import run_task2
        return run_task2(cam_index=cam_index, show_result=show_result)
    if number == 3:
        from task3_clock_draw import run_task3
        return run_task3(cam_index=cam_index, show_result=show_result)
    if number == 4:
        from task4_naming import run_task4
        return run_task4(show_result=show_result)
    if number == 5:
        from task5_memory import run_task5
        return run_task5(show_result=show_result)
    if number == 6:
        from task6_attention import run_task6
        return run_task6(cam_index=cam_index, show_result=show_result)
    if number == 7:
        from task6_attention import run_task7
        return run_task7(cam_index=cam_index, show_result=show_result)
    if number == 8:
        from task6_attention import run_task8
        return run_task8(cam_index=cam_index, show_result=show_result)
    if number == 9:
        from task9_sentence_repetition import run_task9
        return run_task9(show_result=show_result)
    if number == 10:
        from task10_fluency import run_task10
        return run_task10(show_result=show_result)
    if number == 11:
        from task11_abstraction import run_task11
        return run_task11(show_result=show_result)
    if number == 12:
        from task12_delayed_recall import run_task12
        return run_task12(show_result=show_result)
    if number == 13:
        from task13_orientation import run_task13
        return run_task13(show_result=show_result)
    raise ValueError(f"no task {number}")
