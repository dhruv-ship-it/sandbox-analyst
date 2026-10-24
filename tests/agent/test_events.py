from sandbox_analyst.agent.events import AgentEvent, EventEmitter, new_run_id


def test_new_run_id_is_unique():
    assert new_run_id() != new_run_id()


def test_emit_assigns_increasing_seq_numbers():
    received: list[AgentEvent] = []
    emitter = EventEmitter("run-1", on_event=received.append)

    emitter.emit("run_started", 0, {"a": 1})
    emitter.emit("code", 1, {"code": "print(1)"})
    emitter.emit("run_finished", 1, {"status": "answered"})

    assert [e.seq for e in received] == [0, 1, 2]


def test_emit_stamps_run_id_type_and_attempt():
    received: list[AgentEvent] = []
    emitter = EventEmitter("run-xyz", on_event=received.append)

    event = emitter.emit("code", 3, {"code": None})

    assert event.run_id == "run-xyz"
    assert event.type == "code"
    assert event.attempt == 3
    assert event.payload == {"code": None}
    assert received == [event]


def test_emit_works_with_no_subscriber():
    emitter = EventEmitter("run-1", on_event=None)
    event = emitter.emit("profile", 0, {})
    assert event.seq == 0


def test_returned_event_is_also_the_one_forwarded():
    received: list[AgentEvent] = []
    emitter = EventEmitter("run-1", on_event=received.append)
    event = emitter.emit("observation", 2, {"text": "timeout"})
    assert received[-1] is event
