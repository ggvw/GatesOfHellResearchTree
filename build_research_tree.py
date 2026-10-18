#!/usr/bin/env python3
"""Detect the game, export its research data, and build the HTML viewer in one step.

Without folder arguments a small window opens where the game and output
folders can be chosen. Passing --game-path and/or --output (or --no-gui)
runs everything from the command line instead.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
EXPORT_SCRIPT = SCRIPT_DIR / "export_research_trees.py"
HTML_SCRIPT = SCRIPT_DIR / "create_research_tree_html.py"
STEAM_APP_ID = "400750"
GAME_FOLDER_NAME = "Call to Arms - Gates of Hell"
OUTPUT_FOLDER_NAME = "Gates of Hell Research Tree"
MARKER_FILE = "gamelogic.pak"
OUTPUT_SIGNATURE = "<title>Gates of Hell Research Trees</title>"


def resolve_resource_dir(path: Path | str | None) -> Path | None:
    """Return the game's resource directory for a game root or resource path."""
    if not path:
        return None
    path = Path(path).expanduser()
    for candidate in (path, path / "resource"):
        if (candidate / MARKER_FILE).is_file():
            return candidate.resolve()
    return None


def _home_steam_roots(home: Path) -> list[Path]:
    if sys.platform == "darwin":
        support = home / "Library/Application Support"
        roots = [support / "Steam"]
        # The game is Windows-only; on macOS it normally runs in a Wine bottle.
        for pattern in ("CrossOver/Bottles/*/drive_c/Program Files (x86)/Steam",
                        "CrossOver/Bottles/*/drive_c/Program Files/Steam"):
            roots.extend(sorted(support.glob(pattern)))
        whisky = home / "Library/Containers/com.isaacmarovitz.Whisky/Bottles"
        roots.extend(sorted(whisky.glob("*/drive_c/Program Files (x86)/Steam")))
        return roots
    return [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]


def _windows_steam_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg
    except ImportError:
        return roots
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, key_name, value_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                roots.append(Path(winreg.QueryValueEx(key, value_name)[0]))
        except OSError:
            continue
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "Steam")
    return roots


def steam_roots(home: Path | None = None) -> list[Path]:
    """Return possible Steam installation directories for this operating system."""
    roots = _windows_steam_roots() if os.name == "nt" else []
    roots += _home_steam_roots(home or Path.home())
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def steam_libraries(roots: Iterable[Path]) -> list[Path]:
    """Return every steamapps directory, including libraries in libraryfolders.vdf."""
    libraries: list[Path] = []

    def add(path: Path) -> None:
        if path.is_dir() and path not in libraries:
            libraries.append(path)

    for root in roots:
        steamapps = root / "steamapps"
        add(steamapps)
        for config in (steamapps / "libraryfolders.vdf", root / "config/libraryfolders.vdf"):
            try:
                text = config.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for value in re.findall(r'"path"\s+"([^"]+)"', text):
                add(Path(value.replace("\\\\", "\\")) / "steamapps")
    return libraries


def find_game_resource_dirs(home: Path | None = None) -> list[Path]:
    """Return detected game resource directories, most likely first."""
    found: list[Path] = []
    for library in steam_libraries(steam_roots(home)):
        folder = GAME_FOLDER_NAME
        manifest = library / f"appmanifest_{STEAM_APP_ID}.acf"
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
            match = re.search(r'"installdir"\s+"([^"]+)"', text)
            if match:
                folder = match.group(1)
        except OSError:
            pass
        resource = resolve_resource_dir(library / "common" / folder)
        if resource and resource not in found:
            found.append(resource)
    return found


def documents_dir() -> Path:
    home = Path.home()
    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL: the user's (possibly redirected) Documents folder.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    elif sys.platform != "darwin":
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        try:
            match = re.search(r'^XDG_DOCUMENTS_DIR="([^"]+)"', config.read_text(), re.MULTILINE)
            if match:
                path = Path(match.group(1).replace("$HOME", str(home)))
                if path.is_dir():
                    return path
        except OSError:
            pass
    documents = home / "Documents"
    return documents if documents.is_dir() else home


def default_output_dir() -> Path:
    return documents_dir() / OUTPUT_FOLDER_NAME


def is_previous_output(directory: Path) -> bool:
    try:
        with (directory / "index.html").open(encoding="utf-8", errors="replace") as handle:
            return OUTPUT_SIGNATURE in handle.read(4096)
    except OSError:
        return False


