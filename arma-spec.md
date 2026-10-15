# Arma : spécification projet, version Managed Agents (pour Claude Code)

> Ce document fait foi. Il remplace la version Agent SDK.
>
> Il s'accompagne de :
> - `arma-build-plan.md`, le plan de construction ordonné ;
> - `reference/arma-dashboard-prototype.html`, la maquette du dashboard.
>
> **Priorité absolue : une démo qui marche visuellement, à chaque fois.**

> **Déploiement et cible, à ne pas confondre.**
> - **Ce qui est déployé sur Vercel, c'est l'application Arma elle-même** (le dashboard compliance,
>   `web/`). C'est le produit et le lien live du jury.
> - **Maison Lumière est une cible de démonstration temporaire.** C'est un faux site client, servi
>   dans le sandbox des agents, jamais sur Vercel. Il sera remplacé par un vrai site si le temps le
>   permet (§20).

---

## 0. En bref

**Arma** est un dashboard pour les **équipes compliance** des e-commerçants européens. Une
**équipe d'agents Claude hébergée (Claude Managed Agents)** fait quatre choses :
1. elle audite la boutique contre WCAG 2.1 AA, la norme derrière l'**European Accessibility Act**
   (EAA) ;
2. elle corrige **dans le code source** ;
3. elle fait vérifier chaque correctif par un **agent testeur indépendant** ;
4. elle prouve le résultat via un **grader d'outcome indépendant**.

Enfin, elle prépare une pull request que la compliance **envoie en un clic à l'équipe technique**.

**One-line pitch** : *Arma gives compliance teams a hosted AI agent team that audits, fixes and
verifies their store's accessibility, proves it against a rubric, and hands engineering a
ready-to-merge pull request.*

Le projet suit le cadre donné par les organisateurs : **Build it. Let it run. Prove it worked.**

| Étape organisateurs | Dans Arma |
|---|---|
| Sign in with Console | `claude auth login --console` (crédits API du hackathon) |
| Build your agent, hosted | `/claude-api managed-agents-onboard` : agents, environnement et sessions sur Managed Agents (§4 à §7) |
| Give it a finish line | `/goal` dans Claude Code + **`user.define_outcome`** avec rubric dans chaque session (§8) |
| Build the eval | `/claude-api build-eval` : eval déterministe contre la vérité terrain de la boutique piégée (§9) |
| Hill climb | `/claude-api hillclimb` : amélioration des prompts, avec l'historique des scores montré au pitch (§9.3) |

---

## 1. Contexte : hackathon Accel AI Innovate

**Challenge.** *Long Running Agents — From Task to Workflow* : des agents qui tournent longtemps
et/ou en équipe, sur un vrai problème client, en une journée.

**Critères du jury :**

| Critère | Ce qu'Arma montre |
|---|---|
| Real output | Une branche git avec un commit par critère WCAG, une PR, un rapport et une déclaration d'accessibilité |
| Agent design | Agent lead hébergé + sous-agents (auditeurs en parallèle, développeur, testeur, rédacteur) ; refus du testeur suivi d'une relance du développeur dans **le même fil persistant** ; rollback ; escalade ; grader d'outcome |
| Business viability | Obligation EAA, procès contre la grande distribution française, overlays sanctionnés par la FTC |
| Demo & pitch | Dashboard avec logs live (stream SSE de la session) + replay d'un vrai run enregistré |

**Livrables à soumettre :**

| Livrable | Comment on le produit |
|---|---|
| Name + one-line pitch (URL) | Panneau `#about` du dashboard déployé |
| Live link (URL) | Dashboard sur Vercel, en mode replay d'un vrai run |
| Agent design (TXT) | `deliverables/agent-design.txt` |
| Logs or recording (TXT/MP4) | `deliverables/agent-logs.txt` (export du run) + capture écran MP4 |
| Pitch slides (URL) | Hors code |

**Ressources** : les crédits Claude API (obligatoires) et Vercel (lien live).

---

## 2. Utilisateur et valeur

- **Utilisateur principal : la compliance / le juridique** d'un e-commerçant européen. Ce n'est
  pas un développeur. Il doit prouver la conformité, publier une déclaration d'accessibilité et
  faire corriger les écarts.
- **Utilisateur secondaire : l'équipe technique**, qui reçoit une PR découpée par critère et déjà
  vérifiée.
- **La valeur** :
  - un score et un statut EAA ;
  - une spécification par problème : critère, clause EN 301 549, impact, preuve, diff,
    vérification ;
  - une PR envoyée en un clic ;
  - une déclaration pré-remplie ;
  - **une preuve indépendante** : le grader d'outcome et l'eval.
- **Business model** :
  - audit et correctifs à l'acte ;
  - abonnement de surveillance, avec un session programmée à chaque déploiement grâce aux
    *scheduled deployments* de Managed Agents ;
  - offre marque blanche pour les agences.

---

## 3. Périmètre

### MVP
1. Le **dashboard** en mode replay, fiable à 100 % (inchangé par rapport à la v1, piloté par
   événements).
2. L'**équipe d'agents hébergée** sur la boutique démo, qui produit un vrai run enregistré, une
   vraie branche git et de vrais commits (dans le sandbox, puis rapatriés).
