# Arma : plan de construction détaillé (pour Claude Code)

> **À lire par Claude Code avant de commencer.**
> - **Spécification de référence** : `arma-spec.md`. En cas de doute, c'est elle qui fait foi.
> - **Maquette visuelle** : `reference/arma-dashboard-prototype.html`. C'est un prototype
>   fonctionnel du dashboard, données incluses ; il sert de référence pour le rendu.
> - **Méthode** : exécute les étapes **dans l'ordre**. Ne commence pas une étape avant que la
>   vérification de la précédente passe. Commite à la fin de chaque étape.
> - **Priorité** : une démo qui marche visuellement à chaque fois. Le réel est un bonus, le
>   fiable est obligatoire.

---

## Vue d'ensemble

| Jalon | Étapes | État à la fin du jalon |
|---|---|---|
| **A. Démo montrable** | 0 à 3 | Le dashboard en replay sur des données de test, **déployé sur Vercel**. Le lien live existe déjà. |
| **B. Vrais agents** | 4 à 9 | Le moteur `claude-agent-sdk` tourne sur la boutique démo et produit un vrai run enregistré. |
| **C. Démo finale** | 10 à 11 | Le dashboard rejoue le **meilleur vrai run**, redéployé, et les livrables sont prêts. |
| **D. Bonus** | 12 à 14 | Mode live (SSE), vraie PR GitHub, `--chaos` / `--resume`. |

**Budget temps indicatif** (soumission à 15:00) :

| Jalon | Durée |
|---|---|
| A | ~1h15 |
| B | ~1h45 |
| C | ~30 min |
| D | seulement s'il reste du temps |

**Parallélisation possible.** Le contrat d'événements (étape 1) découple le front du back. Dès
l'étape 1 commitée, on peut ouvrir **deux sessions Claude Code** :
- session « web » : étapes 2 et 3 ;
- session « agents » : étapes 4 à 9.

Les deux sessions ne touchent pas aux mêmes dossiers.

**Règles transverses** :
- Python 3.11+, et un venv dans `.venv`.
- Pas de framework front (HTML, CSS et JS vanilla). Pas de base de données.
- Le texte de l'UI et le contenu produit par les agents sont **en anglais**. La boutique démo
  est en français.
- Chaque étape se termine par :
  1. la vérification demandée ;
  2. `git add -A && git commit -m "<message indiqué>"`.
- Si une étape bloque plus longtemps que son budget, appliquer la section **« Si ça bloque »**
  de l'étape au lieu d'insister.

---

## Étape 0 : squelette du dépôt *(~15 min)*

**Objectif.** Avoir un dépôt propre, les dépendances installées, Chromium et axe-core
fonctionnels.

**Actions**
1. **Créer l'arborescence** de `arma-spec.md` §16 avec des fichiers vides :
   - `arma/__init__.py` ;
   - `web/` ;
   - `recordings/`, `runs/` et `state/`, ces trois dossiers étant dans `.gitignore` ;
   - `scripts/`, `deliverables/` et `reference/`.
2. **Dépendances**, dans `requirements.txt` :
   ```
   claude-agent-sdk
   playwright
   pillow
   fastapi
   uvicorn[standard]
   markdown
   ```
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. **Vendoriser axe-core** :
   ```bash
   mkdir -p vendor && cd vendor && npm pack axe-core@4.10.3 && tar xzf axe-core-*.tgz \
     && cp package/axe.min.js . && rm -rf package axe-core-*.tgz && cd ..
   ```
4. **`.gitignore`** : `.venv/`, `runs/`, `state/`, `recordings/*.jsonl`, sauf
   `!web/recordings/*.jsonl`, `__pycache__/` et `.env`.
5. **`.env.example`** avec `ANTHROPIC_API_KEY=` et `GITHUB_REPO=`. Charger `.env` dans `run.py`
   et `server.py` via une petite fonction maison, sans dépendance.
6. **`CLAUDE.md`**, une page maximum, qui contient :
   - le résumé du projet en cinq lignes ;
   - les commandes de §20 de la spec ;
   - les règles transverses ci-dessus ;
   - le lien vers `arma-spec.md` et ce plan.
7. **`scripts/smoke_browser.py`** : ouvre Chromium, charge `<html><img src=x></html>` avec
   `set_content`, injecte axe avec `page.add_script_tag(content=open('vendor/axe.min.js').read())`,
   lance `axe.run()`, puis affiche le nombre de violations.