def check_output_dir(output_dir: Path, resource_dir: Path | None = None) -> str | None:
    """Return why output_dir must not be replaced, or None when it is safe."""
    output_dir = output_dir.expanduser().resolve()
    for protected in (Path.home().resolve(), SCRIPT_DIR, Path(output_dir.anchor)):
        if output_dir == protected or output_dir in protected.parents:
            return f"Choose a dedicated output folder, not {output_dir}"
    if resource_dir:
        game_dir = resource_dir.resolve().parent
        if output_dir == game_dir or game_dir in output_dir.parents or output_dir in game_dir.parents:
            return "The output folder must be outside the game folder"
    if output_dir.exists():
        if not output_dir.is_dir():
            return f"{output_dir} is not a folder"
        if any(output_dir.iterdir()) and not is_previous_output(output_dir):
            return (
                f"{output_dir} is not empty and does not contain a previous research tree. "
                "Its contents would be deleted; choose an empty or new folder"
            )
    return None


def run_pipeline(resource_dir: Path, output_dir: Path, emit: Callable[[str], None]) -> int:
    """Run the export and HTML scripts, passing each output line to emit."""
    if find_spec("PIL") is None:
        emit("ERROR: Pillow is required: python3 -m pip install Pillow")
        return 1
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryDirectory(prefix="goh_research_export_") as temp:
        export_dir = Path(temp) / "research_export"
        commands = [
            [sys.executable, str(EXPORT_SCRIPT), str(resource_dir), "--output", str(export_dir)],
            [sys.executable, str(HTML_SCRIPT), str(resource_dir),
             "--input", str(export_dir), "--output", str(output_dir)],
        ]
        for command in commands:
            emit(f"Running {Path(command[1]).name}")
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, env=env, cwd=SCRIPT_DIR,
                                  creationflags=flags) as process:
                assert process.stdout is not None
                for raw in process.stdout:
                    emit(raw.decode("utf-8", errors="replace").rstrip())
            if process.returncode:
                emit(f"ERROR: {Path(command[1]).name} failed with exit code {process.returncode}")
                return process.returncode
    emit(f"Done: {output_dir / 'index.html'}")
    return 0


