#!/usr/bin/env python
"""Step-by-step CM configuration test — DOES NOT CLICK GO!

Run with CM already open on the DRIVE page.
Tests each interaction step and pauses between them so you can verify.

Usage:  python scripts/test_cm_steps.py
"""
from __future__ import annotations
import ctypes, time, sys
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import pyautogui
import pywinauto
pyautogui.FAILSAFE = False

def pause(msg: str):
    print(f"\n>>> {msg}")
    print("    Press Enter to continue (or Ctrl+C to stop)...")
    input()

def main():
    print("=" * 60)
    print("CM Step-by-Step Test (NO Go! click)")
    print("=" * 60)

    # Connect to CM
    print("\nConnecting to Content Manager...")
    try:
        app = pywinauto.Application(backend="uia").connect(
            title_re=".*Content Manager.*", timeout=10
        )
    except Exception:
        print("ERROR: Content Manager not running. Open it first!")
        return

    win = app.top_window()
    win.set_focus()
    time.sleep(1)

    # Step 1: Go to DRIVE
    print("\n--- STEP 1: Navigate to DRIVE tab ---")
    for b in win.descendants(control_type="Button"):
        if b.window_text() == "DRIVE":
            b.click_input()
            time.sleep(2)
            print("  Clicked DRIVE tab")
            break

    pause("Check: are you on the DRIVE page?")

    # Step 2: Click RACE session type
    print("\n--- STEP 2: Click RACE tab ---")
    win = app.top_window()
    for t in win.descendants(control_type="Text"):
        try:
            if t.window_text() == "RACE":
                r = t.rectangle()
                cx = r.left + (r.right - r.left) // 2
                cy = r.top + (r.bottom - r.top) // 2
                pyautogui.click(cx, cy)
                print(f"  Clicked RACE at ({cx}, {cy})")
                time.sleep(2)
                break
        except:
            pass

    pause("Check: is RACE tab selected (bold white text)?")

    # Step 3: Set time to 14:00
    print("\n--- STEP 3: Set time to 14:00 ---")
    win = app.top_window()
    for e in win.descendants(control_type="Edit"):
        try:
            r = e.rectangle()
            t = e.window_text()
            if ":" in t and 250 < r.top < 500:
                print(f"  Found time field: '{t}' at ({r.left}, {r.top})")
                e.set_edit_text("14:00")
                time.sleep(0.5)
                print(f"  Set to: '{e.window_text()}'")
                break
        except:
            pass

    pause("Check: does the time show 14:00?")

    # Step 4: Scan all Edit fields in RACE mode
    print("\n--- STEP 4: Scan all Edit fields ---")
    win = app.top_window()
    edits = []
    for e in win.descendants(control_type="Edit"):
        try:
            r = e.rectangle()
            t = e.window_text()
            if r.top > 700 and len(t) < 30:
                edits.append((r.top, r.left, r.right - r.left, t, e))
                print(f"  Edit [{r.left},{r.top} w={r.right-r.left}] = '{t}'")
        except:
            pass

    edits.sort(key=lambda x: (x[0], x[1]))

    # Step 5: Set AI strength to 80
    print("\n--- STEP 5: Set AI strength ---")
    # From the screenshot, AI strength "91" is the first 2-digit number in the
    # second row of edits (around y=1150-1200)
    for top, left, width, val, ctrl in edits:
        if val.isdigit() and 40 <= int(val) <= 100 and width > 25:
            print(f"  Found AI strength: '{val}' at ({left}, {top})")
            ctrl.set_edit_text("80")
            time.sleep(0.5)
            print(f"  Set to: '{ctrl.window_text()}'")
            break

    pause("Check: does Opponents strength show ~80%?")

    # Step 6: Set opponents to 23
    print("\n--- STEP 6: Set opponent count ---")
    # Opponents count is typically the right-side edit in the strength row
    for top, left, width, val, ctrl in edits:
        if val.isdigit() and 1 <= int(val) <= 30 and left > 1500:
            print(f"  Found opponents: '{val}' at ({left}, {top})")
            ctrl.set_edit_text("23")
            time.sleep(0.5)
            print(f"  Set to: '{ctrl.window_text()}'")
            break

    pause("Check: does it show 23 opponents?")

    # Step 7: Set race duration (laps)
    print("\n--- STEP 7: Set race laps ---")
    for top, left, width, val, ctrl in edits:
        if val.isdigit() and 1 <= int(val) <= 50 and left < 1000:
            print(f"  Found race laps: '{val}' at ({left}, {top})")
            ctrl.set_edit_text("5")
            time.sleep(0.5)
            print(f"  Set to: '{ctrl.window_text()}'")
            break

    pause("Check: does Race duration show 5 laps?")

    # Step 8: Select car (Abarth 500)
    print("\n--- STEP 8: Select car ---")
    win = app.top_window()
    # Click car image area (left side of drive page)
    pyautogui.click(311, 440)
    print("  Clicked car image area at (311, 440)")
    time.sleep(2)

    # Find filter box and type
    win = app.top_window()
    filter_text = "abarth 500 assetto"
    typed = False
    for ctrl in list(win.descendants(control_type="ComboBox")) + list(win.descendants(control_type="Edit")):
        try:
            r = ctrl.rectangle()
            if r.left > 1500 and 100 < r.top < 500 and (r.right - r.left) > 200:
                ctrl.click_input()
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite(filter_text, interval=0.04)
                typed = True
                print(f"  Typed filter '{filter_text}' at ({r.left}, {r.top})")
                time.sleep(1.5)
                break
        except:
            pass

    if not typed:
        print("  WARNING: No filter box found")

    # Find and click matching item
    win = app.top_window()
    frag = "abarth"
    found = False
    for item in win.descendants(control_type="ListItem"):
        try:
            t = item.window_text()
            if frag in t.lower():
                r = item.rectangle()
                pyautogui.doubleClick((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                print(f"  Selected ListItem: {t}")
                found = True
                time.sleep(1)
                break
        except:
            pass

    if not found:
        # Try Text elements
        for t_el in win.descendants(control_type="Text"):
            try:
                txt = t_el.window_text()
                r = t_el.rectangle()
                if frag in txt.lower() and r.top > 200 and len(txt) < 100:
                    pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                    print(f"  Selected Text: {txt}")
                    found = True
                    time.sleep(1)
                    break
            except:
                pass

    if not found:
        print("  WARNING: No car match found")

    # Go back
    win = app.top_window()
    for b in win.descendants(control_type="Button"):
        try:
            if b.window_text() == "Back":
                b.click_input()
                print("  Clicked Back")
                time.sleep(1)
                break
        except:
            pass

    pause("Check: did the car change to Abarth 500 Assetto Corse?")

    # Step 9: Select track (Imola)
    print("\n--- STEP 9: Select track ---")
    win = app.top_window()
    pyautogui.click(988, 440)
    print("  Clicked track image area at (988, 440)")
    time.sleep(2)

    # Look for "Imola" in visible track list
    win = app.top_window()
    found = False
    for t_el in win.descendants(control_type="Text"):
        try:
            r = t_el.rectangle()
            txt = t_el.window_text()
            if "imola" in txt.lower() and r.left > 2000 and r.top > 350:
                pyautogui.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                print(f"  Clicked track: {txt}")
                found = True
                time.sleep(1)
                break
        except:
            pass

    if not found:
        print("  WARNING: Imola not found in track list")

    # Click OK
    win = app.top_window()
    for b in win.descendants(control_type="Button"):
        try:
            if b.window_text() == "OK":
                r = b.rectangle()
                if r.top > 1500:
                    b.click_input()
                    print("  Clicked OK")
                    time.sleep(1)
                    break
        except:
            pass

    pause("Check: did the track change to Imola?")

    print("\n" + "=" * 60)
    print("ALL STEPS COMPLETE — Go! was NOT clicked.")
    print("If everything looks correct, you can click Go! manually")
    print("or run the full autopilot.")
    print("=" * 60)


if __name__ == "__main__":
    main()
