# Arma — spécification projet (pour Claude Code)

> Ce document décrit le projet de bout en bout. Claude Code doit le lire en entier avant
> d'écrire du code, puis suivre le **plan de construction (§17)** dans l'ordre.
>
> **Priorité absolue : une démo qui marche visuellement, à chaque fois.** On vise l'efficacité,
> pas l'exhaustivité. Tout ce qui est réel est un bonus ; tout ce qui est montré doit être fiable.

---

## 0. En bref

**Arma** est un dashboard pour les **équipes compliance** des e-commerçants européens. Une
équipe d'agents Claude, construite avec `claude-agent-sdk`, fait quatre choses :
1. elle audite la boutique contre WCAG 2.1 AA, la norme technique derrière l'**European
   Accessibility Act (EAA)** ;
2. elle corrige les problèmes **dans le code source** ;
3. elle fait **vérifier chaque correctif par un agent testeur indépendant** ;
4. elle prépare une pull request que l'équipe compliance **envoie en un clic à l'équipe technique**.

**One-line pitch** : *Arma gives compliance teams an AI agent team that audits, fixes and
verifies their store's accessibility, then hands engineering a ready-to-merge pull request.*

---

## 1. Contexte : hackathon Accel AI Innovate

**Challenge.** *Future Founders: Long Running Agents — From Task to Workflow* : des agents qui
tournent longtemps et/ou travaillent en équipe, sur un vrai problème client, construits en une
journée.

**Critères du jury et réponse de Arma :**

| Critère | Ce que Arma montre |
|---|---|
| Real output | Une branche git avec un commit par critère WCAG, une PR, un rapport et une déclaration d'accessibilité |
| Agent design & architecture | Planification par lots, passations explicites via un état partagé, **refus du testeur → nouvelle tentative**, rollback, escalade humaine, reprise après crash |
| Business viability | Obligation légale (EAA), procès en cours contre la grande distribution française, overlays sanctionnés par la FTC |
| Demo & pitch | Dashboard avec logs d'agents en direct + mode replay d'un vrai run enregistré |

**Livrables à soumettre :**

| Livrable | Format | Comment on le produit |
|---|---|---|
| Project name and one-line pitch | Hosted URL | Section « About » de la landing du dashboard déployé (§15) |
| Live link to the product | Hosted URL | Dashboard déployé sur **Vercel** en mode replay (§14, §15) |
| Short description of your agent design | TXT | `deliverables/agent-design.txt`, généré à partir de §6 à §9 |
| Agent logs or a recording of a run | TXT / MP4 | `recordings/run-<date>.jsonl` → export `deliverables/agent-logs.txt` + capture écran MP4 |
| Pitch slides link | Hosted URL | Slides séparées (hors périmètre code) |

**Ressources du hackathon :**
- **Claude API credits** : la clé `ANTHROPIC_API_KEY`, indispensable.
- **Vercel** : héberger le dashboard, pour le lien live.
- **Supabase** : optionnel, non requis.
- Les autres packs sont hors périmètre.

---

## 2. Utilisateur, problème, proposition de valeur

- **Utilisateur principal : responsable compliance / juridique** d'une PME ou ETI e-commerce
  européenne.
  - Il n'est pas développeur.
  - Il doit prouver la conformité EAA, publier une déclaration d'accessibilité et faire corriger
    les écarts par l'équipe technique.
- **Utilisateur secondaire : l'équipe technique**, qui reçoit une PR propre, découpée par
  critère, déjà vérifiée.
- **Le problème.**
  - Les audits manuels sont chers et lents.
  - Les overlays JavaScript ne corrigent rien (amende FTC contre accessiBe en 2025).
  - Les scanners automatiques ne voient qu'une partie des problèmes.
  - La compliance ne sait pas traduire un rapport en tickets techniques.
- **La valeur.**
  - Un score et un statut EAA compréhensibles par la compliance.
  - Des spécifications précises par problème : critère, clause EN 301 549, impact, preuve,
    correctif, vérification.
  - Une PR prête à merger envoyée à la tech.
  - Une déclaration d'accessibilité pré-remplie.
- **Business model** :
  - audit et correctifs facturés à l'acte ;
  - abonnement de surveillance continue, avec un re-audit à chaque déploiement ;
  - offre marque blanche pour les agences web.

---

## 3. Périmètre

### MVP (obligatoire pour la démo)
1. Le dashboard compliance (§12), en **mode replay**, fiable à 100 %.
2. Le moteur d'agents réel (§6 à §9) sur la **boutique démo piégée** (§11) :
   - il produit un vrai run enregistré en JSONL ;
   - il crée une vraie branche git avec de vrais commits.
3. Le **mode live** : le dashboard branché en direct sur un run en cours via SSE.
4. Le bouton « Send PR to engineering » : vraie PR si `gh` et un remote sont configurés, sinon
   envoi simulé (§13).
5. Le déploiement Vercel et les fichiers livrables.

### Nice-to-have (seulement si le MVP est terminé)
- Rapport HTML exportable.
- Injection de panne `--chaos` (§9.4).
- Reprise `--resume` après un Ctrl-C.
- Audit d'une URL réelle saisie dans le dashboard, en lecture seule, sans correctifs.

### Hors périmètre
- Authentification et multi-tenant.
- Base de données (le JSON sur disque suffit).
- Frameworks front (pas de React : du HTML, du CSS et du JS vanilla).
- Sites autres que du HTML/CSS/JS statique.

### Règle d'arbitrage
En cas de conflit entre « réel » et « fiable à l'écran », **le fiable gagne**.

