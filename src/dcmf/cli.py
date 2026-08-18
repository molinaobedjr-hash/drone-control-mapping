"""Command-line access to DCMF data, analysis, and device checks."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from dcmf.analysis.session_quality import evaluate_session, list_experiments
from dcmf.analysis.synchronized import analyze_experiment, load_session
from dcmf.config.settings import AppSettings


def _resolve_experiment(database: Path, value: str) -> dict[str, Any]:
    experiments = list_experiments(database, completed_only=False)
    exact = [
        item
        for item in experiments
        if item["id"] == value or str(item["name"]).casefold() == value.casefold()
    ]
    if exact:
        return exact[0]
    partial = [
        item
        for item in experiments
        if str(item["id"]).startswith(value)
        or value.casefold() in str(item["name"]).casefold()
    ]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No experiment matches: {value}")
    names = "\n".join(f"  {item['id']}  {item['name']}" for item in partial)
    raise SystemExit(f"Experiment selector is ambiguous:\n{names}")


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    connection = sqlite3.connect(
        f"file:{resolved}?mode=ro", uri=True, timeout=30.0
    )
    connection.row_factory = sqlite3.Row
    return connection


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _command_list(args, settings: AppSettings) -> int:
    experiments = list_experiments(
        args.database, completed_only=not args.all
    )
    if args.json:
        _print_json(experiments)
        return 0
    if not experiments:
        print("No experiments found.")
        return 0
    print(f"{'ID':36}  {'STATUS':10}  {'STARTED (UTC)':27}  NAME")
    for item in experiments:
        print(
            f"{item['id']:36}  {item['status']:10}  "
            f"{str(item.get('started_utc_iso') or '—'):27}  {item['name']}"
        )
    return 0


def _command_show(args, settings: AppSettings) -> int:
    experiment = _resolve_experiment(args.database, args.experiment)
    session = load_session(args.database, experiment["id"])
    payload = {
        "experiment": session.experiment,
        "counts": {
            "controller_samples": len(session.controller),
            "manual_control_messages": len(session.manual_control),
            "rc_channel_messages": len(session.rc_channels),
            "servo_output_messages": len(session.servo_outputs),
            "events": len(session.events),
            "guided_trials": len(session.trials),
            "complete_guided_trials": (
                int(session.trials["complete"].fillna(False).sum())
                if "complete" in session.trials
                else 0
            ),
            "sdr_records": len(session.sdr),
        },
        "mavlink_counts": session.mavlink_counts,
        "trials": session.trials.to_dict(orient="records"),
        "iq_files": sorted(
            {str(value) for value in session.sdr.get("iq_file", []) if value}
        ),
    }
    _print_json(payload)
    return 0


def _command_markers(args, settings: AppSettings) -> int:
    experiment = _resolve_experiment(args.database, args.experiment)
    connection = _connect_read_only(args.database)
    try:
        rows = connection.execute(
            """
            SELECT monotonic_ns, utc_ns, kind,
                   json_extract(payload_json, '$.label') AS label,
                   json_extract(payload_json, '$.action') AS action,
                   json_extract(payload_json, '$.trial_number') AS trial_number
            FROM events
            WHERE experiment_id = ? AND source = 'OPERATOR'
            ORDER BY monotonic_ns, id
            """,
            (experiment["id"],),
        ).fetchall()
        _print_json([dict(row) for row in rows])
    finally:
        connection.close()
    return 0


def _command_hex(args, settings: AppSettings) -> int:
    experiment = _resolve_experiment(args.database, args.experiment)
    connection = _connect_read_only(args.database)
    try:
        where_name = ""
        parameters: list[Any] = [experiment["id"]]
        if args.message:
            where_name = " AND message_name = ?"
            parameters.append(args.message)
        parameters.append(args.limit)
        rows = connection.execute(
            f"""
            SELECT id, monotonic_ns, direction, message_name, system_id,
                   component_id, raw_hex, decoded_json
            FROM mavlink_messages
            WHERE experiment_id = ? {where_name}
            ORDER BY monotonic_ns DESC, id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        _print_json([dict(row) for row in reversed(rows)])
    finally:
        connection.close()
    return 0


def _command_quality(args, settings: AppSettings) -> int:
    experiment = _resolve_experiment(args.database, args.experiment)
    report = evaluate_session(
        database_path=args.database,
        experiment_root=settings.experiment_directory,
        export_root=settings.export_directory,
        iq_root=settings.iq_directory,
        experiment_id=experiment["id"],
    )
    payload = report.to_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        print(args.output)
    else:
        _print_json(payload)
    return 1 if report.overall_status == "FAIL" else 0


def _command_analyze(args, settings: AppSettings) -> int:
    experiment = _resolve_experiment(args.database, args.experiment)
    result = analyze_experiment(
        args.database,
        experiment["id"],
        args.output,
        tolerance_ms=args.tolerance_ms,
    )
    _print_json(
        {
            "experiment_id": result.experiment_id,
            "output_directory": result.output_directory,
            "synchronized_csv": result.synchronized_csv,
            "summary_json": result.summary_json,
            "row_count": result.row_count,
        }
    )
    return 0