**Vérification**
```bash
python scripts/smoke_browser.py        # doit afficher au moins une violation (image-alt)
python -c "import claude_agent_sdk; print('sdk ok')"
```

**Commit** : `chore: scaffold repo, deps, vendored axe-core`

**Si ça bloque.** Si `playwright install` échoue, essayer `python -m playwright install --with-deps chromium`.
Si npm est absent, télécharger `axe.min.js` depuis le paquet npm `axe-core` par tout autre moyen.

---

## Étape 1 : contrat d'événements + fixture *(~20 min)*

**Objectif.** Figer l'interface unique entre agents et dashboard (`arma-spec.md` §5), et produire
une fixture réaliste qui permet de construire tout le front sans agents.

**Fichiers.** `arma/events.py`, `web/events-contract.md` (copie du tableau §5 de la spec),
`scripts/make_fixture.py`, `web/recordings/fixture.jsonl`.

**`arma/events.py`**
```python
EVENT_TYPES = {"run.started","phase.changed","agent.status","subagents","log","baseline",
  "issue.detected","issue.merged","issue.status","score","batch.started","commit.created",
  "reaudit","document.written","pr.ready","pr.sent","run.finished"}

class EventBus:
    def __init__(self, path: Path): ...         # ouvre le .jsonl en append, t0 = time.monotonic()
    def emit(self, type: str, data: dict, agent: str | None = None) -> dict:
        # valide type ∈ EVENT_TYPES, ajoute "t" (secondes depuis t0, 2 décimales),
        # écrit une ligne JSON (ensure_ascii=False) + flush, pousse dans chaque asyncio.Queue abonnée
    def subscribe(self) -> asyncio.Queue: ...
    def unsubscribe(self, q): ...
```
Rendre `emit` thread-safe avec un `threading.Lock`, car des outils peuvent tourner en parallèle.

**`scripts/make_fixture.py`** génère `web/recordings/fixture.jsonl` en reproduisant **le scénario
complet** d'un run, avec des temps cohérents :
- **Données** : les **16 problèmes** de `reference/arma-dashboard-prototype.html` (tableau `ISSUES` :
  reprendre id, wcag, sévérité, source, pages, titre, impact, evidence, fix, files, statut final,
  `human`).
- **Déroulé** : identique au `buildScript()` du prototype :
  1. cartographie ;
  2. baseline ;
  3. audit avec quatre sous-auditeurs et une panne injectée relancée ;
  4. plan en lots par critère ;
  5. boucle de correction avec **le refus du testeur sur A07** (`role="button"` refusé, puis
     `<button>` validé) et **le rollback du lot 1.4.3** (diff visuel de 18 %, puis texte seul
     validé) ;
  6. commits ;
  7. re-audit ;
  8. documents du writer (`pr-body.md` et `accessibility-statement.md`, avec du vrai contenu) ;
  9. `pr.ready` ;
  10. `run.finished`.
- **Score** : émettre un événement `score` à chaque changement de statut (formule §6.3 de la
  spec). Utiliser `arma/scoring.py` s'il existe déjà, sinon une copie locale de la formule.

**Vérification**
```bash
python scripts/make_fixture.py
python - <<'EOF'
import json; ev=[json.loads(l) for l in open('web/recordings/fixture.jsonl')]
types={e['type'] for e in ev}; print(len(ev), 'events'); print(sorted(types))
assert {'issue.detected','issue.status','score','commit.created','pr.ready','document.written'} <= types
assert all(ev[i]['t']<=ev[i+1]['t'] for i in range(len(ev)-1))
print('rejects:', sum(1 for e in ev if e['type']=='issue.status' and e['data']['status']=='rejected'))
EOF
```
Le script doit afficher au moins deux rejets, et tous les types d'événements doivent être présents.

**Commit** : `feat: event contract, EventBus and realistic fixture run`

---

## Étape 2 : dashboard en mode replay *(~45 min)*

**Objectif.** Le dashboard compliance complet (`arma-spec.md` §12), piloté uniquement par les
événements, sur la fixture.

**Fichiers.** `web/index.html`, `web/styles.css`, `web/app.js`.

**Point de départ.** Reprendre `reference/arma-dashboard-prototype.html` :
- garder sa mise en page, ses styles, ses composants et ses textes ;
- remplacer son moteur de script interne (`buildScript`, `ISSUES` codés en dur) par **un réducteur
  d'événements**.