3. Le **pont local** (`bridge.py`) :
   - il crée la session ;
   - il répond aux custom tools ;
   - il traduit les événements Managed Agents vers le contrat du dashboard ;
   - il enregistre le JSONL ;
   - il rapatrie les fichiers de sortie.
4. **L'outcome avec rubric**, et l'**eval** déterministe.
5. **« Send PR to engineering »** : vraie PR si `gh` et un remote sont configurés, sinon simulée.
6. Le **déploiement Vercel** et les livrables.

### Nice-to-have
- Mode live dans le dashboard (SSE du pont).
- Hill climb avec historique des scores affiché.
- Scheduled deployment (« re-audit à chaque déploiement »).

### Règle d'arbitrage
En cas de conflit entre « réel » et « fiable à l'écran », **le fiable gagne**.

Le replay d'un vrai run est honnête : on montre ce que les agents ont fait, accéléré. Un badge
« Demo workspace » reste visible en permanence. **On ne fabrique jamais d'événements à la main**
pour simuler un run réel. Les données de test servent uniquement au développement du front.

---

## 4. Architecture

```
┌──────────────── Anthropic Managed Agents (hébergé) ─────────────────┐
│ Environment "arma-env" (cloud sandbox : chromium, playwright, git…) │
│ Session (une par run)                                                │
│   primary thread : ARMA LEAD (multiagent_20261001)                   │
│     ├─ subagent  PAGE AUDITOR  ×N en parallèle (un par page)         │
│     ├─ subagent  DEVELOPER     (fil persistant : relances avec       │
│     │                           le feedback du testeur)              │
│     ├─ subagent  TESTER        (fil isolé, sans édition)             │
│     └─ subagent  WRITER                                              │
│   Filesystem partagé : /workspace/site (git), /workspace/arma         │
│   Entrées montées : /mnt/session/uploads/{demo-shop.tgz, tools/…}    │
│   Sorties : /mnt/session/outputs/{patches, pr-body.md, statement,    │
│             report.json, eval.json}                                  │
│   Outcome : user.define_outcome + rubric → grader indépendant        │
└────────────────────┬────────────────────────────────────▲───────────┘
          SSE events │                                    │ user.custom_tool_result
                     ▼                                    │ user.message / define_outcome
┌──────────────────── bridge.py (local, Python, SDK anthropic) ────────┐
│ • upload des entrées (Files API), création de session (+budget)      │
│ • répond aux custom tools = LE LEDGER (§6) : issues, statuts,        │
│   commits, score → Store + EventBus                                  │
│ • traduit les events Managed Agents → contrat dashboard (§10)        │
│ • enregistre recordings/run-<date>.jsonl ; SSE /api/events           │
│ • à la fin : télécharge /mnt/session/outputs, applique les patches   │
│   sur le dépôt local du site, prépare la PR                          │
└────────────────────┬─────────────────────────────────────────────────┘
                     ▼
            web/ (dashboard statique) : LiveSource (SSE du pont)
                                        | ReplaySource (JSONL)
```

### Décisions clés
1. **Le cerveau et les mains sont hébergés.** Raisonnement, bash, fichiers, navigateur et git
   tournent dans le sandbox. **Le registre de conformité reste chez nous.** Chaque constat et
   chaque changement de statut passe par un **custom tool**, auquel le pont répond. On obtient
   ainsi :
   - des passations typées et auditables ;
   - le flux d'événements du dashboard ;
   - un point de gouvernance (validation des transitions de statut).
2. **Les outils déterministes** (crawl, axe, parcours clavier, diff visuel) sont des **scripts
   Python montés dans le sandbox** (`/mnt/session/uploads/tools/`). Les agents les lancent via
   `bash`. Pas de navigateur côté client.
3. **Le dashboard ne connaît que le contrat d'événements** (§10). Live et replay donnent un rendu
   identique. Vercel n'héberge que du statique.

---

## 5. Ressources Managed Agents

Elles sont versionnées dans le dépôt sous forme de fichiers `ant` (`managed/`), appliquées avec
`ant apply`. Les identifiants sont dans `claude-lock.json`, qui est commité.

Toutes les requêtes passent par le beta header `managed-agents-2026-04-01`, posé automatiquement
par le SDK `anthropic` et la CLI `ant`.

### 5.1 Environnement : `managed/environment.yaml`
```yaml
# yaml-language-server: $schema=https://platform.claude.com/schemas/ant/beta/environment.json
name: arma-env
config:
  type: cloud
  packages:
    apt: [chromium, git, fonts-dejavu-core]
    pip: [playwright, pillow]
    npm: [axe-core@4.10.3]
  networking:
    type: limited
    allow_package_managers: true
    # la boutique est servie en local dans le sandbox (http://127.0.0.1:8765) : aucun hôte externe requis
```

- **Navigateur** : Playwright est lancé avec `executable_path="/usr/bin/chromium"`.
  `playwright install` n'est jamais appelé, car il télécharge depuis un CDN non autorisé.
- **Fallback** si Chromium est indisponible dans le sandbox : `tools/audit_static.js`
  (Node + jsdom + axe-core). Le contraste n'est alors pas mesuré par axe ; l'auditeur le calcule à
  partir du CSS. Voir l'étape « smoke test sandbox » du plan.

### 5.2 Agents : `managed/agents/*.md`

Tous utilisent `tools: [{type: agent_toolset_20260401, configs…}]` et les custom tools du §6.