Le replay d'un vrai run enregistré est une démo honnête : on montre ce que les agents ont
réellement fait, accéléré. Un badge **« Demo workspace »** reste visible en permanence dans le
dashboard.

---

## 4. Architecture

```
┌────────────────────────── backend Python ──────────────────────────┐
│                                                                     │
│  run.py ──► Orchestrator (machine à états persistée)                │
│               │  lance des sessions claude-agent-sdk (query())      │
│               │  avec outils MCP en processus + hooks               │
│               ▼                                                     │
│     Agents : cartographer · lead-auditor (+ page-auditors ×N)       │
│              developer · tester · writer                            │
│               │ (outils MCP) ──► Store (state.json)                 │
│               ▼                                                     │
│     EventBus.emit(event) ──► recordings/run-<date>.jsonl            │
│                          └─► abonnés SSE                            │
│                                                                     │
│  server.py (FastAPI)                                                │
│     GET  /api/events      SSE : flux d'événements du run courant    │
│     GET  /api/state       snapshot (state.json)                     │
│     POST /api/run         lance un run (démo)                       │
│     POST /api/pr          envoie la PR (réelle ou simulée)          │
│     GET  /                sert web/ (dashboard statique)            │
└─────────────────────────────────────────────────────────────────────┘
                     ▲ live (SSE)              ▲ replay (fichier)
┌──────────────────────────── web/ (statique) ───────────────────────┐
│  dashboard : index.html + app.js + styles.css                       │
│  source d'événements = LiveSource (SSE) | ReplaySource (JSONL)      │
│  ?mode=replay&speed=2 par défaut sur Vercel                         │
└─────────────────────────────────────────────────────────────────────┘
```

**Décision clé.** Le dashboard **ne connaît que des événements** (§5) :
- le moteur d'agents les émet ;
- le replay les relit avec leurs horodatages.

Live et replay donnent exactement le même rendu. Le déploiement Vercel n'a besoin d'aucun backend :
c'est `web/` plus un fichier `recordings/demo-run.jsonl`.

---

## 5. Contrat d'événements (l'interface unique backend ↔ UI)

Chaque ligne de `run-<date>.jsonl` est un événement :

```jsonc
{ "t": 12.4,            // secondes depuis le début du run
  "type": "issue.detected",
  "agent": "auditor·product",   // optionnel : qui l'a produit
  "data": { ... } }
```

| `type` | `data` | Effet dans l'UI |
|---|---|---|
| `run.started` | `{site, repo, branch}` | Réinitialise l'état, horloge à zéro |
| `phase.changed` | `{phase}` parmi `crawl, baseline, audit, plan, fix, reaudit, report, pr` | Rail des phases |
| `agent.status` | `{agent, status: idle\|working\|done, activity}` | Panneau « Agent team » |
| `subagents` | `{agent:"auditors", states:["working","done",…]}` | Points des sous-auditeurs parallèles |
| `log` | `{text, kind: msg\|tool\|ok\|err\|reject\|rollback\|commit\|phase}` | Journal en direct |
| `baseline` | `{axe_violations, unreachable, focus_visible:[a,b]}` | Indicateurs avant |
| `issue.detected` | objet issue complet (§6.1) | Ligne dans Findings (surlignée), KPIs |
| `issue.merged` | `{id, page}` | Ajoute une page à un problème existant |
| `issue.status` | `{id, status, by, note, attempt}` | Pill de statut + piste de vérification |
| `score` | `{value, baseline, by_principle:{P,O,U,R}}` | Jauge, barres, sparkline |
| `batch.started` | `{id, criterion, issue_ids, attempt}` | Log de type phase |
| `commit.created` | `{sha, criterion, message, files}` | Log vert + liste de commits |
| `reaudit` | `{axe_violations, unreachable, focus_visible:[a,b]}` | Indicateurs après |
| `document.written` | `{name, path, content}` | Onglet Statement / contenu de la PR |
| `pr.ready` | `{repo, branch, base, commits, files, body}` | Active « Send PR to engineering » |
| `pr.sent` | `{number, url, notified:[…], simulated:bool}` | Carte de confirmation |
| `run.finished` | `{cost_usd, duration_s}` | Horloge « Last run » |

Règles :
- **L'UI est une pure fonction de la séquence d'événements** : `state = events.reduce(apply)`.
  Pas de logique métier côté UI, à l'exception du recalcul d'affichage.
- **Le score est calculé côté backend** et émis via `score`. L'UI ne fait que l'afficher.
- Les événements sont **append-only** : on ne réécrit jamais un fichier enregistré.

---

## 6. Modèle de données

### 6.1 Issue
```jsonc
{
  "id": "A07",
  "wcag": "2.1.1", "criterion_name": "Keyboard", "level": "A",
  "principle": "O",                       // P | O | U | R
  "en301549": "9.2.1.1",                  // = "9." + wcag
  "title": "“Add to bag” cannot be reached with the keyboard",
  "impact": "Keyboard and switch users cannot add anything to their bag.",
  "evidence": "<div class=\"btn\" onclick=\"addToCart()\">Add to bag</div>",
  "severity": "critical",                 // critical | major | minor
  "source": "axe" | "keyboard" | "agent", // agent = jugement, invisible pour les scanners
  "selector": "div.btn", "rule": "",
  "pages": ["/products/leather-sneakers"],
  "status": "detected",                   // detected | fixing | fixed_pending | rejected | validated | needs_human
  "attempts": 0, "files": [], "fix_diff": "", "fix_note": "",
  "history": [{"t": 0, "status": "detected", "by": "auditor·product", "note": "…"}],
  "human_action": ""                      // si needs_human : quoi faire et par qui
}
```