**Architecture de `app.js`**
```js
// 1. état dérivé
const initial = () => ({phase:null, phasesDone:[], agents:{}, subagents:[], logs:[], issues:{},
  order:[], score:null, baseline:null, byPrinciple:null, scoreHist:[], commits:[], docs:{},
  pr:null, prSent:null, baselineMetrics:null, reauditMetrics:null, finished:false, t:0});
function apply(state, ev) { switch(ev.type) { ... } return state; }   // pur, un case par type §5

// 2. sources
class ReplaySource { constructor(url){} async load(){} start(speed, onEvent, onEnd){} stop(){} }
class LiveSource   { constructor(){} start(onEvent, onEnd){} stop(){} }   // étape 12, laisser un stub

// 3. rendu
function render(state) { renderRail(); renderScore(); renderAgents(); renderLog(); renderRows();
  renderPR(); renderStatement(); renderButtons(); }   // appelé au plus une fois par frame (requestAnimationFrame)

// 4. démarrage
// - mode = URLSearchParams 'mode' (replay par défaut), recording = 'run' (défaut recordings/demo-run.jsonl,
//   repli recordings/fixture.jsonl si 404)
// - au chargement : appliquer TOUS les événements d'un coup → page complète au repos (dernier run)
// - "Run audit" : reset + replay temporel à la vitesse choisie (1×/2×/4×) ; devient "Stop" pendant le run
```

**Points d'attention**
- **Les numéros d'horloge** du log sont dérivés de `ev.t` (format `mm:ss`).
- **Le log** ajoute ses lignes de façon incrémentale. Il défile automatiquement seulement si
  l'utilisateur est déjà en bas.
- **Une ligne nouvellement détectée** flashe une fois.
- **L'envoi de PR en replay** est entièrement simulé côté client :
  - checklist animée étape par étape ;
  - puis la carte « Pull request #218 opened » ;
  - avec la mention « Demo workspace: no external system was contacted ».
- **Le formulaire PR** gère `submit` avec `preventDefault()`.
- **Accessibilité du dashboard**, exigée :
  - `lang="en"` et onglets ARIA avec flèches gauche/droite ;
  - lignes dépliables au clavier (Enter/Espace) avec `aria-expanded` ;
  - focus visible ;
  - contrastes AA dans les deux thèmes ;
  - `prefers-reduced-motion` respecté.
- **Responsive** : une colonne sous 980 px. La table défile dans son conteneur, et la page ne
  défile jamais horizontalement, y compris à 400 px.
- **Bouton « About »** dans la barre : ouvre un panneau (`#about`) avec le one-line pitch, le
  problème EAA en trois lignes, le schéma des agents (un `<pre>` ou un SVG simple) et le lien
  GitHub.

**Vérification**, par un script `scripts/check_web.py` (Playwright) qui :
1. sert `web/` avec `python -m http.server` sur un port libre ;
2. ouvre `/?run=recordings/fixture.jsonl` à 1400 px puis à 400 px, en clair puis en sombre
   (`color_scheme`) ;
3. vérifie qu'il n'y a **aucune erreur console** et que `document.documentElement.scrollWidth <=`
   la largeur de la fenêtre ;
4. vérifie que le score affiché vaut le dernier événement `score`, et que les compteurs
   correspondent ;
5. clique « Run audit » en vitesse 4× et attend `finished` ;
6. clique « Send PR to engineering », puis « Send pull request », et attend la carte de
   confirmation ;
7. enregistre des captures dans `state/checks/`.

Relire les captures une fois et corriger ce qui est visiblement cassé.

**Commit** : `feat: compliance dashboard driven by event replay`

**Si ça bloque.** Copier tel quel le prototype dans `web/index.html`, en remplaçant uniquement ses
données codées en dur par le chargement de la fixture. La démo reste assurée.

---

## Étape 3 : premier déploiement Vercel *(~10 min)*

**Objectif.** Obtenir le **lien live dès maintenant**, puis le mettre à jour plus tard.

**Actions**
1. `web/vercel.json` : site statique, avec `cleanUrls` et un header `Cache-Control: no-store`
   sur `/recordings/*`.
2. Copier `web/recordings/fixture.jsonl` vers `web/recordings/demo-run.jsonl`. Ce fichier sera
   remplacé à l'étape 10.
3. Lancer `cd web && npx vercel --prod`. Si la CLI n'est pas connectée, l'utilisateur fait
   `npx vercel login` une fois.
