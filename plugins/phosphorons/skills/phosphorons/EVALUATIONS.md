# Évaluations

Scénarios de référence pour tester le skill, au format recommandé par Anthropic. Chaque scénario se joue sur une instance neuve qui charge le skill ; une réponse passe si elle tient chaque comportement attendu. À rejouer avec chaque modèle visé (Haiku, Sonnet, Opus) après toute modification du skill. Les scénarios ne reprennent jamais l'exemple du SKILL.md, sinon le modèle le recopie et le test ne mesure plus rien.

```json
[
  {
    "skills": ["phosphorons"],
    "name": "E-1 · Un outil personnel n'a pas de marché",
    "query": "Je veux un petit outil pour suivre mes séances de course à pied selon le plan d'entraînement que je me suis construit. Aujourd'hui je note tout dans un carnet et je perds le fil au bout de trois semaines.",
    "expected_behavior": [
      "Propose une lecture du cadre (produit, destination « outil personnel », raison d'être) et la fait valider, au lieu de poser des questions ouvertes",
      "Ne pose aucune question de marché : ni intensité de la douleur, ni concurrence, ni rôle dans la décision d'achat, ni pourquoi maintenant",
      "Traite l'utilisateur comme l'unique persona, sans lui inventer de collègues",
      "Au pari, demande ce que l'outil changera et pourquoi le construire plutôt qu'utiliser l'existant, une question par échange, puis ce qui l'invaliderait",
      "Respecte le format d'un tour : questions numérotées, quatre au plus, chacune avec une recommandation qu'un « oui » valide"
    ]
  },
  {
    "skills": ["phosphorons"],
    "name": "E-2 · Une liste de fonctionnalités n'est pas un pari",
    "query": "On lance une app B2B de relance de factures pour les PME : relances automatiques, tableau de bord, intégration comptable. Écris-moi la spec.",
    "expected_behavior": [
      "N'écrit pas la spec d'emblée : ouvre l'entretien par le cadre, puis les personas",
      "Cherche le bloqueur, puisque l'argent et les données comptables sont en jeu",
      "Refuse la liste de fonctionnalités comme pari et demande la conviction non évidente qui fera gagner le produit, une question par échange",
      "Ne rédige jamais le pari à la place de l'utilisateur ; faute de pari, l'inscrit comme première question ouverte",
      "N'aborde le pourquoi maintenant qu'après avoir vérifié que le pari dépend du moment"
    ]
  },
  {
    "skills": ["phosphorons"],
    "name": "E-3 · Les faits se lisent, ils ne se demandent pas",
    "setup": "Un dépôt avec un README qui décrit le produit, un dossier docs/ et un code dont les routes exposent déjà trois fonctionnalités.",
    "query": "Phosphorons sur ce projet avant que j'ajoute la facturation.",
    "expected_behavior": [
      "Lit le README, la documentation et l'arborescence du code avant la première question, et les résume en trois lignes",
      "Ne demande à l'utilisateur aucun fait disponible dans le dépôt (stack, fonctionnalités existantes, vocabulaire)",
      "Propose un slug et l'emplacement par défaut docs/produit/<slug>-spec-fonctionnelle.html",
      "Part de l'existant pour proposer une lecture du cadre au lieu de réinterroger depuis zéro"
    ]
  },
  {
    "skills": ["phosphorons"],
    "name": "E-4 · La spec livrée tient la vérification",
    "setup": "La session a atteint le niveau 7 avec deux questions ouvertes ; l'agent peut créer des Artifacts et travaille dans un dépôt.",
    "query": "C'est bon pour moi, on a la même compréhension. Génère la spec.",
    "expected_behavior": [
      "Produit une page HTML autonome qui couvre les douze sections du gabarit, avec une mise en page composée pour le produit",
      "La livre sous forme d'Artifact HTML et enregistre aussi le fichier dans le dépôt",
      "Affiche « À trancher » dans chaque section sans contenu tranché, avec un renvoi à la question ouverte, et un badge « Hypothèse » sur chaque hypothèse acceptée",
      "Dessine chaque parcours en Mermaid avec un couloir par acteur et les deux issues de chaque point de décision",
      "Repasse la liste de vérification avant de livrer, puis conclut par un récapitulatif et la prochaine étape conseillée"
    ]
  },
  {
    "skills": ["phosphorons"],
    "name": "E-5 · Accélérer sans rien inventer",
    "query": "J'ai peu de temps : pose-moi le strict minimum et rédige la spec.",
    "expected_behavior": [
      "Augmente la part d'hypothèses, chacune signalée comme telle, et ne garde que les questions dont la réponse changerait la spec",
      "Continue à faire formuler le pari et ce qui l'invaliderait par l'utilisateur",
      "Demande la confirmation de la compréhension commune avant d'écrire la spec"
    ]
  }
]
```
