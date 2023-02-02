import time
from typing import Any, AsyncGenerator, Dict, List, Mapping, Tuple

from controller import Controller
from controller.protocols import (CredAttrSpec, CredentialPreview,
                                  V10CredentialConnFreeOfferRequest,
                                  V10CredentialExchange, didexchange,
                                  indy_anoncred_credential_artifacts,
                                  indy_anoncred_onboard, indy_anoncreds_revoke,
                                  indy_issue_credential_v1,
                                  indy_issue_credential_v2,
                                  indy_present_proof_v1, indy_present_proof_v2)


class MigrationTestCases:
    def __init__(self):
        self._cases = (
            self.connections(),
            self.credentials_without_revocation(),
            self.credentials_without_revocation_v2(),
            self.credentials_with_revocation(),
            self.revoked_credential(
                {"revoked_test": "Bob", "revoked_last": "Builder"},
                [
                    {
                        "name": "revoked_test",
                    }
                ],
                supports_revocation=True,
            ),
            self.large_credential_without_revocation(),
            self.composite_credential_proof(
                {"nick_name": "Bob", "last_name": "Builder"},
                {"first_name": "William", "last_name": "Builder"},
                [
                    {
                        "name": "nick_name",
                    },
                    {
                        "name": "last_name",
                    },
                ],
                supports_revocation=False,
            ),
            self.migration_during_credential(
                {"abc": "Bob", "defg": "Builder"},
                [
                    {
                        "name": "abc",
                    },
                    {
                        "name": "defg",
                    },
                ],
            ),
        )

    async def pre(self, alice: Controller, bob: Controller):
        for case in self._cases:
            await anext(case)  # advance to first yield
            await case.asend((alice, bob))

    async def post(self, alice: Controller, bob: Controller):
        for case in self._cases:
            try:
                await case.asend((alice, bob))
            except StopAsyncIteration:
                pass

    async def connections(self) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        alice, bob = yield
        alice_conn, bob_conn = await didexchange(alice, bob)

        alice, bob = yield

        await alice.post(f"/connections/{alice_conn.connection_id}/send-ping")

    async def onboard_and_issue_v1(
        self, alice, bob, cred_attrs, supports_revocation, connections=None
    ):
        alice_conn, bob_conn = connections or await didexchange(alice, bob)
        # Issuance prep
        await indy_anoncred_onboard(alice)
        schema, cred_def = await indy_anoncred_credential_artifacts(
            alice,
            list(cred_attrs.keys()),
            support_revocation=supports_revocation,
        )
        # Issue the thing
        await indy_issue_credential_v1(
            alice,
            bob,
            alice_conn.connection_id,
            bob_conn.connection_id,
            cred_def.credential_definition_id,
            cred_attrs,
        )
        return alice_conn, bob_conn

    async def onboard_and_issue_v2(
        self, alice, bob, cred_attrs, supports_revocation, connections=None
    ):
        alice_conn, bob_conn = connections or await didexchange(alice, bob)
        # Issuance prep
        await indy_anoncred_onboard(alice)
        schema, cred_def = await indy_anoncred_credential_artifacts(
            alice,
            list(cred_attrs.keys()),
            support_revocation=supports_revocation,
        )
        # Issue the thing
        await indy_issue_credential_v2(
            alice,
            bob,
            alice_conn.connection_id,
            bob_conn.connection_id,
            cred_def.credential_definition_id,
            cred_attrs,
        )
        return alice_conn, bob_conn

    async def credentials_v1(
        self,
        cred_attrs: Dict[str, str],
        requested_attributes: List[Mapping[str, Any]],
        supports_revocation: bool = False,
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        alice, bob = yield

        alice_conn, bob_conn = await self.onboard_and_issue_v1(
            alice, bob, cred_attrs, supports_revocation
        )

        alice, bob = yield

        _, alice_pres_ex_askar = await indy_present_proof_v1(
            bob,
            alice,
            bob_conn.connection_id,
            alice_conn.connection_id,
            requested_attributes=requested_attributes,
        )
        assert alice_pres_ex_askar.state == "verified"
        assert alice_pres_ex_askar.verified == "true"

    async def credentials_v2(
        self,
        cred_attrs: Dict[str, str],
        requested_attributes: List[Mapping[str, Any]],
        supports_revocation: bool = False,
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        alice, bob = yield

        alice_conn, bob_conn = await self.onboard_and_issue_v2(
            alice, bob, cred_attrs, supports_revocation
        )

        alice, bob = yield

        _, alice_pres_ex_askar = await indy_present_proof_v2(
            bob,
            alice,
            bob_conn.connection_id,
            alice_conn.connection_id,
            requested_attributes=requested_attributes,
        )
        assert alice_pres_ex_askar.state == "done"
        assert alice_pres_ex_askar.verified == "true"

    def credentials_with_revocation(
        self,
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        now = int(time.time())
        return self.credentials_v1(
            {"first_name0": "Bob", "last_name": "Builder"},
            [
                {
                    "name": "first_name0",
                }
            ],
            supports_revocation=True,
        )

    def credentials_without_revocation(self):
        return self.credentials_v1(
            {"first_name1": "Alice", "last_name": "Cooper"},
            [{"name": "first_name1"}],
            supports_revocation=False,
        )

    def credentials_without_revocation_v2(self):
        return self.credentials_v2(
            {"first_name2": "Alice", "last_name": "Cooper"},
            [{"name": "first_name2"}],
            supports_revocation=False,
        )

    def large_credential_without_revocation(self):
        return self.credentials_v1(
            {
                "a": "A",
                "b": "B",
                "c": "C",
                "d": "D",
                "e": "E",
                "f": "F",
                "g": "G",
                "h": "H",
                "i": "I",
                "j": "J",
                "k": "K",
                "l": "L",
                "m": "M",
                "n": "N",
                "o": "O",
                "p": "P",
                "q": "Q",
                "r": "R",
                "s": "S",
                "t": "T",
                "u": "U",
                "v": "V",
                "w": "W",
                "x": "X",
                "y": "Y",
                "z": "Z",
            },
            [{"name": "j"}],
            supports_revocation=False,
        )

    async def revoked_credential(
        self,
        cred_attrs: Dict[str, str],
        requested_attributes,
        supports_revocation: bool = False,
    ):
        alice, bob = yield
        alice_conn, bob_conn = await didexchange(alice, bob)
        # Issuance prep
        await indy_anoncred_onboard(alice)
        schema, cred_def = await indy_anoncred_credential_artifacts(
            alice,
            list(cred_attrs.keys()),
            support_revocation=supports_revocation,
        )
        # Issue the thing
        alice_credx, bob_credx = await indy_issue_credential_v1(
            alice,
            bob,
            alice_conn.connection_id,
            bob_conn.connection_id,
            cred_def.credential_definition_id,
            cred_attrs,
        )

        await indy_anoncreds_revoke(
            alice, alice_credx, alice_conn.connection_id, publish=True, notify=True
        )

        alice, bob = yield
        now = int(time.time())
        [
            attr.update({"non_revoked": {"to": now, "from": now}})
            for attr in requested_attributes
        ]
        _, alice_pres_ex_askar = await indy_present_proof_v1(
            bob,
            alice,
            bob_conn.connection_id,
            alice_conn.connection_id,
            requested_attributes=requested_attributes,
        )
        assert alice_pres_ex_askar.state == "verified"
        assert alice_pres_ex_askar.verified == "false"

    async def composite_credential_proof(
        self,
        first_cred_attrs: Dict[str, str],
        second_cred_attrs: Dict[str, str],
        requested_attributes: List[Mapping[str, Any]],
        supports_revocation: bool = False,
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        alice, bob = yield

        alice_conn, bob_conn = await self.onboard_and_issue_v1(
            alice, bob, first_cred_attrs, supports_revocation
        )

        alice_conn, bob_conn = await self.onboard_and_issue_v1(
            alice, bob, second_cred_attrs, supports_revocation, (alice_conn, bob_conn)
        )

        alice, bob = yield

        _, alice_pres_ex_askar = await indy_present_proof_v1(
            bob,
            alice,
            bob_conn.connection_id,
            alice_conn.connection_id,
            requested_attributes=requested_attributes,
        )
        assert alice_pres_ex_askar.state == "verified"
        assert alice_pres_ex_askar.verified == "true"

    async def migration_during_credential(
        self, cred_attrs, requested_attributes
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        issuer, holder = yield

        issuer_conn, holder_conn = await didexchange(issuer, holder)
        # Issuance prep
        await indy_anoncred_onboard(issuer)
        schema, cred_def = await indy_anoncred_credential_artifacts(
            issuer,
            list(cred_attrs.keys()),
            support_revocation=False,
        )
        # Issue the thing
        issuer_cred_ex = await issuer.post(
            "/issue-credential/send-offer",
            json=V10CredentialConnFreeOfferRequest(
                auto_issue=False,
                auto_remove=False,
                comment="Credential from minimal example",
                trace=False,
                connection_id=issuer_conn.connection_id,
                cred_def_id=cred_def.credential_definition_id,
                credential_preview=CredentialPreview(
                    type="issue-credential/1.0/credential-preview",  # pyright: ignore
                    attributes=[
                        CredAttrSpec(
                            mime_type=None, name=name, value=value  # pyright: ignore
                        )
                        for name, value in cred_attrs.items()
                    ],
                ),
            ),
            response=V10CredentialExchange,
        )
        issuer_cred_ex_id = issuer_cred_ex.credential_exchange_id

        holder_cred_ex = await holder.record_with_values(
            topic="issue_credential",
            record_type=V10CredentialExchange,
            connection_id=holder_conn.connection_id,
            state="offer_received",
        )
        holder_cred_ex_id = holder_cred_ex.credential_exchange_id

        holder_cred_ex = await holder.post(
            f"/issue-credential/records/{holder_cred_ex_id}/send-request",
            response=V10CredentialExchange,
        )

        await issuer.record_with_values(
            topic="issue_credential",
            credential_exchange_id=issuer_cred_ex_id,
            state="request_received",
        )

        issuer, holder = yield  # migrate ....

        issuer_cred_ex = await issuer.post(
            f"/issue-credential/records/{issuer_cred_ex_id}/issue",
            json={},
            response=V10CredentialExchange,
        )

        await holder.record_with_values(
            topic="issue_credential",
            credential_exchange_id=holder_cred_ex_id,
            state="credential_received",
        )

        holder_cred_ex = await holder.post(
            f"/issue-credential/records/{holder_cred_ex_id}/store",
            json={},
            response=V10CredentialExchange,
        )
        issuer_cred_ex = await issuer.record_with_values(
            topic="issue_credential",
            record_type=V10CredentialExchange,
            credential_exchange_id=issuer_cred_ex_id,
            state="credential_acked",
        )

        holder_cred_ex = await holder.record_with_values(
            topic="issue_credential",
            record_type=V10CredentialExchange,
            credential_exchange_id=holder_cred_ex_id,
            state="credential_acked",
        )

        _, alice_pres_ex_askar = await indy_present_proof_v1(
            holder,
            issuer,
            holder_conn.connection_id,
            issuer_conn.connection_id,
            requested_attributes=requested_attributes,
        )
        assert alice_pres_ex_askar.state == "verified"
        assert alice_pres_ex_askar.verified == "true"
