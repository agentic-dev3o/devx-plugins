# Gabarit de spécification fonctionnelle

La spec est une page HTML autonome. Ce gabarit fixe le **contenu attendu** ; la **mise en page** se compose sur mesure pour chaque produit, en suivant les règles ci-dessous et en partant du squelette en fin de fichier.

Rédige la page dans la langue de l'utilisateur. Chaque affirmation doit avoir été tranchée pendant la session ; les hypothèses acceptées portent un badge « Hypothèse ». Une section sans contenu tranché affiche « À trancher » et renvoie à la question ouverte correspondante.

## Sommaire

- Contenu attendu : les douze sections de la spec
- Mise en forme : les règles de présentation
- Exemples de diagrammes : un parcours et un modèle de données en Mermaid
- Squelette de départ : une page HTML minimale à adapter

## Contenu attendu

1. **En bref** : le produit (ce que c'est, ce qu'il permet), sa destination (outil personnel, outil interne ou produit de marché), le ou les personas principaux, le pari, l'état cible et la v1 en une phrase.
2. **Produit et raison d'être** : le produit en une ou deux phrases ; sa destination (pour qui, et s'il sera vendu ou diffusé) ; sa raison d'être (problème à résoudre, quotidien à simplifier, méthode à outiller, pratique à systématiser…) ; comment on s'y prend aujourd'hui sans lui, et ce que ça coûte.
3. **Personas** : pour chacun, sa situation (« Quand …, je …, mais je voudrais …, pour …. Ce qui me retient : … »), ce qui est en jeu (le gain attendu, ou une douleur latente, modérée, forte ou critique, avec l'élément observé qui la justifie) et, si d'autres doivent adopter le produit, son rôle dans la décision (décideur, utilisateur, prescripteur ou bloqueur).
4. **Thèse** : le pari, ce qui l'invaliderait (un signal observable), l'état cible, et le pourquoi maintenant (ou « Ne dépend pas du moment », ou « Sans objet » pour un outil personnel ou interne).
5. **Principes** : chaque principe en une phrase testable, avec sa justification rattachée au pari.
6. **Carte des fonctionnalités** : un tableau fonctionnalité · persona · intention · critères de succès · priorité (v1 ou plus tard).
7. **Fonctionnalités de la v1** : pour chacune, son intention, le persona servi, son périmètre (inclus, exclu), les objets métier concernés, son parcours (diagramme), ses écrans et leurs états (vide, chargement, erreur, succès), ses règles de gestion et ses critères d'acceptation (« Étant donné… quand… alors… »).
8. **Modèle de données** : un diagramme entité-relation, puis un tableau objet métier · attributs clés · remarques (cycle de vie, immuabilité, propriétaire).
9. **Hors périmètre** : ce que le produit ne fera pas, et pourquoi.
10. **Décisions et règles** : le journal des décisions (décision, justification, date) et les règles permanentes.
11. **Contradictions et questions ouvertes** : sujet, type (contradiction ou question), ce que ça bloque, qui tranche.
12. **Prochaines étapes** : le brief de maquette (écrans par ordre de priorité, avec l'état le plus important de chacun) et l'ordre de développement conseillé (la plus petite tranche qui permet de tester le pari). C'est la seule section que tu proposes au lieu de la reprendre de la session : elle porte le badge « Proposition ».

## Mise en forme

- **Un seul fichier autonome** : le CSS dans une balise `<style>`, aucune dépendance hormis le script Mermaid.
- **Une mise en page au service du contenu**, pas du markdown converti : fiches pour les personas, encadré pour le pari et ce qui l'invaliderait, tableaux pour la carte des fonctionnalités et le modèle de données, grille pour l'inventaire des écrans.
- **Une navigation** : un sommaire à ancres en tête de page, ou en colonne latérale sur grand écran.
- **Des statuts visibles** : des badges « Hypothèse », « À trancher » et « Proposition » repérables d'un coup d'œil.
- **Lisible partout** : la prose limitée à ~70 caractères par ligne, une typographie système, un contraste suffisant, les thèmes clair et sombre via `prefers-color-scheme`, une mise en page qui tient sur mobile (tableaux défilables horizontalement) et s'imprime proprement (`@media print`).
- **Des diagrammes Mermaid** dans des blocs `<pre class="mermaid">` : leur code reste lisible si le script ne se charge pas. Échappe `<` et `&` dans les libellés. Dessine les parcours de haut en bas (`flowchart TB`) : de gauche à droite, ils deviennent illisibles sur un téléphone. Garde les diagrammes à leur taille naturelle, avec un défilement horizontal dans leur cadre plutôt qu'un rétrécissement.
- **Une page accessible** : l'attribut `lang` sur `<html>`, des titres hiérarchisés (un seul `h1`, puis `h2` et `h3`), des en-têtes `<th>` dans les tableaux.

## Exemples de diagrammes

Un parcours, avec un couloir par acteur ; chaque point de décision a ses deux issues :

```html
<pre class="mermaid">
flowchart TB
  subgraph P[Gérant]
    p1[Valide la relance]
    p2[Corrige l'adresse e-mail]
  end
  subgraph S[Système]
    s1[Prépare la relance]
    d1{Adresse valide ?}
  end
  subgraph X[Service d'e-mail]
    x1[Envoie la relance]
  end
  p1 --> s1 --> d1
  d1 -- oui --> x1
  d1 -- non --> p2
</pre>
```

Le modèle de données :

```html
<pre class="mermaid">
erDiagram
  CLIENT ||--o{ FACTURE : "reçoit"
  FACTURE {
    string numero
    date dateEmission
    decimal montantTotal
  }
</pre>
```

## Squelette de départ

Un point de départ à adapter librement, pas un cadre imposé.

```html
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nom du produit : spécification fonctionnelle</title>
  <style>
    :root { --fond: #ffffff; --texte: #1c1c1c; --discret: #6b6b6b; --trait: #e4e4e4; --accent: #3451d1; }
    @media (prefers-color-scheme: dark) {
      :root { --fond: #151515; --texte: #ececec; --discret: #9b9b9b; --trait: #2b2b2b; --accent: #8fa3ff; }
    }
    body { margin: 0; background: var(--fond); color: var(--texte); font: 16px/1.6 system-ui, sans-serif; }
    main { max-width: 960px; margin: 0 auto; padding: 32px 16px; }
    p, li { max-width: 70ch; }
    .tableau, .mermaid { overflow-x: auto; }
    .mermaid svg { max-width: none !important; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px; border-bottom: 1px solid var(--trait); text-align: left; vertical-align: top; }
    .badge { display: inline-block; padding: 2px 8px; border: 1px solid var(--trait); border-radius: 999px; font-size: 12px; color: var(--discret); }
    @media print { nav { display: none; } }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Nom du produit : spécification fonctionnelle</h1>
      <p>Version 1 · date · Statut : brouillon pour maquette et développement</p>
    </header>
    <nav><!-- sommaire : un lien vers chaque section --></nav>
    <section id="en-bref"><h2>En bref</h2></section>
    <!-- une section par entrée du contenu attendu -->
  </main>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.15.0/mermaid.min.js"></script>
  <script>
    mermaid.initialize({ startOnLoad: true, theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "default" })
  </script>
</body>
</html>
```
