"""Warm the live worker and verify its first real result before opening the game."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKET_FILES = (
    "creature.glb",
    "forms.json",
    "base_albedo.png",
    "base_normal.png",
    "previous_albedo.png",
    "previous_normal.png",
    "next_albedo.png",
    "next_normal.png",
)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def ready_packet(directory):
    packet = read_json(directory / "latest.json")
    if not isinstance(packet, dict) or packet.get("sequence") != 1:
        return None
    folder = Path(packet.get("directory", "")).resolve()
    if folder.parent != directory.resolve():
        raise RuntimeError("The first packet points outside its session directory")
    if not all(
        (folder / name).is_file() and (folder / name).stat().st_size for name in REQUIRED_PACKET_FILES
    ):
        return None
    if packet.get("diffusion", {}).get("mock") is not False or not packet.get("reconstruction", {}).get(
        "neural"
    ):
        raise RuntimeError("The first packet is not a real neural result")
    if packet.get("texture_method") and any(
        packet.get("texture", {}).get(name, {}).get("diffusion", {}).get("mock") is not False
        for name in ("front", "back", "face")
    ):
        raise RuntimeError("The first texture is not a real neural result")
    return packet


def wait_ready(worker, directory, timeout=600):
    started, last_status = time.monotonic(), None
    while True:
        if worker.poll() is not None:
            state = read_json(directory / "status.json") or {}
            raise RuntimeError(
                f"Нейрорендер завершился до запуска игры: {state.get('error', 'см. worker.log')}"
            )
        packet = ready_packet(directory)
        if packet:
            return packet
        state = read_json(directory / "status.json") or {}
        message = state.get("stage", "Запуск Python и CUDA…")
        if state.get("error"):
            message += ": " + str(state["error"])
        if message != last_status:
            print(message, flush=True)
            last_status = message
        if time.monotonic() - started > timeout:
            raise TimeoutError("Не удалось получить первую форму за 10 минут; см. worker.log")
        time.sleep(0.15)


def stop_process(process, graceful=10):
    if process is None or process.poll() is not None:
        return
    try:
        process.wait(timeout=graceful)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def launch(arguments):
    session = ROOT / "artifacts/3d/live" / f"{time.time_ns()}_launch"
    session.mkdir(parents=True)
    worker, game = None, None

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        # Godot resolves its own user:// location; share exactly the current UI defaults.
        exported = subprocess.run(
            [
                str(ROOT / ".tools/godot"),
                "--headless",
                "--path",
                str(ROOT / "godot"),
                "--script",
                "res://tools/export_launch_settings.gd",
                "--",
                "--output=" + str(session / "settings.json"),
                *(
                    ["--defaults"]
                    if any(
                        a.startswith(("--smoke-", "--record-")) or a in ("--scenario", "--morph-demo")
                        for a in arguments
                    )
                    else []
                ),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if exported.returncode or not (session / "settings.json").exists():
            raise RuntimeError("Не удалось прочитать настройки Godot: " + exported.stdout + exported.stderr)
        print("Подготовка нейрорендера. Окно игры откроется после первой готовой формы.", flush=True)
        print("Журнал: " + str(session / "worker.log"), flush=True)
        with (session / "worker.log").open("w") as log:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/live_3d.py"),
                    "--output",
                    str(session),
                    "--seed",
                    str(int(read_json(session / "settings.json").get("seed", 1928))),
                    "--parent",
                    str(os.getpid()),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            packet = wait_ready(worker, session)
            ready_at = time.time()
            print("Первая форма и текстуры готовы. Открываю игру.", flush=True)
            game = subprocess.Popen(
                [
                    str(ROOT / ".tools/godot"),
                    "--path",
                    str(ROOT / "godot"),
                    "--disable-vsync",
                    "--max-fps",
                    "60",
                    "res://room_3d.tscn",
                    "--",
                    *arguments,
                    "--prepared-session=" + str(session),
                    "--prepared-worker=" + str(worker.pid),
                ],
                cwd=ROOT,
            )
            (session / "launch.json").write_text(
                json.dumps(
                    {
                        "first_packet_sequence": packet["sequence"],
                        "ready_at": ready_at,
                        "game_started_at": time.time(),
                        "worker_pid": worker.pid,
                        "game_pid": game.pid,
                        "first_frame_expected_sequence": 1,
                    },
                    indent=2,
                )
            )
            while game.poll() is None:
                if worker.poll() is not None and not (session / "worker_exited").exists():
                    (session / "worker_exited").write_text(str(worker.returncode))
                time.sleep(.15)
            return game.returncode
    except KeyboardInterrupt:
        print("\nЗапуск остановлен.", flush=True)
        return 130
    except (RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        print("Диагностика: " + str(session / "worker.log"), file=sys.stderr)
        return 1
    finally:
        (session / "stop").write_text("stop")
        if game is not None and game.poll() is None:
            game.terminate()
        stop_process(game, 3)
        stop_process(worker)


if __name__ == "__main__":
    raise SystemExit(launch(sys.argv[1:]))