def _command_features(args, settings: AppSettings) -> int:
    from dcmf.ml.features import generate_feature_dataset

    ids = None
    if args.experiment:
        ids = [
            _resolve_experiment(args.database, value)["id"]
            for value in args.experiment
        ]
    result = generate_feature_dataset(
        args.database,
        args.output,
        experiment_ids=ids,
        include_iq_power=not args.skip_iq,
    )
    _print_json(
        {
            "csv_path": result.csv_path,
            "metadata_path": result.metadata_path,
            "row_count": result.row_count,
            "feature_count": result.feature_count,
            "experiment_count": result.experiment_count,
        }
    )
    return 0


def _command_train(args, settings: AppSettings) -> int:
    from dcmf.ml.classifier import train_random_forest

    result = train_random_forest(args.dataset, args.output)
    _print_json(
        {
            "status": result.status,
            "output_directory": result.output_directory,
            "model_path": result.model_path,
            "metrics_path": result.metrics_path,
            "predictions_path": result.predictions_path,
            "feature_importance_path": result.feature_importance_path,
        }
    )
    return 0 if result.status == "complete" else 2


def _command_devices(args, settings: AppSettings) -> int:
    from dcmf.acquisition.mavlink.reader import discover_serial_ports
    from dcmf.acquisition.sdr.reader import discover_uhd_devices, uhd_backend_status

    serial = [
        {
            "device": item.device,
            "description": item.description,
            "manufacturer": item.manufacturer,
            "product": item.product,
            "vid": item.vid,
            "pid": item.pid,
        }
        for item in discover_serial_ports()
    ]
    controller: dict[str, Any] = {"detected": False}
    try:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        controller = {"detected": count > 0, "count": count, "devices": []}
        for index in range(count):
            joystick = pygame.joystick.Joystick(index)
            joystick.init()
            controller["devices"].append(
                {
                    "index": index,
                    "name": joystick.get_name(),
                    "axes": joystick.get_numaxes(),
                    "buttons": joystick.get_numbuttons(),
                    "hats": joystick.get_numhats(),
                }
            )
            joystick.quit()
        pygame.joystick.quit()
        pygame.quit()
    except Exception as exc:
        controller = {"detected": False, "error": str(exc)}
    backend = uhd_backend_status()
    try:
        uhd_devices = [
            {
                "display_name": item.display_name,
                "device_args": item.device_args,
                "serial": item.serial,
                "product": item.product,
            }
            for item in discover_uhd_devices()
        ] if backend["uhd_find_devices"] else []
    except Exception as exc:
        uhd_devices = [{"error": str(exc)}]
    _print_json(
        {
            "controller": controller,
            "serial_ports": serial,
            "uhd_backend": backend,
            "uhd_devices": uhd_devices,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    settings = AppSettings()
    parser = argparse.ArgumentParser(
        prog="python -m dcmf.cli",
        description="Inspect and analyze DCMF experiments without editing SQLite.",
    )
    parser.add_argument(
        "--database", type=Path, default=settings.database_path,
        help=f"SQLite database (default: {settings.database_path})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("list", help="List experiments")
    command.add_argument("--all", action="store_true", help="Include recording sessions")
    command.add_argument("--json", action="store_true")
    command.set_defaults(handler=_command_list)

    command = subparsers.add_parser("show", help="Show one experiment summary")
    command.add_argument("experiment", help="Full/partial ID or name")
    command.set_defaults(handler=_command_show)

    command = subparsers.add_parser("markers", help="Show manual and guided markers")
    command.add_argument("experiment")
    command.set_defaults(handler=_command_markers)

    command = subparsers.add_parser("hex", help="Show saved MAVLink raw hex")
    command.add_argument("experiment")
    command.add_argument("--message", help="Filter by MAVLink message name")
    command.add_argument("--limit", type=int, default=25)
    command.set_defaults(handler=_command_hex)

    command = subparsers.add_parser("quality", help="Run Milestone 9 checks")
    command.add_argument("experiment")
    command.add_argument("--output", type=Path)
    command.set_defaults(handler=_command_quality)

    command = subparsers.add_parser("analyze", help="Write synchronized analysis files")
    command.add_argument("experiment")
    command.add_argument("--output", type=Path, default=settings.analysis_directory)
    command.add_argument("--tolerance-ms", type=float, default=250.0)
    command.set_defaults(handler=_command_analyze)

    command = subparsers.add_parser("features", help="Build guided-trial ML dataset")
    command.add_argument("--experiment", action="append", help="Repeat to select sessions")
    command.add_argument("--output", type=Path, default=settings.analysis_directory / "ml")
    command.add_argument("--skip-iq", action="store_true", help="Do not read IQ samples")
    command.set_defaults(handler=_command_features)

    command = subparsers.add_parser("train", help="Train Random Forest baseline")
    command.add_argument("dataset", type=Path)
    command.add_argument("--output", type=Path, default=settings.analysis_directory / "model")
    command.set_defaults(handler=_command_train)

    command = subparsers.add_parser("devices", help="Detect controller, serial, and USRP devices")
    command.set_defaults(handler=_command_devices)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = AppSettings(database_path=args.database)
    try:
        return int(args.handler(args, settings))
    except BrokenPipeError:
        return 0
    except (FileNotFoundError, KeyError, RuntimeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
