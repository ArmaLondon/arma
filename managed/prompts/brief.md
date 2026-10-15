Run Arma on the store "{site}".

- Store archive: /mnt/session/uploads/demo-shop.tgz → extract to /workspace/site.
- Tools archive: /mnt/session/uploads/tools.tgz → extract to /workspace/arma/tools.
- Serve the store at http://127.0.0.1:8765/ (start page: index.html).
- Git branch for the fixes: {branch}
- Follow your protocol: crawl, baseline, audit (parallel page auditors), plan, fix and verify
  (developer ⇄ tester, rollback on regression, three attempts max), re-audit, report, pr outputs.
{until}