4. Noter l'URL dans `README.md` et dans `deliverables/links.md`.

**Vérification.** Ouvrir l'URL en navigation privée : le dashboard est complet au repos, et
« Run audit » rejoue.

**Commit** : `chore: deploy dashboard to Vercel (fixture replay)`

> ✅ **Jalon A atteint.** Il y a maintenant quelque chose à montrer et à soumettre.

---

## Étape 4 : boutique démo piégée *(~15 min)*

**Objectif.** Créer `demo-shop/` (« Maison Lumière ») avec exactement les défauts de
`arma-spec.md` §11.

**Fichiers.** `demo-shop/index.html`, `product.html`, `cart.html`, `checkout.html`, `styles.css`
et `img/*.svg` (des aplats colorés générés par script).

**Contraintes**
- **En-tête et pied de page identiques** sur les quatre pages. C'est ce qui rend la fusion du
  composant visible.
- **`checkout.html`** n'est atteignable que via `onclick="location.href='checkout.html'"` depuis
  le panier.
- **Contraste** : le hero a un fond `#faf7f2` et un texte `#b5b5b5`, pour inciter une première
  correction maladroite (assombrir le fond).
- **Le CTA « Ajouter au panier »** est un `div.btn` avec `onclick`.
- **Paiement** : ajouter un `<iframe title="" src="about:blank" class="card-field">` qui simule
  le champ de carte d'un prestataire. Ce sera le problème A16, escaladé.
- **Le JS reste minimal et inline.** La boutique doit fonctionner à la souris.

**Vérification**
```bash
python -m http.server 8765 -d demo-shop &
python - <<'EOF'
# axe sur les 4 pages : doit trouver color-contrast, html-has-lang, image-alt
# et NE PAS trouver les défauts « agent » (emoji buttons, placeholders, div buttons) → c'est voulu
EOF
```
Implémenter ce contrôle dans `scripts/check_demo_shop.py`, en réutilisant `arma/browser.py` dès
qu'il existe (étape 5). Pour l'instant, un script autonome suffit.

**Commit** : `feat: trapped demo storefront (Maison Lumière)`

---

## Étape 5 : outils navigateur déterministes *(~25 min)*

**Objectif.** Écrire `arma/browser.py` (spec §8, colonne « effet ») sans aucun appel à Claude.

**Fonctions (toutes async)**

| Fonction | Ce qu'elle fait |
|---|---|
| `crawl(base_url, max_pages=30)` | Parcours en largeur des `a[href]` internes + des cibles de `location.href` trouvées dans les `[onclick]` |
| `axe_audit(url, screenshot_path=None)` | Injecte axe (tags `wcag2a, wcag2aa, wcag21a, wcag21aa`) ; renvoie `{url, violations:[{rule, impact, help, wcag:["1.4.3"], nodes:[{target, html≤200, summary≤300}], count}], total_nodes}` ; capture pleine page si demandée |
| `keyboard_walk(url, max_tabs=40)` | Presse Tab en boucle ; à chaque arrêt, relève sélecteur, nom accessible, focus visible (outline ou box-shadow), présence à l'écran ; détecte le retour au premier arrêt ; liste les éléments `[onclick]`, `.btn`, `[role=button]` non focusables |
| `page_html(url, max_chars=15000)` | HTML rendu, tronqué |
| `screenshot(url, path)` | Capture pleine page |
| `visual_diff(before, after, out)` | Pillow : padder à la même taille, différence en niveaux de gris avec seuil, superposition rouge ; renvoie la part de pixels modifiés |

Chaque fonction lance son Chromium dans un `async with`, sous un `asyncio.Semaphore(4)`. La
conversion des critères se fait avec `re.fullmatch(r"wcag\d{3,4}", tag)`, ce qui donne
`"1.4.3"` ou `"1.4.10"`.

**Vérification** : `scripts/check_demo_shop.py` passe sur `arma/browser.py` et affiche :
- le crawl : **quatre pages**, checkout comprise ;
- axe sur index : `color-contrast`, `html-has-lang`, `image-alt` ;
- `keyboard_walk(product)` : aucun focus visible, et des `div.size` et `div.btn` inaccessibles ;
- `visual_diff` sur deux captures identiques : `0.0`.

**Commit** : `feat: deterministic browser tools (crawl, axe, keyboard, visual diff)`

---

## Étape 6 : état, score, contexte *(~15 min)*