**Dédoublonnage dans `add_issue`** : même `wcag` + même `selector` + même règle (ou même titre)
signifie le même composant. On ajoute seulement la page, et on émet `issue.merged`.

### 6.2 Batch
`{id, criterion, issue_ids, status: todo|in_progress|done|escalated, attempt, commits:[sha]}`

### 6.3 Score
- **Pénalités par sévérité** : critical 10, major 6, minor 3.
- **Score** : `round(100 × (1 − pénalité_ouverte / (pénalité_totale_détectée × 1.6)))`. Un
  problème est « ouvert » tant qu'il n'est pas `validated`.
- **Le multiplicateur** garde le score de départ dans une zone crédible. On le **fige** une fois
  l'audit terminé, pour que le score ne bouge que grâce aux correctifs.
- **Par principe (P, O, U, R)** : part de la pénalité résolue.
- **Statut EAA** :
  - au moins un problème ouvert non escaladé : `Non-compliant` ;
  - tous résolus sauf des `needs_human` : `Partially compliant` ;
  - tous `validated` : `Compliant (automated scope)`.
  - On n'affiche **jamais** « Fully compliant ».
- **Seuil cible** : affiché sur la sparkline (85).

---

## 7. Les agents

Toutes les sessions passent par `claude_agent_sdk.query()`.

Préambule commun à tous les prompts :
- tu fais partie d'une équipe ;
- tout passe par les outils ;
- erreur transitoire : diagnostiquer en une phrase, relancer une fois, puis continuer ;
- messages courts, car ils sont affichés au jury ;
- contenu produit en **anglais**.

| Agent | Session | Outils | Mission |
|---|---|---|---|
| **cartographer** | une session | `crawl_site`, `register_page`, `list_pages` | Crawler, identifier les gabarits (home, category, product, cart, checkout…), deux pages max par gabarit, vérifier que le tunnel d'achat est couvert |
| **lead-auditor** | une session avec sous-agents | `Agent`, `list_pages`, `list_issues` | Lancer un `page-auditor` **par page, tous dans le même message** (parallèle), vérifier la couverture, relancer une page manquante, résumer |
| **page-auditor** | `AgentDefinition` (sous-agent) | `audit_page`, `keyboard_walk`, `get_page_html`, `add_issue` | Couche scanner (axe) + couche clavier + **couche jugement** (§7.1) ; description = impact concret + preuve |
| **developer** | une session par tentative de lot, `cwd` = dépôt du site | `Read`, `Edit`, `Glob`, `Grep`, `mark_fixed`, `cannot_fix`, `list_issues` | Corriger la **source partagée** ; HTML natif d'abord ; contraste = la couleur conforme **la plus proche** de la marque ; ne jamais inventer de contenu (sinon `cannot_fix`) ; traiter exactement les refus transmis |
| **tester** | une session par tentative, **sans droit d'écriture** | `Read`, `compare_with_baseline`, `keyboard_walk`, `get_page_html`, `verdict`, `batch_verdict`, `list_issues` | Indépendant (n'a pas vu le travail du dev) ; ouvrir la capture diff si plus de 2 % de pixels changent ; refuser les correctifs cosmétiques ; raisons **actionnables** ; refuser le lot seulement en cas de régression |
| **writer** | une session, écriture limitée à `out/` | `Write`, `Read` | `pr-body.md` (résumé, une section par critère, « Needs human review ») et `accessibility-statement.md` (partially compliant, contenus non accessibles, méthode, champs `[TO COMPLETE]`) |

### 7.1 Couche « jugement » de l'auditeur (le différenciateur)

L'auditeur doit chercher au minimum ces problèmes, que les scanners ne voient pas :

| Problème | Critère WCAG |
|---|---|
| Bouton-icône nommé par un emoji ou un symbole | 4.1.2 |
| `alt` présent mais inutile (« image », nom de fichier) | 1.1.1 |
| Lien ambigu hors contexte (« Learn more ») | 2.4.4 |
| Placeholder utilisé à la place d'un label | 3.3.2 / 1.3.1 |
| Erreur signalée par la couleur seule | 1.4.1 / 3.3.1 |
| Pas de `h1` ou niveaux de titres sautés | 1.3.1 |
| Titre de page vague | 2.4.2 |
| `div` cliquables ou sélecteurs personnalisés sans rôle ni état | 2.1.1 / 4.1.2 |
| Focus supprimé (`outline: none`) | 2.4.7 |

Le KPI **« missed by automated scanners »** = nombre de problèmes dont `source != "axe"`. C'est
l'argument central du pitch.

---

## 8. Outils MCP

Un serveur en processus : `create_sdk_mcp_server(name="a11y", tools=[...])`. Les noms vus par
les agents sont de la forme `mcp__a11y__<outil>`.

Un objet de contexte global donne accès :
- au Store et à l'EventBus ;
- à `base_url`, au dossier du site et au dossier de travail ;
- au flag chaos et au verdict de lot courant.

Chaque outil qui modifie l'état **émet l'événement correspondant**.