| Agent | Modèle | Outils intégrés | Custom tools | Rôle |
|---|---|---|---|---|
| `arma-lead` | `claude-opus-5-5` | bash, read, glob, grep (pas write ni edit) | `register_page`, `list_issues`, `plan_batches`, `start_batch`, `record_commit`, `rollback_batch`, `emit_progress` | Orchestre le run (§7). `multiagent: {type: multiagent_20261001, subagents: {type: enabled, inline_agents: {type: disabled}, predefined_agents: [page-auditor, developer, tester, writer]}, workflows: null}` |
| `arma-page-auditor` | `claude-sonnet-5-5` | bash, read, glob, grep | `report_issue`, `emit_progress` | Audite une page : scripts axe + clavier + jugement (§7.2) |
| `arma-developer` | `claude-sonnet-5-5` | bash, read, edit, write, glob, grep | `mark_fixed`, `cannot_fix`, `emit_progress` | Corrige la source partagée dans `/workspace/site` |
| `arma-tester` | `claude-opus-5-5` | bash, read, glob, grep (**pas write ni edit**) | `verdict`, `batch_verdict`, `emit_progress` | Vérifie de façon indépendante (scripts compare, clavier, diff visuel ; ouvre les captures avec `read`) |
| `arma-writer` | `claude-sonnet-5-5` | read, write, glob | `emit_progress` | Écrit `pr-body.md` et `accessibility-statement.md` dans `/mnt/session/outputs/` |

Notes :
- Les sous-agents **ne doivent pas** avoir de champ `multiagent`, car la délégation est limitée à
  un niveau.
- `web_search` et `web_fetch` sont désactivés partout (`configs: [{name: web_search, enabled: false}, {name: web_fetch, enabled: false}]`).
- Les noms des custom tools ne commencent jamais par `mcp__` ou `ant__`.

### 5.3 Session (créée par `bridge.py` à chaque run)
```python
session = client.beta.sessions.create(
    agent=LEAD_ID, environment_id=ENV_ID, title=f"Arma run {date}",
    resources=[
      {"type":"file","file_id": shop_tgz.id,  "mount_path":"/demo-shop.tgz"},
      {"type":"file","file_id": tools_tgz.id, "mount_path":"/tools.tgz"},
      {"type":"file","file_id": rubric.id,    "mount_path":"/rubric.md"},
    ],
    budget={"type":"limit","max_list_cost":{"amount": str(BUDGET_CENTS), "currency":"USD"}},
)
```
- Les fichiers montés sont en lecture seule, sous `/mnt/session/uploads/…`. Le lead les extrait
  dans `/workspace`.
- Le run démarre avec deux événements :
  1. `user.message` : le brief du run (URL locale, étapes) ;
  2. `user.define_outcome` : la description et la rubric (§8).
- En développement : `agent_with_overrides` avec `model: claude-sonnet-5-5` pour réduire le coût.

---

## 6. Custom tools : le registre de conformité

**Déclaration.** Chaque custom tool est déclaré dans la définition de l'agent qui l'utilise :
`type: custom`, `name`, `description` (trois ou quatre phrases), `input_schema`.

**Fonctionnement.** Claude ne les exécute pas. Le pont reçoit `agent.custom_tool_use`, exécute,
puis renvoie `user.custom_tool_result` avec `custom_tool_use_id` et `content`.

**Champ commun.** Chaque appel inclut `agent` (le nom de rôle, ex. `auditor·product`). Il sert à
étiqueter les logs, car les appels bloquants des sous-agents sont relayés sur le fil principal.

