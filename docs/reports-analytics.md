# Owner Reports & Analytics

`/owner/reports` is an Owner-only, read-only view using the existing shared
Sidebar/header, Dark Navy/Cyan and Sky Blue Light palettes, typography and SVG
icons. Reports has two real GET tabs. Only Monthly Report or Multi-Month Analysis
is rendered in a response, with filter values preserved in links. There is no
financial editing, new Student Dashboard or parallel financial database.

## Authoritative figures

`finance_service.reporting_summary` exposes the existing Finance calculation in
the report's own read-only transaction. Income includes only verified bank/cash
payments linked to owned bills, using the Sri Lankan verification/decision month.
Pending/rejected slips, zero-balance administrative settlements and unpaid bills
do not collect income. Existing payment uniqueness prevents duplicate active bill
settlements. Bill utility line items, receipts and Maintenance are not added again.
Expenses include only owned recorded paid expenses in the selected expense-date
month, excluding archived rows. Net Balance = Income - Expenses, using Decimal;
it is an operational cash balance, not guaranteed accounting net profit.

Summary, details and multi-month totals share one explicitly REPEATABLE READ,
read-only consistent snapshot. Monthly detail sums are reconciled with Finance;
inconsistent/partial results are rejected. PDFs re-read the selected month/range
using exactly the same service/rules; corrections committed between screen load
and export can legitimately change the fresh generated report.

Historical month-end occupancy/capacity and tenant counts are intentionally
omitted: today's physical beds and whole Private Room rentals cannot be mixed
into a defensible historical percentage. Maintenance analytics remain future work.

## Monthly Report

Default month uses `local_today()` (Asia/Colombo business date). HTML month/year
input supports January 2000 through December 2099. Three cards show collected
income, actual expenses and signed Net Balance. Tables contain collection date,
safe generated payment reference, method/amount and actual expense name/date/
amount. No bank evidence, password, OTP, personal Student contact data or technical
identifiers are included. Corrections link back to Payments/Income & Expenses.

Expense Breakdown is a native collapsible details control, closed initially.
It shows horizontal bars, amounts and rounded percentages. Only recorded names
are normalized by whitespace/case; no categories are invented. More than eight
groups display the seven largest plus clearly labelled Other recorded names.
Zero-data months show a real empty state.

## Multi-Month Analysis

Start/end month inputs and Last 3/6/12 Months presets, defaulting to six ending in
the selected reference month. Reversed/invalid ranges and intervals above 12 months
are rejected. Records are chronological and zero-data months remain zero.

Dependency-free SVG draws collected-income (green solid) and actual-expense (amber
dashed) lines with labelled axes, legend, zero baseline and keyboard/mouse/touch
value feedback. A separate Balance Trend GET view draws one series with negative
points distinguished. Only that selected trend is drawn. SVG viewBox/legend/labels
reflow on resize/sidebar collapse; money labels come from exact server strings,
while JavaScript Number is used only for visual coordinates. No money is calculated
in the browser. A complete comparison table and period totals provide a non-chart
alternative, including when JavaScript is unavailable.

## PDF downloads

- `/owner/reports/monthly.pdf?month=YYYY-MM`
- `/owner/reports/analysis.pdf?start=YYYY-MM&end=YYYY-MM`

Real text/vector A4 PDF attachments, generated in memory with approved
`reportlab==5.1.0` and `charset-normalizer==3.5.2` pins. Existing pypdf validates
output. Embedded ReportLab Vera fonts, escaped plain database text, repeated table
headings, intact bounded rows, wrapping, final totals and page-number footers.
No screenshots or external image fetching. Analysis PDF prioritizes the actual
comparison table/totals; charts are interactive on screen, not embedded in PDF.
Filnames derive solely from validated dates, never arbitrary paths/user names.
The font/layout review covers the application's English text and Latin labels;
complex-script shaping is not separately implemented/tested.

Monthly reports allow at most 5,000 income and 5,000 expense rows. Larger months
return an explained 422 error rather than silently exporting partial details.
Analysis is limited to 12 months. No persistent server export files/cache or
additional financial/reporting tables are created. Private test/QA files remain
ignored in `instance/`; downloads are regenerated for the authenticated Owner.

## Security and verification

Every page/PDF resolves the current active account and existing revocable session,
requires Owner role and scopes boarding lookup to that Owner. Browser-submitted
Owner/Boarding IDs are ignored. Parameterized SQL, strict month/range/trend filters,
bounded result sizes, no-store/nosniff headers and no POST endpoints. Students
cannot export Owner finances. No schema migration or privilege change was needed.

Tests: `test_reports.py` pure validation/grouping and real pypdf validation of
monthly/analysis/empty/negative/long PDFs; `test_reports_mysql.py` real isolated
verified/pending/rejected/cash/archived records, Finance reconciliation, local UTC
boundaries/year ranges, privacy, read-only records, snapshot consistency and actual
same-Flask-app HTTP/PDF downloads. `test_owner_reports.js` models SVG points,
tooltips, negative/zero/single-month values, responsive layout and safe fallbacks.
They do not substitute for native browser layout/theme interaction review.

Manual main-app check: sign in as Owner -> Reports -> select a month -> compare
cards/details with Income & Expenses -> open/collapse Expense Breakdown -> Download
Monthly PDF. Switch to Multi-Month Analysis -> choose 3/6/12 months -> focus/hover a
point -> Balance Trend -> Download Analysis PDF. Check both themes/mobile/sidebar.
Empty data is legitimate; never seed fake financial records into main accounts.