| Outil | Entrée | Sortie / effet |
|---|---|---|
| `crawl_site` | `max_pages` | Pages internes en largeur d'abord (Playwright), y compris la navigation cachée dans `onclick="location.href=…"` |
| `register_page` | `url, title, template` | Store |
| `list_pages` | — | Pages |
| `audit_page` | `url` | Violations axe-core (tags `wcag2a, wcag2aa, wcag21a, wcag21aa`), critère normalisé `wcag143 → 1.4.3`, nœuds tronqués |
| `keyboard_walk` | `url` | Ordre de tabulation (sélecteur, nom, focus visible ?), éléments cliquables non focusables, cycle complet ou non |
| `get_page_html` | `url` | HTML rendu, tronqué |
| `add_issue` | champs de §6.1 | Id (fusion si doublon) ; émet `issue.detected` ou `issue.merged` |
| `list_issues` | `status?` | Problèmes |
| `mark_fixed` | `issue_id, files, explanation` | → `fixed_pending` ; l'orchestrateur calcule `fix_diff` via `git diff` |
| `cannot_fix` | `issue_id, reason` | → `needs_human` + `human_action` |
| `compare_with_baseline` | `url` | `resolved`, `still_failing`, `new_violations_regressions`, `changed_pixels_ratio`, chemins des captures avant/après/diff |
| `verdict` | `issue_id, accepted, reason` | → `validated` / `rejected` |
| `batch_verdict` | `accepted, reason` | Verdict de lot (rollback si refus) |

Règles :
- **Les erreurs ne lèvent pas d'exception.** Elles renvoient
  `{"content":[{"type":"text","text":"<message actionnable>"}], "is_error": True}`.
- **Chaque outil navigateur lance son propre Chromium**, avec un sémaphore qui limite le nombre
  de navigateurs simultanés.
- **axe-core est vendorisé** dans `vendor/axe.min.js` et injecté avec `page.add_script_tag(content=…)`.
  Pas de CDN au runtime.
- **Le diff visuel** (Pillow) renvoie la part des pixels modifiés et une image de superposition.

---

## 9. Orchestration

### 9.1 Machine à états persistée

```
crawl → baseline → audit → plan → fix → reaudit → report → pr
```

