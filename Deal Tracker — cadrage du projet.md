# Deal Tracker — cadrage du projet

Oct 15, 2026 · @Manon

## L'idée

Un analyste de due diligence persistant pour les fonds VC et private equity : il suit chaque deal du premier deck jusqu'au comité d'investissement, vérifie les affirmations, garde la trace de ce qui reste non résolu et met à jour ses conclusions quand de nouvelles preuves arrivent.

**Pitch** : « The analyst who never drops the ball. » Contrairement à un outil de recherche ponctuel, il sait où il s'est arrêté, ce qui reste à vérifier, et reprend le travail dès qu'une information arrive. Chaque conclusion est traçable, chaque communication externe passe par une validation humaine, et la décision reste au partner.

Le nom reste à arrêter : éviter « Autopilot », qui suggère une absence de contrôle humain.

## Client et problème

**Client** : les fonds VC et private equity, en priorité les petites et moyennes équipes où chaque analyste mène plusieurs deals en parallèle.

**Problème** : une due diligence s'étale sur des semaines et se disperse entre deck, data room, emails et appels. Les questions ouvertes se perdent, les relances tombent, et une contradiction découverte tard peut remettre en cause une conclusion déjà actée.

**Ce que le fonds achète** : aucun deal ne perd le fil, chaque conclusion est sourcée, et le comité reçoit un mémo qui distingue clairement le confirmé, le contesté et l'inconnu.

## Fonctionnement

Le deal est l'unité de travail : un dossier unique et persistant, pas une suite de conversations indépendantes. Il contient les documents, les affirmations à vérifier, les preuves, les questions ouvertes, les décisions et un journal d'événements.

1. **Le deal démarre** : l'utilisateur importe un deck. L'orchestrateur extrait les affirmations, crée les tâches et les agents d'analyse produisent une première évaluation.
2. **Le deal évolue** : un nouveau document arrive. Le système identifie les affirmations et questions concernées, relance uniquement les tâches touchées et met à jour le statut des risques. Une contradiction peut rouvrir une question déjà close.
3. **Le deal aboutit** : l'agent sceptique challenge les conclusions, le vérificateur contrôle les sources, et le système produit le mémo d'investissement.

La persistance est réelle, jamais simulée : checkpoints, état des tâches et preuves sont enregistrés. Après une interruption, le système reprend exactement là où il s'était arrêté.

## Architecture des agents

&#91;embedded content: architecture des agents et boucle de vérification\]

Tous les agents lisent et écrivent dans l'état du deal. Les documents passent d'abord par un garde-fou qui les traite comme des données. Le vérificateur renvoie à l'orchestrateur toute affirmation sans preuve ou toute contradiction, ce qui relance uniquement les tâches concernées.

**Récupération d'erreurs** : un agent qui échoue ou renvoie une sortie invalide est relancé ; une source inaccessible est remplacée par une autre ou signalée comme limite dans le mémo. Les questions destinées au founder attendent une validation humaine avant tout envoi.

## Prototype et vision

La vision couvre plusieurs semaines de deal ; le prototype doit prouver cette continuité en quelques minutes de démo.

| Vision produit | Prototype du hackathon |
| --- | --- |
| Suivre un deal pendant plusieurs semaines | Plusieurs cycles de travail persistants, temps accéléré |
| Connecter emails et data room | Importer un deck, puis ajouter un document |
| Attendre et relancer les founders | Générer une liste de questions à valider humainement |
| Organiser les appels de références clients | Reporté |
| Préparer le comité d'investissement | Générer un mémo réellement exploitable |
| Historique complet du deal | Journal d'événements et checkpoints réels |

Les documents de démo s'appuient sur un vrai deck public plutôt qu'un dossier inventé, pour que le mémo soit vérifiable.

## Scénario de démo

Le moment fort : un nouveau document contredit une affirmation, rouvre une question close et fait changer la conclusion du mémo.

1. **Ouverture** : import du deck, les agents se répartissent le travail dans le journal en direct.
2. **Première analyse** : un rapport encore plein de trous, avec la liste des questions à envoyer au founder, en attente de validation.
3. **Récupération d'erreur** : une source est inaccessible ou une sortie d'agent invalide ; le système réessaie, change de source ou signale la limite.
4. **Tentative d'injection** : un document contient une instruction cachée ; le système la traite comme une donnée et la signale.
5. **Pause et reprise** : interruption puis relance ; les tâches terminées sont conservées et seules les restantes repartent.
6. **Nouveau document** : une contradiction rouvre une question close, un red flag disparaît, un autre apparaît.
7. **Mémo final** : confirmé, contesté, inconnu, chaque point relié à sa source.

Format : enregistrement accéléré d'un run complet, puis quelques étapes en direct.

## Responsible design

- **Documents non fiables** : tout ce qui vient du founder est traité comme une donnée, jamais comme une instruction. Les tentatives d'injection sont détectées et signalées.
- **Confidentialité** : les documents de la data room sont isolés par deal, non conservés après le deal, et jamais utilisés pour autre chose.
- **Contrôle humain** : aucun message externe n'est envoyé sans validation. L'agent recommande, le partner décide.
- **Traçabilité** : chaque conclusion est reliée à sa source ; une affirmation sans preuve est marquée comme non vérifiée.
- **Données personnelles** : l'analyse de l'équipe se limite aux informations professionnelles publiques, sans profilage personnel.
- **Limites affichées** : le mémo indique son niveau de confiance et ce qui reste inconnu.

## Modèle économique et différenciation

**Modèle** : un abonnement par fonds, dont l'usage croît avec le nombre de deals suivis. Le produit accompagne tout le cycle d'un deal, ce qui justifie un revenu récurrent plutôt qu'un paiement par rapport.

**Différenciation** : les outils d'IA pour VC sont nombreux, mais ils produisent des analyses ponctuelles. Ici, la valeur tient à l'état persistant du deal et à la traçabilité de chaque conclusion. Le produit prépare le jugement du partner sans prétendre le remplacer.

**Extensions futures** : connexion aux emails et data rooms, relances automatiques après validation, appels de références, suivi du portefeuille après investissement.

## Ordre de construction

Le socle passe avant tout : sans état persistant, il n'y a pas de long-running.

- [ ] État du deal persistant : documents, affirmations, tâches, preuves, journal d'événements, checkpoints
- [ ] Orchestrateur : extraction des affirmations, création et reprise des tâches
- [ ] Agents d'analyse : marché, finance, équipe, concurrence
- [ ] Mise à jour ciblée sur nouveau document, avec réouverture des questions en cas de contradiction
- [ ] Gestion des erreurs : nouvel essai, source alternative, limite signalée
- [ ] Garde-fou contre l'injection dans les documents
- [ ] Agent sceptique et vérificateur
- [ ] Mémo d'investissement final
- [ ] Interface minimale : un journal d'événements lisible plutôt qu'un tableau de bord
- [ ] Enregistrement accéléré du run complet pour la démo