**Fichiers.** `arma/state.py`, `arma/scoring.py`, `tests/test_state.py`.

**`state.py`** reprend `Store` de la spec §6 :
- JSON dans `state/state.json` ;
- écritures atomiques (`.tmp` puis `os.replace`) sous `threading.RLock` ;
- `phases_done`, `pages`, `issues`, `batches`, `baseline`, `final`, `cost_usd`.

Méthodes :
- `add_page` ;
- `add_issue(**fields)`, qui renvoie `(issue, merged: bool)` avec le dédoublonnage de la spec ;
- `set_status(id, status, by, note)` ;
- `issues(status=None)`, `issue(id)` ;
- `phase_done`, `start_phase`, `finish_phase`.

**Les statuts sont des constantes**, jamais des chaînes libres.

**`scoring.py`**
```python
PEN = {"critical":10, "major":6, "minor":3}
def compute(issues, frozen_total=None) -> dict:
    # returns {"value": int, "by_principle": {"P":%,"O":%,"U":%,"R":%}, "eaa": "non_compliant|partially_compliant|compliant_automated"}
```
- **Gel du total** : `frozen_total` (pénalité totale × 1.6) est enregistré dans le store à la fin
  de l'audit.
- **Principe** : on le dérive du critère (préfixe 1 = P, 2 = O, 3 = U, 4 = R).

**Vérification** : `python -m pytest -q tests/`. Les tests couvrent :
- la fusion de doublons ;
- l'atomicité (relecture après écriture) ;
- un score de départ dans la zone 30 à 45 pour les seize problèmes de la fixture ;
- un score de 95 environ avec A04 et A16 ouverts.

**Commit** : `feat: persistent store and scoring`

---

## Étape 7 : outils MCP, agents, orchestrateur (cartographie et audit) *(~35 min)*

**Objectif.** Faire tourner les **premiers vrais agents** : la cartographie, puis l'audit avec des
sous-agents parallèles, avec émission des événements.

**Fichiers.** `arma/tools.py`, `arma/agents.py`, `arma/orchestrator.py`, `run.py`.

**`tools.py`**
- **Contexte** : `CTX` contient `store`, `bus`, `base_url`, `site_dir`, `work_dir`, `chaos`,
  `chaos_fired`, `batch_verdict` et `current_agent`.
- **Outils** : les treize outils de la spec §8, avec `@tool(name, description, schema)`.
- **Retours** : `_ok(payload)` et `_err(msg)` (avec `is_error: True`). Pas d'exception qui
  remonte.
- **Effets** : `add_issue` émet `issue.detected` ou `issue.merged`. `register_page` émet un
  `log`.
- **Exports** : `server()` (`create_sdk_mcp_server("a11y", ...)`) et `t(*names)`, qui renvoie
  les noms `mcp__a11y__*`.

**`agents.py`**
- **Prompts** : ceux de la spec §7, en anglais, avec le préambule commun.
- **Outils** : une liste par rôle.
- **`audit_subagents(model)`** renvoie
  `{"page-auditor": AgentDefinition(description, prompt, tools, model=model or "inherit", background=False, maxTurns=40)}`.
  Les champs de `AgentDefinition` sont en camelCase.

**`orchestrator.py`** (seulement les phases `crawl`, `baseline`, `audit` à cette étape)
- **`run_agent(role, system, prompt, allowed, *, cwd, write_root, subagents, max_turns, retries=1)`** :
  1. construit `ClaudeAgentOptions` comme dans la spec §10 ;
  2. le hook `guard` journalise chaque appel d'outil (`log` kind `tool`, avec l'agent issu de
     `input_data.get("agent_type") or role`) et refuse les écritures hors `write_root` ;
  3. dans la boucle `async for msg in query(...)` :
     - `TextBlock` → `log` kind `msg` ;
     - `ToolUseBlock` nommé `Agent` → `log` « dispatching sub-agent » et mise à jour `subagents` ;
     - `ResultMessage` → cumul du coût, et exception si `is_error` ;
  4. sur exception : log `err`, puis une seule relance avec le préfixe « RESUMING… ».
- **Émissions** :
  - `agent.status` (working, puis done) autour de chaque session ;
  - `phase.changed` à chaque phase ;
  - `run.started` au début.
