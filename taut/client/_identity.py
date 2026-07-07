"""Identity and member-resolution behavior for TautClient."""

from __future__ import annotations

from typing import Any, cast

from simplebroker.ext import IntegrityError

import taut.identity as identity
from taut import addressing
from taut._constants import route_key, validate_member_name
from taut._exceptions import IdentityError, NotFoundError, TokenError
from taut.state import MemberRow

from ._base import _ClientBase, _ResolvedMember
from ._models import Member


class IdentityMixin(_ClientBase):
    def whoami(self, *, explain: bool = False) -> Member:
        resolved = self._resolve_member(create=False)
        if resolved.row is None:
            raise IdentityError("unrecognized caller")
        return self._member_from_row(
            resolved.row,
            capture=resolved.capture,
            explain=identity.explain_capture(resolved.capture, resolved.rule)
            if explain
            else None,
        )

    def who(self, thread: str | None = None) -> list[Member]:
        self._resolve_member(create=False, allow_guest=True)
        if thread is not None:
            thread = addressing.validate_chat_thread_name(thread, allow_subthread=True)
            self._ensure_no_incomplete_channel_rename()
            if self._state.get_thread(thread) is None:
                raise NotFoundError(f"thread not found: {thread}")
            rows = self._state.list_thread_members(thread)
        else:
            rows = self._state.list_members()
        return [self._member_from_row(row) for row in rows]

    def rejoin(
        self,
        name_or_alias: str | None = None,
        *,
        token: str | None = None,
    ) -> Member:
        if token is not None and self.token is not None:
            raise IdentityError("provide exactly one rejoin selector")
        if name_or_alias is not None and (token is not None or self.token is not None):
            raise IdentityError("provide exactly one of name or token")
        if name_or_alias is None and token is None:
            if self.as_name and self.token:
                raise IdentityError("provide exactly one rejoin selector")
            if self.as_name:
                name_or_alias = self.as_name
            elif self.token:
                token = self.token
            else:
                raise IdentityError("provide exactly one of name or token")
        capture = self._capture()
        claim = identity.claim_for_capture(capture)
        selector = (
            self._state.get_member_by_token(token)
            if token is not None
            else self._state.get_member_by_route_key(
                route_key(cast(str, name_or_alias))
            )
        )
        if selector is None:
            raise NotFoundError("member not found")
        claimant = self._state.get_member_by_claim_hash(claim.claim_hash)
        if claimant is not None and claimant["member_id"] != selector["member_id"]:
            raise IdentityError(
                f"current identity claim already belongs to {claimant['display_name']}"
            )
        active_ts = self._meta_queue.generate_timestamp()
        updated = selector
        if capture.anchor is not None and capture.anchor.start_time is not None:
            updated = self._state.update_member_anchor(
                member_id=selector["member_id"],
                host_id=capture.host.host_id,
                host_label=capture.host.host_label,
                anchor_pid=capture.anchor.pid,
                anchor_start_time=capture.anchor.start_time,
                fingerprint=identity.fingerprint_for_process(capture.anchor) or "{}",
                active_ts=active_ts,
            )
        else:
            self._state.update_member_activity(selector["member_id"], active_ts)
            updated = self._state.get_member(selector["member_id"]) or updated
        self._record_claim(updated, claim, active_ts)
        return self._member_from_row(updated)

    def set_name(self, name: str) -> Member:
        validate_member_name(name)
        resolved = self._resolve_member(create=False)
        member = self._require_member(resolved)
        try:
            updated = self._state.update_member_name(member["member_id"], name)
        except IntegrityError as exc:
            raise IdentityError(str(exc)) from exc
        self.as_name = name
        return self._member_from_row(updated)

    def _resolve_member(
        self,
        *,
        create: bool,
        force_new: bool = False,
        persona: str | None = None,
        allow_guest: bool = False,
    ) -> _ResolvedMember:
        self.last_created_member = None
        self.last_candidates = []
        capture = self._capture()
        claim = identity.claim_for_capture(capture)
        active_ts: int | None = None

        def next_active_ts() -> int:
            nonlocal active_ts
            if active_ts is None:
                active_ts = self._meta_queue.generate_timestamp()
            return active_ts

        explicit = self.as_name
        if explicit:
            validate_member_name(explicit)
            row = self._state.get_member_by_route_key(route_key(explicit))
            if row is None:
                if not create and not allow_guest:
                    raise NotFoundError(f"member not found: {explicit}")
                if not create:
                    return _ResolvedMember(None, capture, claim, rule="guest")
                row = self._create_member(
                    capture,
                    claim=claim,
                    name=explicit,
                    persona=persona,
                    active_ts=next_active_ts(),
                    force_new=force_new,
                )
                return self._created_resolution(row, capture, claim, "explicit --as")
            self._state.update_member_activity(row["member_id"], next_active_ts())
            if persona is not None:
                row = (
                    self._state.update_member_persona(row["member_id"], persona) or row
                )
            return _ResolvedMember(row, capture, claim, rule="explicit --as")

        if self.token:
            row = self._state.get_member_by_token(self.token)
            if row is None:
                raise TokenError("TAUT_TOKEN does not match a taut member")
            active = next_active_ts()
            token_claim = identity.claim_for_token(self.token)
            self._record_claim(row, token_claim, active)
            self._state.update_member_activity(row["member_id"], active)
            return _ResolvedMember(row, capture, claim, rule="continuity token")

        if not force_new:
            row = self._state.get_member_by_claim_hash(claim.claim_hash)
            if row is not None:
                self._state.update_member_activity(row["member_id"], next_active_ts())
                if persona is not None:
                    row = (
                        self._state.update_member_persona(row["member_id"], persona)
                        or row
                    )
                return _ResolvedMember(row, capture, claim, rule="identity claim")

        if not force_new and capture.kind == "agent":
            # [IAN-3.3] step 4: a live anchor that changed mutable claim
            # inputs (cwd, tty, pgid) still matches by the stable
            # (host_id, anchor_pid, anchor_start_time) triple.
            row = identity.match_anchor(capture, self._state.list_members())
            if row is not None:
                active = next_active_ts()
                try:
                    # Heal: record the current claim so subsequent commands
                    # resolve at step 3.
                    self._record_claim(row, claim, active)
                except IntegrityError:
                    # Healing race: another process associated this claim
                    # hash first. Step-3 semantics outrank anchor match, so
                    # if the hash now belongs to a different member, that
                    # owner wins with the full step-3 side effects.
                    owner = self._state.get_member_by_claim_hash(claim.claim_hash)
                    if owner is not None and owner["member_id"] != row["member_id"]:
                        self._state.update_member_activity(owner["member_id"], active)
                        if persona is not None:
                            owner = (
                                self._state.update_member_persona(
                                    owner["member_id"], persona
                                )
                                or owner
                            )
                        return _ResolvedMember(
                            owner, capture, claim, rule="identity claim"
                        )
                    # Same member or no owner: proceed with the anchor match
                    # without the healing claim.
                self._state.update_member_activity(row["member_id"], active)
                if persona is not None:
                    row = (
                        self._state.update_member_persona(row["member_id"], persona)
                        or row
                    )
                return _ResolvedMember(row, capture, claim, rule="anchor match")

        if capture.kind == "human" and not force_new:
            row = self._state.get_member_by_uid(
                host_id=capture.host.host_id,
                uid=capture.uid,
            )
            if row is not None:
                active = next_active_ts()
                self._state.update_member_activity(row["member_id"], active)
                self._record_claim(row, claim, active)
                return _ResolvedMember(row, capture, claim, rule="human uid fallback")

        if not create:
            return _ResolvedMember(None, capture, claim, rule="guest")

        members = self._state.list_members()
        candidates = identity.rank_candidates(capture, members)
        row = self._create_member(
            capture,
            claim=claim,
            name=None,
            persona=persona,
            active_ts=next_active_ts(),
            force_new=force_new,
        )
        resolved = self._created_resolution(row, capture, claim, "new identity")
        resolved.candidates = candidates
        self.last_candidates = [
            (candidate["display_name"], reasons) for candidate, reasons in candidates
        ]
        return resolved

    def _created_resolution(
        self,
        row: MemberRow,
        capture: identity.IdentityCapture,
        claim: identity.IdentityClaim,
        rule: str,
    ) -> _ResolvedMember:
        member = self._member_from_row(row, capture=capture, token=row["token"])
        self.last_created_member = member
        return _ResolvedMember(
            row=row,
            capture=capture,
            claim=claim,
            created=True,
            created_token=row["token"],
            rule=rule,
        )

    def _create_member(
        self,
        capture: identity.IdentityCapture,
        *,
        claim: identity.IdentityClaim,
        name: str | None,
        persona: str | None,
        active_ts: int,
        force_new: bool,
    ) -> MemberRow:
        auto_named = name is None
        anchor = capture.anchor if capture.kind == "agent" else None
        meta = {"persona": persona} if persona is not None else {}
        # First contact may race another first contact on the same name seed
        # ([IAN-9] deterministic fallback allows retry). Every retry re-mints
        # all three unique values — name, member_id, and token — inside the
        # loop body so a stale collision candidate can never be reused.
        # Explicit names (from --as) keep fail-loud behavior: one attempt.
        attempts = 5 if auto_named else 1
        for attempt in range(attempts):
            if name is not None:
                candidate = name
            else:
                seed = (
                    capture.anchor.basename
                    if capture.anchor is not None
                    else capture.login
                )
                fallback = "agent" if capture.kind == "agent" else "human"
                candidate = identity.choose_name(
                    seed=seed,
                    taken=self._state.member_names_in_use(),
                    fallback=fallback,
                )
            validate_member_name(candidate)
            try:
                member = self._state.insert_member(
                    member_id=identity.random_member_id(),
                    display_name=candidate,
                    kind=capture.kind,
                    uid=capture.uid,
                    host_id=capture.host.host_id,
                    host_label=capture.host.host_label,
                    anchor_pid=anchor.pid if anchor is not None else None,
                    anchor_start_time=(
                        anchor.start_time if anchor is not None else None
                    ),
                    fingerprint=identity.fingerprint_for_process(anchor),
                    token=identity.mint_token(),
                    meta=meta,
                    created_ts=active_ts,
                )
            except IntegrityError as exc:
                resolved = (
                    None
                    if force_new
                    else self._state.get_member_by_claim_hash(claim.claim_hash)
                )
                if resolved is not None:
                    return resolved
                if not auto_named:
                    raise IdentityError(str(exc)) from exc
                if attempt + 1 >= attempts:
                    raise IdentityError(
                        f"could not create a member after {attempts} attempts; "
                        f"last candidate: {candidate}"
                    ) from exc
                continue
            self._ensure_notification_thread(member, active_ts)
            if self._state.get_member_by_claim_hash(claim.claim_hash) is None:
                try:
                    self._record_claim(member, claim, active_ts)
                except IntegrityError:
                    if force_new:
                        return member
                    resolved = self._state.get_member_by_claim_hash(claim.claim_hash)
                    if resolved is not None:
                        return resolved
                    raise
            return member
        raise AssertionError("unreachable: member-creation retry loop fell through")

    def _record_claim(
        self,
        member: MemberRow,
        claim: identity.IdentityClaim,
        seen_ts: int,
    ) -> None:
        self._state.add_identity_claim(
            claim_hash=claim.claim_hash,
            member_id=member["member_id"],
            claim_kind=claim.claim_kind,
            host_id=claim.host_id,
            host_label=claim.host_label,
            evidence=claim.evidence,
            seen_ts=seen_ts,
        )

    def _ensure_notification_thread(
        self,
        member: MemberRow,
        created_ts: int,
    ) -> None:
        self._state.upsert_thread(
            name=addressing.notification_queue_name(member["member_id"]),
            kind="notification",
            parent=None,
            origin_ts=None,
            created_by=member["member_id"],
            meta={"member_id": member["member_id"]},
            created_ts=created_ts,
        )

    def _member_from_row(
        self,
        row: MemberRow,
        *,
        capture: identity.IdentityCapture | None = None,
        token: str | None = None,
        explain: dict[str, Any] | None = None,
    ) -> Member:
        local_host_id = (
            capture.host.host_id
            if capture
            else identity.capture_host_identity().host_id
        )
        meta = row["meta"]
        persona = meta.get("persona") if isinstance(meta.get("persona"), str) else None
        return Member(
            member_id=row["member_id"],
            name=row["display_name"],
            aliases=tuple(self._state.list_member_aliases(row["member_id"])),
            kind=row["kind"],
            presence=identity.member_presence(row, local_host_id),
            last_active_ts=row["last_active_ts"],
            persona=persona,
            token=token,
            explain=explain,
        )
