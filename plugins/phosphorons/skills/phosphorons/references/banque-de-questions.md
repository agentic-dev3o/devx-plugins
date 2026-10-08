# Banque de questions

Pour chaque niveau : les questions qui font avancer, les réponses à ne pas laisser passer et les angles pour mettre le problème à l'épreuve. C'est une réserve d'idées pour formuler tes recommandations, pas un script : propose toujours une lecture avant de demander.

## Sommaire

1. Cadre
2. Pour qui (personas)
3. Le pari
4. Principes
5. Fonctionnalités
6. Détail : objets métier, parcours, écrans, règles de gestion, critères d'acceptation
7. Cohérence

## 1. Cadre

**À demander**
- En une ou deux phrases : qu'est-ce que c'est, et que doit-il permettre ?
- À qui est-il destiné : à toi seul, à ton équipe ou ton organisation, ou à des utilisateurs extérieurs ? Sera-t-il vendu ou diffusé ?
- Qu'est-ce qui motive sa création : un problème à résoudre, un quotidien à simplifier, une méthode à outiller, une routine à automatiser ?
- Comment tu t'y prends aujourd'hui, sans lui ?

**À ne pas laisser passer**
- Un slogan (« le Doctolib de X », « une IA qui révolutionne Y ») : demander ce que le produit fait concrètement.

**À ne pas faire**
- Exiger un problème ou une douleur quand l'utilisateur décrit un gain, une méthode ou une envie : une raison d'être suffit.

## 2. Pour qui (personas)

**Pour un outil personnel**
- Dans quelle situation vas-tu t'en servir, et à quelle fréquence ?
- Qu'est-ce qu'il va te faire gagner : du temps, de la régularité, de la fiabilité, de la sérénité ?
- Quelqu'un d'autre va-t-il s'en servir ? Si non, un seul persona suffit : toi.

**Rôle dans la décision (outil interne ou produit de marché)**
- Qui signe ou paie ? (décideur)
- Qui s'en sert tous les jours ? (utilisateur)
- Qui va porter le projet en interne ? (prescripteur)
- Qui peut tout arrêter : sécurité, juridique, DSI, responsable de l'outil remplacé ? (bloqueur)
- Le décideur est-il aussi l'utilisateur ? Sinon, de quoi chacun a-t-il besoin pour dire oui ?

**Situation**
- Qu'est-ce qui déclenche le besoin ? Une échéance, un événement, une demande de quelqu'un ?
- Quel est le contournement actuel, et que coûte-t-il (temps, argent, risque, image) ?
- Quel progrès ces personnes recherchent-elles, avec leurs propres mots ?
- Qu'est-ce qui les fait hésiter à changer : la peur de la migration, l'habitude, un échec passé ?

**Douleur (outil interne ou produit de marché)**
- À quel moment précis le problème fait-il mal ? Raconte-moi la dernière fois que c'est arrivé.
- Cherchent-elles activement une solution en ce moment ?
- Paient-elles déjà un contournement (outil, prestataire, heures supplémentaires) ?
- Y a-t-il une échéance ou une conséquence si rien ne change ?

**À ne pas laisser passer**
- L'âge, la ville ou les loisirs en guise de persona.
- Une fonctionnalité manquante présentée comme un problème (« il n'existe pas d'appli pour X ») : demander ce qui se passe mal sans elle. Pour un outil personnel, en revanche, « aucun outil ne fait ça à ma façon » est une raison d'être recevable.
- Un problème sans moment précis (« collaborer, c'est compliqué ») : demander la dernière situation concrète.
- Une entreprise en guise de persona : décrire la personne dont la crédibilité ou la prise de risque est en jeu.
- Trois utilisateurs et aucun bloqueur dans un produit B2B.
- Tous les personas en douleur critique.

## 3. Le pari

**À demander, une question à la fois (produit de marché)**
- Qu'est-ce que tu crois sur ce marché que la plupart des gens contesteraient ?
- Pourquoi vas-tu réussir là où d'autres ont échoué ou n'ont pas essayé ? Que vas-tu faire que les alternatives ne font pas ?
- Quel résultat, observé dans les prochains mois, prouverait que tu as tort ?
- Si ça marche, à quoi ressemble le quotidien de tes utilisateurs dans deux ou trois ans ?
- Le pari dépend-il d'un changement récent (une capacité nouvelle, une baisse de coût, une nouvelle réglementation) ? Sinon, on laisse le pourquoi maintenant vide.

**À demander, une question à la fois (outil personnel ou interne)**
- Qu'est-ce que cet outil changera concrètement, une fois en place ?
- Pourquoi le construire plutôt que de s'en tenir à un tableur ou à un outil existant ?
- Qu'est-ce qui montrerait, au bout d'un mois, qu'il ne te sert pas ?
- À quoi ressemblera ta façon de travailler quand il sera rodé ?

**À ne pas laisser passer**
- Une liste de fonctionnalités (« on a X, Y et Z ») : demander pourquoi cette combinaison l'emporte.
- Le problème reformulé (« les gens ont besoin d'une meilleure façon de faire X »).
- Une proposition de valeur que tout le monde revendique (« simple et rapide »).
- Un signal d'invalidation qui ne peut pas se déclencher (« si personne ne l'utilise ») : demander un signal précis, observable et lié au pari.
- Un pourquoi maintenant qui décrit une tendance plutôt qu'un changement (« l'IA est partout », « le marché est en croissance »).

