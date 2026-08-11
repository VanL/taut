from __future__ import annotations

import json
from pathlib import Path

import pytest

from taut import addressing, identity
from taut._exceptions import EmptyResultError, NotFoundError, ThreadNameError
from taut.client import Message, TautClient
from taut.state import MemberRow, SqlSidecarTautState

pytestmark = pytest.mark.sqlite_only


def _client(tmp_path: Path, name: str) -> TautClient:
    db_path = tmp_path / ".taut.db"
    if not db_path.exists():
        TautClient.init(db_path=db_path)
    return TautClient(db_path=db_path, as_name=name)


def _agent_capture(*, cwd: str) -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=4242,
        ppid=1,
        start_time="stable-start",
        exe="/usr/local/bin/workerbot",
        argv=("workerbot",),
        uid=501,
        pgid=4242,
        session_id=99,
        tty="ttys009",
        cwd=cwd,
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity("host:test", "test-host"),
        uid=501,
        login="tester",
        anchor=process,
        kind="agent",
        rule="test capture",
    )


def _human_capture(*, login: str) -> identity.IdentityCapture:
    return identity.IdentityCapture(
        chain=(),
        host=identity.HostIdentity("host:human-test", "human-test-host"),
        uid=502,
        login=login,
        anchor=None,
        kind="human",
        rule="test capture",
    )


