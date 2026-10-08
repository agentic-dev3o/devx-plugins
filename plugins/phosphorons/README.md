# phosphorons

Passe ton produit sur le grill jusqu'à ce que sa définition tienne la route, et repars avec une spécification fonctionnelle prête pour la maquette et le développement. Produit de marché, outil interne ou outil personnel : la méthode s'adapte à la destination.

Inspiré du skill [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) de Matt Pocock : le même interrogatoire méthodique en arbre de décisions, par tours de questions courts accompagnés d'une réponse recommandée, mais pensé pour la définition produit et rédigé en français.

## Installation

```
/plugin install phosphorons@devx-plugins
```

## Ce que fait le skill

**Se déclenche quand tu demandes à :** phosphorer sur une idée de produit, la challenger ou la mettre à l'épreuve, définir un produit ou un MVP, rédiger une spec fonctionnelle, un PRD ou un cahier des charges.

L'entretien suit une colonne vertébrale fixe ; chaque niveau ne s'ouvre que lorsque le précédent tient :

1. **Cadre** : le produit, sa destination (outil personnel, outil interne ou produit de marché) et sa raison d'être, qui n'est pas forcément un problème : simplifier son quotidien ou outiller une méthode suffit
2. **Pour qui** : les personas, avec leur situation (jobs-to-be-done), ce qui est en jeu (douleur, ou gain attendu pour un outil personnel) et, si d'autres doivent l'adopter, leur rôle dans la décision
3. **Le pari** : la conviction qui justifie le produit (ce qui le fera gagner face aux alternatives, ou pourquoi construire cet outil plutôt que d'utiliser l'existant), ce qui l'invaliderait, l'état cible, et le pourquoi maintenant (seulement si le timing compte)
4. **Principes** : quelques lois testables qui découlent du pari
5. **Fonctionnalités** : une carte de la v1 où chaque fonctionnalité sert un persona et se rattache au pari
6. **Détail** : objets métier, parcours en couloirs, écrans et leurs états, règles de gestion, critères d'acceptation
7. **Cohérence** : contradictions et questions ouvertes rendues explicites

L'agent cherche les faits lui-même et te soumet chaque décision avec sa recommandation. Il n'écrit jamais ton pari à ta place.

## Le livrable

Une spécification fonctionnelle sous forme de page HTML autonome (par défaut `docs/produit/<slug>-spec-fonctionnelle.html`), mise en page sur mesure pour être lisible : sommaire, personas en fiches, parcours et modèle de données en Mermaid, inventaire des écrans et de leurs états, critères d'acceptation, journal des décisions, questions ouvertes, brief de maquette et ordre de développement conseillé. Elle se remet telle quelle à un designer ou à un agent de code. Avec Claude, elle est livrée sous forme d'Artifact, prête à lire et à partager.

Les longues sessions peuvent tenir un journal de décisions (`docs/produit/<slug>-journal.md`) pour reprendre plus tard.
