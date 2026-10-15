# Arma : plan de construction, version Managed Agents (pour Claude Code)

> **À lire avant de commencer.**
> - **`arma-spec.md`** fait foi. Ce plan dit **dans quel ordre** construire.
> - **`reference/arma-dashboard-prototype.html`** est la maquette fonctionnelle du dashboard.
> - **Règle d'or** : exécuter les étapes dans l'ordre. Une étape ne commence pas tant que la
>   vérification de la précédente n'est pas passée. Commit à la fin de chaque étape.
> - **Priorité** : une démo qui marche visuellement, à chaque fois.
> - **Vercel héberge l'application Arma** (le dashboard `web/`), c'est-à-dire le produit et le
>   lien live. **Maison Lumière est une cible de démo temporaire**, servie dans le sandbox et
>   jamais sur Vercel. Elle se remplace par un vrai site via `targets/*.json` (spec §20).

---

## Vue d'ensemble

| Jalon | Étapes | Résultat |
|---|---|---|
| **A. Démo montrable** | 0 à 3 | Dashboard en replay sur la fixture, **déployé sur Vercel**. Le lien live existe. |
| **B. Équipe hébergée** | 4 à 10 | Session Managed Agents réelle sur la boutique démo : audit, correctifs, vérification, outcome, sorties rapatriées, vrai run enregistré. |
| **C. Prouver** | 11 et 12 | Eval contre la vérité terrain, meilleur run en replay redéployé, livrables. |
| **D. Bonus** | 13 à 15 | Hill climb, mode live SSE, vraie PR GitHub. |

**Budget indicatif** (soumission à 15:00) :

| Jalon | Durée |
|---|---|
| A | ~1h |
| B | ~2h |
| C | ~30 min |
| D | seulement s'il reste du temps |

**Parallélisation.** Après l'étape 1 (le contrat d'événements commité), on peut ouvrir deux
sessions Claude Code :
- **« web »** : étapes 2 et 3, uniquement dans `web/` ;
- **« agents »** : étapes 4 et suivantes, dans tout le reste sauf `web/`.

**Correspondance avec la slide des organisateurs** :

| Étape organisateurs | Étape du plan |
|---|---|
| `claude auth login --console` | étape 0 |
| `/claude-api managed-agents-onboard` | étape 5 |
| `/goal` | étape 0 |
| `/claude-api build-eval` | étape 11 |
| `/claude-api hillclimb` | étape 13 |

---

## Étape 0 : connexion, squelette, ligne d'arrivée *(~15 min)*