def choose_directory(title: str, initial: Path, parent=None) -> Path | None:
    """Show the platform's folder picker and return the selection."""
    start = initial if initial.is_dir() else next(
        (p for p in initial.parents if p.is_dir()), Path.home())
    if sys.platform.startswith("linux"):
        # Tk's own dialog is not native on Linux; prefer the desktop's dialog when available.
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        tools = ["kdialog", "zenity"] if "KDE" in desktop else ["zenity", "kdialog"]
        for tool in tools:
            if not shutil.which(tool):
                continue
            if tool == "zenity":
                command = ["zenity", "--file-selection", "--directory",
                           f"--title={title}", f"--filename={start}{os.sep}"]
            else:
                command = ["kdialog", "--title", title, "--getexistingdirectory", str(start)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except OSError:
                continue
            selection = result.stdout.strip()
            return Path(selection) if result.returncode == 0 and selection else None
    from tkinter import filedialog

    selection = filedialog.askdirectory(parent=parent, title=title, initialdir=str(start),
                                        mustexist=False)
    return Path(selection) if selection else None


def run_gui(game_path: Path | None, output_dir: Path) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Gates of Hell Research Tree")
    root.minsize(640, 420)
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(4, weight=1)

    game_var = tk.StringVar(value=str(game_path or ""))
    output_var = tk.StringVar(value=str(output_dir))
    status_var = tk.StringVar()
    messages: queue.Queue = queue.Queue()
    result = {"code": None}

    def browse(variable: tk.StringVar, title: str) -> None:
        selection = choose_directory(title, Path(variable.get() or Path.home()).expanduser(), root)
        if selection:
            variable.set(str(selection))

    ttk.Label(frame, text="Game folder:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frame, textvariable=game_var).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(frame, text="Browse…", command=lambda: browse(
        game_var, "Select the Call to Arms - Gates of Hell folder")).grid(row=0, column=2)
    ttk.Label(frame, textvariable=status_var).grid(row=1, column=1, sticky="w", padx=6)
    ttk.Label(frame, text="Output folder:").grid(row=2, column=0, sticky="w", pady=(8, 0))
    ttk.Entry(frame, textvariable=output_var).grid(row=2, column=1, sticky="ew", padx=6, pady=(8, 0))
    ttk.Button(frame, text="Browse…", command=lambda: browse(
        output_var, "Select the output folder")).grid(row=2, column=2, pady=(8, 0))

    buttons = ttk.Frame(frame)
    buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=8)
    open_button = ttk.Button(buttons, text="Open research tree", state="disabled")
    open_button.pack(side="right")
    build_button = ttk.Button(buttons, text="Build")
    build_button.pack(side="right", padx=6)

    log_frame = ttk.Frame(frame)
    log_frame.grid(row=4, column=0, columnspan=3, sticky="nsew")
    log = tk.Text(log_frame, height=16, wrap="word", state="disabled")
    scrollbar = ttk.Scrollbar(log_frame, command=log.yview)
    log.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    log.pack(side="left", fill="both", expand=True)

    def update_status(*_args) -> None:
        resource = resolve_resource_dir(game_var.get().strip())
        status_var.set(f"Game data found: {resource}" if resource
                       else f"{MARKER_FILE} not found in this folder or its resource subfolder")

    game_var.trace_add("write", update_status)
    update_status()

    def append(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

    def poll() -> None:
        while True:
            try:
                kind, value = messages.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                append(value)
            else:
                result["code"] = value
                build_button.configure(state="normal")
                if value == 0:
                    open_button.configure(state="normal")
                    messagebox.showinfo("Finished", "The research tree was created.", parent=root)
                else:
                    messagebox.showerror("Failed", "The build failed; see the log for details.",
                                         parent=root)
        root.after(100, poll)

    def build() -> None:
        resource = resolve_resource_dir(game_var.get().strip())
        if not resource:
            messagebox.showerror("Game folder", "Select the Call to Arms - Gates of Hell "
                                 f"installation folder (containing resource/{MARKER_FILE}).",
                                 parent=root)
            return
        if not output_var.get().strip():
            messagebox.showerror("Output folder", "Select an output folder.", parent=root)
            return
        target = Path(output_var.get().strip()).expanduser().resolve()
        problem = check_output_dir(target, resource)
        if problem:
            messagebox.showerror("Output folder", problem, parent=root)
            return
        if is_previous_output(target) and not messagebox.askokcancel(
                "Replace output", f"Replace the existing research tree in {target}?", parent=root):
            return
        build_button.configure(state="disabled")
        open_button.configure(state="disabled")
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        open_button.configure(command=lambda: webbrowser.open((target / "index.html").as_uri()))

        def worker() -> None:
            try:
                code = run_pipeline(resource, target, lambda line: messages.put(("line", line)))
            except Exception as exc:  # Report unexpected failures instead of losing the thread.
                messages.put(("line", f"ERROR: {exc}"))
                code = 1
            messages.put(("done", code))

        threading.Thread(target=worker, daemon=True).start()

    build_button.configure(command=build)
    poll()
    root.mainloop()
    return 0 if result["code"] in (None, 0) else result["code"]


def gui_available() -> bool:
    if find_spec("tkinter") is None:
        return False
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return True


def parse_args(argv: list[str] | None = None, default_output: Path | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the research trees from an installed copy of Call to Arms - Gates of Hell\n"
            "and build the interactive HTML viewer. Without --game-path, --output, or --no-gui\n"
            "a window opens to choose the folders; otherwise everything runs on the command line."
        ),
        epilog=(
            "Examples:\n"
            "  build_research_tree.py\n"
            "  build_research_tree.py --no-gui\n"
            "  build_research_tree.py --game-path \"C:\\Program Files (x86)\\Steam\\steamapps\\"
            "common\\Call to Arms - Gates of Hell\" --output research_tree"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--game-path", type=Path,
        help="game installation folder or its resource folder (default: auto-detected Steam install)",
    )
    parser.add_argument(
        "--output", type=Path,
        help=f"folder to replace with the generated website (default: {default_output})",
    )
    parser.add_argument("--no-gui", action="store_true",
                        help="do not open a window; use auto-detected or given folders")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    default_output = default_output_dir()
    args = parse_args(argv, default_output)
    output_dir = args.output or default_output
    use_gui = not (args.no_gui or args.game_path or args.output)
    detected = [] if args.game_path else find_game_resource_dirs()
    if use_gui and gui_available():
        return run_gui(args.game_path or (detected[0].parent if detected else None), output_dir)
    if use_gui:
        print("No graphical display or tkinter available; continuing on the command line.",
              file=sys.stderr)

    if args.game_path:
        resource_dir = resolve_resource_dir(args.game_path)
        if not resource_dir:
            print(f"ERROR: {MARKER_FILE} not found in {args.game_path} or its resource folder",
                  file=sys.stderr)
            return 2
    elif detected:
        resource_dir = detected[0]
        print(f"Detected game data: {resource_dir}")
    else:
        print("ERROR: Could not find the game; pass --game-path", file=sys.stderr)
        return 2
    output_dir = output_dir.expanduser().resolve()
    problem = check_output_dir(output_dir, resource_dir)
    if problem:
        print(f"ERROR: {problem}", file=sys.stderr)
        return 2
    return run_pipeline(resource_dir, output_dir, lambda line: print(line, flush=True))


if __name__ == "__main__":
    sys.exit(main())