- **`phase_baseline`** :
  1. préparation git du site : init si besoin, refus d'un dépôt sale, branche
     `a11y/eaa-remediation-<date>` ;
  2. pour chaque page, en parallèle : `axe_audit` + `keyboard_walk` + capture `before.png` ;
  3. émet l'événement `baseline` agrégé.
- **Fin de `phase_audit`** : gel du score, émission de `score`, puis log de synthèse (total,
  invisibles pour axe, bloquants du tunnel).

**`run.py`**
- **Options** : `--demo`, `--site`, `--url`, `--resume`, `--model`, `--chaos`, `--budget`,
  `--until <phase>` (pour s'arrêter après une phase).
- **En `--demo`** :
  1. copie `demo-shop/` vers `runs/demo-shop/` ;
  2. sert ce dossier en thread sur 8765 (`ThreadingHTTPServer`, handler sans cache et
     silencieux) ;
  3. ouvre l'EventBus sur `recordings/run-<YYYYmmdd-HHMM>.jsonl`.

**Vérification**
```bash
python run.py --demo --model sonnet --until audit
```
- `state/state.json` contient quatre pages et **au moins douze problèmes**, dont une majorité en
  `source != "axe"`.
- Le JSONL contient des `issue.detected` et un `score`.
- Les logs montrent des sous-agents parallèles (étiquettes `auditor·<page>`).
- **Ouvrir ce run dans le dashboard** :
  `python -m http.server -d web 8080` puis copier le JSONL dans `web/recordings/`, et ouvrir
  `/?run=recordings/<fichier>`. Le rendu doit être correct.

**Commit** : `feat: real agent team for mapping and audit (claude-agent-sdk)`

**Si ça bloque.**
- **Si les sous-agents ne se lancent pas en parallèle** : remplacer le lead-auditor par une
  boucle Python qui lance N sessions `page-auditor` avec `asyncio.gather`. La démo est identique
  et le parallélisme reste réel.
- **Si le coût ou la durée explosent** : `max_turns` plus bas et `--model sonnet`.

---

## Étape 8 : boucle de correction *(~40 min)*

**Objectif.** Implémenter le cœur de la démo : développeur ⇄ testeur, rollback, commits et
escalade (spec §9.2).

**À ajouter dans `orchestrator.py`**
- **`phase_plan`** : un lot par critère, tri par sévérité maximale puis par critère ; émet un
  `log` par lot.
- **`phase_fix` → `_fix_batch(batch)`** : exactement le pseudo-code §9.2, plus :
  - au début de chaque tentative, émettre `batch.started` et passer les problèmes en `fixing`
    (`issue.status`, avec `attempt`) ;
  - après le développeur, pour chaque problème en `fixed_pending` : calculer `fix_diff` avec
    `git diff -- <files>` et l'enregistrer dans l'issue ;
  - émettre `issue.status` à **chaque** changement (y compris ceux faits par les outils
    `mark_fixed`, `verdict` et `cannot_fix`) et `score` après chaque changement ;
  - rollback : `git checkout -- . && git clean -fd`, log kind `rollback` ;
  - commit : `git -c user.name=arma-agent -c user.email=arma@localhost commit -m "fix(a11y): WCAG <crit> — <titres>"` ;
    émettre `commit.created {sha, criterion, message, files}`.
- **Prompt du développeur** : le lot en JSON, plus une section
  `PREVIOUS TESTER REJECTIONS (fix exactly these)` construite à partir des notes `rejected` de
  l'historique.
- **Prompt du testeur** : les problèmes déclarés corrigés (avec `fix_note` et `files`) et les
  pages concernées. Le testeur ne voit pas le diff, ce qui garantit son indépendance.
- **`compare_with_baseline`** : comparer à `baseline[url]` (clés `(rule, target)`) ; capture
  `after.png` ; `visual_diff`.

**Vérification**
1. **Sur un seul lot d'abord** : ajouter `--only-batch 2.1.1` et lancer
   `python run.py --demo --model sonnet --resume --only-batch 2.1.1`.
   - Les statuts doivent changer ;
   - un commit doit apparaître dans `runs/demo-shop` (`git log --oneline`) ;
   - le diff doit être lisible.
2. **Puis tous les lots** : `python run.py --demo --model sonnet --until fix`.
   - Au moins dix problèmes `validated`, et A04 et A16 en `needs_human` ;
   - le score monte ;
   - un commit par critère.
3. **Vérifier dans le dashboard** (replay du nouveau JSONL) que :
   - les pills changent ;
   - les lignes dépliées montrent le diff et la piste de vérification ;
   - les commits apparaissent dans le log.

**Commit** : `feat: developer/tester remediation loop with rollback and escalation`

**Si ça bloque.**
- **Si le testeur ne rend pas de verdict** : l'orchestrateur marque `rejected` (« no verdict »)
  et continue. C'est déjà prévu dans la spec.
- **Si un lot boucle sans fin** : le plafond de trois tentatives escalade le problème.
- **Si aucun refus n'apparaît naturellement** : renforcer la consigne du testeur. Un
  `role="button"` sur un `div` non focusable doit être refusé, et un diff visuel supérieur à 2 %
  doit déclencher la lecture de la capture et un refus si le fond a changé. Puis relancer.
  **Ne jamais fabriquer d'événements.**

---

## Étape 9 : re-audit, documents, PR prête *(~20 min)*

**À ajouter**
- **`phase_reaudit`** : mesures finales sur toutes les pages, puis événement `reaudit`.
- **`phase_report`** :
  1. session `writer` (écriture limitée à `state/out/`) qui produit `pr-body.md` et
     `accessibility-statement.md` à partir d'un JSON de synthèse (issues, statuts, commits,
     métriques avant/après) ;
  2. émettre `document.written {name, path, content}` pour chaque fichier ;
  3. **repli** : si le writer échoue, générer les deux documents depuis un template Python, pour
     que la démo ne soit jamais bloquée.