1. **Connexion Console** (l'utilisateur le fait si nécessaire) : `claude auth login --console`,
   sur le compte qui porte les crédits API du hackathon. Mettre `ANTHROPIC_API_KEY` dans `.env`.
2. **`/goal`** : définir la ligne d'arrivée avec le texte exact de `arma-spec.md` §8.1.
3. **Arborescence** de la spec §16, avec des fichiers vides. Dans `.gitignore` : `.venv/`,
   `runs/`, `state/`, `recordings/*.jsonl` (sauf `!web/recordings/*.jsonl`), `__pycache__/`,
   `.env` et `*.tgz`.
4. **Dépendances**, dans `requirements.txt` :
   ```
   anthropic
   fastapi
   uvicorn[standard]
   ```
   Pas de Playwright local : le navigateur tourne dans le sandbox.
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. **CLI `ant`** : installer selon la doc Managed Agents (Homebrew `anthropics/tap/ant` ou binaire
   GitHub), puis `ant --version`.
6. **Vendoriser axe-core** dans `sandbox_tools/vendor/axe.min.js`
   (`npm pack axe-core@4.10.3`, puis extraction).
7. **`CLAUDE.md`**, une page :
   - le résumé ;
   - les commandes ;
   - les règles d'or ;
   - les pièges de la spec §17 ;
   - les liens vers la spec et le plan.

**Vérification**
```bash
python -c "import anthropic; c=anthropic.Anthropic(); print(c.beta.environments.list())"
ant --version
```
La liste des environnements répond, même vide.

**Commit** : `chore: scaffold, deps, ant CLI, goal`

---

## Étape 1 : contrat d'événements + fixture *(~20 min)*

**Fichiers.** `arma_bridge/events.py`, `scripts/make_fixture.py`, `web/recordings/fixture.jsonl`
et `web/events-contract.md` (copie de la spec §10).

- **`EventBus`** :
  - `emit(type, data, agent=None)` valide le type, ajoute `t` (secondes depuis le début), écrit
    une ligne JSONL avec flush, et pousse dans les files `asyncio.Queue` abonnées ;
  - `subscribe()` / `unsubscribe()` ;
  - thread-safe (`threading.Lock`).
- **`make_fixture.py`** reproduit **le scénario complet** du prototype :
  - **les seize problèmes** du tableau `ISSUES` de la maquette ;
  - auditeurs parallèles et une panne d'outil relancée ;
  - **le refus A07** (`role="button"`, puis `<button>`, **même fil développeur**) ;
  - **le rollback du lot 1.4.3** (18 % de pixels, puis texte seul) ;
  - commits, re-audit et documents réels (`pr-body.md`, `accessibility-statement.md`) ;
  - **`outcome`** : `needs_revision` à l'itération 0 avec une explication plausible, puis
    `satisfied` à l'itération 1 ;
  - **`eval`** avec des métriques plausibles marquées PASS ;
  - `pr.ready` et `run.finished`.

  Les événements `score` sont calculés avec la formule de la spec §10.

**Vérification** : un script Python qui parse la fixture et vérifie :
- la présence de tous les types de la spec §10 ;
- des `t` croissants ;
- au moins deux `rejected` ;
- un `outcome` avec `satisfied`.

**Commit** : `feat: event contract and realistic fixture`

---

## Étape 2 : dashboard en replay *(~40 min)*

**Fichiers.** `web/index.html`, `web/styles.css`, `web/app.js`.

1. **Partir du prototype** : garder la mise en page, les styles, les composants et les textes.
   Remplacer son `buildScript()` et ses données codées en dur par un **réducteur d'événements
   pur** (`apply(state, ev)`, un `case` par type) et un rendu throttlé par
   `requestAnimationFrame`.
2. **`ReplaySource`** :
   - charge `?run=…`, avec repli `recordings/demo-run.jsonl` puis `recordings/fixture.jsonl` ;
   - au chargement, applique tout d'un coup : la page est complète au repos ;
   - « Run audit » rejoue en 1×, 2× ou 4× ; le bouton devient « Stop » pendant le run.
3. **`LiveSource`** : un stub (étape 14).
4. **Ajouts propres à Managed Agents** (spec §15) :
   - badge « Hosted on Claude Managed Agents · session … » ;
   - carte **Independent grader** (itération, résultat, explication) ;
   - carte **Eval** (métriques, seuils, PASS/FAIL) ;
   - l'équipe d'agents affiche Lead, Auditors ×N, Developer, Tester et Writer.
5. **Envoi de PR en replay** : simulé côté client (checklist animée, puis carte de confirmation
   avec la mention « Demo workspace »).
6. **Panneau `#about`** : le pitch en une ligne, le problème EAA, le schéma de l'équipe hébergée
   et le lien GitHub.
7. **Accessibilité et responsive** (exigés) :
   - onglets ARIA avec les flèches ;
   - lignes dépliables au clavier, avec `aria-expanded` ;
   - focus visible ;
   - contrastes AA en clair et en sombre ;
   - `prefers-reduced-motion` ;
   - pas de scroll horizontal à 400 px.

**Vérification** : `scripts/check_web.py` (Playwright local, installé à part pour ce test :
`pip install playwright && python -m playwright install chromium`) :
- teste 1400 et 400 px, en clair et en sombre ;
- vérifie qu'il n'y a pas d'erreur console et que `scrollWidth` ne dépasse pas la largeur ;
- vérifie que le score affiché vaut le dernier `score` ;
- lance un replay 4× jusqu'à la fin ;
- envoie la PR ;
- prend des captures dans `state/checks/`.

Relire les captures une fois et corriger.

**Commit** : `feat: compliance dashboard driven by event replay`

**Si ça bloque** : copier le prototype tel quel, et brancher seulement le chargement de la fixture.

---

## Étape 3 : premier déploiement Vercel *(~10 min)*

1. Créer `web/vercel.json` : site statique, avec un header `Cache-Control: no-store` sur
   `/recordings/*`.
2. Copier `fixture.jsonl` en `demo-run.jsonl` (il sera remplacé à l'étape 12).
3. Lancer `cd web && npx vercel --prod`. Si la CLI n'est pas connectée, l'utilisateur fait
   `npx vercel login`.
4. Noter l'URL dans `deliverables/links.md` et dans le `README.md`.

**Vérification** : en navigation privée, la page est complète au repos et le replay fonctionne.

**Commit** : `chore: first Vercel deploy`

> ✅ **Jalon A atteint.** Il y a quelque chose à montrer et à soumettre.

---

## Étape 4 : boutique démo + outils du sandbox *(~30 min)*

### 4a. `demo-shop/` (cible temporaire)
Créer aussi `targets/maison-lumiere.json` (spec §20). `bridge.py` lit la cible via
`--target` (défaut : ce fichier) au lieu de chemins codés en dur.

Créer la boutique avec **exactement** les défauts de la spec §11 :
- en-tête et pied de page identiques sur les quatre pages ;
- checkout atteint via `onclick` ;
- hero en `#b5b5b5` sur `#faf7f2` ;
- « Ajouter au panier » en `div` ;
- iframe tiers dans le paiement.

### 4b. `sandbox_tools/`
Écrire les scripts de la spec §12 : `common.py`, `crawl.py`, `audit.py`, `keyboard.py`,
`baseline.py`, `reaudit.py`, `compare.py` et `audit_static.js`. Règles :
- **Chromium** : `executable_path` pris dans la variable `ARMA_CHROMIUM` (défaut
  `/usr/bin/chromium`), avec `--no-sandbox`.
- **axe** : chargé depuis `vendor/axe.min.js`, relatif au script.
- **Sorties** : un JSON sur stdout ; en cas d'erreur, `{"error": "...actionable..."}` et un code
  de sortie non nul.
- **Fichiers de travail** : `ARMA_WORK` (défaut `/workspace/arma`) pour les JSON et les captures.

### 4c. Test local des outils
Lancer avec un Chromium local (celui de Playwright installé à l'étape 2) :
```bash
python -m http.server 8765 -d demo-shop &
ARMA_CHROMIUM=$(python -c "from playwright.sync_api import sync_playwright as p; s=p().start(); print(s.chromium.executable_path)") \
ARMA_WORK=state/local python sandbox_tools/crawl.py http://127.0.0.1:8765/index.html
python sandbox_tools/audit.py http://127.0.0.1:8765/index.html
python sandbox_tools/keyboard.py http://127.0.0.1:8765/product.html
python sandbox_tools/baseline.py http://127.0.0.1:8765/index.html
python sandbox_tools/compare.py http://127.0.0.1:8765/index.html
```

**Attendus** :
- le crawl renvoie quatre pages, checkout comprise ;
- axe trouve `color-contrast`, `html-has-lang` et `image-alt`, et **pas** les défauts de
  jugement ;
- le parcours clavier signale le focus invisible et les `div` inaccessibles ;
- `compare.py` juste après `baseline.py` renvoie zéro régression et environ 0 % de pixels modifiés.

**Commit** : `feat: trapped demo shop and sandbox tools`

---

## Étape 5 : onboarding Managed Agents + smoke test du sandbox *(~25 min)*

**C'est l'étape la plus risquée. On valide la chaîne d'outils du sandbox avant toute autre chose.**

1. **Lancer `/claude-api managed-agents-onboard`.** S'en servir pour générer ou valider la
   structure `managed/` et le flux `ant apply`. Ce qu'il propose est conservé s'il est compatible
   avec la spec §5.
2. **`managed/environment.yaml`** : copier la spec §5.1, puis `ant apply managed/environment.yaml`.
   L'identifiant va dans `claude-lock.json`.
3. **`managed/agents/smoke.md`** : un agent minimal, avec `agent_toolset_20260401` (bash, read,
   write) et le prompt « Run the commands you are given and report outputs verbatim. ». Puis
   `ant apply`.
4. **`scripts/smoke_sandbox.py`** :
   1. compresse `demo-shop/` et `sandbox_tools/` ;
   2. les uploade (`client.files.upload`) ;
   3. crée une session avec `resources` (les deux fichiers tgz) et un budget faible ;
   4. ouvre le stream, **puis** envoie un `user.message` qui demande de :
      - extraire les deux tgz dans `/workspace` ;
      - lancer `which chromium` et `python -c "import playwright"` ;
      - démarrer `http.server` ;
      - lancer `crawl.py`, puis `audit.py` sur l'index ;
      - écrire le résultat dans `/mnt/session/outputs/smoke.json` ;
   5. attend `session.status_idle`, puis télécharge `smoke.json` via
      `client.beta.files.list(scope_id=session.id, betas=["managed-agents-2026-04-01"])`.

**Vérification** : `smoke.json` contient les quatre pages et des violations axe.

**Si ça bloque** (Chromium ou Playwright indisponible dans le sandbox), essayer dans l'ordre :
1. ajouter `apt: [chromium-driver]` ou chercher le binaire (`ls /usr/bin | grep -i chrom`) et
   l'indiquer dans `ARMA_CHROMIUM` ;
2. passer `audit.py` et `keyboard.py` en mode `audit_static.js` (Node + jsdom + axe), en ajoutant
   `npm: [jsdom]` à l'environnement. Le parcours clavier est alors remplacé par une analyse
   statique des éléments interactifs (`onclick` non focusables, `outline: none`).

Le diff visuel est alors désactivé : le testeur s'appuie sur le diff CSS.

**Le plafond pour cette étape est de 40 minutes.** Au-delà, prendre l'option 2.

**Commit** : `feat: managed environment validated by sandbox smoke test`

---

## Étape 6 : ledger + custom tools + pont minimal *(~25 min)*

**Fichiers.** `arma_bridge/store.py`, `scoring.py`, `custom_tools.py`, `translate.py`, `bridge.py`
et `tests/`.

- **`store.py`** :
  - `state/state.json` en écritures atomiques, sous `RLock` ;
  - pages, issues, batches, commits ;
  - `add_issue` avec dédoublonnage (spec §6) ;
  - **machine à états des statuts** : transitions autorisées
    `detected → fixing → fixed_pending → validated | rejected`, `rejected → fixing`,
    `* → needs_human`.
- **`scoring.py`** : la formule de la spec §10, avec le total figé.
- **`custom_tools.py`** :
  - un handler par outil de la spec §6 (y compris `start_batch`) ;
  - chacun valide les entrées et l'appelant (`verdict` réservé à `tester`) ;
  - chacun émet les événements prévus ;
  - chacun renvoie un texte court et actionnable.
- **`translate.py`** : la correspondance des événements Managed Agents vers le contrat (spec §10).
  Les étiquettes d'agent viennent du champ `agent` des custom tools et des événements de fil.
- **`bridge.py run`** (premier jet) :
  1. upload des entrées ;
  2. session ;
  3. stream ouvert **avant** l'envoi ;
  4. boucle d'événements ;
  5. réponse aux `agent.custom_tool_use` dès réception ;
  6. reconnexion avec dédoublonnage par `event.id` ;
  7. fin sur l'idle `end_turn` ;
  8. enregistrement de `recordings/run-<date>.jsonl`.

**Tests** (`pytest -q`) :
- le dédoublonnage ;
- les transitions illégales refusées ;
- un score de départ entre 30 et 45 sur les données de la fixture, puis environ 95 avec A04 et A16
  ouverts ;
- un handler `report_issue` qui émet `issue.detected`.

**Commit** : `feat: compliance ledger, custom tool handlers, bridge skeleton`

---

## Étape 7 : agents Managed (cartographie + audit) *(~30 min)*

1. **Écrire les agents** dans `managed/agents/` selon la spec §5.2, avec leurs custom tools
   (`type: custom`, descriptions détaillées, `input_schema`) :
   - **`page-auditor.md`** : le protocole de la spec §7.2 en entier, avec la liste des problèmes
     de jugement et l'appel obligatoire à `emit_progress` à chaque étape ;
   - **`developer.md`**, **`tester.md`** et **`writer.md`** : leurs prompts, même s'ils ne servent
     qu'à l'étape 8 ;
   - **`lead.md`** : le protocole complet de la spec §7, et le bloc `multiagent` avec les quatre
     sous-agents en `predefined_agents` et `inline_agents` désactivé.
2. **Appliquer d'abord les sous-agents, puis le lead** (`ant apply`), pour que le lead épingle les
   bonnes versions.
3. **`managed/prompts/brief.md`** : le brief du run (extraire, git, servir, cartographier,
   mesurer, auditer en parallèle, planifier, corriger et vérifier, re-auditer, documents,
   sorties). Ajouter un drapeau `--until audit` dans `bridge.py` : le brief demande alors de
   s'arrêter après la planification.
4. **Lancer** `python bridge.py run --until audit --model-override sonnet`.

**Vérification**
- `state/state.json` contient quatre pages et **au moins douze problèmes**, dont une majorité en
  `source != "axe"`.
- Le JSONL montre des fils d'auditeurs en parallèle (`session.thread_created`, puis des
  `report_issue` étiquetés `auditor·<page>`).
- **Ouvrir ce JSONL dans le dashboard** (`?run=…`) : le rendu est correct.

**Commit** : `feat: hosted lead + parallel page auditors on Managed Agents`

**Si ça bloque** :
- **si la délégation parallèle échoue** : le lead délègue les pages une par une. C'est moins
  spectaculaire, mais fonctionnel ;
- **si un sous-agent n'appelle pas les custom tools** : renforcer son prompt avec la consigne
  « Every finding MUST be recorded with report_issue; findings only in text are lost ».

---

## Étape 8 : boucle correction ⇄ vérification *(~40 min)*

1. **Compléter le brief et le prompt du lead** avec la boucle de la spec §7.4 :
   - `start_batch` ;
   - délégation au développeur, **en réutilisant le même fil** pour les relances ;
   - délégation au testeur ;
   - rollback (`git checkout`, puis `rollback_batch`) ;
   - commit, puis `record_commit` ;
   - plafond de trois tentatives.
2. **Prompt du testeur** :
   - indépendance : il ne lit pas le diff, il juge le résultat ;
   - refus des correctifs cosmétiques (`role="button"` sur un `div` non focusable) ;
   - si plus de 2 % des pixels changent, ouvrir la capture diff et refuser si le fond ou la mise
     en page a changé ;
   - raisons actionnables.
3. **Lancer d'abord un seul lot** : `python bridge.py run --only-batch 2.1.1 --model-override sonnet`.
   Le brief n'exécute alors que ce lot.
4. **Puis le run complet** jusqu'au re-audit.

**Vérification**
- Dans le JSONL :
  - au moins un `issue.status rejected`, puis `validated` pour le même identifiant, **avec le même
    fil développeur** (même `session_thread_id` si disponible, ou étiquette identique) ;
  - au moins un `rollback` ;
  - des `commit.created` par critère.
- Dans le state :
  - au moins dix problèmes `validated` ;
  - A04 et A16 en `needs_human`.

**Commit** : `feat: hosted developer/tester loop with rollback and escalation`

**Si aucun refus n'apparaît naturellement** : durcir le prompt du testeur, puis relancer. **Ne
jamais fabriquer d'événements.**

---

## Étape 9 : outcome + sorties rapatriées *(~25 min)*

1. **Rubric** : `managed/rubric.md` (spec §8.2), uploadée par le pont. La session reçoit
   `user.define_outcome` avec la rubric en fichier et `max_iterations: 3`, juste après le brief.
2. **`translate.py`** : `span.outcome_evaluation_start` et `span.outcome_evaluation_end`
   deviennent des événements `outcome`. Ne pas considérer le run terminé avant un résultat
   terminal (`satisfied`, `max_iterations_reached`, `failed`).
3. **Fin de run** (`arma_bridge/outputs.py`) :
   - lister et télécharger `/mnt/session/outputs/*` dans `state/out/`, en réessayant après
     quelques secondes ;
   - copier `demo-shop/` vers `runs/demo-shop/`, faire `git init` puis le commit de baseline, et
     appliquer `git am state/out/patches/*.patch` sur la branche `a11y/eaa-remediation-<date>` ;
   - émettre `document.written` (`pr-body`, `statement`), `reaudit` (depuis `report.json`),
     `pr.ready` et `run.finished` (coût via `session.usage`).

**Vérification** : run complet `python bridge.py run --model-override sonnet` :
- l'outcome est `satisfied`, éventuellement après un `needs_revision` ;
- `state/out/` contient les documents et les patchs ;
- `git log` dans `runs/demo-shop` montre un commit par critère ;
- le dashboard affiche la carte grader et les onglets PR et Statement remplis avec le **vrai**
  contenu.

**Commit** : `feat: outcome rubric grading and output retrieval`

> ✅ **Jalon B atteint.**

---

## Étape 10 : robustesse du run long *(~15 min)*

- **`bridge.py resume <session_id>`** : rattache le stream, relit l'historique
  (`events.list`), dédoublonne et reprend les réponses aux custom tools en attente.
- **Démonstration** : couper le pont (Ctrl-C) en pleine phase fix, puis lancer `resume`. La
  session a continué côté serveur et le dashboard rattrape. C'est l'argument « long running ».
- **Budget** : en cas d'idle `budget_reached`, journaliser proprement et proposer `resume` après
  hausse du budget.
- **`session.error`** : journaliser ; ne pas abandonner si `retry_status` indique une relance
  automatique.

**Vérification** : le test Ctrl-C puis `resume` sur un run en cours se termine correctement.

**Commit** : `feat: resumable bridge for long-running sessions`

---

## Étape 11 : eval *(~25 min)*

1. **`/claude-api build-eval`** : s'en servir pour générer ou valider l'eval à partir de la spec
   §9.
2. **`eval/ground_truth.json`** : seize entrées (spec §11), avec leurs règles de correspondance et
   `expected_final`.
3. **`eval/run_eval.py state/out/report.json [state/out/final.json]`** :
   - calcule les métriques et les seuils de la spec §9.2 ;
   - affiche PASS/FAIL ;
   - écrit `eval/results/<run>.json` ;
   - renvoie un code de sortie non nul en cas d'échec.
4. **Pont** : à la fin du run, lancer l'eval et émettre l'événement `eval`. Ajouter une ligne à
   `eval/history.csv` avec la version des agents (lue dans `claude-lock.json`).

**Vérification** : sur le run de l'étape 9, l'eval sort avec un tableau lisible. Si elle échoue,
noter les métriques en échec : elles sont la cible du hill climb.

**Commit** : `feat: ground-truth eval`

---

## Étape 12 : meilleur run → replay → redéploiement + livrables *(~25 min)*

1. **`scripts/pick_demo_run.py <run.jsonl>`** :
   - vérifie la présence d'un refus suivi d'une validation sur le même identifiant, d'un
     rollback, de sous-agents parallèles, d'un `outcome satisfied`, d'un `eval` PASS et de
     `pr.ready` ;
   - plafonne chaque écart entre événements à 4 secondes ;
   - écrit `web/recordings/demo-run.jsonl`.
2. **Run final** : un run complet sans override de modèle si le budget le permet. Sinon, garder le
   meilleur run sonnet.
3. **Vérification du dashboard** : `scripts/check_web.py` sur `demo-run.jsonl`, puis
   `cd web && npx vercel --prod`.
4. **`scripts/export_logs.py`** produit `deliverables/agent-logs.txt` :
   - un en-tête : session, modèle(s), coût, durée, résultat de l'outcome, eval ;
   - une ligne `mm:ss [agent] texte` par log ;
   - des séparateurs de phase.
5. **`deliverables/agent-design.txt`**, une page, en anglais :
   1. architecture hébergée (lead + sous-agents, fils persistants et isolés, sandbox partagé) ;
   2. passations via les custom tools du registre de conformité ;
   3. boucle plan → act → verify, avec rollback et escalade ;
   4. outcome rubric et grader indépendant ;
   5. eval contre la vérité terrain et hill climb ;
   6. reprise (sessions côté serveur, `resume`, budget) ;
   7. gouvernance (outils par rôle, testeur sans édition, machine à états, audit trail, aucune
      affirmation de conformité totale) ;
   8. stack.
6. **`deliverables/links.md`** : l'URL Vercel, `#about`, le dépôt, et un emplacement pour les
   slides.
7. **MP4** : l'utilisateur enregistre l'écran du replay 2× sur l'URL Vercel.

**Vérification** : sur l'URL Vercel, en navigation privée, on voit le **vrai** run : grader
`satisfied`, eval PASS, refus, rollback, commits et PR.

**Commit** : `chore: ship real run replay and deliverables`

> ✅ **Jalon C atteint. Prêt à soumettre.**

---

## Bonus, dans cet ordre

### Étape 13 : hill climb *(~30 min)*
1. Lancer `/claude-api hillclimb` sur `eval/run_eval.py`. Cibler d'abord le prompt de
   `page-auditor` (`recall_agent_only`), puis celui du testeur (`false_fix`, `verified_fix_rate`).
2. À chaque itération :
   - `ant apply` du sous-agent modifié **puis du lead**, pour ré-épingler les versions ;
   - un run ;
   - l'eval ;
   - une ligne dans `history.csv`.
3. Le dashboard affiche la mini-courbe de l'historique dans la carte Eval.
4. Redéployer avec le meilleur run.

### Étape 14 : mode live (SSE)
- **`server.py`** :
  - `GET /api/events` (SSE depuis l'EventBus) ;
  - `GET /api/state` ;
  - `POST /api/run` (lance `bridge.run` en tâche de fond ; renvoie 409 si un run est en cours) ;
  - `POST /api/pr` ;
  - statique `web/`.
- **`LiveSource`** : `EventSource('/api/events')`. Mode `live` par défaut si `/api/state` répond,
  avec repli automatique sur le replay (et un toast).

### Étape 15 : vraie PR GitHub
- **`arma_bridge/pr.py`** : si `GITHUB_REPO` est défini, `gh` connecté et un remote présent, alors
  `git push` puis `gh pr create --body-file state/out/pr-body.md`. Sinon, envoi simulé.
- **Émettre** `pr.sent`.

### Étape 16 : passer à un vrai site
Créer `targets/<site>.json` (spec §20) et adapter l'environnement (`packages`, `allowed_hosts`).
Lancer `bridge.py run --target …`, rejouer dans le dashboard, puis redéployer si le run est bon.

---

## Ordre de coupe si le temps manque

1. Bonus 15, puis 14, puis 13.
2. **Étape 10** : ne garder que la reconnexion et le dédoublonnage.
3. **Étape 8** : limiter aux lots 2.4.7, 2.1.1, 1.4.3 et 4.1.2.
4. **Étape 5**, si le navigateur du sandbox est impossible : le fallback statique.

**Ne jamais couper** :
- le dashboard en replay et le déploiement (étapes 2 et 3) ;
- **au moins un vrai run hébergé** avec audit parallèle (étape 7) ;
- l'outcome (étape 9) ;
- les livrables (étape 12).

**Filet de sécurité absolu** : si aucune session hébergée n'aboutit, le dashboard reste en ligne
sur la fixture. Le dire honnêtement au pitch et montrer les logs du smoke test.

---

## Pièges à garder en tête

Résumé de la spec §17 :
- **Stream avant envoi.**
- **Répondre à chaque `agent.custom_tool_use` immédiatement**, même pendant `running`.
- **Un seul niveau de multiagent.** Après une mise à jour d'un sous-agent, ré-appliquer le lead.
- **Fils développeur persistants** : réutiliser le même pour les relances.
- **Sorties** uniquement depuis `/mnt/session/outputs/`, avec quelques secondes de délai.
- **Budget** fixé à la création de la session.
- **Ne jamais appeler `playwright install` dans le sandbox** (réseau `limited`).
- **Développement en `claude-sonnet-5-5`** via `agent_with_overrides`.
- **Ne jamais fabriquer d'événements** pour simuler un run réel.