| Tool | Entrée | Effet côté pont | Événements dashboard émis |
|---|---|---|---|
| `register_page` | `agent, url, template` | Store.pages | `log` |
| `report_issue` | `agent, page, wcag, title, impact, evidence, severity, selector, source(axe\|keyboard\|agent), rule?` | `Store.add_issue` avec dédoublonnage (même wcag + selector + rule/titre → ajoute la page) ; renvoie l'`id` | `issue.detected` ou `issue.merged`, `log` |
| `list_issues` | `status?` | Lecture | — |
| `plan_batches` | `agent, batches:[{criterion, issue_ids}]` | Store.batches (vérifie que chaque issue n'est que dans un lot) | `log` par lot |
| `start_batch` | `agent, batch_id, attempt` | Statuts des problèmes ouverts du lot → `fixing` | `batch.started`, `issue.status` |
| `mark_fixed` | `agent, issue_id, files[], explanation, diff` | Statut → `fixed_pending` (refusé si le statut courant n'est pas `fixing`) | `issue.status`, `score` |
| `cannot_fix` | `agent, issue_id, reason, human_action` | → `needs_human` | `issue.status`, `score` |
| `verdict` | `agent, issue_id, accepted, reason` | → `validated` / `rejected` (refusé si l'appelant n'est pas le testeur) | `issue.status`, `score` |
| `batch_verdict` | `agent, batch_id, accepted, reason` | Verdict de lot | `log` (reject ou ok) |
| `rollback_batch` | `agent, batch_id, reason` | Statuts du lot → `rejected` | `log` kind `rollback` |
| `record_commit` | `agent, batch_id, sha, message, files[]` | Store.commits | `commit.created`, `log` |
| `emit_progress` | `agent, text, kind(msg\|tool\|ok\|reject)` | — | `log`, `agent.status` |

**Gouvernance côté pont** (argument du pitch) :
- **Machine à états des statuts.** Elle est validée : une transition illégale renvoie un
  `user.custom_tool_result` explicatif, par exemple « verdict refused: issue A07 is not
  fixed_pending ».
- **Seul `arma-tester` peut appeler `verdict`.** Le pont vérifie `agent`, et le testeur est le seul
  agent qui déclare cet outil.
- **Audit trail.** Chaque transition est horodatée avec son auteur, dans `history`.

---

## 7. Déroulé d'un run (piloté par `arma-lead`)

Le prompt système du lead décrit ce protocole. Le brief du run le rappelle.

### 7.1 Préparation (lead, via bash)
1. Extraire `/mnt/session/uploads/demo-shop.tgz` vers `/workspace/site` et
   `/mnt/session/uploads/tools.tgz` vers `/workspace/arma/tools`.
2. `cd /workspace/site && git init && git add -A && git commit -m "baseline"`, puis créer la
   branche `a11y/eaa-remediation-<date>`.
3. Servir le site : `python -m http.server 8765 -d /workspace/site &`.
4. **Cartographie** : `python tools/crawl.py http://127.0.0.1:8765/index.html`, puis
   `register_page` pour chaque page avec son gabarit.
5. **Mesure de départ** : `python tools/baseline.py`, qui produit `/workspace/arma/baseline.json`
   et les captures `before`. Rapporter les métriques via `emit_progress`.

### 7.2 Audit (sous-agents en parallèle)
- Le lead délègue **un `arma-page-auditor` par page, toutes les délégations ensemble**.
- Chaque auditeur :
  1. lance `python tools/audit.py <url>` (axe-core) → `report_issue` source `axe`, en regroupant
     les nœuds identiques ;
  2. lance `python tools/keyboard.py <url>` → focus invisible et éléments non atteignables →
     source `keyboard` ;
  3. lit la source HTML/CSS (`read`, `grep`) et applique son **jugement** → source `agent`. Il
     cherche au minimum :

     | Problème | Critère |
     |---|---|
     | Bouton-icône nommé par un emoji ou un symbole | 4.1.2 |
     | `alt="image"` ou alt inutile | 1.1.1 |
     | « Learn more » ambigu | 2.4.4 |
     | Placeholder sans label | 3.3.2 |
     | Erreur signalée par la couleur seule | 3.3.1 |
     | Pas de `h1` ou niveaux sautés | 1.3.1 |
     | Titre de page vague | 2.4.2 |
     | `div` cliquable ou sélecteur sans rôle ni état | 2.1.1 / 4.1.2 |
     | `outline: none` | 2.4.7 |
     | Iframe tiers non vérifiable | 1.3.1 |

  4. Utilise un sélecteur stable pour les composants partagés (en-tête, pied de page), afin que
     la fusion fonctionne.
- Le lead vérifie la couverture (`list_issues`) et relance une page manquante si besoin.

### 7.3 Plan
Le lead appelle `plan_batches` : un lot par critère WCAG, trié par sévérité maximale (purchase
blockers first).

### 7.4 Correction ⇄ vérification (le cœur de la démo)
```
pour chaque lot :
  start_batch(lot, tentative)
  → DEVELOPER (fil persistant) : lot + refus précédents
      corrige la source partagée, HTML natif d'abord, contraste = couleur conforme la plus
      proche de la marque, ne jamais inventer de contenu (sinon cannot_fix) ;
      mark_fixed(issue, files, explanation, diff = `git diff -- files`)
  → TESTER (fil isolé, sans édition) : problèmes déclarés corrigés + pages
      python tools/compare.py <url> (baseline vs maintenant, régressions, % pixels modifiés,
      captures before/after/diff) ; tools/keyboard.py si clavier, focus ou interactif ;
      read de la capture diff si plus de 2 % ; verdict par problème (raison actionnable) ;
      batch_verdict (refus uniquement si régression ou design cassé)
  si lot refusé : le lead fait git checkout -- . && git clean -fd, rollback_batch, puis renvoie
                  le feedback au MÊME fil développeur (suivi) et recommence
  sinon : le lead commite les fichiers validés
          git commit -m "fix(a11y): WCAG <crit> — <titres>" → record_commit ;
          les problèmes refusés repartent vers le développeur (même fil) avec la raison
  plafond de trois tentatives par problème → cannot_fix / needs_human (via le développeur)
```

**Ce que le jury doit voir** :
1. un refus du testeur avec sa raison ;
2. le **même** développeur qui reprend en tenant compte du feedback ;
3. la validation ;
4. le commit ;
5. au moins un rollback pour régression visuelle.

**Démo déterministe.** La boutique (§11) est conçue pour provoquer naturellement deux refus :
- **« Add to bag »** : un `div` corrigé d'abord avec `role="button"` (refusé parce qu'il reste non
  focusable) ;
- **le hero** : un fond assombri (refusé pour régression visuelle).

Si un run n'en montre pas, on relance et on garde le meilleur.

### 7.5 Re-audit, documents, sorties
1. `python tools/reaudit.py`, qui produit `/workspace/arma/final.json`.
2. Le `arma-writer` écrit `pr-body.md` et `accessibility-statement.md` dans
   `/mnt/session/outputs/`.
3. Le lead écrit dans `/mnt/session/outputs/` :
   - `patches/` (`git format-patch baseline..HEAD`) ;
   - `changes.diff` ;
   - `report.json` (issues, statuts, métriques avant/après, commits).
4. Le lead termine son tour. Le **grader d'outcome** évalue alors la rubric (§8).

---

## 8. Ligne d'arrivée : `/goal` et outcome

### 8.1 `/goal` dans Claude Code (pour la construction)
```
/goal Arma is done when: the dashboard is deployed on Vercel and replays a real recorded Managed
Agents run; the run shows parallel page auditors, at least one tester rejection followed by a
validated fix in the same developer thread, one rollback, and git commits per WCAG criterion; the
outcome grader returns "satisfied"; the eval passes its thresholds; "Send PR to engineering"
completes; deliverables/agent-design.txt and deliverables/agent-logs.txt exist.
```

### 8.2 Outcome de session (pour chaque run) : `managed/rubric.md`
```markdown
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
```

- **Envoi** : `user.define_outcome` avec `description: "Remediate maison-lumiere storefront accessibility to WCAG 2.1 AA and deliver a verified PR package"`,
  `rubric: {type: "file", file_id: rubric.id}` et `max_iterations: 3`.
- **Résultat** : le pont traduit `span.outcome_evaluation_start` et `span.outcome_evaluation_end`
  (`result` vaut `satisfied`, `needs_revision`, etc., avec une `explanation`) en événement
  `outcome` pour le dashboard.
- **Affichage** : un badge « Independent grader: satisfied », avec l'explication au survol ou au
  dépli.

---

## 9. Eval et hill climb

### 9.1 Vérité terrain : `eval/ground_truth.json`
Un objet par défaut planté de la boutique (§11) :
```json
{"key":"hero-contrast","wcag":"1.4.3","pages":["*"],"match":{"wcag":["1.4.3"],"selector_any":[".hero p",".price-note",".footer"]},
 "detectable_by_axe":true,"expected_final":"validated"}
```
- **Correspondance** : un problème rapporté correspond à un défaut si son critère est dans
  `match.wcag` ET que son sélecteur ou son evidence recoupe `selector_any` ou `evidence_any`.
- **`expected_final`** : `validated`, ou `needs_human` pour l'alt produit et l'iframe tiers.

### 9.2 `eval/run_eval.py <report.json> [final.json]` : métriques et seuils

| Métrique | Définition | Seuil |
|---|---|---|
| `recall_all` | Défauts plantés retrouvés / total | ≥ 0.9 |
| `recall_agent_only` | Idem, sur les défauts invisibles pour axe | ≥ 0.8 |
| `precision` | Problèmes rapportés correspondant à un défaut ou à une vraie violation axe / total rapporté | ≥ 0.8 |
| `verified_fix_rate` | Défauts `expected_final=validated` effectivement validés ET absents de `final.json` | ≥ 0.85 |
| `false_fix` | Validés par le testeur mais toujours présents au re-audit | = 0 |
| `regressions` | Nouvelles violations au re-audit | = 0 |
| `honesty` | Les deux défauts `needs_human` attendus sont escaladés, pas « corrigés » | = 1 |

La sortie est `eval/results/<run>.json`. Le script affiche un tableau PASS/FAIL et renvoie un code
de sortie non nul en cas d'échec. **C'est la cible de `/claude-api build-eval`.**

### 9.3 Hill climb
- **Cible** : `/claude-api hillclimb` itère sur les prompts de `arma-page-auditor`, puis de
  `arma-tester` (`ant apply` crée une nouvelle version d'agent), relance un run et mesure.
- **Historique** : `eval/history.csv` (version de l'agent, métriques).
- **Dashboard** : le panneau « About » ou une carte « Eval » affiche la courbe
  `recall_agent_only` et `verified_fix_rate` par version. C'est la preuve chiffrée du
  « Prove it worked ».

---

## 10. Contrat d'événements (dashboard)

C'est le contrat de la v1, inchangé, plus un type `outcome` et un type `eval`. Chaque ligne JSONL
a la forme `{t, type, agent?, data}`.

| `type` | `data` | Source côté pont |
|---|---|---|
| `run.started` | `{site, repo, branch, session_id}` | Création de session |
| `phase.changed` | `{phase}` : crawl, baseline, audit, plan, fix, reaudit, report, pr | `emit_progress` avec `kind=phase`, ou appels caractéristiques |
| `agent.status` | `{agent, status, activity}` | `session.thread_status_running` / `_idle`, `emit_progress` |
| `subagents` | `{agent:"auditors", states:[…]}` | `session.thread_created` et statuts de fil, agrégés |
| `log` | `{text, kind}` | `agent.message` (texte), `agent.tool_use` (kind `tool` : bash, read…), `emit_progress`, résultats de custom tools |
| `baseline` / `reaudit` | métriques | `emit_progress` + lecture de `report.json` à la fin |
| `issue.detected` / `issue.merged` / `issue.status` | voir v1 | Custom tools (§6) |
| `score` | `{value, baseline, by_principle}` | Calculé par le pont après chaque statut (formule ci-dessous) |
| `batch.started` | `{id, criterion, issue_ids, attempt}` | `start_batch` |
| `commit.created` | `{sha, criterion, message, files}` | `record_commit` |
| `document.written` | `{name, content}` | Après téléchargement des sorties |
| `outcome` | `{iteration, result, explanation}` | `span.outcome_evaluation_*` |
| `pr.ready` | `{repo, branch, base, commits, files, body}` | Après téléchargement et application des patches |
| `pr.sent` | `{number, url, notified, simulated}` | `POST /api/pr` |
| `eval` | `{metrics, thresholds, passed}` | Après `run_eval.py` |
| `run.finished` | `{cost_usd, duration_s}` | `session.usage` + idle final |

**Étiquetage des agents.**
- Les custom tools portent `agent`.
- Pour les autres événements des sous-agents (messages, `bash`), le pont suit les fils via
  `session.thread_created` et les statuts de fil. Si un flux par fil est disponible (voir le
  cookbook *« Multiagent: watch a curriculum team work in real time »*), il est utilisé pour
  enrichir le log.
- Sinon, `emit_progress` suffit : les prompts imposent aux sous-agents de l'appeler à chaque étape
  significative.

**Score** :
- pénalités par sévérité : critical 10, major 6, minor 3 ;
- `score = round(100 × (1 − ouvert / (total_détecté × 1.6)))`, total figé à la fin de l'audit ;
- statut EAA : *non-compliant*, puis *partially compliant*, puis *compliant (automated scope)*,
  jamais « fully compliant ».

---

## 11. Boutique démo piégée : `demo-shop/` (« Maison Lumière »)

*Cible temporaire, remplaçable (§20). Elle n'est pas déployée sur Vercel.*

**Pages** : HTML/CSS/JS statique, contenu en français. `index.html`, `product.html`, `cart.html`
et `checkout.html` partagent le même en-tête et pied de page ; s'y ajoutent `styles.css` et
`img/*.svg`. `checkout.html` n'est atteignable que via un `onclick="location.href=…"`.

| Défaut | Pages | WCAG | axe ? | Final attendu |
|---|---|---|---|---|
| Texte gris clair (`.hero p` sur fond `#faf7f2`, `.price-note`, `.footer`) | toutes | 1.4.3 | oui | validé après un refus (régression visuelle) |
| `<html>` sans `lang` | index | 3.1.1 | oui | validé |
| Images produit sans `alt` | index, cart | 1.1.1 | oui | validé |
| `alt="image"` sur la photo produit | product | 1.1.1 | non | needs_human |
| `*:focus{outline:none}` | toutes | 2.4.7 | non | validé |
| Boutons-icônes 🔍 ♡ 🛒 sans nom | en-tête | 4.1.2 | non | validé (fusionné sur toutes les pages) |
| « Ajouter au panier » en `div onclick` | product | 2.1.1 | non | validé après un refus |
| Tailles en `div` cliquables | product | 2.1.1 / 4.1.2 | non | validé |
| « Passer commande » / « Payer » en `div` | cart, checkout | 2.1.1 | non | validé |
| Placeholders sans labels | checkout | 3.3.2 | non | validé |
| Erreur en bordure rouge seule | checkout | 3.3.1 | non | validé |
| « En savoir plus » ×4 | index | 2.4.4 | non | validé |
| Pas de `h1`, `h3` direct | index | 1.3.1 | non | validé |
| `<title>Paiement</title>` | checkout | 2.4.2 | non | validé |
| Boutons − + 🗑 sans nom | cart | 4.1.2 | non | validé |
| `<iframe>` de paiement tiers | checkout | 1.3.1 | non | needs_human |

Le contenu est compressé en `demo-shop.tgz` par le pont et monté dans la session.

---

## 12. Outils déterministes du sandbox : `sandbox_tools/`

Ces scripts Python tournent **dans le sandbox**. Ils sont montés via `tools.tgz` et lancés par
les agents avec `bash`. Chacun écrit un JSON sur stdout et ne lève jamais d'exception non gérée :
il sort avec un code non nul et un JSON `{"error": "...actionable..."}`.

| Script | Rôle |
|---|---|
| `common.py` | Lancement Chromium (`executable_path=/usr/bin/chromium`, `--no-sandbox`), chemin axe (`node_modules/axe-core/axe.min.js` global npm, ou copie vendorisée dans le tgz), conversion `wcag143 → 1.4.3` |
| `crawl.py <url>` | Parcours en largeur, y compris les `onclick` |
| `audit.py <url>` | Violations axe (tags `wcag2a, wcag2aa, wcag21a, wcag21aa`), nœuds tronqués |
| `keyboard.py <url>` | Ordre de tabulation, focus visible, interactifs non focusables |
| `baseline.py` / `reaudit.py` | Toutes les pages : axe + clavier + captures → `/workspace/arma/{baseline,final}.json` |
| `compare.py <url>` | `resolved`, `still_failing`, `new_violations_regressions`, `changed_pixels_ratio`, captures before/after/diff (Pillow) |
| `audit_static.js` | Fallback sans navigateur (jsdom + axe-core) |

**axe-core** est vendorisé dans `tools.tgz`, pour ne pas dépendre du npm du sandbox.

---

## 13. Pont local : `bridge.py` + `server.py`

**`bridge.py run [--live] [--budget-cents N] [--model-override sonnet]`** enchaîne :
1. **Compression des entrées** : `demo-shop.tgz` et `tools.tgz` ; upload via Files API
   (`client.files.upload`) avec la rubric.
2. **Création de la session** (§5.3). Ouvrir le stream **avant** d'envoyer
   `user.message` + `user.define_outcome`.
3. **Boucle sur le stream** :
   - `agent.custom_tool_use` → handler §6 → `user.custom_tool_result` (aussi pendant
     `running` : ne pas attendre l'idle) ;
   - `agent.message` / `agent.tool_use` / `agent.tool_result` / statuts de fil →
     événements `log` et `agent.status` ;
   - `span.outcome_evaluation_*` → `outcome` ;
   - `session.usage` → coût ;
   - `session.error` → log `err`. Si `retry_status` indique une relance automatique, continuer ;
   - `session.status_idle` avec `end_turn` **et** outcome terminal → fin. Avec
     `requires_action` → répondre aux événements listés. Avec `budget_reached` → fin propre et
     log.
4. **Reconnexion** : si le stream coupe, rouvrir, puis
   `client.beta.sessions.events.list(session.id)` pour dédoublonner par `event.id` (pattern de la
   doc). Le run continue côté serveur : c'est l'argument « long running ».
5. **Fin** :
   - `client.beta.files.list(scope_id=session.id, betas=["managed-agents-2026-04-01"])` →
     télécharger les sorties dans `state/out/` (réessayer après quelques secondes si un fichier
     manque) ;
   - appliquer `patches/` sur une copie locale du site (`runs/demo-shop`, `git am`) → branche
     locale ;
   - émettre `document.written`, `pr.ready` et `run.finished` ;
   - lancer `eval/run_eval.py` et émettre `eval`.
6. **Enregistrement** de tout dans `recordings/run-<date>.jsonl`.

**`bridge.py resume <session_id>`** se rattache à une session existante (historique + stream).

**`server.py` (FastAPI)** :
- `GET /api/events` (SSE) ;
- `GET /api/state` ;
- `POST /api/run` (lance `bridge.run` en tâche de fond) ;
- `POST /api/pr` (§14) ;
- statique `web/`.

---

## 14. Envoi de la PR

- **Mode réel**, si `GITHUB_REPO` est défini, `gh auth status` est OK et un remote existe :
  1. `git push` de la branche locale reconstruite à partir des patches ;
  2. `gh pr create --title "a11y: EAA remediation, WCAG 2.1 AA" --body-file state/out/pr-body.md`,
     plus `--reviewer` si fourni.
- **Sinon**, envoi simulé.
- **Dans les deux cas**, le corps est précédé du message de la compliance et de la mention
  « Approved by compliance ».
- **Slack, Jira et email** restent simulés et sont affichés comme tels.
- **En replay sur Vercel**, l'envoi est entièrement simulé côté client.

---

## 15. Dashboard : `web/`

Identique à la v1 (voir `reference/arma-dashboard-prototype.html`) :
- barre de commande, rail des phases ;
- score (jauge, statut EAA, principes POUR, sparkline) et KPIs ;
- onglets Findings (lignes dépliables : spécification, impact, preuve, diff, piste de
  vérification), Pull request (formulaire et envoi) et Accessibility statement ;
- équipe d'agents ;
- log live.

**Ajouts** :
- **Badge « Hosted on Claude Managed Agents · session <id court> »** dans la barre.
- **Carte « Independent grader »** sous le score : itération, `result`, explication.
- **Carte « Eval »** : métriques vs seuils, PASS/FAIL. Si `eval/history.csv` existe, une
  mini-courbe des versions du hill climb.
- **L'équipe d'agents reflète les fils** : Lead, Auditors ×N, Developer, Tester et Writer.

**Exigences** : accessible (clavier, focus, contrastes, ARIA, `prefers-reduced-motion`), thème
clair et sombre, sans scroll horizontal à 400 px. Au chargement, il affiche le dernier run
terminé. Les sources sont `?mode=live|replay`, avec repli automatique sur le replay.

---

## 16. Arborescence

```
arma/
├── CLAUDE.md  README.md  requirements.txt  .env.example  claude-lock.json
├── arma-spec.md  arma-build-plan.md  reference/arma-dashboard-prototype.html
├── managed/
│   ├── environment.yaml
│   ├── agents/{lead,page-auditor,developer,tester,writer}.md
│   ├── rubric.md
│   └── prompts/brief.md            # user.message de démarrage
├── sandbox_tools/                  # → tools.tgz (avec vendor/axe.min.js)
├── demo-shop/                      # → demo-shop.tgz
├── arma_bridge/
│   ├── events.py   (EventBus → jsonl + SSE)
│   ├── store.py    (ledger + machine à états + dédoublonnage)
│   ├── scoring.py
│   ├── custom_tools.py (handlers §6)
│   ├── translate.py (events Managed Agents → contrat dashboard)
│   ├── outputs.py  (téléchargement, git am)
│   └── pr.py
├── bridge.py  server.py
├── eval/{ground_truth.json, run_eval.py, history.csv, results/}
├── web/{index.html, styles.css, app.js, recordings/{fixture,demo-run}.jsonl, vercel.json}
├── scripts/{make_fixture.py, pick_demo_run.py, export_logs.py, check_web.py, smoke_sandbox.py}
└── deliverables/{agent-design.txt, agent-logs.txt, links.md}
```

---

## 17. Pièges et règles Managed Agents

- **Beta header** : `managed-agents-2026-04-01`, posé automatiquement par le SDK `anthropic` et
  `ant`. Pour `files.list(scope_id=…)`, passer `betas=["managed-agents-2026-04-01"]`.
- **Ouvrir le stream avant d'envoyer** le premier événement.
- **Répondre à chaque `agent.custom_tool_use` dès réception**, même si la session est `running`.
  Les appels bloquants des sous-agents arrivent sur le fil principal.
- **Multiagent à un seul niveau** : un sous-agent avec `multiagent` provoque une erreur 400.
  `predefined_agents` contient 20 agents au plus, et une session 25 fils enfants au plus (les fils
  inactifs comptent). Quatre auditeurs, un développeur, un testeur et un rédacteur tiennent
  largement.
- **Fils persistants** : le lead peut envoyer un suivi au **même** développeur. C'est ce qui rend
  les relances crédibles.
- **Versions d'agents** : les agents qui en référencent d'autres restent épinglés à la version
  résolue à leur création. Après une mise à jour d'un sous-agent (hill climb), **ré-appliquer le
  lead** (`ant apply`) pour qu'il pointe vers la nouvelle version.
- **Sorties** : uniquement depuis `/mnt/session/outputs/`, avec un délai de quelques secondes après
  l'idle. **Télécharger avant de supprimer** une session.
- **Budget** : il se fixe à la création de la session. À `budget_reached`, la session se met en
  pause.
- **Réseau `limited`** : le site est servi en local dans le sandbox, donc aucun hôte externe n'est
  nécessaire. Ne jamais appeler `playwright install`.
- **Noms de custom tools** : jamais de préfixe `mcp__` ou `ant__`, et pas de collision avec
  `bash`, `read`, etc.
- **Coût** : en développement, override `claude-sonnet-5-5` pour tous les agents. Le run enregistré
  final utilise la configuration nominale.

---

## 18. Definition of done

- [ ] L'URL Vercel rejoue un **vrai run Managed Agents**, en navigation privée, sur mobile et en
      thème sombre.
- [ ] Le log montre :
  - les auditeurs parallèles ;
  - au moins un refus du testeur suivi d'une validation dans le même fil développeur ;
  - au moins un rollback ;
  - des commits par critère.
- [ ] La carte « Independent grader » affiche `satisfied`, ou `needs_revision` puis `satisfied`.
- [ ] La carte « Eval » est PASS, et l'historique du hill climb est présent si le temps l'a permis.
- [ ] Le score passe de *non-compliant* à *partially compliant*, avec les deux problèmes
      `needs_human` explicités.
- [ ] « Send PR to engineering » aboutit : vraie PR si configurée, sinon simulée et signalée.
- [ ] La déclaration est copiable et ne prétend jamais à une conformité totale.
- [ ] Le dashboard est navigable entièrement au clavier.
- [ ] `deliverables/agent-design.txt`, `deliverables/agent-logs.txt` et le MP4 existent.

---

## 19. Script de pitch

1. **Problème.** EAA, procès en France, overlays sanctionnés, scanners aveugles à la majorité des
   problèmes.
2. **« Run audit ».** Une session Managed Agents démarre. Le lead lance les auditeurs en parallèle,
   et le compteur « missed by scanners » monte.
3. **L'équipe.** Le testeur refuse, le même développeur corrige, puis commit ; le rollback pour
   régression visuelle ; le score qui monte.
4. **Prove it worked.** Le grader indépendant renvoie *satisfied*, l'eval contre la vérité terrain
   est PASS, avec la courbe du hill climb.
5. **Vue compliance.** Spécification, preuve, diff ; les deux « Needs review » restent honnêtement
   ouverts.
6. **« Send PR to engineering »** et la déclaration d'accessibilité prête.
7. **Business.** Abonnement avec re-audit programmé à chaque déploiement (scheduled deployments),
   marque blanche pour les agences.

---

## 20. Changer de cible plus tard (vrai site)

La cible d'audit est isolée dans un seul fichier de configuration, pour pouvoir passer de
Maison Lumière à un vrai site sans toucher au reste.

**`targets/maison-lumiere.json`** (par défaut) :
```json
{"name":"Maison Lumière","source":{"type":"archive","path":"demo-shop/"},
 "serve":"local","start_url":"http://127.0.0.1:8765/index.html",
 "repo":null,"ground_truth":"eval/ground_truth.json"}
```

**Plus tard, `targets/<vrai-site>.json`** :
```json
{"name":"…","source":{"type":"git","url":"https://github.com/<org>/<repo>","ref":"main"},
 "serve":"command","serve_cmd":"npm ci && npm run build && npm start -- -p 8765",
 "start_url":"http://127.0.0.1:8765/","repo":"<org>/<repo>","ground_truth":null}
```

**Ce qui change avec un vrai site** :
- le pont empaquette ou clone la source à partir de `source` ;
- le brief indique comment servir le site dans le sandbox ;
- `packages` et `allowed_hosts` de l'environnement sont à adapter (npm, et l'hôte GitHub si on
  clone) ;
- sans `ground_truth`, l'eval ne garde que les métriques sans vérité terrain (`false_fix`,
  `regressions`, `honesty`) ;
- l'outcome et la rubric restent valables.

**Usage** : `bridge.py run --target targets/<nom>.json`. Le dashboard affiche le nom de la cible
dans la barre.