| Phase | Ce qui se passe |
|---|---|
| `crawl` | Session cartographer. Repli : crawl brut en Python si aucune page n'est enregistrée |
| `baseline` | Python, sans agent. Préparation git (init si besoin, refus d'un dépôt sale, branche `a11y/eaa-remediation-<date>`), puis pour chaque page : axe + clavier + capture `before.png`. Émet `baseline` |
| `audit` | Session lead-auditor avec sous-agents parallèles. Puis calcul et gel du score de départ, émission de `score` |
| `plan` | Python. Un lot par critère WCAG, trié par sévérité max (purchase blockers first) |
| `fix` | Boucle §9.2 |
| `reaudit` | Python. Re-mesure toutes les pages, émet `reaudit` |
| `report` | Session writer, puis `document.written` ; rapport HTML optionnel |
| `pr` | Python. `git diff base..branch`, `format-patch` ; émet `pr.ready` avec le body |

Chaque phase terminée est ajoutée à `phases_done` dans `state.json`.

### 9.2 Boucle de correction par lot (le cœur de la démo)

```
pour chaque lot non terminé :
  tant que attempt < 3 :
    todo = problèmes du lot en detected | rejected | fixing | fixed_pending ; si vide → sortir
    attempt += 1 ; émettre batch.started ; statut → fixing
    DEVELOPER (prompt = lot en JSON + « PREVIOUS TESTER REJECTIONS » tirées de l'historique)
      → mark_fixed | cannot_fix
    resté en fixing → rejected (« not handled by developer »)
    TESTER → verdict par problème + batch_verdict
    resté en fixed_pending → rejected (« no verdict »)
    si lot refusé : git checkout -- . && git clean -fd ; émettre log rollback ; tous → rejected ; continuer
    sinon : si des problèmes sont validés et le dépôt modifié → git commit
            "fix(a11y): WCAG <crit> — <titres>" ; émettre commit.created ; recalculer score
            (les refusés repartent pour la tentative suivante, sur le code déjà commité)
  restants → needs_human ; lot → done | escalated
```

C'est **ce que le jury doit voir** :
1. un refus du testeur, avec une raison précise ;
2. le développeur qui corrige exactement ça ;
3. la validation ;
4. le commit ;
5. et au moins une fois, un rollback pour régression visuelle.

### 9.3 Reprise
- **Après une phase** : `--resume` saute les phases faites.
- **En plein lot** : annule les modifications non commitées, puis rejoue la tentative.
- **Session d'agent en échec** : l'exception est journalisée, puis une relance unique avec le
  préfixe « RESUMING after an interruption: check state via tools, finish only what is missing ».
- **Budget** : arrêt propre si le coût cumulé dépasse `--budget`.

### 9.4 Injection de panne (`--chaos`)
Le premier appel à `audit_page` renvoie **une fois** une erreur transitoire (« Chromium crashed
during analysis (Target closed)… may be retried »). L'agent doit la diagnostiquer et relancer.

Elle est annoncée dans le log comme `Injected fault`, sans rien cacher.

### 9.5 Rendre la démo déterministe (important)
Le run réel doit **produire naturellement** les deux refus. Le site démo (§11) est conçu pour :

- **Contraste.** Le prompt du dev l'incite à préserver la marque, mais le fond du hero a lui aussi
  un contraste limite. Une première tentative qui assombrit le fond est probable, et le testeur la
  refuse (diff > 2 %).
- **« Add to bag ».** Un `div` avec `onclick` est souvent « corrigé » d'abord par `role="button"`.
  Le testeur le refuse car l'élément n'est pas focusable.

Si un run réel ne montre aucun refus :
1. **on relance** (le coût est faible sur le site démo) ;
2. **on garde le meilleur run** comme `recordings/demo-run.jsonl`.

On ne fabrique jamais d'événements à la main.

---

## 10. Gouvernance et sécurité

C'est un argument du pitch : des agents contrôlables et auditables.

Options de chaque session :

```python
ClaudeAgentOptions(
  system_prompt=..., mcp_servers={"a11y": server},
  tools=[built-in tools of the role],      # ex. ["Read","Edit","Glob","Grep"] ; ["Agent"] pour le lead
  allowed_tools=role_tools + subagent_tools,
  disallowed_tools=other_a11y_tools,
  permission_mode="dontAsk",               # tout ce qui n'est pas autorisé est refusé sans prompt
  cwd=..., agents=subagents, model=..., max_turns=..., setting_sources=[],
  hooks={"PreToolUse": [HookMatcher(hooks=[guard])]},
)
```

**Hook `guard`** :
- il refuse tout `Edit` / `Write` / `MultiEdit` hors du périmètre du rôle (dépôt du site pour le
  dev, `out/` pour le writer, rien pour les autres) ;
- il émet un `log` pour chaque appel d'outil, avec le nom de l'agent (`input_data["agent_type"]`
  pour les sous-agents).

**Audit trail.**
- Chaque changement de statut est horodaté avec son auteur (agent ou humain) dans `history`.
- La signature compliance (clic sur « Send PR ») est enregistrée comme un événement `pr.sent`
  avec `by: "compliance"`.

---

## 11. Boutique démo piégée : `demo-shop/` (« Maison Lumière »)

**Pages** : HTML/CSS/JS statique, sans build. Quatre pages partagent le même en-tête et pied de
page : `index.html`, `product.html`, `cart.html`, `checkout.html`, plus `styles.css` et des
images produit en SVG dans `img/`. Le contenu est en français (c'est une boutique française) ;
l'UI de Arma est en anglais.

**Défauts plantés** (le tableau final doit les montrer corrigés) :

| Défaut | Pages | WCAG | Scanner ? | Résultat attendu |
|---|---|---|---|---|
| Texte gris clair (`.hero p`, `.price-note`, `.footer`) | toutes | 1.4.3 | oui | validé après **un refus** |
| `<html>` sans `lang` | index | 3.1.1 | oui | validé |
| Images produit sans `alt` | index, cart | 1.1.1 | oui | validé |
| `alt="image"` sur la photo produit | product | 1.1.1 | non | **needs_human** (couleur et matière à confirmer) |
| `*:focus { outline: none }` | toutes | 2.4.7 | non | validé |
| Boutons-icônes 🔍 ♡ 🛒 sans nom accessible | en-tête | 4.1.2 | non | validé (fusion de toutes les pages) |
| « Add to bag » en `div onclick` | product | 2.1.1 | non | validé après **un refus** |
| Tailles en `div` cliquables | product | 2.1.1 / 4.1.2 | non | validé (fieldset + radios) |
| « Checkout » et « Pay » en `div onclick` | cart, checkout | 2.1.1 | non | validé |
| Champs avec placeholder et sans label | checkout | 3.3.2 | non | validé |
| Erreurs signalées par une bordure rouge seule | checkout | 3.3.1 | non | validé |
| « En savoir plus » répétés | index | 2.4.4 | non | validé |
| Pas de `h1`, `h3` direct | index | 1.3.1 | non | validé |
| `<title>Paiement</title>` | checkout | 2.4.2 | non | validé |
| Boutons − + 🗑 sans nom | cart | 4.1.2 | non | validé |
| `<iframe>` de paiement tiers | checkout | 1.3.1 | non | **needs_human** (rapport de conformité du prestataire) |

**Fonctionnement en démo.**
- `run.py --demo` **copie** `demo-shop/` vers `runs/demo-shop/` : le modèle reste vierge et le
  run est rejouable.
- La copie est initialisée en dépôt git, puis servie sur `localhost:8765` avec
  `Cache-Control: no-store`.
- Pour la vraie PR, cette copie peut être poussée vers un dépôt GitHub de démo (§13).

---

## 12. Dashboard compliance : `web/`

### 12.1 Principes
- **Utilisateur** : un non-développeur. Le vocabulaire est compliance (score, criterion, evidence,
  status, needs review), pas technique.
- **Lecture** : la synthèse d'abord, le détail ensuite. L'état se lit à la forme (pills,
  pastilles de sévérité, couleurs sémantiques).
- **Accessible lui-même** : contrastes AA, focus visible, navigation clavier complète, onglets
  ARIA, `lang="en"`, `prefers-reduced-motion`, thème clair et sombre. *Un outil d'accessibilité
  inaccessible serait éliminatoire devant le jury.*
- **Identité visuelle** :
  - accent jaune « bande podotactile » (`#f4c20d`), réservé à la marque et à l'action principale ;
  - neutres ardoise ;
  - police **Atkinson Hyperlegible Next** + **Atkinson Hyperlegible Mono** (Google Fonts),
    conçues pour la lisibilité par le Braille Institute. C'est un détail propre au sujet, à
    mentionner au pitch.
- **Démarrage** : au chargement, le dashboard affiche **le dernier run terminé** (page complète au
  repos). « Run audit » relance un replay ou un run live.

### 12.2 Mise en page
```
┌ Command bar (sticky) ───────────────────────────────────────────────────────────┐
│ ▣ Arma  [DEMO WORKSPACE]  ● maison-lumiere.fr storefront·main   1× 2× 4×   │
│                                          [▶ Run audit] [Send PR to engineering] │
├ Phase rail ─────────────────────────────────────────────────────────────────────┤
│ ✓ Map site — ✓ Baseline — ● Audit — Plan — Fix & verify — Re-audit — Report — PR│
├───────────────────────────────────────────────┬─────────────────────────────────┤
│ COMPLIANCE SCORE                               │ AGENT TEAM                      │
│  jauge semi-circulaire 0–100 + repère baseline │ ● Orchestrator   activité       │
│  pill EAA status · « baseline 38 »             │ ● Cartographer                  │
│  BY WCAG PRINCIPLE : 4 barres P/O/U/R + %      │ ● Auditors ●●●● (sous-agents)   │
│  sparkline du score sur le run (cible 85)      │ ● Developer · ● Tester · ● Writer│
│ ─ KPIs : issues found | missed by scanners |   ├─────────────────────────────────┤
│          fixed & verified | need human review  │ LIVE AGENT LOG   [Copy log]     │
├───────────────────────────────────────────────┤ 00:42 [tester] REJECTED A07: …  │
│ [Findings 16] [Pull request] [Accessibility    │ 00:43 [orchestrator] Rollback…  │
│  statement]                                    │ (monospace, couleur par agent,  │
│ filtres : All · Open · Fixed · Needs review ·  │  auto-scroll si en bas)         │
│           Missed by scanners                   │                                 │
│ table : ID | Criterion (num, level, nom) |     │                                 │
│   Issue (+ pages) | Severity | Found by | Status│                                │
│ ▸ ligne dépliable : Specification (WCAG +      │                                 │
│   EN 301 549 + principe), User impact,         │                                 │
│   Evidence (code), Fix applied (diff coloré +  │                                 │
│   fichiers), Verification trail (historique)   │                                 │
└───────────────────────────────────────────────┴─────────────────────────────────┘
```
Sous 980 px, une seule colonne. Les tables défilent horizontalement dans leur conteneur, et la
page ne défile jamais horizontalement.

### 12.3 Composants et états
- **Jauge** :
  - « – » avant la fin de l'audit, puis la valeur ;
  - couleur rouge sous 60, orange sous 85, vert à partir de 85 ;
  - trait rouge au niveau du score de départ.
- **Pills de statut** :

  | Statut | Libellé | Couleur |
  |---|---|---|
  | `detected` | Detected | rouge |
  | `fixing` | Developer fixing | bleu |
  | `fixed_pending` | Tester verifying | bleu |
  | `rejected` | Rejected, retrying | orange |
  | `validated` | Fixed and verified | vert |
  | `needs_human` | Needs review | orange |

  Afficher « attempt N » sous la pill quand il y a eu plus d'une tentative.
- **« Found by »** : « Scanner (axe) » en gris ou « Agent review » en bleu accentué.
- **Nouvelle ligne** : flash de surbrillance bref à l'apparition.
- **Agent team** : pastille grise (idle), jaune pulsée (working) ou verte (done), avec
  l'activité courante en monospace tronquée.
- **Log** :
  - `tool` en gris ;
  - `err`, `reject` et `rollback` en rouge ;
  - `ok` et `commit` en vert ;
  - `phase` en gras avec un espacement au-dessus.
- **Contrôles de replay** : vitesse 1×, 2×, 4×. « Run audit » devient « Stop » pendant un run.

### 12.4 Onglet « Pull request »
- **Avant `pr.ready`** : état vide explicatif (« assembled once every fix has been verified »)
  avec le nombre de commits déjà faits.
- **Après `pr.ready`** :
  - **Colonne gauche** :
    - titre de PR et dépôt ;
    - branche → main ;
    - nombre de commits, de fichiers et de problèmes corrigés ;
    - **Open items** : les problèmes `needs_human` ;
    - score avant → après ;
    - liste des commits (sha + message).
  - **Colonne droite** : formulaire.
    - Reviewers : cases à cocher (Frontend team, Tech lead, QA).
    - Notify : Slack #eng-frontend, ticket Jira A11Y, email du rapport au juridique.
    - Message à l'équipe technique, pré-rempli et éditable.
    - Bouton **Send pull request**.
  - **À l'envoi** :
    - checklist animée : push branch, open PR, request reviews, post Slack, create Jira…, une
      étape à la fois ;
    - puis carte verte « Pull request #N opened » avec le lien si la PR est réelle, et la
      mention « Demo workspace: no external system contacted » si elle est simulée.
- **Le bouton du header** « Send PR to engineering » est désactivé tant que la PR n'est pas prête.
  Une fois actif, il ouvre l'onglet et met le focus sur « Send pull request ».

### 12.5 Onglet « Accessibility statement »
- Rendu du `accessibility-statement.md` du writer, avec un badge « Draft · partially compliant ».
- Les champs `[TO COMPLETE]` sont surlignés.
- Bouton « Copy statement ».

### 12.6 Sources d'événements (`app.js`)
```js
class ReplaySource  { constructor(url, speed) … }  // fetch JSONL, émet selon e.t / speed
class LiveSource    { constructor('/api/events') … } // EventSource SSE
```
- **Mode** : `?mode=replay` (par défaut si `/api/state` ne répond pas, comme sur Vercel) ou
  `?mode=live`.
- **Bouton « Run audit »** :
  - en live : `POST /api/run`, puis abonnement SSE ;
  - en replay : rejoue `recordings/demo-run.jsonl`.
- **Repli automatique** : si le live échoue (backend absent, erreur), le dashboard bascule en
  replay et affiche un toast discret.

**L'écran ne doit jamais rester vide.**

---

## 13. Envoi de la PR (`POST /api/pr`)

- **Entrée** : `{reviewers[], notify:{slack,jira,email}, message}`.
- **Mode réel**, si `GITHUB_REPO` est défini, `gh auth status` est OK et un remote existe :
  1. `git push -u origin <branch>` ;
  2. `gh pr create --title "a11y: EAA remediation, WCAG 2.1 AA" --body-file out/pr-body.md --head <branch> [--reviewer …]` ;
  3. renvoie l'URL et le numéro.

  Slack, Jira et email restent simulés : on ne les connecte pas pendant le hackathon.
- **Mode simulé**, dans tous les autres cas : renvoie un numéro plausible avec `simulated: true`.
- **Dans les deux cas** :
  - on émet `pr.sent` avec la liste des étapes ;
  - le corps de la PR est **le vrai `pr-body.md`** du writer ;
  - la message de compliance est ajouté en tête, avec la signature « Approved by compliance ».
- **Dans le mode replay statique (Vercel)**, l'envoi est entièrement simulé côté client.

---

## 14. Enregistrement, replay et livrables de run

- Tout run réel écrit `recordings/run-<date>.jsonl` via l'EventBus.
- `scripts/pick_demo_run.py <file>` copie le run choisi vers `web/recordings/demo-run.jsonl`.
  Il peut **compresser les temps morts** : gaps plafonnés à quelques secondes, ordre conservé.
- `scripts/export_logs.py` produit `deliverables/agent-logs.txt` au format lisible
  `mm:ss [agent] texte`, à partir des événements `log`.
- **MP4** : capture d'écran du dashboard en replay à 2×. C'est le filet de sécurité si le wifi
  lâche.

---

## 15. Déploiement et livrables

- **Vercel** : déployer le dossier `web/` (statique), qui contient `recordings/demo-run.jsonl`.
  Pas de backend. L'URL obtenue sert de **Live link to the product**.
- **Landing** : le dashboard lui-même. Un lien « About » ouvre un panneau avec le one-line pitch,
  le problème EAA, l'architecture des agents en une figure et le lien GitHub. Cette URL avec
  `#about` sert de **Project name and one-line pitch**.
- `deliverables/agent-design.txt` : une page maximum, en anglais.
  - Rôles des agents et passations via l'état partagé et les outils.
  - Boucle développeur ⇄ testeur avec rollback et escalade.
  - Sous-agents parallèles.
  - Gouvernance (permissions par rôle, hook de périmètre, audit trail).
  - Reprise (checkpoints, `--resume`, relance des sessions, injection de panne).
- `deliverables/agent-logs.txt` + MP4.

---

## 16. Arborescence cible

```
arma/
├── CLAUDE.md                 # résumé de ce document + commandes
├── README.md
├── pyproject.toml / requirements.txt   # claude-agent-sdk, playwright, pillow, fastapi, uvicorn, markdown
├── run.py                    # CLI : --demo --site --url --resume --chaos --model --budget
├── server.py                 # FastAPI : SSE, run, pr, statique web/
├── vendor/axe.min.js
├── demo-shop/                # modèle piégé (jamais modifié)
├── runs/                     # copies de travail (gitignored)
├── recordings/               # runs enregistrés (.jsonl)
├── state/                    # state.json, shots/, out/ (gitignored)
├── arma/
│   ├── events.py             # EventBus : emit → jsonl + abonnés SSE (asyncio.Queue)
│   ├── state.py              # Store JSON atomique + dédoublonnage
│   ├── scoring.py            # §6.3
│   ├── browser.py            # crawl, axe, keyboard_walk, html, screenshot, visual_diff
│   ├── tools.py              # outils MCP
│   ├── agents.py             # prompts + outils par rôle + AgentDefinition
│   ├── orchestrator.py       # phases, boucle de lots, git, reprise
│   └── pr.py                 # envoi réel (gh) ou simulé
├── web/
│   ├── index.html  styles.css  app.js
│   └── recordings/demo-run.jsonl
├── scripts/
│   ├── pick_demo_run.py
│   └── export_logs.py
└── deliverables/
    ├── agent-design.txt
    └── agent-logs.txt
```

---

## 17. Plan de construction (ordre imposé)

**Chaque étape se termine par une vérification. On ne passe pas à la suivante sans elle.**

| # | Étape | Vérification |
|---|---|---|
| 1 | **Squelette** : venv, dépendances, `playwright install chromium`, vendoriser axe-core, `CLAUDE.md` | Un script ouvre Chromium et injecte axe |
| 2 | **Contrat d'événements** (§5) + `events.py` + un **faux run JSONL écrit à la main** (`recordings/fixture.jsonl`) couvrant tous les types | Le fichier se parse ; chaque type est présent |
| 3 | **Dashboard en replay** (§12) sur la fixture | Rendu complet, filtres, lignes dépliables, onglets, envoi PR simulé, thème sombre, largeur mobile sans scroll horizontal, navigation clavier complète |
| 4 | **Boutique démo** (§11) | La servir et la parcourir |
| 5 | `browser.py` | Le crawl trouve les quatre pages (dont checkout via `onclick`) ; axe trouve contraste, `lang` et `alt` ; `keyboard_walk` voit le focus invisible et les `div` inaccessibles ; le diff visuel fonctionne |
| 6 | `state.py` + `scoring.py` | Test unitaire dédoublonnage + score |
| 7 | `tools.py` + `agents.py` + orchestrateur, **phases `crawl` et `audit` seulement** | Run réel ; issues dans `state.json` ; événements dans le JSONL ; replay correct dans le dashboard |
| 8 | **Boucle de correction** (§9.2), d'abord sur un seul lot, puis tous | Commits réels, rollback, escalade |
| 9 | `reaudit`, `report`, `pr` (writer + `pr.ready`) | Run complet `python run.py --demo --model sonnet` |
| 10 | `server.py` (SSE, `/api/run`, `/api/pr`) + `LiveSource` + repli automatique | Run live visible dans le dashboard |
| 11 | **Meilleur run** → `web/recordings/demo-run.jsonl` (§9.5) | Au moins un refus et un rollback visibles |
| 12 | **Déploiement Vercel** de `web/` | URL publique fonctionnelle en navigation privée |
| 13 | **Livrables** : `agent-design.txt`, `agent-logs.txt`, MP4 | Fichiers présents |
| 14 | *(nice-to-have)* `--chaos`, `--resume`, vraie PR GitHub, rapport HTML | — |

**Si le temps manque**, couper dans cet ordre :
1. le nice-to-have ;
2. le mode live (le replay d'un vrai run suffit) ;
3. la vraie PR (le simulé suffit) ;
4. la phase `report` agentique (un template statique de déclaration suffit).

**Ne jamais couper** : le dashboard en replay, les refus du testeur visibles, le déploiement.

---

## 18. Pièges connus du SDK Python (`claude-agent-sdk`)

- **Les champs de `AgentDefinition` sont en camelCase** (`maxTurns`, `permissionMode`,
  `disallowedTools`). Utiliser du snake_case lève une `TypeError`. Mettre `background=False` sur
  le `page-auditor` pour que le lead attende ses sous-agents.
- **`allowed_tools` auto-approuve mais ne restreint pas.** La restriction passe par `tools=`
  (outils intégrés), `disallowed_tools=` et `permission_mode="dontAsk"`.
- **Les outils MCP utilisés par des sous-agents** doivent aussi être dans `allowed_tools` de la
  session parente.
- **Noms des outils MCP** : `mcp__<server>__<tool>`.
- **Retour d'outil en erreur** : `{"content":[…], "is_error": True}`. Ne pas lever d'exception.
- **`setting_sources=[]`** pour ne pas hériter de la config locale de Claude Code.
- **Ne jamais faire `break`** dans `async for msg in query(...)`. Utiliser un drapeau.
- **`ResultMessage`** donne `total_cost_usd` et `is_error` : cumuler le coût, lever une erreur si
  `is_error`.
- **`AssistantMessage.parent_tool_use_id`** non nul signifie un message de sous-agent : l'étiqueter
  `auditor·<page>`.
- **Dans les hooks**, `input_data["agent_type"]` identifie le sous-agent.
- **Modèle** : `--model sonnet` pour les répétitions (rapide, économique), le modèle par défaut
  pour le run enregistré.
- **Budget** : `--budget` en USD, avec une vérification après chaque `ResultMessage`.

---

## 19. Definition of done

- [ ] L'URL Vercel ouvre le dashboard en replay d'un **vrai run**. Il fonctionne en navigation
      privée, sur mobile et en thème sombre.
- [ ] Le score passe d'un niveau « non-compliant » à « partially compliant », avec les
      problèmes `needs_human` explicités.
- [ ] Le KPI « missed by automated scanners » est majoritaire.
- [ ] Le log montre :
  - les sous-auditeurs parallèles ;
  - au moins un refus du testeur suivi d'une correction validée ;
  - au moins un rollback ;
  - des commits.
- [ ] Chaque problème déplié montre spécification, impact, preuve, diff et piste de vérification.
- [ ] « Send PR to engineering » aboutit à une confirmation : vraie PR GitHub si configurée,
      sinon simulée et signalée.
- [ ] La déclaration d'accessibilité est copiable et ne prétend jamais à une conformité totale.
- [ ] Le dashboard est lui-même navigable entièrement au clavier, avec un focus visible.
- [ ] `deliverables/agent-design.txt`, `deliverables/agent-logs.txt` et le MP4 existent.

---

## 20. Commandes

```bash
# installation
python3 -m venv .venv && source .venv/bin/activate
pip install claude-agent-sdk playwright pillow fastapi uvicorn markdown
python -m playwright install chromium
export ANTHROPIC_API_KEY=...          # crédits Claude API du hackathon

# run réel sur la boutique démo (répétition)
python run.py --demo --model sonnet --chaos

# serveur + dashboard live
uvicorn server:app --port 8000        # http://localhost:8000/?mode=live

# choisir le run de démo et exporter les logs
python scripts/pick_demo_run.py recordings/run-<date>.jsonl
python scripts/export_logs.py web/recordings/demo-run.jsonl > deliverables/agent-logs.txt

# déploiement statique
cd web && vercel --prod
```

---

## 21. Script de démo (pitch)

1. **Problème.** EAA en vigueur ; procès contre la grande distribution française ; overlays
   sanctionnés par la FTC ; les scanners ne voient qu'une partie des problèmes.
2. **« Run audit ».** Le cartographe, puis les auditeurs en parallèle ; le compteur « missed by
   scanners » monte.
3. **Le travail d'équipe.** Un refus du testeur avec sa raison, la correction, le commit ; le
   score qui remonte.
4. **Vue compliance.** Une ligne dépliée : spécification WCAG et EN 301 549, preuve, diff,
   vérification. Les deux « Needs review » restent honnêtement ouverts.
5. **« Send PR to engineering ».** La PR part à la tech, et la déclaration d'accessibilité est
   prête.
6. **Business.** Audit et correctifs facturés à l'acte, surveillance continue, marque blanche
   pour les agences.