def test_dm_route_and_stable_handle_share_history_and_read_cursor(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id

    sent = alice.say("@bob", "one")
    stable = addressing.dm_queue_name(alice_id, bob_id)
    assert sent.thread == stable

    membership_before = bob._state.get_membership(thread=stable, member_id=bob_id)
    actor_before = bob._state.get_member(bob_id)
    assert membership_before is not None
    assert actor_before is not None

    assert [item.text for item in bob.log("@alice")] == ["one"]
    assert [item.text for item in bob.log(stable)] == ["one"]
    assert (
        bob._state.get_membership(thread=stable, member_id=bob_id) == membership_before
    )
    assert bob._state.get_member(bob_id) == actor_before

    assert [item.text for item in bob.read("@alice")] == ["one"]
    membership_after = bob._state.get_membership(thread=stable, member_id=bob_id)
    assert membership_after is not None
    assert membership_after["last_seen_ts"] == sent.ts
    with pytest.raises(EmptyResultError, match="nothing unread"):
        bob.read(stable)


def test_stable_dm_handle_survives_rename_while_route_tracks_current_owner(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    stable = alice.say("@bob", "before rename").thread

    bob.set_name("robert")

    assert [item.text for item in alice.log(stable)] == ["before rename"]
    assert [item.text for item in alice.log("@robert")] == ["before rename"]
    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        alice.log("@bob")


def test_dm_route_accepts_taut_member_alias(tmp_path: Path) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    bob_id = bob.whoami().member_id
    sent = alice.say("@bob", "through alias")
    alice._state.add_member_alias(
        member_id=bob_id,
        alias="builder",
        created_ts=alice._meta_queue.generate_timestamp(),
    )

    assert [item.text for item in alice.log("@builder")] == ["through alias"]
    assert alice.log("@builder")[0].thread == sent.thread


def test_route_reuse_targets_new_owner_without_retargeting_stable_handle(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    original_bob = _client(tmp_path, "bob")
    original_bob.join("lobby")
    old_message = alice.say("@bob", "old owner")
    original_bob.set_name("robert")

    new_bob = _client(tmp_path, "bob")
    new_bob.join("lobby")
    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        alice.log("@bob")
    new_message = new_bob.say("@alice", "new owner")

    assert new_message.thread != old_message.thread
    assert [item.text for item in alice.log("@bob")] == ["new owner"]
    assert [item.text for item in alice.log(old_message.thread)] == ["old owner"]


def test_dm_selection_misses_are_uniform_and_do_not_open_queues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")
    dave = _client(tmp_path, "dave")
    dave.join("lobby")
    other_pair = carol.say("@dave", "private").thread
    absent = "dm.d_" + "a" * 26

    def fail_queue(_name: str, *, persistent: bool | None = None) -> None:
        del persistent
        raise AssertionError("inaccessible DM selection opened a queue")

    monkeypatch.setattr(alice, "queue", fail_queue)

    messages = []
    for selector in ("@ghost", "@alice", "@bob", absent, other_pair):
        with pytest.raises(NotFoundError) as caught:
            alice.log(selector)
        messages.append(str(caught.value))

    assert messages == ["direct message not found or inaccessible"] * 5
    for selector in ("@bob", absent, other_pair):
        with pytest.raises(NotFoundError) as caught:
            alice.read(selector)
        assert str(caught.value) == "direct message not found or inaccessible"


def test_malformed_route_owner_id_uses_uniform_content_free_miss(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    created_ts = alice._meta_queue.generate_timestamp()
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_members (
                member_id, display_name, name_key, kind, uid, host_id,
                host_label, anchor_pid, anchor_start_time, fingerprint,
                token, meta, created_ts, last_active_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "malformed-id",
                "corrupt",
                "corrupt",
                "agent",
                501,
                "host:test",
                "test-host",
                None,
                None,
                None,
                None,
                "{}",
                created_ts,
                created_ts,
            ),
        )

    with pytest.raises(NotFoundError) as caught:
        alice.log("@corrupt")

    assert str(caught.value) == "direct message not found or inaccessible"


def test_malformed_stable_dm_selector_is_a_validation_error(tmp_path: Path) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")

    with pytest.raises(ThreadNameError):
        alice.log("dm.d_short")
    with pytest.raises(ThreadNameError):
        alice.read("dm.d_" + "A" * 26)


def test_list_direct_messages_includes_caught_up_and_empty_conversations(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")

    older = bob.say("@alice", "older")
    alice.read(older.thread)
    newer = carol.say("@alice", "newer")

    listed = alice.list_direct_messages()
    assert [item.name for item in listed] == [newer.thread, older.thread]
    assert [item.unread for item in listed] == [True, False]
    assert [item.display_name for item in listed] == [
        "DM with carol",
        "DM with bob",
    ]

    carol.delete_message(str(newer.ts))
    without_row = alice.list_direct_messages()
    assert [item.name for item in without_row] == [older.thread, newer.thread]
    assert without_row[-1].last_ts is None
    assert without_row[-1].display_name == "DM with carol"


def test_list_direct_messages_returns_empty_result_without_creating_state(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    before_threads = alice._state.list_threads(include_internal=True)
    before_memberships = alice._state.list_memberships(alice.whoami().member_id)

    with pytest.raises(EmptyResultError, match="no direct messages"):
        alice.list_direct_messages()

    assert alice._state.list_threads(include_internal=True) == before_threads
    assert alice._state.list_memberships(alice.whoami().member_id) == before_memberships


def test_dm_selection_requires_both_persisted_memberships(tmp_path: Path) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    stable = alice.say("@bob", "existing").thread

    assert alice._state.remove_membership(thread=stable, member_id=bob_id)

    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        alice.log(stable)
    with pytest.raises(EmptyResultError, match="no direct messages"):
        alice.list_direct_messages()
    assert alice._state.get_membership(thread=stable, member_id=alice_id) is not None


def _corrupt_direct_message_state(
    alice: TautClient,
    *,
    stable: str,
    corruption: str,
    alice_id: str,
    bob_id: str,
    carol_id: str,
) -> None:
    if corruption == "missing-actor-membership":
        assert alice._state.remove_membership(thread=stable, member_id=alice_id)
        return
    if corruption == "missing-other-membership":
        assert alice._state.remove_membership(thread=stable, member_id=bob_id)
        return
    if corruption == "missing-participant-row":
        with alice._meta_queue.sidecar(transaction=True) as session:
            session.run(
                "DELETE FROM taut_membership WHERE member_id = ?",
                (bob_id,),
            )
            session.run(
                "DELETE FROM taut_identity_claims WHERE member_id = ?",
                (bob_id,),
            )
            session.run(
                "DELETE FROM taut_member_aliases WHERE member_id = ?",
                (bob_id,),
            )
            session.run("DELETE FROM taut_members WHERE member_id = ?", (bob_id,))
        return

    metadata: dict[str, dict[str, object]] = {
        "missing-members-meta": {},
        "members-not-list": {"members": "not-a-list"},
        "member-not-string": {"members": [alice_id, 7]},
        "wrong-cardinality-one": {"members": [alice_id]},
        "wrong-cardinality-three": {"members": [alice_id, bob_id, carol_id]},
        "duplicate-member-ids": {"members": [alice_id, alice_id]},
        "invalid-member-id": {"members": [alice_id, "invalid-id"]},
        "pair-name-mismatch": {"members": [alice_id, carol_id]},
        "actor-absent-metadata": {"members": [bob_id, carol_id]},
        "wrong-kind": {"members": [alice_id, bob_id]},
    }
    if corruption == "pair-name-mismatch":
        alice._state.add_membership(
            thread=stable,
            member_id=carol_id,
            joined_ts=alice._meta_queue.generate_timestamp(),
            last_seen_ts=0,
        )
    kind = "channel" if corruption == "wrong-kind" else "dm"
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_threads SET kind = ?, meta = ? WHERE name = ?",
            (kind, json.dumps(metadata[corruption]), stable),
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-members-meta",
        "members-not-list",
        "member-not-string",
        "wrong-cardinality-one",
        "wrong-cardinality-three",
        "duplicate-member-ids",
        "invalid-member-id",
        "pair-name-mismatch",
        "wrong-kind",
        "actor-absent-metadata",
        "missing-actor-membership",
        "missing-other-membership",
        "missing-participant-row",
    ],
)
def test_corrupt_dm_state_fails_closed_before_queue_or_watch_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    from taut.client import _watching

    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")
    alice_id = alice.whoami().member_id
    bob_id = bob.whoami().member_id
    carol_id = carol.whoami().member_id
    stable = alice.say("@bob", "private body").thread

    _corrupt_direct_message_state(
        alice,
        stable=stable,
        corruption=corruption,
        alice_id=alice_id,
        bob_id=bob_id,
        carol_id=carol_id,
    )

    def fail_queue(_name: str, *, persistent: bool | None = None) -> None:
        del persistent
        raise AssertionError("corrupt DM selection opened a queue")

    def fail_runtime(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("corrupt DM selection constructed a watch runtime")

    monkeypatch.setattr(alice, "queue", fail_queue)
    monkeypatch.setattr(_watching, "_watch_runtime_for_client", fail_runtime)

    for operation in (alice.log, alice.read):
        with pytest.raises(NotFoundError) as caught:
            operation(stable)
        assert str(caught.value) == "direct message not found or inaccessible"
    with pytest.raises(NotFoundError) as caught:
        alice.say(stable, "must fail before queue construction")
    assert str(caught.value) == "direct message not found or inaccessible"
    with pytest.raises(EmptyResultError, match="no direct messages"):
        alice.list_direct_messages()
    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        alice.watch(lambda _item: None, threads=[stable])


@pytest.mark.parametrize("operation", ["read", "directory", "watch"])
def test_dm_navigation_touches_activity_without_healing_identity_claims(
    tmp_path: Path,
    operation: str,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    original_capture = _agent_capture(cwd="/workspace/one")
    alice = TautClient(db_path=db_path, identity_capture=original_capture)
    alice.join("lobby")
    alice_member = alice.whoami()
    bob = TautClient(db_path=db_path, as_name="bob")
    bob.join("lobby")
    sent = bob.say(f"@{alice_member.name}", "pending")

    changed_capture = _agent_capture(cwd="/workspace/two")
    changed_claim = identity.claim_for_capture(changed_capture)
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_identity_claims WHERE member_id = ?",
            (alice_member.member_id,),
        )
    before = alice._state.get_member(alice_member.member_id)
    assert before is not None
    assert alice._state.get_identity_claim(changed_claim.claim_hash) is None

    navigating = TautClient(db_path=db_path, identity_capture=changed_capture)
    watcher = None
    if operation == "read":
        assert [item.text for item in navigating.read(sent.thread)] == ["pending"]
    elif operation == "directory":
        assert [item.name for item in navigating.list_direct_messages()] == [
            sent.thread
        ]
    else:
        watcher = navigating.watch(
            lambda _item: None,
            threads=[sent.thread],
            persistent=False,
        )
    if watcher is not None:
        watcher.stop()

    after = navigating._state.get_member(alice_member.member_id)
    assert after is not None
    assert after["last_active_ts"] > before["last_active_ts"]
    assert navigating._state.get_identity_claim(changed_claim.claim_hash) is None


def test_stable_dm_send_touches_activity_without_healing_identity_claims(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    original_capture = _agent_capture(cwd="/workspace/one")
    alice = TautClient(db_path=db_path, identity_capture=original_capture)
    alice.join("lobby")
    alice_member = alice.whoami()
    bob = TautClient(db_path=db_path, as_name="bob")
    bob.join("lobby")
    stable = bob.say(f"@{alice_member.name}", "pending").thread

    changed_capture = _agent_capture(cwd="/workspace/two")
    changed_claim = identity.claim_for_capture(changed_capture)
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_identity_claims WHERE member_id = ?",
            (alice_member.member_id,),
        )
    before = alice._state.get_member(alice_member.member_id)
    assert before is not None
    assert alice._state.get_identity_claim(changed_claim.claim_hash) is None

    sending = TautClient(db_path=db_path, identity_capture=changed_capture)
    sent = sending.say(stable, "stable reply")

    assert sent.thread == stable
    after = sending._state.get_member(alice_member.member_id)
    assert after is not None
    assert after["last_active_ts"] > before["last_active_ts"]
    assert sending._state.get_identity_claim(changed_claim.claim_hash) is None


def test_nonhealing_dm_resolution_honors_claim_owner_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    original_capture = _agent_capture(cwd="/workspace/one")
    alice = TautClient(db_path=db_path, identity_capture=original_capture)
    alice.join("lobby")
    alice_member = alice.whoami()
    bob = TautClient(db_path=db_path, as_name="bob")
    bob.join("lobby")
    stable = bob.say(f"@{alice_member.name}", "private for alice").thread
    carol = TautClient(db_path=db_path, as_name="carol")
    carol.join("lobby")
    carol_id = carol.whoami().member_id

    changed_capture = _agent_capture(cwd="/workspace/two")
    changed_claim = identity.claim_for_capture(changed_capture)
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_identity_claims WHERE member_id = ?",
            (alice_member.member_id,),
        )
    alice._state.add_identity_claim(
        claim_hash=changed_claim.claim_hash,
        member_id=carol_id,
        claim_kind=changed_claim.claim_kind,
        host_id=changed_claim.host_id,
        host_label=changed_claim.host_label,
        evidence=changed_claim.evidence,
        seen_ts=alice._meta_queue.generate_timestamp(),
    )

    real_lookup = SqlSidecarTautState.get_member_by_claim_hash
    lookups = 0

    def claim_arrives_after_initial_lookup(
        state: SqlSidecarTautState,
        claim_hash: str,
    ) -> MemberRow | None:
        nonlocal lookups
        if claim_hash == changed_claim.claim_hash:
            lookups += 1
            if lookups == 1:
                return None
        return real_lookup(state, claim_hash)

    monkeypatch.setattr(
        SqlSidecarTautState,
        "get_member_by_claim_hash",
        claim_arrives_after_initial_lookup,
    )
    navigating = TautClient(db_path=db_path, identity_capture=changed_capture)

    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        navigating.read(stable)
    assert lookups >= 2


@pytest.mark.parametrize("operation", ["log", "read"])
def test_human_fallback_dm_resolution_honors_claim_owner_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    db_path = tmp_path / ".taut.db"
    TautClient.init(db_path=db_path)
    original_capture = _human_capture(login="alice")
    alice = TautClient(db_path=db_path, identity_capture=original_capture)
    alice.join("lobby")
    alice_member = alice.whoami()
    bob = TautClient(db_path=db_path, as_name="bob")
    bob.join("lobby")
    stable = bob.say(f"@{alice_member.name}", "private for alice").thread
    carol = TautClient(
        db_path=db_path,
        as_name="carol",
        identity_capture=_agent_capture(cwd="/workspace/carol"),
    )
    carol.join("lobby")
    carol_id = carol.whoami().member_id

    changed_capture = _human_capture(login="alice-new-session")
    changed_claim = identity.claim_for_capture(changed_capture)
    with alice._meta_queue.sidecar(transaction=True) as session:
        session.run(
            "DELETE FROM taut_identity_claims WHERE member_id = ?",
            (alice_member.member_id,),
        )
    alice._state.add_identity_claim(
        claim_hash=changed_claim.claim_hash,
        member_id=carol_id,
        claim_kind=changed_claim.claim_kind,
        host_id=changed_claim.host_id,
        host_label=changed_claim.host_label,
        evidence=changed_claim.evidence,
        seen_ts=alice._meta_queue.generate_timestamp(),
    )
    real_lookup = SqlSidecarTautState.get_member_by_claim_hash
    lookups = 0

    def claim_arrives_after_initial_lookup(
        state: SqlSidecarTautState,
        claim_hash: str,
    ) -> MemberRow | None:
        nonlocal lookups
        if claim_hash == changed_claim.claim_hash:
            lookups += 1
            if lookups == 1:
                return None
        return real_lookup(state, claim_hash)

    monkeypatch.setattr(
        SqlSidecarTautState,
        "get_member_by_claim_hash",
        claim_arrives_after_initial_lookup,
    )
    navigating = TautClient(db_path=db_path, identity_capture=changed_capture)

    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        if operation == "log":
            navigating.log(stable)
        else:
            navigating.read(stable)
    assert lookups >= 2


def test_watch_resolves_dm_routes_once_and_deduplicates_stable_aliases(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    stable = alice.say("@bob", "existing").thread

    watcher = alice.watch(
        lambda _item: None,
        threads=["@bob", stable, "@bob"],
        persistent=False,
    )
    try:
        assert watcher.list_queues() == [stable]
        assert watcher._thread_filter == {stable}

        bob.set_name("robert")
        assert watcher._thread_filter == {stable}
    finally:
        watcher.stop()


@pytest.mark.parametrize(
    "selector",
    ["@ghost", "dm.d_" + "a" * 26, "dm.d_short"],
)
def test_watch_rejects_dm_misses_before_runtime_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    from taut.client import _watching

    alice = _client(tmp_path, "alice")
    alice.join("lobby")

    def fail_runtime(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("watch runtime constructed before DM preflight")

    monkeypatch.setattr(_watching, "_watch_runtime_for_client", fail_runtime)

    expected = ThreadNameError if selector == "dm.d_short" else NotFoundError
    with pytest.raises(expected):
        alice.watch(lambda _item: None, threads=[selector])


def test_watch_rejects_another_pairs_real_handle_before_runtime_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.client import _watching

    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")
    dave = _client(tmp_path, "dave")
    dave.join("lobby")
    other_pair = carol.say("@dave", "private").thread

    def fail_runtime(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("watch runtime constructed before DM preflight")

    monkeypatch.setattr(_watching, "_watch_runtime_for_client", fail_runtime)

    with pytest.raises(NotFoundError, match="direct message not found or inaccessible"):
        alice.watch(lambda _item: None, threads=[other_pair])


def test_empty_dm_is_valid_for_log_and_watch(tmp_path: Path) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    sent = alice.say("@bob", "temporary")
    alice.delete_message(str(sent.ts))

    with pytest.raises(EmptyResultError, match="empty"):
        alice.log(sent.thread)
    watcher = alice.watch(
        lambda _item: None,
        threads=[sent.thread],
        persistent=False,
    )
    try:
        assert watcher.list_queues() == [sent.thread]
    finally:
        watcher.stop()


def test_empty_dm_directory_ties_use_canonical_thread_name(tmp_path: Path) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")
    first = alice.say("@bob", "first")
    second = alice.say("@carol", "second")
    alice.delete_message(str(first.ts))
    alice.delete_message(str(second.ts))

    listed = alice.list_direct_messages()
    assert [item.name for item in listed] == sorted([first.thread, second.thread])
    assert all(item.last_ts is None for item in listed)


def test_two_dm_watch_filters_do_not_derive_schedule_from_input_order(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    carol = _client(tmp_path, "carol")
    carol.join("lobby")
    first = alice.say("@bob", "first").thread
    second = alice.say("@carol", "second").thread

    forward = alice.watch(
        lambda _item: None,
        threads=[first, second],
        persistent=False,
    )
    reverse = alice.watch(
        lambda _item: None,
        threads=[second, first],
        persistent=False,
    )
    try:
        assert forward.list_queues() == reverse.list_queues()
        assert set(forward.list_queues()) == {first, second}
    finally:
        forward.stop()
        reverse.stop()


def test_bare_watch_labels_dm_created_after_watcher_construction(
    tmp_path: Path,
) -> None:
    alice = _client(tmp_path, "alice")
    alice.join("lobby")
    bob = _client(tmp_path, "bob")
    bob.join("lobby")
    labels_seen: list[str | None] = []

    def capture_label(item: object) -> None:
        if isinstance(item, Message) and item.thread.startswith("dm."):
            labels_seen.append(alice.last_thread_display_names.get(item.thread))

    watcher = alice.watch(capture_label, persistent=False)
    try:
        alice.log("lobby")
        bob.say("@alice", "created while watching")
        watcher._next_membership_refresh_at = 0
        for _ in range(4):
            watcher.process_once()
            if labels_seen:
                break
        assert labels_seen == ["DM with bob"]
    finally:
        watcher.stop()
