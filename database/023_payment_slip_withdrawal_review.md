# Pending payment-slip withdrawal

The live application supports withdrawal with the existing schema. It records
the Student as the actor on the inactive payment row and adds a
`student_withdrawal` audit action. The application displays this as Withdrawn.
The SQL below is a historical proposal and is unnecessary for this workflow.

`023_payment_slip_withdrawal.sql` adds a distinct Withdrawn state to the existing
payment and audit enums. The CHECK keeps the existing Owner decision rules and
allows a Student withdrawal only when the decider is the original submitter.
The active-bill key already reserves the bill for submitted and verified rows
only. Withdrawal therefore admits a corrected submission on the same invoice.

The Student confirms the action from My Payments. The server checks the logged-in
Student and locks the bill in the same order used for Owner verification and
rejection. The first successful action wins. A withdrawn slip disappears from
Owner Payments, old slip URLs are closed, and the Student history retains a
Withdrawn entry. The original evidence stays in private audit storage. Files
already delivered outside the app, such as email attachments, cannot be recalled.
