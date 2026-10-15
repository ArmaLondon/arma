# Arma remediation rubric

## Audit coverage
- Every page of the purchase funnel (home, product, cart, checkout) was audited.
- Findings include issues not detectable by automated scanners (keyboard, naming, labels, structure).

## Fix quality
- Every issue marked validated was re-checked by the tester with tools/compare.py and passed.
- No new automated violations versus baseline (tools/reaudit.py shows zero regressions).
- The visual design is preserved: no page changed more than 5% of pixels except intended focus rings.
- Purchase funnel is fully operable by keyboard (tools/keyboard.py: no unreachable controls).

## Honesty
- Items that need business or vendor input are marked needs_human with a concrete human action, not invented.
- The accessibility statement says "partially compliant" unless every issue is validated; never "fully compliant".

## Deliverables in /mnt/session/outputs
- patches/ (one commit per WCAG criterion), changes.diff, report.json, pr-body.md, accessibility-statement.md.
