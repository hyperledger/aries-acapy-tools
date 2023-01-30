from typing import AsyncGenerator, Tuple
from controller import Controller
from controller.protocols import (
    didexchange,
    indy_anoncred_credential_artifacts,
    indy_anoncred_onboard,
    indy_issue_credential_v1,
    indy_present_proof_v1,
)


class MigrationTestCases:
    def __init__(self):
        self._cases = (
            self.connections(),
            self.credentials(),
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

    async def credentials(self) -> AsyncGenerator[None, Tuple[Controller, Controller]]:
        alice, bob = yield
        alice_conn, bob_conn = await didexchange(alice, bob)
        # Issuance prep
        await indy_anoncred_onboard(alice)
        schema, cred_def = await indy_anoncred_credential_artifacts(
            alice,
            ["firstname", "lastname"],
            support_revocation=True,
        )

        # Issue the thing
        alice_cred_ex, bob_cred_ex = await indy_issue_credential_v1(
            alice,
            bob,
            alice_conn.connection_id,
            bob_conn.connection_id,
            cred_def.credential_definition_id,
            {"firstname": "Bob", "lastname": "Builder"},
        )

        alice, bob = yield

        _, alice_pres_ex_askar = await indy_present_proof_v1(
            bob,
            alice,
            bob_conn.connection_id,
            alice_conn.connection_id,
            requested_attributes=[{"name": "firstname"}],
        )
        assert alice_pres_ex_askar.state == "verified"
        assert alice_pres_ex_askar.verified == "true"
