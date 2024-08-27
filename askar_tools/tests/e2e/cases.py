from typing import Any, AsyncGenerator, Dict, List, Mapping, Tuple

from acapy_controller import Controller
from acapy_controller.protocols import (
    didexchange,
    indy_anoncred_credential_artifacts,
    indy_anoncred_onboard,
    indy_issue_credential_v2,
    indy_present_proof_v2,
)


class BaseTestCases:
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
        assert alice_pres_ex_askar.state == "verified"

    def credentials_with_revocation(
        self,
    ) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        return self.credentials_v2(
            {"first_name0": "Bob", "last_name": "Builder"},
            [
                {
                    "name": "first_name0",
                }
            ],
            supports_revocation=True,
        )


class MtConvertToMwTestCases(BaseTestCases):
    def __init__(self):
        self._cases = (self.connections(), self.credentials_with_revocation())


class ExportTestCases(BaseTestCases):
    def __init__(self):
        self._cases = (self.connections(), self.credentials_with_revocation())