**Angles de mise à l'épreuve, une fois le pari énoncé seulement**
- Produit de marché :
  - Douloureux : combien le problème leur coûte-t-il aujourd'hui, en chiffres ?
  - Urgent : pourquoi agiraient-ils ce trimestre plutôt que l'an prochain ?
  - Reconnu : nomment-ils ce problème d'eux-mêmes, sans qu'on le leur souffle ?
- Outil personnel ou interne :
  - Rentable : le gain vaut-il l'effort de construire puis de maintenir l'outil ?
  - Durable : t'en serviras-tu encore dans trois mois, une fois l'enthousiasme retombé ?
  - Nécessaire : un outil existant ne ferait-il pas l'affaire à 80 % ?

## 4. Principes

**À demander**
- Au vu du pari, que le produit ne doit-il jamais faire ?
- Quel arbitrage feras-tu toujours dans le même sens (vitesse plutôt qu'exhaustivité, confidentialité plutôt que confort…) ?
- Quelle idée de fonctionnalité refuserais-tu même si un gros client la réclamait, et pourquoi ?

**Tester chaque principe**
- Peut-on citer une fonctionnalité plausible qui l'enfreindrait ? Sinon, il est trop vague.
- Se rattache-t-il au pari ? Sinon, c'est une préférence, pas un principe.

**À ne pas laisser passer**
- « Centré utilisateur », « simple », « sécurisé », « de qualité », « scalable ».

## 5. Fonctionnalités

**À demander**
- Que doit pouvoir faire un persona dès le premier jour pour que le pari puisse seulement être testé ?
- Pour cette fonctionnalité : quel persona, et qu'est-ce qui change pour lui une fois qu'elle existe ?
- Comment sauras-tu qu'elle fonctionne ? Cite quelque chose d'observable ou de mesurable.
- Qu'est-ce qui n'en fait explicitement pas partie en v1 ?
- Laquelle n'est pas indispensable pour tester le pari en v1 ?

**À ne pas laisser passer**
- Des modules techniques présentés comme des fonctionnalités (authentification, back-office, paramètres, API).
- Une fonctionnalité sans persona, ou avec des critères de succès que personne ne pourrait observer.
- Plus de huit fonctionnalités en v1.

## 6. Détail

**Objets métier**
- Quels mots tes utilisateurs emploient-ils ? Que doit contenir chacun de ces objets ?
- Comment sont-ils liés : un-à-plusieurs, plusieurs-à-plusieurs ? Qui possède quoi ?
- Qu'est-ce qui peut être supprimé, archivé, ou ne doit jamais changer ?

**Parcours**
- Qu'est-ce qui le déclenche : une action utilisateur, une tâche planifiée, un événement entrant ?
- Qui réalise chaque étape : le persona, le système, un service externe ?
- À chaque point de décision : que se passe-t-il sur l'autre issue ?
- En cas d'échec, qui le constate, et que peut-il faire ?

**Écrans**
- De quels écrans cette fonctionnalité a-t-elle besoin, et à quoi sert chacun ?
- Qu'affiche chaque écran sans données, pendant le chargement, en cas d'erreur ?

**Règles de gestion**
- Qu'est-ce qui doit rester vrai quoi qu'il arrive (plafonds, immuabilité, droits d'accès, ordre des opérations) ?

**Critères d'acceptation**
- Étant donné quel état de départ, quand quelle action, alors quel résultat observable ?

## 7. Cohérence

- Quelle fonctionnalité ne se rattache ni à un persona ni au pari ?
- Quel principe une fonctionnalité prévue met-elle à mal ?
- Quelles décisions se contredisent ?
- Que ne savons-nous toujours pas, et qui peut y répondre ?
