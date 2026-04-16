FREDDIE MAC SFLLD 2021 — FAIR LENDING AUDIT PACKAGE
======================================================

Generated : 2026-04-13T02:14:47.692921+00:00
Packet ID : 31f0405e-a20e-4274-8761-dabab0ea8e19
Source    : ai-risk-workflow.freddie_mac_sflld.freddie_origination

CONTENTS
--------
exam_packet.json
    Machine-readable ExamPacket following the OCC/CFPB examination format.
    Contains all component data with pass/fail flags.

exam_packet.pdf
    PDF rendering of exam_packet.json (OCC examination layout).

executive_summary.txt
    One-page human-readable compliance summary with key findings.

data/
    Individual JSON reports for each fair lending test and the CSV
    loan-terms disparity table. These are the authoritative outputs
    from the BigQuery analysis pipeline.

methodology/
    fair_lending_methodology.txt  — Full methodology description including
    rate-spread definition, proxy construction, and regulatory references.

    model_documentation_record.json  — SR 11-7 Model Documentation Record
    for the fair lending analyzer.

chain_of_custody.json
    Data provenance record including source table, query parameters,
    row counts, run timestamps, and software versions.

REGULATORY FRAMEWORK
--------------------
This package is prepared to support:
  • CFPB Fair Lending Examination (ECOA / Reg B)
  • HMDA / Regulation C supervisory review
  • OCC large-institution fair lending module
  • Internal Model Risk Management (SR 11-7) documentation

OVERALL COMPLIANCE STATUS
--------------------------
✓ ALL DIR TESTS PASSED — No disparate impact violations detected.
