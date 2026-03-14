import argparse
import json
import sys

from utils.scenario_manager import (
    add_schedule,
    get_scenario_details,
    get_schedules,
    list_problem_patterns,
    remove_schedule,
    start_scenario,
    stop_scenario,
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="otel-demo-cli",
        description="AI-friendly CLI for managing OTEL demo scenarios and cron-scheduled problem injections.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format. Defaults to json for agent-friendly consumption.",
    )

    subparsers = parser.add_subparsers(dest="command")

    help_parser = subparsers.add_parser("help", help="Show help for the CLI or a specific command")
    help_parser.add_argument("topic", nargs="?", help="Optional command name")

    subparsers.add_parser("list", help="List scenarios, status, RPM, schedules, and available problem patterns")

    start_parser = subparsers.add_parser("start", help="Start a scenario")
    start_parser.add_argument("scenario", help="Scenario name to start")

    stop_parser = subparsers.add_parser("stop", help="Stop a scenario")
    stop_parser.add_argument("scenario", help="Scenario name to stop")

    problems_parser = subparsers.add_parser("problems", help="List available problem patterns for scenarios")
    problems_parser.add_argument("scenario", nargs="?", help="Optional scenario name filter")

    schedules_parser = subparsers.add_parser("schedules", help="List cron schedule entries")
    schedules_parser.add_argument("scenario", nargs="?", help="Optional scenario name filter")

    add_schedule_parser = subparsers.add_parser("add-schedule", help="Add a cron-scheduled problem pattern to a scenario")
    add_schedule_parser.add_argument("scenario", help="Scenario name")
    add_schedule_parser.add_argument("--pattern", required=True, help="Problem pattern name")
    add_schedule_parser.add_argument("--cron", required=True, help="5-field cron expression")
    add_schedule_parser.add_argument(
        "--duration-minutes",
        required=True,
        type=int,
        help="Duration in minutes for which the problem stays active after the cron trigger",
    )

    remove_schedule_parser = subparsers.add_parser("remove-schedule", help="Remove a cron schedule entry from a scenario")
    remove_schedule_parser.add_argument("scenario", help="Scenario name")
    remove_schedule_parser.add_argument("schedule_id", help="Schedule entry id to remove")

    return parser, {
        "help": help_parser,
        "list": subparsers.choices["list"],
        "start": start_parser,
        "stop": stop_parser,
        "problems": problems_parser,
        "schedules": schedules_parser,
        "add-schedule": add_schedule_parser,
        "remove-schedule": remove_schedule_parser,
    }


def render_output(result, output_format):
    if output_format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    command = result.get("command")
    if command == "list":
        for name, details in result.get("scenarios", {}).items():
            status = "running" if details.get("running") else "stopped"
            print(f"{name}: {status}")
            description_lines = details.get("description_lines", [])
            if description_lines:
                print("  description:")
                for line in description_lines:
                    print(f"    {line}")
            print(f"  rpm: {details.get('rpm')}")
            print(f"  pid: {details.get('pid')}")
            print(f"  patterns: {', '.join(details.get('available_patterns', []))}")
            schedules = details.get("schedule_entries", [])
            if schedules:
                print("  schedules:")
                for schedule in schedules:
                    print(
                        f"    - {schedule['id']}: {schedule['cron']} -> {schedule['pattern']} for {schedule['duration_minutes']} min"
                    )
            else:
                print("  schedules: none")
    elif command == "problems":
        for name, patterns in result.get("problems", {}).items():
            print(f"{name}: {', '.join(patterns)}")
    elif command == "schedules":
        for name, schedules in result.get("schedules", {}).items():
            print(f"{name}:")
            if schedules:
                for schedule in schedules:
                    print(
                        f"  - {schedule['id']}: {schedule['cron']} -> {schedule['pattern']} for {schedule['duration_minutes']} min"
                    )
            else:
                print("  - none")
    elif command in {"start", "stop", "add-schedule", "remove-schedule"}:
        if result.get("ok"):
            print(f"{command}: ok")
            for key in sorted(k for k in result if k not in {"ok", "command"}):
                print(f"  {key}: {result[key]}")
        else:
            print(f"{command}: error")
            print(f"  error: {result.get('error')}")
    else:
        print(result)


def main():
    parser, parser_map = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "help":
        if getattr(args, "topic", None) and args.topic in parser_map:
            parser_map[args.topic].print_help()
        else:
            parser.print_help()
        return 0

    if args.command == "list":
        result = {
            "ok": True,
            "command": "list",
            "scenarios": get_scenario_details(),
        }
        render_output(result, args.format)
        return 0

    if args.command == "start":
        action_result = start_scenario(args.scenario)
        result = {"ok": not bool(action_result.get("error")), "command": "start", **action_result}
        render_output(result, args.format)
        return 0 if result["ok"] else 1

    if args.command == "stop":
        action_result = stop_scenario(args.scenario)
        result = {"ok": not bool(action_result.get("error")), "command": "stop", **action_result}
        render_output(result, args.format)
        return 0 if result["ok"] else 1

    if args.command == "problems":
        problems = list_problem_patterns()
        if args.scenario:
            if args.scenario not in problems:
                result = {
                    "ok": False,
                    "command": "problems",
                    "error": f"Unknown scenario '{args.scenario}'",
                }
                render_output(result, args.format)
                return 1
            problems = {args.scenario: problems[args.scenario]}
        result = {"ok": True, "command": "problems", "problems": problems}
        render_output(result, args.format)
        return 0

    if args.command == "schedules":
        all_schedules = {}
        if args.scenario:
            all_schedules[args.scenario] = get_schedules(args.scenario)
        else:
            for scenario_name in get_scenario_details():
                all_schedules[scenario_name] = get_schedules(scenario_name)
        result = {"ok": True, "command": "schedules", "schedules": all_schedules}
        render_output(result, args.format)
        return 0

    if args.command == "add-schedule":
        action_result = add_schedule(args.scenario, args.pattern, args.cron, args.duration_minutes)
        result = {"ok": not bool(action_result.get("error")), "command": "add-schedule", **action_result}
        render_output(result, args.format)
        return 0 if result["ok"] else 1

    if args.command == "remove-schedule":
        action_result = remove_schedule(args.scenario, args.schedule_id)
        result = {"ok": not bool(action_result.get("error")), "command": "remove-schedule", **action_result}
        render_output(result, args.format)
        return 0 if result["ok"] else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
