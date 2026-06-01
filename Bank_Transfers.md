Here’s the implementation plan I’d use for AgriPlot, based on that Jenga/Finserve suggestion and the current payment model in the repo.

The big idea is to treat bank transfer as a first-class payout rail inside the existing payments workflow, not as a one-off special case. That means the system should create a payout request, reserve the money in escrow/ledger, send the bank instruction through a provider adapter, then confirm and reconcile the final settlement asynchronously.

Plan

Build a bank transfer provider abstraction.

Add a BankTransferProvider service interface under payments.
Implement a JengaBankTransferProvider behind it.
Keep the provider isolated from views so you can swap Finserve/Jenga later if needed.
Extend the payment lifecycle for bank payouts.

Use the existing PaymentRequest.Method.BANK_TRANSFER.
Add payout states such as queued, submitted, settled, failed, reversed, and reconciled.
Record the provider reference, bank transaction reference, routing choice, and callback payload on the transaction.
Design the signing and idempotency layer.

Generate a canonical payload string before signing.
Sign requests with your private key if the Jenga API requires RSA signing.
Add a unique idempotency key per payout request so duplicate retries do not double-pay.
Enforce a uniqueness constraint on the provider reference and internal payout reference.
Route transfers by amount and urgency.

Use PesaLink for fast transfers under the provider’s limit.
Fall back to RTGS for larger settlements.
Make the routing rule explicit in code, not buried in the UI.
Save the chosen rail on the payout record so finance can audit why a transfer went through a given channel.
Add bank account verification and beneficiary records.

Create a BankBeneficiary or PayoutDestination model.
Store bank name, bank code, account number, account name, and verification status.
Validate seller account ownership before enabling a live payout.
Keep verification separate from transfer execution.
Add callback handling and webhook verification.

Create a signed callback endpoint for deposit confirmations and payout settlement callbacks.
Verify the provider signature before touching the wallet or payment tables.
Make callback handlers idempotent and safe to replay.
Persist raw callback payloads for audit and dispute handling.
Wire payout execution into the transaction workflow.

On completion of a land transfer, compute the seller payout amount.
Freeze the escrow amount first.
Issue the bank transfer instruction only after the legal completion gate is satisfied.
Release the ledger entry only when the bank confirms settlement.
Add nightly reconciliation.

Compare internal payout records with the bank statement or settlement export.
Mark mismatches for review.
Surface unreconciled items in the finance dashboard.
Keep an immutable audit trail for every reconciliation run.
Update the UI and admin tools.

Add a bank payout panel to the payment workspace.
Show provider status, routing rail, beneficiary details, and callback state.
Add finance admin actions for retry, reverse, and mark reconciled.
Keep the seller-facing UI simple and status-based.
Cover the risky bits with tests.

Test request signing and signature verification.
Test idempotent retry behavior.
Test PesaLink vs RTGS routing.
Test callback replay handling.
Test reconciliation mismatches and manual override flows.
What I’d prioritize first

Provider abstraction and data model.
Signed request execution and callback verification.
Idempotency and payout state machine.
Reconciliation.
UI polish.