- **`phase_pr`** :
  1. `git diff base..branch > state/out/changes.diff` ;
  2. `git format-patch` dans `state/out/patches/` ;
  3. émettre `pr.ready {repo, branch, base, commits, files, body}` ;
  4. émettre `run.finished {cost_usd, duration_s}`.

**Vérification**
```bash
python run.py --demo --model sonnet           # run complet
```
- Le JSONL se termine par `pr.ready` et `run.finished`.
- `state/out/` contient les deux documents, le diff et les patchs.
- La déclaration indique « partially compliant » et contient des champs `[TO COMPLETE]`.
- Dans le dashboard, les onglets « Pull request » et « Accessibility statement » sont remplis
  avec le **vrai** contenu.

**Commit** : `feat: re-audit, writer documents, PR-ready output`

> ✅ **Jalon B atteint.** Un vrai run complet est enregistré.

---

## Étape 10 : choisir le meilleur run et redéployer *(~15 min)*

**`scripts/pick_demo_run.py <run.jsonl>`**
- **Contrôles** : le fichier contient `pr.ready`, au moins un `issue.status` en `rejected` suivi
  d'un `validated` sur le même id, au moins un `log` kind `rollback`, et au moins un `subagents`.
  Afficher OK ou KO pour chaque contrôle.
- **Compression des temps morts** : chaque écart entre deux événements consécutifs est plafonné
  à 4 secondes. L'ordre est conservé et les `t` sont recalculés.
- **Sortie** : `web/recordings/demo-run.jsonl`.

**Actions**
1. Lancer deux ou trois runs complets si nécessaire, puis garder celui qui passe tous les
   contrôles. Utiliser le modèle par défaut pour le run final si le budget le permet.
2. Relancer `scripts/check_web.py` sur `demo-run.jsonl`.
3. Redéployer avec `cd web && npx vercel --prod`.

**Vérification.** Sur l'URL Vercel, en navigation privée :
- « Run audit » rejoue le **vrai** run ;
- un refus, un rollback et des commits sont visibles ;
- la PR et la déclaration sont présentes.

**Commit** : `chore: ship best real run as demo replay`

---

## Étape 11 : livrables *(~15 min)*

**`scripts/export_logs.py <run.jsonl>`** écrit `deliverables/agent-logs.txt`, avec :
- un en-tête : projet, date, site, modèle, coût, durée ;
- puis une ligne par événement `log` au format `mm:ss [agent] texte` ;
- et des séparateurs lisibles aux `phase.changed`.

**`deliverables/agent-design.txt`**, une page maximum, en anglais, en texte brut :
1. **Overview** : le problème et ce que fait l'équipe.
2. **Agents and roles** : cartographer, lead-auditor + parallel page-auditors, developer, tester,
   writer, et le Python orchestrator.
3. **Handoffs** : un état partagé, seulement via des outils typés ; les transitions de statut.
4. **Plan → act → verify loop** : lots par critère WCAG, testeur indépendant, rejets avec
   feedback actionnable, rollback en cas de régression, plafond de trois tentatives, escalade
   humaine.
