# Guide d'intégration — console d'administration web

Marketplace Burundi — API REST v1, espace `/api/v1/admin/`

Ce document s'adresse au développeur qui construit la **console web
d'administration** : une application de bureau, consultée sur grand écran par
deux ou trois personnes, pour surveiller la plateforme et modérer. Ce n'est
pas l'application mobile — celle-ci a son propre guide
([GUIDE_FLUTTER.md](GUIDE_FLUTTER.md)) et n'appelle jamais `/admin/...`.

La référence exhaustive des champs reste Swagger :
<http://127.0.0.1:8000/api/docs/>. Ce guide dit ce que Swagger ne dit pas :
qui a le droit de quoi, dans quel ordre construire les écrans, et où le
serveur refusera délibérément d'obéir.

---

## Sommaire

| Étape | Écran | Dépend de |
| ----- | ----- | --------- |
| [0](#0-les-regles-communes) | Les règles communes | — |
| [1](#1-connexion-et-droits) | Connexion et calcul des droits | 0 |
| [2](#2-tableau-de-bord-global) | Tableau de bord global | 1 |
| [3](#3-file-de-moderation) | File de modération (signalements) | 1 |
| [4](#4-comptes-utilisateurs) | Comptes : consulter, suspendre | 1 |
| [5](#5-catalogue-annonces) | Catalogue : modérer les annonces | 1 |
| [6](#6-categories) | Catégories | 1 |
| [7](#7-avis) | Avis : masquer, réafficher | 1 |
| [8](#8-litiges-historiques) | Litiges : stock, ventes, réservations | 1 |
| [9](#9-journal-daudit) | Journal d'audit | 1 |
| [10](#10-configuration-de-la-plateforme) | Configuration de la plateforme | 1 |

Je recommande cet ordre : le tableau de bord donne tout de suite une page
utile, la file de modération est l'écran le plus utilisé au quotidien, et la
configuration — la plus sensible — vient en dernier.

---

## 0. Les règles communes

### Base

```
http://127.0.0.1:8000/api/v1/admin/
```

Les routes d'administration partagent le même socle que le reste de l'API :
mêmes jetons, même enveloppe d'erreur, même pagination. Ce qui change, c'est
qu'elles exigent des **permissions** en plus du jeton.

### Authentification

Identique au mobile : `POST /api/v1/auth/login/`, puis sur chaque appel

```
Authorization: Bearer <access>
```

`access` vit **60 minutes**, `refresh` **15 jours** et **change à chaque
rafraîchissement** : écrasez-le en mémoire, sinon le suivant sera rejeté.

Sur un poste d'administration partagé, préférez le stockage **en mémoire** ou
`sessionStorage` à `localStorage` : la session se ferme avec l'onglet. Et
appelez `POST /api/v1/auth/logout/` avec le refresh à la déconnexion, pour le
mettre en liste noire côté serveur.

### Enveloppe d'erreur

```json
{
  "success": false,
  "status_code": 403,
  "message": "Vous n'avez pas la permission d'effectuer cette action.",
  "errors": {}
}
```

| Code | Dans cette console, signifie |
| ---- | ---------------------------- |
| `400` | règle métier ou champ invalide → afficher `errors`, puis `message` |
| `401` | jeton expiré → rafraîchir, sinon retourner au login |
| `403` | **votre compte n'a pas la permission** → l'écran n'aurait pas dû être accessible |
| `404` | l'objet n'existe pas |
| `405` | **la route n'accepte pas cette méthode** — et c'est souvent voulu (voir § 8 et 9) |

Un `403` dans cette console est presque toujours un défaut d'interface : les
droits sont connus **avant** l'appel (§ 1), donc une action interdite ne
devrait pas être proposée.

### Pagination, tri, filtres

```json
{ "count": 142, "next": "...?page=2", "previous": null, "results": [ ... ] }
```

`?page=`, `?page_size=` (défaut 20, maximum 100), `?ordering=champ` ou
`-champ`. Les filtres texte cherchent « contient » sans tenir compte de la
casse ; les intervalles s'écrivent `?created_at_gte=`, `?created_at_lte=`
(ISO 8601), `?montant_min=`, `?montant_max=`.

Sur grand écran, montez `page_size` à 50 ou 100 : les tableaux de modération
se lisent mieux ainsi, et le serveur plafonne de toute façon à 100.

---

## 1. Connexion et droits

### Le modèle d'accès : deux niveaux, pas plus

| Niveau | Comment on l'obtient | Portée |
| ------ | -------------------- | ------ |
| **Superutilisateur** | `manage.py createsuperuser` | **tout**, y compris les suppressions, la configuration et les statistiques globales |
| Groupe **`Moderateur`** | `manage.py init_groupes`, puis ajout du compte au groupe | consulter tout l'espace d'administration, suspendre un compte, modérer annonces et avis, traiter les signalements, lire le journal et les historiques |

Il n'y a **aucun autre groupe**. Tout compte hors de ces deux cas est un
utilisateur ordinaire : il reçoit `403` sur l'ensemble de `/admin/...`, et
continue d'utiliser normalement l'application mobile.

Django accorde au superutilisateur **toutes** les permissions : sa liste
`permissions` les contient effectivement toutes (113 aujourd'hui). Un test
sur la liste fonctionne donc, mais testez `is_superuser` **d'abord** — c'est
explicite, stable, et cela ne dépend pas du nombre d'applications installées.

### Ce que le groupe `Moderateur` ne peut pas faire

C'est délibéré, et votre interface doit le refléter plutôt que d'attendre un
`403` :

| Interdit au modérateur | Pourquoi |
| ---------------------- | -------- |
| toute suppression (`DELETE`) | un modérateur masque, suspend ou retire ; il n'efface pas |
| créer un compte, une annonce, un avis | il n'agit pas à la place des utilisateurs |
| lire `/admin/statistics/` | les chiffres globaux relèvent du superutilisateur |
| écrire dans `/admin/settings/` | la configuration relève du superutilisateur |
| écrire dans le journal d'audit | **personne** ne peut : aucune route d'écriture n'existe |

### Calculer les droits une fois, au démarrage

La réponse de connexion contient déjà tout :

```json
POST /api/v1/auth/login/
{ "username": "moderateur", "password": "Modo@2026" }

→ {
  "access": "...", "refresh": "...",
  "utilisateur": {
    "id": 3, "username": "moderateur",
    "is_superuser": false, "is_staff": false,
    "is_active": true, "statut_compte": "ACTIF",
    "groupes": ["Moderateur"],
    "permissions": [
      "accounts.change_user", "accounts.view_user",
      "categories.change_categorie", "categories.view_categorie",
      "messaging.change_signalementconversation",
      "messaging.view_signalementconversation",
      "moderation.view_journalaudit",
      "products.change_produit", "products.view_mouvementstock",
      "products.view_produit",
      "reservations.view_reservation",
      "reviews.change_evaluation", "reviews.view_evaluation",
      "sales.view_lignevente", "sales.view_vente"
    ]
  }
}
```

`GET /api/v1/me/settings/` renvoie la même information à tout moment.

Construisez un garde unique et faites-en dériver menus, boutons et routes :

```ts
// Un seul endroit décide de tout ce qui est visible.
const estSuperutilisateur = utilisateur.is_superuser === true;

function peut(permission: string): boolean {
  return estSuperutilisateur || utilisateur.permissions.includes(permission);
}

// Exemples d'usage
peut("products.change_produit");            // modérer une annonce
peut("moderation.consulter_statistiques");  // voir le tableau de bord global
```

> `is_superuser` est renvoyé à son propre titulaire. Pour un
> superutilisateur, `permissions` contient de toute façon la totalité des
> permissions, donc la fonction `peut()` ci-dessus serait correcte même sans
> le raccourci. Gardez-le quand même : il exprime l'intention, et il reste
> juste si une nouvelle application ajoute des permissions demain.

### Permission exigée par chaque écran

| Écran | Permission | Superuser | Modérateur |
| ----- | ---------- | :-------: | :--------: |
| Tableau de bord global | `moderation.consulter_statistiques` | ✅ | ❌ |
| Signalements — lire | `messaging.view_signalementconversation`, `reviews.view_evaluation` | ✅ | ✅ |
| Signalements — classer | `messaging.change_signalementconversation`, `reviews.change_evaluation` | ✅ | ✅ |
| Comptes — lire | `accounts.view_user` | ✅ | ✅ |
| Comptes — suspendre / réactiver | `accounts.change_user` | ✅ | ✅ |
| Comptes — supprimer | `accounts.delete_user` | ✅ | ❌ |
| Annonces — lire | `products.view_produit` | ✅ | ✅ |
| Annonces — modérer | `products.change_produit` | ✅ | ✅ |
| Annonces — supprimer | `products.delete_produit` | ✅ | ❌ |
| Catégories — lire / modifier | `categories.view_categorie`, `change_categorie` | ✅ | ✅ |
| Catégories — créer / supprimer | `categories.add_categorie`, `delete_categorie` | ✅ | ❌ |
| Avis — lire / masquer | `reviews.view_evaluation`, `change_evaluation` | ✅ | ✅ |
| Litiges (stock, ventes, réservations) | `products.view_mouvementstock`, `sales.view_vente`, `reservations.view_reservation` | ✅ | ✅ |
| Journal d'audit | `moderation.view_journalaudit` | ✅ | ✅ |
| Configuration | `moderation.*_parametreplateforme` | ✅ | ❌ |

Les trois permissions de litige sont **indépendantes** : voir le stock
n'ouvre pas les ventes. Si vous composez un écran de litige unique, vérifiez
les trois et masquez les onglets manquants.

### Deux principes qui gouvernent tout cet espace

**Les actions personnalisées exigent la permission de leur effet réel.**
`POST /admin/products/{id}/moderate/` est un POST, mais son effet est une
modification : il exige `change_produit`, pas `add_produit`. Même chose pour
`/suspend/`, `/activate/`, `/moderate/`, `/resolve/`, `/deactivate/`.

**La lecture est contrôlée, elle aussi.** Contrairement au comportement par
défaut de Django REST Framework, un `GET` exige `view_*`. Un compte sans
permission ne peut donc pas lire l'espace d'administration.

---

## 2. Tableau de bord global

> Superutilisateur uniquement (`moderation.consulter_statistiques`).

### Ce que le serveur garantit

Une seule règle, absolue : **le chiffre d'affaires ne compte que les ventes
confirmées** (`PAID` et `COMPLETED`). Une réservation acceptée, même de
grande valeur, n'est pas un revenu. Ne les additionnez jamais.

```
GET /api/v1/admin/statistics/
```

```json
{
  "utilisateurs": {
    "total": 8, "actifs": 8, "suspendus": 0, "email_verifie": 2,
    "inscrits_ce_mois": 8, "vendeurs": 1
  },
  "annonces": {
    "total": 10,
    "par_statut": { "DRAFT": 1, "PENDING": 0, "ACTIVE": 9, "OUT_OF_STOCK": 0,
                    "PAUSED": 0, "ARCHIVED": 0, "REMOVED": 0 },
    "visibles": 9, "mises_en_avant": 0, "vues_cumulees": 1
  },
  "reservations": {
    "total": 1, "en_attente": 1, "acceptees": 0, "annulees": 0,
    "expirees": 0, "transformees": 0, "taux_de_transformation": null
  },
  "ventes": {
    "total": 1, "statut_initiated": 0, "statut_paid": 0, "statut_completed": 1,
    "statut_cancelled": 0, "statut_refunded": 0,
    "ventes_comptabilisees": 1,
    "chiffre_affaires": "480000.00", "quantite_vendue": 1,
    "panier_moyen": "480000.00", "devise": "BIF"
  },
  "messagerie": { "conversations": 1, "messages": 1, "conversations_bloquees": 0 },
  "evaluations": {
    "total": 0, "visibles": 0, "masquees": 0, "retirees": 0,
    "note_produit_moyenne": null, "note_vendeur_moyenne": null
  },
  "moderation": {
    "signalements_conversations_en_attente": 0, "signalements_avis_en_attente": 0,
    "annonces_en_attente_de_moderation": 0, "annonces_retirees": 0
  },
  "genere_le": "2026-11-19T09:12:00Z"
}
```

### Conseils d'écran

- `par_statut` contient **toutes** les clés, même à zéro : vous pouvez
  dessiner un graphique sans test d'existence.
- `taux_de_transformation` vaut `null` tant qu'aucune réservation n'est
  arrivée à son terme — affichez « — », pas `0 %`.
- `note_produit_moyenne` et `note_vendeur_moyenne` valent `null` sans avis.
- Le bloc `moderation` est votre source pour les **badges** du menu latéral :
  additionnez les deux `signalements_*_en_attente`.
- Un seul appel suffit pour toute la page. Rafraîchissez à la demande ou
  toutes quelques minutes ; il n'y a pas de WebSocket pour ces chiffres.

---

## 3. File de modération

> Modérateur et superutilisateur.

### Ce que le serveur garantit

La plateforme a **deux sortes de signalements**, sur deux modèles distincts :
les conversations (module 7) et les avis (module 11). Le serveur ne les
fusionne **pas** dans une liste unique, volontairement — une fusion imposerait
une table polymorphe ou un tri en mémoire sur deux requêtes, qui mentirait sur
la pagination.

L'API donne donc un résumé commun, puis une liste par sorte. Côté interface,
deux onglets sous un même compteur fonctionnent très bien.

Un signalement « classé » (`traite_le` renseigné) sort de la file et autorise
un nouveau signalement du même objet par la même personne.

### Endpoints

```
GET  /api/v1/admin/reports/                                résumé
GET  /api/v1/admin/reports/conversations/                  en attente
GET  /api/v1/admin/reports/conversations/?traites=true     historique
POST /api/v1/admin/reports/conversations/{id}/resolve/      classer
GET  /api/v1/admin/reports/reviews/                        en attente
GET  /api/v1/admin/reports/reviews/?traites=true           historique
POST /api/v1/admin/reports/reviews/{id}/resolve/            classer
```

Résumé :

```json
GET /api/v1/admin/reports/
→ { "conversations_en_attente": 2, "avis_en_attente": 1,
    "conversations_traitees": 14, "avis_traites": 5 }
```

Un signalement de conversation :

```json
{
  "id": 4, "conversation": 1, "signale_par": 8,
  "motif": "ARNAQUE", "description": "Demande de paiement a l'avance",
  "traite_le": null, "created_at": "..."
}
```

Classer, avec un corps vide :

```
POST /api/v1/admin/reports/conversations/4/resolve/   {}
→ 200, { "success": true, "message": "Signalement classe.", "signalement": { ... } }
```

### Deux chemins pour un avis signalé, à bien distinguer

| Votre décision | Appel | Effet |
| -------------- | ----- | ----- |
| le signalement est **infondé** | `POST /admin/reports/reviews/{id}/resolve/` | classe le signalement, **l'avis reste visible** |
| l'avis est **réellement abusif** | `POST /admin/reviews/{id}/moderate/` avec `statut: "MASQUEE"` | masque l'avis **et** classe automatiquement ses signalements en attente |

Dans le second cas, n'appelez pas `resolve/` : la modération s'en charge.
Proposez donc deux boutons explicites — « signalement infondé » et « masquer
l'avis » — plutôt qu'un seul bouton « traiter ».

Les deux actions sont inscrites au journal d'audit.

---

## 4. Comptes utilisateurs

> Lecture et suspension : modérateur. Suppression : superutilisateur.

### Ce que le serveur garantit

- La suspension est **réversible** et porte un **motif**, qui est renvoyé à
  l'utilisateur dans le message d'erreur de ses écritures. Rédigez-le comme
  un message destiné à la personne, pas comme une note interne.
- Suspendre met `is_active` à faux : le compte ne peut plus se connecter ni
  écrire, mais **reçoit une notification** expliquant la décision, qu'il
  trouvera au retour.
- Il n'y a **pas de rôle** acheteur/vendeur : un « vendeur » est simplement
  un compte qui a publié. Ne construisez pas de gestion de rôles.
- La suppression d'un compte est une opération lourde et rarement souhaitable
  (l'historique des ventes la protège par des clés étrangères `PROTECT`).
  Préférez la suspension, et ne proposez la suppression qu'au
  superutilisateur.

### Endpoints

```
GET    /api/v1/admin/users/                 liste + filtres
POST   /api/v1/admin/users/                 créer         — superutilisateur
GET    /api/v1/admin/users/{id}/
PATCH  /api/v1/admin/users/{id}/            modifier
DELETE /api/v1/admin/users/{id}/            supprimer     — superutilisateur
POST   /api/v1/admin/users/{id}/suspend/    suspendre
POST   /api/v1/admin/users/{id}/activate/   réactiver
```

Suspendre :

```json
POST /api/v1/admin/users/7/suspend/
{ "motif": "Annonces frauduleuses signalees a trois reprises" }
→ 200, { "success": true, "message": "Le compte vendeur_demo est suspendu.",
         "utilisateur": { "statut_compte": "SUSPENDU", "is_active": false, ... } }
```

Réactiver :

```
POST /api/v1/admin/users/7/activate/   {}
```

Filtres : `username` (contient), `nom_complet`, `nom_commercial`, `email`,
`telephone`, `localisation` (contient), `statut_compte`, `email_verifie`,
`is_active`, `groupe`, `date_joined_gte`, `date_joined_lte`, `search=`,
`ordering=-date_joined|username|statut_compte`.

Pour la file « comptes à surveiller », combinez
`?statut_compte=SUSPENDU` et `?email_verifie=false`.

### Attribuer le rôle de modérateur

L'API d'administration expose les groupes d'un compte en lecture. Pour
**ajouter** quelqu'un au groupe `Moderateur`, deux voies :

1. l'admin Django (`/django-admin/`), réservé au superutilisateur — le plus
   simple, et probablement suffisant pour deux ou trois personnes ;
2. `PATCH /api/v1/admin/users/{id}/` en envoyant les groupes, si vous voulez
   l'intégrer à la console. Vérifiez la forme exacte du champ dans Swagger
   avant de l'implémenter, et réservez l'écran au superutilisateur.

---

## 5. Catalogue — annonces

> Lecture et modération : modérateur. Suppression : superutilisateur.

### Ce que le serveur garantit

- Modérer, c'est **changer le statut** et consigner un **motif**. Les statuts
  utiles à la modération sont `ACTIVE` (remettre en ligne), `PENDING`
  (demander une vérification), `PAUSED` et `REMOVED` (retirer).
- Un **motif est obligatoire pour retirer** une annonce.
- Une annonce remise en `ACTIVE` **sans stock disponible** repart
  automatiquement en `OUT_OF_STOCK` : le serveur ne laisse pas annoncer une
  disponibilité inexistante. Relisez la réponse plutôt que de supposer le
  statut demandé.
- Le vendeur reçoit une **notification** avec le motif.
- `est_mis_en_avant` est réservé à l'administration : c'est le levier des
  mises en avant de l'accueil mobile.

### Endpoints

```
GET    /api/v1/admin/products/                 liste, tous statuts
GET    /api/v1/admin/products/{id}/
PATCH  /api/v1/admin/products/{id}/            corriger un champ
DELETE /api/v1/admin/products/{id}/            supprimer      — superutilisateur
POST   /api/v1/admin/products/{id}/moderate/   modérer
```

Modérer :

```json
POST /api/v1/admin/products/12/moderate/
{ "status": "REMOVED", "motif": "Contrefacon", "est_mis_en_avant": false }
→ 200, { "success": true, "message": "Annonce moderee : statut REMOVED",
         "produit": { ... } }
```

Mettre en avant sans changer le statut : renvoyez le statut actuel avec
`est_mis_en_avant: true`.

Filtres : tous ceux du catalogue public (`q`, `titre`, `categorie`,
`categorie_arbre`, `prix_min`, `prix_max`, `etat`, `localisation`,
`disponible`, `owner_username`, `created_at_gte`…) **plus**, ici uniquement,
`status` et `status_in=PENDING,REMOVED`.

La file « annonces à modérer » est donc `?status=PENDING&ordering=created_at`.

---

## 6. Catégories

> Lecture et modification : modérateur. Création et suppression :
> superutilisateur.

### Ce que le serveur garantit

- Les catégories sont **hiérarchiques** (une catégorie a un parent
  facultatif). L'unicité du nom s'applique **au sein d'un même parent** : deux
  « Téléphones » peuvent coexister sous deux parents différents.
- **Désactiver une catégorie désactive aussi ses sous-catégories.** C'est la
  voie douce, à préférer à la suppression.
- Supprimer une catégorie parente supprime ses enfants en cascade. En
  revanche, une catégorie **portant des annonces** est protégée : la
  suppression échoue. Affichez le compte d'annonces avant de proposer le
  bouton.

### Endpoints

```
GET    /api/v1/admin/categories/                   liste
POST   /api/v1/admin/categories/                   créer        — superutilisateur
GET    /api/v1/admin/categories/{id}/
PATCH  /api/v1/admin/categories/{id}/              modifier
DELETE /api/v1/admin/categories/{id}/              supprimer    — superutilisateur
POST   /api/v1/admin/categories/{id}/deactivate/   désactiver (+ enfants)
POST   /api/v1/admin/categories/{id}/activate/     réactiver
```

Créer :

```json
POST /api/v1/admin/categories/
{ "nom": "Téléphones", "parent": 2, "description": "Smartphones et accessoires",
  "ordre": 10, "is_active": true }
```

`parent` est facultatif (`null` = catégorie racine), `slug` est calculé.

Pour l'arborescence d'édition, utilisez la route publique
`GET /api/v1/public/categories/tree/` : elle renvoie l'arbre complet, non
paginé, en un appel.

Filtres : `nom` (contient), `nom_exact`, `description`, `slug`, `recherche`,
`parent`, `parent_slug`, `racines=true`, `is_active`, `ordre_gte`,
`ordre_lte`, `search=`, `ordering=ordre|nom|created_at`.

---

## 7. Avis

> Modérateur et superutilisateur.

### Ce que le serveur garantit

- **Masquer n'efface pas.** Un avis masqué sort des moyennes et des listes
  publiques mais reste en base, avec son texte et ses notes intacts.
- **La modération ne réécrit jamais** les notes ni le commentaire : ils
  appartiennent à leur auteur. Il n'existe aucune route pour les modifier.
- La décision est **explicable et imputable** : `motif_moderation`,
  `moderee_par` et `moderee_le` sont conservés et renvoyés par l'API.
- Masquer un avis **classe automatiquement** ses signalements en attente.
- L'auteur reçoit une **notification** avec le motif.
- Trois statuts : `VISIBLE`, `MASQUEE` (par la modération), `RETIREE` (par son
  auteur). Un avis `RETIREE` n'est pas un problème de modération — ne le
  faites pas remonter dans la file.

### Endpoints

```
GET  /api/v1/admin/reviews/                 tous les avis
GET  /api/v1/admin/reviews/{id}/
GET  /api/v1/admin/reviews/reports/         signalements d'avis (alias de § 3)
POST /api/v1/admin/reviews/{id}/moderate/   masquer ou réafficher
```

Masquer :

```json
POST /api/v1/admin/reviews/9/moderate/
{ "statut": "MASQUEE", "motif": "Propos insultants" }
→ 200, { "success": true, "message": "Avis passe en MASQUEE.",
         "evaluation": { "statut": "MASQUEE", "moderee_par": 1,
                         "moderee_le": "...", ... } }
```

Réafficher : le même appel avec `{"statut": "VISIBLE"}`.

Filtres utiles à la modération :

| Paramètre | Pour |
| --------- | ---- |
| `signalees=true` | **la file de travail** : avis ayant un signalement non traité |
| `statut=MASQUEE` | ce qui a déjà été masqué |
| `note_vendeur__lte=2` | les avis les plus durs, à relire |
| `commentaire=insulte` | recherche plein texte dans le commentaire |
| `vendeur_username=` | tous les avis reçus par un vendeur |
| `created_at_gte=` | sur une période |

---

## 8. Litiges — historiques

> Modérateur et superutilisateur. Trois permissions **indépendantes**.

### Ce que le serveur garantit

Ces trois écrans répondent à une exigence précise du cahier des charges :
« les administrateurs doivent pouvoir consulter l'historique des
modifications de stock et des ventes en cas de litige ».

**Ils sont en lecture seule, et ce n'est pas un oubli.** Il n'existe aucune
route d'écriture : toute tentative renvoie `405`, même pour un
superutilisateur détenant `add_vente` ou `delete_vente`. Le cahier des charges
interdit de modifier silencieusement une vente confirmée ; corriger une vente
reste l'affaire de **son vendeur**, via `/sales/{id}/cancel/` et son motif
obligatoire, ce qui laisse une trace.

Votre interface ne doit donc proposer **aucun** bouton d'action sur ces
écrans — seulement de la lecture, des filtres et un export.

### L'historique du stock : l'écran qui tranche un litige

```
GET /api/v1/admin/stock-movements/
GET /api/v1/admin/stock-movements/{id}/
```

Chaque ligne porte la **photographie du stock après l'opération** :
l'histoire d'un produit se relit sans rien recalculer.

```json
{
  "id": 14, "produit": 5, "produit_titre": "Pantalon jean homme",
  "vendeur_username": "vendeur_demo",
  "type_mouvement": "LIBERATION", "type_libelle": "Quantite liberee",
  "quantite": 3,
  "reference_type": "reservation", "reference_id": 2,
  "effectue_par": 7, "effectue_par_username": "vendeur_demo",
  "commentaire": "Cloture de la reservation 2 : 2 vendue(s), 1 liberee(s)",
  "quantite_totale_apres": 20, "quantite_reservee_apres": 0,
  "quantite_vendue_apres": 2, "quantite_disponible_apres": 18,
  "created_at": "..."
}
```

Types de mouvement : `ENTREE`, `RESERVATION`, `LIBERATION`, `VENTE`,
`ANNULATION_VENTE`, `AJUSTEMENT`.

Filtres : `type_mouvement`, `type_in`, `produit`, `titre` (contient), `owner`,
`owner_username` (contient), `localisation` (contient), `effectue_par`,
`commentaire` (contient), `quantite__gte`, `quantite__lte`, `reference_type`,
`reference_id`, `created_at_gte`, `created_at_lte`.

**Le filtre décisif pour un litige** est `?reference_type=reservation&reference_id=2` :
il donne toute l'histoire d'une réservation en une requête. Proposez-le comme
un lien depuis le détail d'une réservation ou d'une vente.

Triez par `?ordering=created_at` (croissant) pour lire l'histoire dans le bon
sens — le défaut est décroissant.

### Ventes et réservations

```
GET /api/v1/admin/sales/                  toutes les ventes
GET /api/v1/admin/sales/{id}/
GET /api/v1/admin/reservations/            toutes les réservations
GET /api/v1/admin/reservations/{id}/
```

Mêmes champs et mêmes filtres que les routes utilisateur `/sales/` et
`/reservations/`, mais sans restriction de propriété : vous voyez toute la
plateforme.

Filtres de ventes : `statut`, `statut_in=PAID,COMPLETED`,
`comptabilisables=true`, `statut_paiement`, `moyen_paiement`, `acheteur`,
`vendeur`, `acheteur_username`, `vendeur_username`, `produit`, `titre`,
`categorie`, `localisation`, `montant_min`, `montant_max`,
`reservation__isnull`, `created_at_gte`, `confirmee_le_gte`.

Filtres de réservations : `statut`, `statut_in`, `actives`, `expirees`,
`acheteur`, `vendeur`, `produit`, `titre`, `categorie`, `localisation`,
`quantite_demandee__gte`, `created_at_gte`, `expire_le_lte`.

Rappel pour l'affichage : `valeur_estimee` sur une réservation est
**indicative**, au prix du jour. Ce n'est pas un revenu.

---

## 9. Journal d'audit

> Modérateur et superutilisateur, en **lecture seule pour tous**.

### Ce que le serveur garantit

Chaque décision d'administration s'y inscrit **toute seule** : vous n'avez
aucun appel à faire pour journaliser. Sont tracées la suspension et la
réactivation d'un compte, la modération d'une annonce et d'un avis, la
suppression d'une annonce, la modification d'une catégorie, le traitement
d'un signalement et le changement d'un paramètre.

Le journal **ne peut pas être modifié**, par personne : `POST`, `PATCH` et
`DELETE` renvoient `405`, y compris pour un compte détenant
`add_journalaudit` et `change_journalaudit`. Dans l'admin Django aussi,
l'ajout, la modification et la suppression sont désactivés. Un journal que
l'on peut retoucher ne vaut rien devant un litige.

### Endpoints

```
GET /api/v1/admin/audit-logs/
GET /api/v1/admin/audit-logs/{id}/
GET /api/v1/admin/audit-logs/actions/     valeurs possibles de `action`
```

```json
{
  "id": 7, "acteur": 1, "acteur_username": "jospin",
  "action": "SUSPENSION_COMPTE", "action_libelle": "Suspension d'un compte",
  "cible_type": "utilisateur", "cible_id": 7, "cible_libelle": "vendeur_demo",
  "motif": "Annonces frauduleuses",
  "donnees": { "avant": { "statut_compte": "ACTIF" },
               "apres": { "statut_compte": "SUSPENDU" } },
  "adresse_ip": "127.0.0.1", "created_at": "..."
}
```

`acteur_username` est **recopié** au moment de l'action : la trace reste
lisible même si le compte d'administration disparaît ensuite (`acteur` passe
alors à `null`).

`donnees.avant` et `donnees.apres` sont des objets libres selon l'action.
Affichez-les en comparaison côte à côte — c'est ce qui rend une décision
compréhensible des mois plus tard.

`adresse_ip` est fournie à titre **indicatif** : elle peut provenir d'un
en-tête `X-Forwarded-For`, donc falsifiable. Ne vous en servez jamais comme
preuve.

Alimentez votre filtre avec `/audit-logs/actions/` plutôt qu'avec une liste
codée en dur :

```json
GET /api/v1/admin/audit-logs/actions/
→ [ { "valeur": "SUSPENSION_COMPTE", "libelle": "Suspension d'un compte" },
    { "valeur": "MODERATION_ANNONCE", "libelle": "Moderation d'une annonce" }, ... ]
```

Filtres : `action`, `action_in`, `acteur`, `acteur_username` (contient),
`cible_type`, `cible_id`, `cible_libelle` (contient), `motif` (contient),
`adresse_ip`, `created_at_gte`, `created_at_lte`, `search=`,
`ordering=created_at`.

Deux vues à offrir : « tout ce qu'a fait tel administrateur »
(`?acteur=1`) et « tout ce qui est arrivé à tel objet »
(`?cible_type=produit&cible_id=12`). La seconde est celle qu'on ouvre quand un
vendeur se plaint.

---

## 10. Configuration de la plateforme

> Superutilisateur uniquement.

### Ce que le serveur garantit

Trois réglages métier sont modifiables **sans redéploiement**, et prennent
effet **immédiatement** sur l'application mobile :

| Clé | Effet | Défaut |
| --- | ----- | ------ |
| `RESERVATION_DUREE_HEURES` | délai avant expiration d'une réservation | 72 |
| `EVALUATION_DELAI_MODIFICATION_HEURES` | fenêtre de correction d'un avis | 48 |
| `STOCK_SEUIL_ALERTE` | seuil de l'alerte « produit presque épuisé » | 3 |

L'ordre de priorité est : **base de données**, puis `.env`, puis la valeur par
défaut du code. La table **peut rester vide** — la plateforme se comporte
alors comme si ce module n'existait pas. Supprimer un paramètre fait donc
retomber le réglage sur le `.env`, ce n'est pas une opération dangereuse.

Une valeur incompatible avec son type est **refusée en `400`** plutôt
qu'acceptée puis ignorée silencieusement. Chaque création, modification et
suppression est inscrite au journal d'audit.

### Endpoints

```
GET    /api/v1/admin/settings/              paramètres définis
POST   /api/v1/admin/settings/              définir
GET    /api/v1/admin/settings/{id}/
PATCH  /api/v1/admin/settings/{id}/         modifier
DELETE /api/v1/admin/settings/{id}/         retirer (retour au défaut)
GET    /api/v1/admin/settings/known-keys/   catalogue des clés reconnues
```

**Construisez l'écran à partir de `known-keys/`**, pas d'un formulaire libre :

```json
GET /api/v1/admin/settings/known-keys/
→ [
  { "cle": "RESERVATION_DUREE_HEURES", "type_valeur": "ENTIER",
    "description": "Duree de validite d'une reservation, en heures.",
    "valeur_active": "72", "definie_en_base": false },
  { "cle": "EVALUATION_DELAI_MODIFICATION_HEURES", "type_valeur": "ENTIER",
    "description": "Delai pendant lequel un avis reste modifiable, en heures.",
    "valeur_active": "48", "definie_en_base": false },
  { "cle": "STOCK_SEUIL_ALERTE", "type_valeur": "ENTIER",
    "description": "Seuil de l'alerte \"produit presque epuise\", en unites.",
    "valeur_active": "3", "definie_en_base": false }
]
```

Cette route donne, pour chaque clé : son type, sa description, la valeur
**réellement utilisée** et si elle vient de la base ou du `.env`. De quoi
afficher un écran honnête, avec un libellé « valeur par défaut du serveur »
quand `definie_en_base` est `false`.

Une clé absente de cette liste peut être créée, mais **aucun code ne la
lira** : n'offrez pas de champ « nouvelle clé » libre, vous ne créeriez que
des réglages fantômes.

Définir :

```json
POST /api/v1/admin/settings/
{ "cle": "RESERVATION_DUREE_HEURES", "valeur": "24", "type_valeur": "ENTIER",
  "description": "Une journee pour venir retirer" }
```

Types acceptés : `TEXTE`, `ENTIER`, `DECIMAL`, `BOOLEEN` (`true`, `1`, `oui`,
`yes` valent vrai).

Erreur type, à afficher sous le champ :

```json
{ "success": false, "status_code": 400, "message": "Donnees invalides.",
  "errors": { "valeur": ["Valeur incompatible avec le type ENTIER : le reglage serait ignore au profit de la valeur par defaut du serveur."] } }
}
```

### Avertissement à faire figurer dans l'écran

Réduire `RESERVATION_DUREE_HEURES` ne raccourcit pas les réservations déjà en
cours : leur date limite a été calculée à l'acceptation. Le nouveau réglage ne
s'applique qu'aux suivantes. Dites-le, sinon l'administrateur croira à un
bug.

---

## Ce que la console web n'a pas à faire

Pour cadrer le périmètre, voici ce qui existe dans l'API mais **ne relève pas**
de cet espace :

| Non | Pourquoi |
| --- | -------- |
| lire ou écrire dans les conversations | la messagerie est privée ; la modération voit les **signalements**, pas les messages |
| déposer ou corriger un avis | seuls les acheteurs évaluent |
| créer une annonce, réserver, vendre | l'administration ne se substitue pas aux utilisateurs |
| modifier une vente ou un stock | interdit par le cahier des charges ; `405` sur ces routes |
| retoucher le journal d'audit | aucune route d'écriture n'existe |
| gérer des groupes supplémentaires | le modèle d'accès n'a que deux niveaux |

---

## Mise en route

```bash
# 1. Un superutilisateur
python manage.py createsuperuser

# 2. Le groupe de modération
python manage.py init_groupes

# 3. Ajouter un compte au groupe : via /django-admin/ (le plus simple)
```

### Comptes de démonstration (base locale)

| Identifiant | Mot de passe | Rôle | Sert à vérifier |
| ----------- | ------------ | ---- | --------------- |
| `jospin` | celui du `createsuperuser` | superutilisateur | tous les écrans, dont statistiques et configuration |
| `moderateur` | `Modo@2026` | groupe `Moderateur` | que les écrans interdits sont bien masqués, et que `/admin/statistics/` et `/admin/settings/` renvoient `403` |
| `mod_categories` | `Mod@2026` | aucun groupe | que tout `/admin/...` renvoie `403` |

Testez systématiquement avec les trois : c'est le seul moyen de vérifier que
votre garde d'interface et les permissions du serveur disent la même chose.

Pour tout le détail des champs et des codes de retour, Swagger reste la
référence : <http://127.0.0.1:8000/api/docs/>.
