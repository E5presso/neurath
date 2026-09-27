"""Exercise installed Codex hooks through real app-server turns and live steering.

Requires an already installed/trusted project. It never changes trust, permissions
or process state directly. Raw host evidence stays in the caller's local output.
"""

import argparse
import json
from pathlib import Path

from native_host import Host



def probe(project, output):
    output.mkdir(parents=True, exist_ok=True)
    host = Host(project, output)
    report = {"status": "running"}
    try:
        hooks = host.request("hooks/list", {"cwds": [str(project)]})
        (output / "hooks.json").write_text(json.dumps(hooks, indent=2))
        installed = hooks["data"][0]["hooks"]
        assert len(installed) == 9
        assert all(item["trustStatus"] == "trusted" and item["enabled"] for item in installed)
        thread = host.request(
            "thread/start",
            {
                "cwd": str(project),
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
            },
        )["thread"]["id"]
        report["thread"] = thread

        def start(prompt):
            return host.request(
                "turn/start",
                {
                    "threadId": thread,
                    "input": [{"type": "text", "text": prompt}],
                },
            )["turn"]["id"]

        def steer(turn, prompt):
            return host.request(
                "turn/steer",
                {
                    "threadId": thread,
                    "expectedTurnId": turn,
                    "input": [{"type": "text", "text": prompt}],
                },
            )

        def event_for(event, method, turn):
            p = event.get("params", {})
            return (
                event.get("method") == method
                and p.get("threadId") == thread
                and p.get("turnId", p.get("turn", {}).get("id")) == turn
            )

        def sleep_started(turn):
            host.wait(
                lambda e: (
                    event_for(e, "item/started", turn)
                    and e["params"].get("item", {}).get("type") == "commandExecution"
                    and "/bin/sleep" in e["params"]["item"].get("command", "")
                )
            )

        def finished(turn, status="completed"):
            event = host.wait(lambda e: event_for(e, "turn/completed", turn))
            assert event["params"]["turn"]["status"] == status, event

        def snapshot(name):
            state = json.loads(
                (project / ".neurath/local/runs" / thread / ".process-state.json").read_text()
            )
            (output / (name + ".json")).write_text(json.dumps(state, indent=2))
            return state["foreground_turns"][state["session"]["root_actor_id"]]

        restrictions = (
            " This is an authorized read-only Neurath native steering regression. "
            "Do not edit files, spawn children, create workflows, change settings/identity/trust, "
            "or contact integrations. Save only a factual local Neurath checkpoint if the Stop hook requests it."
        )
        first = start(
            "Run /bin/sleep 8 in a standalone native shell call, then report the result."
            + restrictions
        )
        sleep_started(first)
        steer(
            first,
            "Additional input NEURATH_STEER_ONE: after the wait run printf NEURATH_STEER_ONE in a standalone native shell call."
            + restrictions,
        )
        steer(
            first,
            "Additional input NEURATH_STEER_TWO: also run printf NEURATH_STEER_TWO in another standalone native shell call, then finish."
            + restrictions,
        )
        finished(first)
        initial = snapshot("steered")
        assert initial["vendor_turn_id"] == first
        report["steered_turn"] = first

        repeated = (
            "Run /bin/sleep 8 in a standalone native shell call, then run printf NEURATH_REPEAT_OK in another native shell call and finish."
            + restrictions
        )
        interrupted = start(repeated)
        sleep_started(interrupted)
        interrupted_state = snapshot("before-interruption")
        host.request("turn/interrupt", {"threadId": thread, "turnId": interrupted})
        finished(interrupted, "interrupted")
        successor = start(repeated)
        finished(successor)
        after = snapshot("after-interruption")
        assert after["vendor_turn_id"] == successor
        assert after["generation"] > interrupted_state["generation"]
        report.update(interrupted_turn=interrupted, successor_turn=successor)

        from native_evidence import codex_turn

        report["steering_execution"] = codex_turn(
            host.events,
            thread,
            first,
            [
                ("printf NEURATH_STEER_ONE", "NEURATH_STEER_ONE"),
                ("printf NEURATH_STEER_TWO", "NEURATH_STEER_TWO"),
            ],
            checkpoint=True,
        )
        report["successor_execution"] = codex_turn(
            host.events,
            thread,
            successor,
            [
                ("printf NEURATH_REPEAT_OK", "NEURATH_REPEAT_OK"),
            ],
            checkpoint=True,
        )
        host.close()
        host = Host(project, output)
        host.request("thread/resume", {"threadId": thread, "cwd": str(project)})
        resumed = start(
            "Run printf NEURATH_RESUME_OK in a standalone native shell call and finish."
            + restrictions
        )
        finished(resumed)
        report["resumed_execution"] = codex_turn(
            host.events,
            thread,
            resumed,
            [
                ("printf NEURATH_RESUME_OK", "NEURATH_RESUME_OK"),
            ],
            checkpoint=True,
        )
        report["resumed_turn"] = resumed
        snapshot("resumed")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=repr(error))
        raise
    finally:
        (output / "summary.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
        host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe(args.project.resolve(), args.output.resolve())