5. **Error recovery** : relances de session, checkpoints de phase, `--resume`, injection de panne,
   replis déterministes.
6. **Governance** : outils restreints par rôle, `dontAsk`, hook de périmètre d'écriture,
   journal d'audit complet ; jamais d'affirmation de conformité totale.
7. **Stack** : Claude Agent SDK (Python), outils MCP en processus, Playwright + axe-core, git,
   dashboard statique piloté par des événements.

**`deliverables/links.md`** : l'URL Vercel (live link), l'URL `#about` (pitch), le dépôt GitHub,
et un emplacement pour le lien des slides.

**MP4.** Une capture d'écran du dashboard en replay 2× sur l'URL Vercel, faite par l'utilisateur
(enregistreur d'écran du système).

**Commit** : `docs: hackathon deliverables (agent design, logs, links)`

> ✅ **Jalon C atteint. Prêt à soumettre.**

---

## Bonus : seulement s'il reste du temps, dans cet ordre

### Étape 12 : mode live (SSE) *(~25 min)*
- **`server.py` (FastAPI)** :
  - `GET /api/state` ;
  - `GET /api/events` (SSE : `StreamingResponse` qui lit une `asyncio.Queue` de l'EventBus,
    préfixe `data: `, keep-alive) ;
  - `POST /api/run` (lance `Orchestrator.run()` en tâche de fond si aucun run en cours ; sinon
    409) ;
  - `POST /api/pr` (étape 13) ;
  - statique `web/` sur `/`.
- **`LiveSource`** dans `app.js` : `EventSource('/api/events')`.
  - Si `/api/state` répond, le mode par défaut devient `live`.
  - En cas d'erreur, bascule automatique en replay avec un toast discret.
- **Vérification** : `uvicorn server:app --port 8000`, ouvrir `/?mode=live`, cliquer
  « Run audit » et voir le run réel défiler.

### Étape 13 : vraie PR GitHub *(~15 min)*
- **`arma/pr.py`** :
  - si `GITHUB_REPO` est défini, `gh auth status` est OK et un remote `origin` existe : `git push`,
    puis `gh pr create --title "a11y: EAA remediation, WCAG 2.1 AA" --body-file <corps> --head <branch>`,
    puis `--reviewer` si fourni ;
  - sinon, envoi simulé ;
  - le corps est le `pr-body.md`, précédé du message compliance et de « Approved by compliance ».
- **`POST /api/pr`** appelle `pr.py`, émet `pr.sent {number, url, notified, simulated}` et renvoie
  le résultat. Slack, Jira et email restent simulés et sont affichés comme tels.

### Étape 14 : `--chaos` et `--resume`
- **`--chaos`** : la première erreur `audit_page` est injectée, et le log l'étiquette
  « Injected fault ».
- **`--resume`** : relit `state.json`, saute les phases faites et annule les modifications non
  commitées du lot en cours.
- **Vérification** : Ctrl-C en pleine phase `fix`, puis `--resume` repart au bon lot.

---

## Ordre de coupe si le temps manque

1. Bonus 14, puis 13, puis 12.
2. L'étape 9 réduite : documents générés par template plutôt que par le writer.
3. L'étape 8 limitée aux trois ou quatre lots les plus visibles (2.4.7, 2.1.1, 1.4.3, 4.1.2).

**Ne jamais couper** :
- **le dashboard (étape 2) et le déploiement (étape 3)** ;
- **au moins un vrai run** avec cartographie et audit (étape 7) ;
- **les livrables** (étape 11).

---

## Pièges à garder en tête

Rappel de la spec §18 :
- **`AgentDefinition` est en camelCase.** Mettre `background=False` sur le sous-auditeur.
- **`allowed_tools` auto-approuve sans restreindre.** La restriction passe par `tools=`,
  `disallowed_tools=` et `permission_mode="dontAsk"`.
- **Les outils MCP des sous-agents** doivent aussi être dans `allowed_tools` de la session parente.
- **Ne jamais faire `break`** dans `async for … in query(...)`.
- **`setting_sources=[]`**.
- **Les outils renvoient `is_error: True`** plutôt que de lever une exception.
- **Le `cwd` du développeur** est le dépôt du site. Le hook refuse toute écriture ailleurs.
- **Le coût** : `--model sonnet` pour les répétitions. Surveiller `cost_usd` dans `state.json`.
