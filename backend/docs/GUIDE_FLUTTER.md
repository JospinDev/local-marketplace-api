# Guide d'intégration — application mobile Flutter

Marketplace Burundi — API REST v1

Ce document vous conduit du premier appel réseau à l'application complète,
**dans l'ordre où il faut construire**. Chaque étape explique d'abord *ce que
le serveur garantit* (la logique métier), puis donne les endpoints, les corps
de requête et les réponses utiles, et enfin **qui a le droit** d'appeler quoi.

La référence exhaustive reste Swagger : <http://127.0.0.1:8000/api/docs/>.
Ce guide dit ce que Swagger ne dit pas — l'ordre des appels et le pourquoi.

---

## Sommaire

| Étape | Ce que vous construisez | Dépend de |
| ----- | ----------------------- | --------- |
| [0](#0-les-regles-communes) | Les règles communes (client HTTP, erreurs, pagination) | — |
| [1](#1-authentification) | Inscription, connexion, jetons | 0 |
| [2](#2-mon-compte) | Profil, photo, vitrine vendeur | 1 |
| [3](#3-catalogue-public) | Accueil, catégories, recherche, fiche produit | 0 |
| [4](#4-mes-annonces-vendeur) | Publier une annonce, gérer son stock | 1 |
| [5](#5-favoris-et-vendeurs-suivis) | Cœur et abonnements | 1, 3 |
| [6](#6-messagerie-et-temps-reel) | Chat acheteur ↔ vendeur, WebSocket | 1, 3 |
| [7](#7-reservations) | Demander, accepter, annuler une réservation | 1, 3, 4 |
| [8](#8-ventes-et-paiement) | Déclarer une vente, confirmer la réception | 7 |
| [9](#9-evaluations) | Noter un produit et un vendeur | 8 |
| [10](#10-tableau-de-bord-vendeur) | Chiffres du vendeur | 4, 7, 8 |
| [11](#11-notifications) | Historique, badge, push, WebSocket | 1 |

L'ordre n'est pas arbitraire : **une évaluation exige une vente terminée, qui
exige une réservation acceptée (ou une vente directe), qui exige une annonce
avec du stock.** Construire dans un autre ordre vous laissera devant des
écrans que vous ne pourrez pas tester.

---

## 0. Les règles communes

### Base et versionnement

```
http://127.0.0.1:8000/api/v1/
```

Toutes les routes sont préfixées par `/api/v1/`. En développement,
`CORS_ALLOW_ALL_ORIGINS` est actif ; en production, l'origine de
l'application devra être déclarée côté serveur.

### Trois familles de routes, trois niveaux d'accès

| Préfixe | Jeton requis | Pour |
| ------- | ------------ | ---- |
| `/public/...`, `/auth/...` | **non** | catalogue, recherche, vitrines, inscription |
| le reste (`/me/`, `/products/`, `/reservations/`, …) | **oui** | tout ce qui appartient à l'utilisateur |
| `/admin/...` | oui **+ permissions** | administration web — **pas pour le mobile** |

L'application mobile n'appelle **jamais** `/admin/...`. Ces routes sont
documentées dans le guide du front web d'administration.

### Authentification

Un seul en-tête, sur chaque appel authentifié :

```
Authorization: Bearer <access>
```

- `access` vit **60 minutes** ;
- `refresh` vit **15 jours** et **change à chaque rafraîchissement**
  (rotation avec liste noire) : vous devez **écraser** le refresh stocké par
  celui que renvoie `/auth/token/refresh/`, sinon le suivant sera rejeté.

Stockez les deux jetons dans un stockage sécurisé (`flutter_secure_storage`),
jamais dans `SharedPreferences`.

**Intercepteur à écrire en premier.** Sur un `401`, rafraîchir une seule fois,
rejouer la requête, et si le rafraîchissement échoue, déconnecter :

```dart
// Pseudo-code de l'intercepteur, à placer avant tout le reste.
if (reponse.statusCode == 401 && !dejaRejoue) {
  final ok = await rafraichirLesJetons();   // POST /auth/token/refresh/
  if (ok) return rejouer(requete);          // une seule fois
  await deconnecter();                      // vider le stockage, aller au login
}
```

### Format des réponses d'erreur

**Toutes** les erreurs ont la même enveloppe. Écrivez un seul décodeur :

```json
{
  "success": false,
  "status_code": 400,
  "message": "Donnees invalides.",
  "errors": {
    "quantite_demandee": ["Quantite trop elevee : 7 unite(s) disponible(s)."]
  }
}
```

- `errors` est rempli pour les erreurs **de champ** : affichez-les sous les
  champs concernés ;
- `errors` est `{}` pour les erreurs **générales** (permission, introuvable,
  règle métier sans champ) : affichez `message`.

| Code | Signification | Ce que l'application doit faire |
| ---- | ------------- | ------------------------------- |
| `400` | données ou règle métier invalides | afficher `errors` puis `message` |
| `401` | jeton absent, expiré ou invalide | rafraîchir, puis déconnecter |
| `403` | interdit (pas le propriétaire, compte suspendu) | afficher `message`, ne pas réessayer |
| `404` | inexistant **ou pas à vous** | revenir en arrière, rafraîchir la liste |
| `405` | méthode non autorisée | bug côté application |
| `429` | quota dépassé | afficher « réessayez dans un instant » |
| `503` | email indisponible | proposer de réessayer plus tard |

Le `404` mérite une insistance : le serveur ne distingue jamais « n'existe
pas » de « ne vous appartient pas ». Une réservation ou une conversation
d'autrui renvoie `404`, pas `403`. C'est volontaire — cela évite de révéler
l'existence des données d'autres utilisateurs.

### Pagination

Toutes les listes sont paginées de la même façon :

```json
{
  "count": 142,
  "next": "http://.../api/v1/public/products/?page=2",
  "previous": null,
  "results": [ ... ]
}
```

Paramètres : `?page=2`, `?page_size=50` (défaut **20**, maximum **100**).
Pour un défilement infini, suivez `next` jusqu'à `null`.

### Tri et filtres

Chaque liste accepte `?ordering=champ` ou `?ordering=-champ`, et ses propres
filtres, documentés à chaque étape. Deux conventions utiles :

- **texte** : `?titre=guitare` cherche « contient », sans tenir compte de la
  casse ni de la position ;
- **intervalles** : `?prix_min=`, `?prix_max=`, `?created_at_gte=`,
  `?created_at_lte=` (dates au format ISO 8601).

### Quotas

| Routes | Quota |
| ------ | ----- |
| `/auth/login/`, `/auth/register/`, `/auth/password/...` | 20 / minute |
| envoi de code email (`/auth/email/resend/`) | 5 / heure |

---

## 1. Authentification

### La logique métier

Quatre règles décidées côté serveur, qui dictent vos écrans :

1. **`username` est obligatoire et unique** : c'est l'identifiant de
   connexion. La comparaison ignore la casse.
2. **L'email est facultatif** — on peut créer un compte sans adresse. Mais
   s'il est fourni, il doit être **prouvé** : un code à 6 chiffres est envoyé,
   et le compte reste **inactif** jusqu'à sa saisie. Un compte dont le code
   n'est jamais entré est inutilisable.
3. **Le numéro de téléphone n'est jamais vérifié.** C'est une information de
   contact, rien de plus.
4. Il n'y a **pas de rôle** acheteur/vendeur : un seul compte fait les deux.
   N'affichez pas de choix de rôle à l'inscription.

### Inscription

```
POST /api/v1/auth/register/
```

```json
{
  "username": "chris",
  "password": "MotDePasse2026",
  "password_confirmation": "MotDePasse2026",
  "email": "chris@exemple.bi",
  "nom_complet": "Chris Ndayizeye",
  "telephone": "+25769000000",
  "localisation": "Kinindo, Bujumbura"
}
```

Seuls `username`, `password` et `password_confirmation` sont obligatoires.

Réponse `201` **avec email** : le compte existe mais n'est pas utilisable.
Il est créé `is_active = false`, statut `EN_ATTENTE`, et un code part par
email.

```json
{
  "success": true,
  "message": "Compte cree. Un code de verification a ete envoye a chris@exemple.bi. Le compte sera actif apres validation du code.",
  "email_verification_requise": true,
  "utilisateur": { "id": 12, "username": "chris", "email_verifie": false, "...": "..." }
}
```

Réponse `201` **sans email** : le compte est immédiatement utilisable.

```json
{
  "success": true,
  "message": "Compte cree. Vous pouvez vous connecter immediatement.",
  "email_verification_requise": false,
  "utilisateur": { "...": "..." }
}
```

> **Branchez votre navigation sur `email_verification_requise`**, pas sur la
> présence de l'email dans le formulaire : c'est le serveur qui décide.
>
> Attention au nom exact du champ : c'est `email_verification_requise`, et
> non `verification_email_requise`. Les deux mots inversés se lisent
> identiquement en diagonale, mais une faute ici donne toujours `null`, donc
> `false` — l'écran de saisie du code n'apparaît alors **jamais**, et le
> compte reste bloqué en `EN_ATTENTE` sans que personne ne comprenne
> pourquoi.

> **`/auth/register/` ne renvoie aucun jeton**, dans aucun des deux cas.
> Après une inscription sans email, enchaînez vous-même sur
> `POST /auth/login/` avec les identifiants déjà saisis : l'utilisateur ne
> voit rien, et vous obtenez de vrais jetons.
>
> Ne déclarez **jamais** une session ouverte à partir du seul objet
> `utilisateur` de cette réponse : l'application paraîtrait connectée alors
> que le coffre est vide, et chaque appel authentifié répondrait `401`.

Si l'envoi de l'email échoue (SMTP injoignable), vous recevez `503` et **le
compte n'est pas créé** : l'inscription est annulée en entier, pour ne pas
laisser un compte impossible à activer. Proposez de réessayer.

### Vérifier l'email

```
POST /api/v1/auth/email/verify/
{ "username": "chris", "code": "482913" }
```

Réponse `200` : le compte devient actif et la réponse contient `access` et
`refresh` — l'utilisateur est connecté, n'exigez pas une seconde connexion.

Le code expire (15 minutes par défaut) et le nombre d'essais est limité (5).
Prévoyez un bouton « renvoyer » :

```
POST /api/v1/auth/email/resend/
{ "username": "chris" }                      // renvoie à l'adresse connue
{ "username": "chris", "email": "autre@x.bi" } // corrige l'adresse puis renvoie
```

### Connexion

```
POST /api/v1/auth/login/
{ "username": "chris", "password": "MotDePasse2026" }
```

```json
{ "access": "...", "refresh": "...", "utilisateur": { "...": "..." } }
```

Cas d'erreur à traiter distinctement, car le message diffère :

| Situation | Code | Ce que l'application montre |
| --------- | ---- | --------------------------- |
| identifiants faux | `401` | « identifiant ou mot de passe incorrect » |
| email non vérifié | `403` | écran de saisie du code, avec bouton « renvoyer » |
| compte suspendu | `403` | le motif, renvoyé dans `message` |

### Rafraîchir et se déconnecter

```
POST /api/v1/auth/token/refresh/
{ "refresh": "<refresh>" }
→ { "access": "...", "refresh": "<NOUVEAU, à stocker>" }

POST /api/v1/auth/logout/
{ "refresh": "<refresh>" }
→ 205, le refresh est mis en liste noire
```

Appelez `/logout/` à la déconnexion, puis videz le stockage sécurisé. Sans
cet appel, le refresh reste valable jusqu'à son expiration.

### Mot de passe

```
POST /api/v1/auth/password/change/
{ "ancien_password": "...", "nouveau_password": "...", "nouveau_password_confirmation": "..." }

POST /api/v1/auth/password/reset/
{ "username": "chris" }                      // envoie un code sur l'email vérifié

POST /api/v1/auth/password/reset/confirm/
{ "username": "chris", "code": "482913",
  "nouveau_password": "...", "nouveau_password_confirmation": "..." }
```

La réinitialisation n'est possible **que** pour un compte dont l'email est
vérifié : il n'y a pas d'autre canal. Dites-le dans l'écran, sinon
l'utilisateur sans email ne comprendra pas le refus.

---

## 2. Mon compte

### La logique métier

Un même compte porte deux visages : le profil **privé** (email, téléphone) et
la **vitrine commerciale** (nom commercial, description), visible par tous.
`telephone_public` décide si le numéro apparaît sur la vitrine — c'est le
seul réglage de confidentialité, et il appartient au vendeur.

La suppression de compte est **douce** : elle enregistre une demande et
désactive le compte, sans effacer l'historique des ventes.

### Endpoints

```
GET    /api/v1/me/              mon profil complet
PATCH  /api/v1/me/              modifier (multipart si photo)
DELETE /api/v1/me/              demander la suppression (douce)
GET    /api/v1/me/settings/     mes réglages et mes permissions
```

Champs modifiables : `nom_complet`, `telephone`, `photo`, `localisation`,
`nom_commercial`, `description`, `telephone_public`.

En **lecture seule** : `username`, `email`, `email_verifie`, `statut_compte`,
`is_active`. Ne construisez pas de formulaire autour d'eux.

Pour la photo, envoyez en `multipart/form-data` :

```dart
final formulaire = FormData.fromMap({
  "nom_commercial": "Chris Electronics",
  "photo": await MultipartFile.fromFile(chemin),
});
```

### Droits

Chaque utilisateur ne voit et ne modifie que **son** compte. `/me/` n'accepte
aucun identifiant : le serveur part du jeton. Il n'y a aucun moyen, depuis le
mobile, de lire le profil privé de quelqu'un d'autre.

---

## 3. Catalogue public

À construire **en parallèle de l'authentification** : tout ici fonctionne
sans jeton, donc vos premiers écrans peuvent vivre avant que la connexion
soit finie.

### La logique métier

- Une annonce n'est visible du public que si son statut est `ACTIVE` ou
  `OUT_OF_STOCK`, **et** si le compte du vendeur est actif. Les brouillons,
  les annonces en pause, archivées ou retirées par la modération n'existent
  pas pour le public.
- **La localisation est un texte libre.** Il n'y a aucune table de
  provinces ni d'identifiant : le vendeur écrit « Taba », « Kinindo près du
  marché » ou « Gitega centre », et la recherche fonctionne par « contient ».
  Votre champ de recherche de lieu est donc un simple champ texte, pas une
  liste déroulante.
- Les coordonnées GPS sont **facultatives**. Les annonces qui n'en ont pas
  renvoient `distance_km: null` et sont reléguées en fin de tri par
  proximité — ne les cachez pas, elles sont valides.

### Catégories

```
GET /api/v1/public/categories/           liste plate, paginée
GET /api/v1/public/categories/tree/      arbre complet, non paginé
GET /api/v1/public/categories/{id}/
GET /api/v1/public/categories/{id}/children/
```

Pour un menu de navigation, appelez `tree/` **une seule fois** au démarrage et
gardez-le en cache : il change rarement.

### Produits

```
GET /api/v1/public/products/             catalogue + filtres
GET /api/v1/public/products/search/      identique, pensé pour la barre de recherche
GET /api/v1/public/products/featured/    mises en avant (accueil)
GET /api/v1/public/products/latest/      dernières publications (accueil)
GET /api/v1/public/products/popular/     les plus consultées (accueil)
GET /api/v1/public/products/{id}/        fiche complète (incrémente les vues)
GET /api/v1/public/products/{id}/reviews/ avis du produit + note moyenne
```

Filtres de recherche :

| Paramètre | Effet |
| --------- | ----- |
| `q=guitare` | titre **+** description **+** catégorie |
| `titre=`, `description=` | « contient » sur un seul champ |
| `categorie=3` | une catégorie précise |
| `categorie_arbre=3` | la catégorie **et toutes** ses sous-catégories |
| `localisation=taba` | « contient », insensible à la casse |
| `prix_min=`, `prix_max=` | fourchette |
| `etat=NEUF` ou `OCCASION` | état du produit |
| `disponible=true` | uniquement ce qui a du stock disponible |
| `quantite_min=5` | au moins N unités disponibles |
| `owner_username=` | les annonces d'un vendeur |
| `latitude=`, `longitude=`, `rayon_km=` | proximité (voir ci-dessous) |
| `ordering=` | `prix`, `-prix`, `-publie_le`, `-nombre_vues`, `distance_km` |

**Proximité.** Envoyez la position de l'utilisateur pour obtenir
`distance_km` sur chaque ligne, et trier dessus :

```
GET /api/v1/public/products/?latitude=-3.3822&longitude=29.3644&rayon_km=5&ordering=distance_km
```

`rayon_km` sans coordonnées est **ignoré** (sinon la liste se viderait). Des
coordonnées hors bornes renvoient `400` : validez avant d'envoyer.

Ligne de produit (liste) — les champs sur lesquels construire une carte :

```json
{
  "id": 1, "titre": "Guitare acoustique Yamaha F310", "slug": "guitare-...",
  "prix": "250000.00", "devise": "BIF", "etat": "NEUF", "status": "ACTIVE",
  "categorie": 4, "categorie_nom": "Instruments",
  "localisation": "Rohero, Bujumbura", "latitude": null, "longitude": null,
  "distance_km": null,
  "quantite_disponible": 2,
  "image_principale": { "id": 7, "image": "http://.../produits/2026/11/x.jpg", "...": "..." },
  "vendeur_username": "vendeur_demo",
  "est_mis_en_avant": false, "nombre_vues": 42,
  "publie_le": "2026-11-10T08:12:00Z", "created_at": "..."
}
```

La fiche détaillée ajoute `description`, `images` (toutes), `vendeur` (encart
avec photo, nom commercial, téléphone **si** autorisé) et `reputation` :

```json
"reputation": { "note_produit": 4.5, "note_vendeur": 4.0, "nombre_evaluations": 2 }
```

`note_produit` vaut `null` tant qu'aucun avis valide n'existe — prévoyez
l'affichage « pas encore d'avis », pas un `0/5` trompeur.

### Vendeurs

```
GET /api/v1/public/sellers/               vendeurs ayant au moins une annonce visible
GET /api/v1/public/sellers/{id}/          vitrine : note moyenne, abonnés, contact
GET /api/v1/public/sellers/{id}/products/ ses annonces visibles
GET /api/v1/public/sellers/{id}/reviews/  ses avis + répartition par étoile
```

La liste des avis d'un vendeur renvoie aussi sa réputation complète :

```json
"reputation": {
  "note_produit": 4.3, "note_vendeur": 4.6, "nombre_evaluations": 9,
  "repartition": { "1": 0, "2": 1, "3": 0, "4": 2, "5": 6 }
}
```

Les clés `"1"` à `"5"` sont **toujours** présentes, même à zéro : vous pouvez
dessiner l'histogramme sans test d'existence.

### Droits

Aucun jeton requis. Si vous en envoyez un, deux champs s'enrichissent :
`est_suivi` sur les vendeurs. Envoyez donc le jeton quand il existe, mais ne
l'exigez pas.

---

## 4. Mes annonces (vendeur)

### La logique métier

C'est ici que vivent les règles les plus importantes du projet. Lisez-les
avant d'écrire un seul écran.

**Trois quantités, une seule modifiable.** Le stock d'un produit tient dans :

```
quantite_disponible = quantite_totale - quantite_reservee - quantite_vendue
```

Le vendeur ne déclare que `quantite_totale`. `quantite_reservee` et
`quantite_vendue` sont pilotées par les réservations et les ventes, et sont en
**lecture seule** — n'en faites jamais un champ de formulaire. La base
elle-même interdit que leur somme dépasse le total.

**Le cycle de vie d'une annonce** est séparé de celui des réservations et des
ventes :

| Statut | Signification | Visible du public |
| ------ | ------------- | :---------------: |
| `DRAFT` | brouillon, jamais publié | non |
| `PENDING` | en attente de modération | non |
| `ACTIVE` | en ligne, du stock disponible | **oui** |
| `OUT_OF_STOCK` | en ligne, plus de stock | **oui** |
| `PAUSED` | désactivée par le vendeur | non |
| `ARCHIVED` | retirée par le vendeur (suppression douce) | non |
| `REMOVED` | retirée par la modération | non |

Deux transitions sont **automatiques** et ne doivent pas être pilotées depuis
l'application : `ACTIVE → OUT_OF_STOCK` quand le disponible tombe à zéro, et
le retour inverse quand du stock se libère. Après toute opération de stock,
**relisez le produit** plutôt que de recalculer son statut.

Une annonce n'est jamais vraiment supprimée : `DELETE` l'archive, pour que
l'historique des ventes reste lisible.

### Endpoints

```
GET    /api/v1/products/                  mes annonces (tous statuts)
GET    /api/v1/products/my-products/      alias explicite
POST   /api/v1/products/                  créer (statut DRAFT)
GET    /api/v1/products/{id}/
PATCH  /api/v1/products/{id}/             modifier
DELETE /api/v1/products/{id}/             archiver (suppression douce)
POST   /api/v1/products/{id}/publish/     publier
POST   /api/v1/products/{id}/pause/       mettre en pause
GET    /api/v1/products/{id}/stock/       lire le stock
PATCH  /api/v1/products/{id}/stock/       déclarer la quantité totale
POST   /api/v1/products/{id}/images/      ajouter des images (multipart)
DELETE /api/v1/products/{id}/images/{image_id}/
```

### Le parcours de publication, dans l'ordre

```
1. POST   /products/                 → id, statut DRAFT
2. PATCH  /products/{id}/stock/      → { "quantite_totale": 10 }
3. POST   /products/{id}/images/     → multipart, 1 à N images
4. POST   /products/{id}/publish/    → statut ACTIVE (ou OUT_OF_STOCK si 0)
```

Création :

```json
POST /api/v1/products/
{
  "titre": "Guitare acoustique Yamaha F310",
  "description": "Très bon état, housse incluse.",
  "categorie": 4,
  "prix": "250000.00",
  "etat": "NEUF",
  "localisation": "Rohero, Bujumbura",
  "latitude": -3.3822,
  "longitude": 29.3644
}
```

`devise` vaut `BIF` par défaut. `latitude` et `longitude` sont facultatives.
`status` n'est **pas** acceptée : une création donne toujours un `DRAFT`.

Stock :

```json
PATCH /api/v1/products/{id}/stock/
{ "quantite_totale": 10 }
```

Refus (`400`) si la nouvelle valeur est inférieure à ce qui est déjà engagé.
Le message dit exactement quoi : « Le stock total ne peut pas être inférieur à
5 (3 réservé(s) + 2 vendu(s)) ». Affichez-le tel quel.

Images :

```dart
FormData.fromMap({
  "images": [await MultipartFile.fromFile(a), await MultipartFile.fromFile(b)],
  "est_principale": true,   // la première devient l'image principale
});
```

La première image ajoutée devient principale automatiquement, et il n'y en a
jamais deux.

### Filtres

`q`, `titre`, `categorie`, `categorie_arbre`, `prix_min`, `prix_max`, `etat`,
`localisation`, `disponible`, `created_at_gte`, `created_at_lte`,
`ordering=-created_at|prix|-nombre_vues`.

Sur **vos** annonces uniquement, `?status=DRAFT` et `?status_in=DRAFT,PAUSED`
sont également disponibles — utile pour un onglet « brouillons ».

### Droits

Aucune permission, aucun groupe : **tout compte peut vendre**. La protection
est la **propriété** — le serveur filtre sur `owner = vous`. L'annonce d'un
autre vendeur renvoie `404` sur ces routes, même si elle est publique sur
`/public/products/`.

Un compte **suspendu** reçoit `403` sur toute écriture, avec le motif.

---

## 5. Favoris et vendeurs suivis

### La logique métier

Deux choses différentes, à ne pas fusionner dans un seul écran :

| | Favoris | Vendeurs suivis |
| --- | ------- | --------------- |
| porte sur | un **produit** | un **vendeur** |
| sert à | retrouver une annonce, surveiller son prix | voir les nouveautés d'une boutique |
| route | `/favorites/products/` | `/following/sellers/` |

Le favori **mémorise le prix du jour** où il a été ajouté. Le serveur vous
dira ensuite si le prix a changé et de combien : c'est la base de l'écran
« alertes ».

### Endpoints

```
GET    /api/v1/favorites/products/              mes favoris + alertes
POST   /api/v1/favorites/products/{produit_id}/ ajouter (idempotent)
DELETE /api/v1/favorites/products/{produit_id}/ retirer

GET    /api/v1/following/sellers/               mes vendeurs suivis
POST   /api/v1/following/sellers/{vendeur_id}/  suivre
DELETE /api/v1/following/sellers/{vendeur_id}/  ne plus suivre
GET    /api/v1/following/products/              le fil des annonces des vendeurs suivis
```

L'ajout aux favoris est **idempotent** : un produit déjà en favori renvoie
`200` avec `"cree": false` au lieu de `201`. Votre bouton cœur peut donc être
appelé deux fois sans dégât.

Chaque favori porte ses alertes :

```json
{
  "id": 3, "produit": { "...": "..." },
  "prix_a_l_ajout": "250000.00",
  "variation_prix": "-20000.00",
  "prix_a_change": true,
  "est_toujours_disponible": true,
  "est_retire": false
}
```

Filtres utiles : `?prix_a_change=true`, `?disponible=false`, `?retire=true` —
de quoi construire directement un onglet « à surveiller ».

### Droits

Strictement privés : le serveur ne renvoie que **vos** favoris et **vos**
abonnements. Il n'existe aucun moyen de lire les favoris de quelqu'un d'autre.

---

## 6. Messagerie et temps réel

### La logique métier

- Une conversation lie **un acheteur, un vendeur et au plus un produit**. Il
  ne peut pas y en avoir deux pour le même trio : la création est
  **idempotente** et renvoie l'existante.
- Les **rôles sont déduits de l'annonce** : le propriétaire du produit est
  toujours le vendeur. Vous n'envoyez donc pas « qui est acheteur » — sauf
  dans un cas : si **le vendeur écrit le premier sur sa propre annonce**, il
  doit désigner son client avec `interlocuteur`.
- Le **prix affiché au démarrage est figé** dans `prix_initial`. Si le vendeur
  change son prix ensuite, la négociation garde une trace du prix de départ.
  Affichez les deux quand ils diffèrent.
- Le **blocage** empêche l'envoi **dans les deux sens**, mais l'historique
  reste lisible. Seul celui qui a bloqué peut débloquer.

### Endpoints REST

```
GET    /api/v1/conversations/                 mes conversations (triées par activité)
POST   /api/v1/conversations/                 créer ou retrouver
GET    /api/v1/conversations/{id}/
GET    /api/v1/conversations/{id}/messages/   historique paginé
POST   /api/v1/conversations/{id}/messages/   envoyer (texte et/ou image)
POST   /api/v1/conversations/{id}/read/       marquer comme lus
POST   /api/v1/conversations/{id}/block/      bloquer
DELETE /api/v1/conversations/{id}/block/      débloquer
POST   /api/v1/conversations/{id}/report/     signaler
GET    /api/v1/conversations/unread-count/    badge global
```

Ouvrir une conversation depuis une fiche produit :

```json
POST /api/v1/conversations/
{ "produit": 1, "message": "Bonjour, prix negociable ?" }
```

`message` est facultatif. Réponse `201` si elle vient d'être créée, `200` si
elle existait déjà — dans les deux cas vous recevez la conversation complète,
donc traitez les deux pareillement.

Cas du vendeur qui écrit le premier sur **sa** propre annonce :

```json
POST /api/v1/conversations/
{ "produit": 1, "interlocuteur": 8, "message": "Ce produit vous interesse ?" }
```

Sans `interlocuteur`, vous recevez `400` avec le champ en erreur.

Envoyer un message :

```json
POST /api/v1/conversations/{id}/messages/
{ "contenu": "Je passe demain matin" }
```

Avec une image, passez en `multipart/form-data` (`contenu` et/ou `image`). Un
message doit avoir **au moins** l'un des deux, sinon `400`.

### WebSocket

```
ws://127.0.0.1:8000/ws/conversations/{id}/?token=<access>
```

Le jeton est accepté dans l'en-tête `Authorization`, dans le sous-protocole
ou en `?token=`. **En Flutter, utilisez `?token=`** : le paquet `web_socket_channel`
ne permet pas d'ajouter d'en-têtes sur toutes les plateformes.

Trames que vous envoyez :

```json
{"type": "message", "contenu": "Bonjour"}
{"type": "lecture"}
{"type": "saisie", "en_cours": true}
```

Événements que vous recevez :

| Type | Quand | Contenu utile |
| ---- | ----- | ------------- |
| `connexion.ok` | à l'ouverture | `conversation`, `utilisateur` |
| `message.nouveau` | à chaque message, **y compris les vôtres** | `message` complet |
| `messages.lus` | l'autre a lu | `lu_par`, `lu_par_username`, `message_ids` |
| `saisie` | l'autre écrit | `utilisateur`, `username`, `en_cours` |
| `erreur` | règle violée (message vide, conversation bloquée) | `message` |

Codes de fermeture : `4401` non authentifié, `4403` non participant ou compte
suspendu, `4404` conversation inexistante.

**Deux points qui vous feront gagner du temps.**

L'expéditeur reçoit aussi son propre `message.nouveau` : utilisez-le comme
accusé de réception (remplacez le message « en cours d'envoi » par celui du
serveur, qui porte le vrai `id` et la vraie date) plutôt que d'afficher deux
fois la même bulle.

Un message envoyé **par REST** arrive aussi sur le socket, et inversement :
les deux chemins passent par le même service côté serveur. Vous pouvez donc
envoyer en REST (plus simple à réessayer) et ne garder le socket que pour la
réception. C'est la combinaison que je recommande sur mobile, où la connexion
se coupe souvent.

### Droits

Seuls les deux participants voient une conversation ; celle d'autrui renvoie
`404` en REST et une fermeture `4403` en WebSocket. Un compte suspendu ne peut
plus envoyer.

---

## 7. Réservations

C'est le module central du projet. Les règles ci-dessous ne sont pas des
détails d'implémentation : elles changent vos écrans.

### La logique métier

**Le stock n'est immobilisé qu'à l'acceptation du vendeur.** Une demande
(`PENDING`) ne bloque rien : elle est seulement vérifiée contre le disponible
du moment. N'affichez donc pas « réservé » après une simple demande — dites
« demande envoyée, en attente du vendeur ».

Exemple du cahier des charges, qu'il faut avoir en tête : 10 téléphones, un
acheteur en demande 3, **le vendeur confirme** → réservé 3, disponible 7. Un
second acheteur ne peut alors en demander que 7.

**Cycle de vie :**

| Statut | Veut dire | Stock immobilisé |
| ------ | --------- | :--------------: |
| `PENDING` | demande envoyée, le vendeur n'a pas répondu | non |
| `CONFIRMED` | acceptée, quantité mise de côté | **oui** |
| `CANCELLED` | annulée par l'un des deux, ou refusée | non |
| `EXPIRED` | délai de retrait dépassé | non |
| `FULFILLED` | transformée en vente | non |

**Une seule réservation active par couple (acheteur, produit).** Pour changer
d'avis, on modifie la quantité — on n'empile pas les demandes. Une seconde
demande renvoie `400` avec un message explicite.

**L'expiration est automatique** (72 heures par défaut, configurable côté
serveur), et le compte à rebours **repart à l'acceptation**. Affichez
`expire_le` comme un délai de retrait, c'est son vrai sens.

Une annulation ou une expiration **ne compte jamais comme une vente** : le
stock vendu n'est pas touché.

### Endpoints

```
POST /api/v1/reservations/                   demander
GET  /api/v1/reservations/                    toutes (les deux rôles)
GET  /api/v1/reservations/my-requests/        mes demandes (acheteur)
GET  /api/v1/reservations/my-sales/           demandes reçues (vendeur)
GET  /api/v1/reservations/summary/            compteurs, pour les badges
GET  /api/v1/reservations/{id}/
POST /api/v1/reservations/{id}/accept/        accepter      — vendeur
POST /api/v1/reservations/{id}/reject/        refuser       — vendeur
POST /api/v1/reservations/{id}/cancel/        annuler       — les deux
POST /api/v1/reservations/{id}/quantity/      changer la quantité
POST /api/v1/reservations/{id}/complete/      transformer en vente — vendeur
```

Demander :

```json
POST /api/v1/reservations/
{ "produit": 5, "quantite_demandee": 3, "message": "Je passe demain matin" }
```

Refus possibles, tous en `400`, tous avec un message affichable tel quel :
quantité supérieure au disponible (le message donne le disponible exact),
annonce non active, rupture de stock, votre propre annonce, réservation déjà
en cours sur ce produit.

Accepter, éventuellement **partiellement** :

```json
POST /api/v1/reservations/{id}/accept/
{}                  // accepte toute la quantité demandée
{ "quantite": 2 }   // il ne reste que 2 des 3 souhaitées
```

C'est ici que le serveur verrouille la ligne de stock. Si une autre
réservation a été acceptée entre-temps, vous recevez `400`
« Stock insuffisant : N unité(s) disponible(s) » — proposez alors au vendeur
d'accepter N au lieu de la quantité demandée.

Refuser / annuler :

```json
POST /api/v1/reservations/{id}/reject/   { "motif": "Plus en stock" }
POST /api/v1/reservations/{id}/cancel/   { "motif": "Client absent" }
```

Changer la quantité — **la règle de rôle est inhabituelle, lisez-la bien** :

| État | Qui peut changer | Pourquoi |
| ---- | ---------------- | -------- |
| `PENDING` | l'**acheteur** | le vendeur n'a encore rien promis |
| `CONFIRMED` | le **vendeur** | c'est son stock qui est engagé ; l'acheteur reste libre d'annuler |

```json
POST /api/v1/reservations/{id}/quantity/   { "quantite": 5 }
```

Appeler cette route dans le mauvais rôle renvoie `403` avec un message qui
indique l'alternative (« vous pouvez l'accepter partiellement avec /accept/ »,
« vous pouvez annuler avec /cancel/ »).

Réponse type d'une réservation :

```json
{
  "id": 2, "produit": 5, "produit_detail": { "...": "..." },
  "acheteur": 8, "acheteur_username": "acheteur_demo",
  "vendeur": 7, "vendeur_username": "vendeur_demo",
  "quantite_demandee": 3, "quantite_confirmee": 0, "quantite_livree": 0,
  "quantite_immobilisee": 0, "quantite_non_achetee": 0,
  "valeur_estimee": "105000.00",
  "statut": "PENDING", "statut_libelle": "Demande en attente",
  "est_expiree": false, "message": "Je passe demain matin",
  "expire_le": "2026-11-22T06:27:00Z",
  "confirmee_le": null, "cloturee_le": null, "cloturee_par": "", "motif": "",
  "mon_role": "ACHETEUR",
  "created_at": "...", "updated_at": "..."
}
```

**`mon_role` est votre meilleur ami** : il vaut `ACHETEUR` ou `VENDEUR` selon
qui consulte. Construisez l'écran de détail autour de ce champ plutôt que de
comparer des identifiants.

`valeur_estimee` est **indicative**, au prix du jour. Ne l'affichez jamais
comme un revenu — ce n'en est pas un.

### Droits

Propriété, encore : seules vos réservations (comme acheteur **ou** comme
vendeur) sont visibles, le reste renvoie `404`. Les actions vérifient en plus
le rôle : accepter et refuser sont réservés au vendeur, annuler est ouvert aux
deux.

---

## 8. Ventes et paiement

### La logique métier

**Il n'y a pas de passerelle de paiement.** Le moyen de paiement est
déclaratif (`CASH`, `LUMICASH`, `ECOCASH`, `VIREMENT`, `AUTRE`) et
l'application ne prétend pas vérifier un transfert. Dites-le dans l'interface,
sinon l'utilisateur croira à un paiement en ligne.

**Le double accusé.** Une vente passe par trois états utiles :

```
INITIATED  → le vendeur a déclaré la vente
   ↓ POST /sales/{id}/confirm/            (vendeur : « j'ai reçu le paiement »)
PAID       → la vente compte dans le chiffre d'affaires
   ↓ POST /sales/{id}/buyer-confirmation/ (acheteur : « j'ai reçu le produit »)
COMPLETED  → terminée, et seule forme qui ouvre le droit à un avis
```

Cette seconde confirmation n'est pas décorative : c'est elle qui empêche un
vendeur de se fabriquer de bonnes notes avec de fausses ventes. Mettez-la en
avant dans l'écran « mes achats ».

**La vente partielle** est le scénario central. Le client avait réservé 3
pantalons, il n'en prend que 2 : le serveur enregistre la vente de 2, libère
les 3 unités réservées, en passe 2 en vendues et **rend la troisième
disponible** — tout dans une seule transaction.

**Les prix sont figés.** Chaque ligne de vente garde son `prix_unitaire`.
Changer le prix de l'annonce ensuite ne modifie aucun revenu passé.

**Annuler exige un motif**, remet les quantités en disponible et laisse une
trace. Si le paiement avait été déclaré reçu, la vente part en `REFUNDED` et
non `CANCELLED`, pour que le remboursement reste visible.

### Endpoints

```
POST /api/v1/sales/                        déclarer une vente        — vendeur
GET  /api/v1/sales/                        mes ventes et mes achats
GET  /api/v1/sales/my-sales/               mes ventes (vendeur)
GET  /api/v1/sales/my-purchases/           mes achats (acheteur)
GET  /api/v1/sales/summary/                mon chiffre d'affaires
GET  /api/v1/sales/{id}/
POST /api/v1/sales/{id}/confirm/           paiement reçu             — vendeur
POST /api/v1/sales/{id}/buyer-confirmation/ réception confirmée      — acheteur
POST /api/v1/sales/{id}/cancel/            annuler, motif requis     — vendeur
```

Depuis une réservation acceptée — **la voie normale** :

```json
POST /api/v1/reservations/{id}/complete/
{ "quantite": 2, "moyen_paiement": "LUMICASH", "prix_unitaire": "30000.00" }
```

Tout est facultatif : sans `quantite`, toute la quantité réservée est vendue ;
sans `prix_unitaire`, le prix affiché de l'annonce s'applique. La réponse
contient **la vente et la réservation mise à jour** — rafraîchissez les deux
écrans avec.

Vente directe, sans réservation (client venu sur place) :

```json
POST /api/v1/sales/
{ "produit": 5, "acheteur": 8, "quantite": 2, "moyen_paiement": "CASH" }
```

`produit` + `acheteur` + `quantite` sont alors obligatoires, et la quantité
est plafonnée au **disponible** : ce qui est réservé par d'autres n'est pas
vendable.

Annuler :

```json
POST /api/v1/sales/{id}/cancel/
{ "motif": "Produit defectueux" }     // obligatoire, sinon 400
```

Réponse type d'une vente :

```json
{
  "id": 1, "reservation": 2,
  "acheteur": 8, "acheteur_username": "acheteur_demo",
  "vendeur": 7, "vendeur_username": "vendeur_demo",
  "lignes": [
    { "id": 1, "produit": 5, "produit_titre": "Pantalon jean homme",
      "quantite": 2, "prix_unitaire": "35000.00", "sous_total": "70000.00" }
  ],
  "quantite_totale": 2, "montant_total": "70000.00", "devise": "BIF",
  "moyen_paiement": "LUMICASH", "moyen_paiement_libelle": "Lumicash",
  "statut": "PAID", "statut_libelle": "Paiement confirme par le vendeur",
  "statut_paiement": "RECU", "est_comptabilisable": true,
  "confirmee_le": "...", "confirmee_par_acheteur_le": null,
  "annulee_le": null, "motif_annulation": "",
  "mon_role": "VENDEUR", "created_at": "...", "updated_at": "..."
}
```

`est_comptabilisable` vous dit d'un coup d'œil si la vente compte dans le
chiffre d'affaires. `mon_role` fonctionne comme pour les réservations.

### Droits

Déclarer, confirmer le paiement et annuler : le **vendeur propriétaire**
uniquement. Confirmer la réception : l'**acheteur** uniquement. Tout le reste
renvoie `403`. Les ventes d'autrui renvoient `404`.

---

## 9. Évaluations

### La logique métier

- **Deux notes distinctes**, de 1 à 5 : `note_produit` (qualité du produit) et
  `note_vendeur` (accueil, exactitude, ponctualité). Votre écran doit montrer
  deux jeux d'étoiles, pas un seul.
- **Un avis exige une vente `COMPLETED`**, donc confirmée par le vendeur puis
  par l'acheteur. Tant que l'acheteur n'a pas confirmé la réception, le bouton
  « laisser un avis » ne doit pas apparaître.
- **Seul l'acheteur évalue.** Le produit et le vendeur sont déduits de la
  vente : on ne peut pas noter un vendeur chez qui on n'a rien acheté.
- **Un seul avis par vente.** Deux achats chez le même vendeur donnent bien
  droit à deux avis.
- **Correction possible pendant 48 heures** (configurable). Passé ce délai,
  l'avis est définitif — affichez le délai restant.
- **Supprimer un avis le retire sans l'effacer** : il sort des moyennes et des
  listes publiques. Le `DELETE` renvoie `200` avec l'avis, pas `204`.

### Endpoints

```
POST   /api/v1/reviews/                  déposer
GET    /api/v1/reviews/                  les avis qui me concernent
GET    /api/v1/reviews/my-reviews/       ceux que j'ai écrits
GET    /api/v1/reviews/received/         ceux reçus sur mes ventes
GET    /api/v1/reviews/my-rating/        ma réputation de vendeur
GET    /api/v1/reviews/{id}/
PATCH  /api/v1/reviews/{id}/             corriger (dans le délai)
DELETE /api/v1/reviews/{id}/             retirer
POST   /api/v1/reviews/{id}/report/      signaler un avis abusif
```

Déposer :

```json
POST /api/v1/reviews/
{ "vente": 1, "note_produit": 5, "note_vendeur": 4,
  "commentaire": "Telephone conforme, vendeur ponctuel" }
```

`commentaire` est facultatif. Erreurs à traiter : vente non terminée (`400`,
le message nomme `/sales/{id}/buyer-confirmation/`), vente qui n'est pas la
vôtre (`403`), avis déjà déposé (`400`).

Signaler :

```json
POST /api/v1/reviews/{id}/report/
{ "motif": "INSULTE", "description": "Insultes personnelles" }
```

Motifs : `INSULTE`, `FAUX`, `HORS_SUJET`, `SPAM`, `AUTRE`. Ouvert à tout
compte connecté sauf l'auteur de l'avis.

Ma réputation :

```json
GET /api/v1/reviews/my-rating/
→ { "note_produit": 4.5, "note_vendeur": 4.0, "nombre_evaluations": 2 }
```

Les trois valeurs ne comptent que les avis **valides** : un avis masqué par la
modération ou retiré par son auteur n'entre dans aucune moyenne.

### Droits

Vous voyez les avis que vous avez écrits **et** ceux reçus sur vos ventes.
Seul l'auteur modifie ou retire le sien. Les avis publics se lisent sans
jeton sur `/public/products/{id}/reviews/` et `/public/sellers/{id}/reviews/`.

---

## 10. Tableau de bord vendeur

### La logique métier

Une seule règle, mais elle est absolue : **le chiffre d'affaires ne compte que
les ventes confirmées**. Une réservation acceptée, même de grande valeur,
n'est pas un revenu. Le serveur renvoie les deux chiffres séparément, et vous
ne devez jamais les additionner :

| Champ | Nature |
| ----- | ------ |
| `chiffre_affaires_total` | argent réellement encaissé (ventes `PAID` et `COMPLETED`) |
| `valeur_reservations_en_cours` | valeur immobilisée — **pas** un revenu |

Les périodes (jour, semaine depuis lundi, mois) se mesurent à la date de
confirmation du paiement : le moment où l'argent est entré.

### Endpoints

```
GET /api/v1/seller-dashboard/overview/      vue générale
GET /api/v1/seller-dashboard/revenue/       revenus, par produit et par catégorie
GET /api/v1/seller-dashboard/sales/         historique des ventes (filtres de /sales/)
GET /api/v1/seller-dashboard/inventory/     état des stocks
GET /api/v1/seller-dashboard/reservations/  compteurs — `?liste=true` pour la liste
GET /api/v1/seller-dashboard/top-products/  palmarès — `?limite=5`
```

`overview/` donne tout ce qu'il faut pour un écran d'accueil vendeur :

```json
{
  "produits_publies": 9, "produits_disponibles": 9, "produits_en_rupture": 0,
  "produits_total": 10,
  "demandes_de_reservation_en_attente": 1, "reservations_en_cours": 0,
  "ventes_confirmees": 1, "nombre_clients": 1, "nombre_conversations": 1,
  "note_moyenne_vendeur": null, "nombre_evaluations": 0
}
```

`demandes_de_reservation_en_attente` est le badge « à traiter » de l'onglet
vendeur.

`inventory/` donne les quatre quantités en total **et** ligne par ligne, avec
la valeur du stock disponible. `revenue/` ajoute `par_produit` et
`par_categorie`, déjà triés par revenu décroissant — pas de tri à refaire.

### Droits

Chaque vendeur ne voit que ses propres chiffres : tout part du jeton, il n'y a
aucun identifiant à passer, donc rien à falsifier.

---

## 11. Notifications

### La logique métier

Trois canaux, dans cet ordre de fiabilité :

1. la **notification interne**, en base : la seule source de vérité ;
2. le **WebSocket**, qui la transmet instantanément si l'application est
   ouverte ;
3. le **push** (Firebase), si le serveur est configuré pour.

Conséquence pratique : **ne comptez jamais sur le push seul**. Au retour au
premier plan, rechargez `/notifications/` et `/notifications/unread-count/` —
l'historique est complet même si les deux transports ont échoué.

Demandez d'abord au serveur si le push est opérationnel, au lieu de le
supposer :

```
GET /api/v1/notifications/devices/status/
→ { "push_configure": false, "appareils_actifs": 0 }
```

Si `push_configure` est `false`, **ne proposez pas** l'activation des
notifications push : le serveur n'a pas de clé, rien ne partira.

Il n'existe aucun moyen de créer une notification depuis l'application :
c'est toujours la conséquence d'un événement métier.

### Les événements que vous recevrez

| Vous êtes | Vous êtes prévenu quand |
| --------- | ----------------------- |
| acheteur | nouveau message ; réservation acceptée, refusée, annulée, expirée ; un favori devient indisponible ; un vendeur suivi publie |
| vendeur | nouveau message ; nouvelle demande de réservation ; réservation annulée ou expirée ; réception confirmée par le client ; nouvel avis ; produit presque épuisé ; produit en rupture |
| les deux | compte suspendu ou réactivé ; annonce ou avis modéré |

Chaque notification porte `reference_type` et `reference_id` : c'est de quoi
construire un lien profond sans que le serveur connaisse vos écrans.

| `reference_type` | Ouvrir |
| ---------------- | ------ |
| `conversation` | le fil de discussion |
| `reservation` | le détail de la réservation |
| `vente` | le détail de la vente |
| `produit` | la fiche ou l'écran de stock |
| `evaluation` | l'avis |
| `utilisateur` | le profil |

### Endpoints

```
GET    /api/v1/notifications/                  mon historique
GET    /api/v1/notifications/unread-count/     badge
POST   /api/v1/notifications/read/             marquer tout, ou une sélection
POST   /api/v1/notifications/{id}/read/        marquer une notification
DELETE /api/v1/notifications/{id}/             supprimer de l'historique
GET    /api/v1/notifications/devices/          mes appareils push
POST   /api/v1/notifications/devices/          enregistrer un jeton
DELETE /api/v1/notifications/devices/{jeton}/  désinscrire un appareil
GET    /api/v1/notifications/devices/status/   le push est-il configuré ?
```

### Côté Flutter, pour activer le push

Le serveur utilise **FCM HTTP v1** (l'API « legacy » et sa clé serveur ont
été désactivées par Google en 2024). Côté application, cela ne change rien à
la marche à suivre :

```bash
dart pub global activate flutterfire_cli
flutterfire configure     # génère firebase_options.dart + google-services.json
flutter pub add firebase_core firebase_messaging
```

Le nom de paquet déclaré dans la console Firebase doit être **identique** à
`applicationId` dans `android/app/build.gradle.kts`, sinon le jeton sera
rejeté à l'envoi.

```dart
final jeton = await FirebaseMessaging.instance.getToken();
if (jeton != null) await api.enregistrerAppareil(jeton);

// Le jeton change : à la réinstallation, au nettoyage des données, et
// parfois spontanément. Sans cet écouteur, les notifications cessent
// d'arriver sans que personne ne comprenne pourquoi.
FirebaseMessaging.instance.onTokenRefresh.listen(api.enregistrerAppareil);
```

FCM exige les **Google Play Services** sur l'appareil. C'est le cas de la
grande majorité des téléphones Android, mais pas de tous (certains Huawei
récents en sont dépourvus). D'où la règle déjà énoncée : l'historique et le
WebSocket restent la source de vérité, le push n'est qu'un confort.

Enregistrer l'appareil, après avoir obtenu le jeton FCM :

```json
POST /api/v1/notifications/devices/
{ "jeton": "<jeton FCM>", "plateforme": "ANDROID", "libelle": "Pixel de Chris" }
```

Idempotent : renvoyer le même jeton met simplement l'appareil à jour.
**Appelez `DELETE /devices/{jeton}/` à la déconnexion**, sinon l'appareil
continuera de recevoir les notifications du compte précédent.

Marquer comme lu :

```json
POST /api/v1/notifications/read/
{}                              // tout
{ "identifiants": [12, 13] }    // une sélection
```

Une notification :

```json
{
  "id": 1, "type_notification": "MESSAGE_NOUVEAU",
  "type_libelle": "Nouveau message",
  "titre": "Message de acheteur_demo",
  "message": "Bonjour, est-ce toujours disponible ?",
  "reference_type": "conversation", "reference_id": 1,
  "donnees": { "message_id": 3 },
  "est_lue": false, "lu_le": null, "created_at": "..."
}
```

### WebSocket

```
ws://127.0.0.1:8000/ws/notifications/?token=<access>
```

**Un seul socket pour toute l'application**, à ouvrir après la connexion et à
garder ouvert. Vous recevez :

| Type | Contenu |
| ---- | ------- |
| `connexion.ok` | `utilisateur`, `non_lues` — initialisez le badge avec |
| `notification.nouvelle` | `notification` (même forme qu'en REST) + `non_lues` |
| `notifications.lues` | `non_lues` — un autre appareil a lu, mettez à jour le badge |
| `compteur` | réponse à votre demande |
| `erreur` | `message` |

Vous pouvez envoyer `{"type": "lecture"}` (avec `identifiants` facultatifs) et
`{"type": "compteur"}`. Fermetures : `4401` non authentifié, `4403` compte
suspendu.

La forme de `notification` est **identique** en REST et en WebSocket :
écrivez un seul modèle Dart et un seul décodeur.

---

## Récapitulatif des droits, en une page

| Action | Qui |
| ------ | --- |
| parcourir le catalogue, lire les avis, voir une vitrine | **tout le monde**, sans jeton |
| publier une annonce, gérer son stock | tout compte connecté, **sur ses propres annonces** |
| demander une réservation | tout compte connecté, **sauf sur sa propre annonce** |
| accepter, refuser une réservation | le **vendeur** de l'annonce |
| annuler une réservation | l'acheteur **ou** le vendeur |
| changer la quantité | l'**acheteur** si `PENDING`, le **vendeur** si `CONFIRMED` |
| déclarer une vente, confirmer le paiement, annuler | le **vendeur** |
| confirmer la réception | l'**acheteur** |
| déposer un avis | l'**acheteur** d'une vente `COMPLETED` |
| signaler un avis ou une conversation | tout compte connecté |
| `/admin/...` | superutilisateur et groupe `Moderateur` — **jamais le mobile** |

Un compte **suspendu** garde la lecture mais perd toute écriture : `403` avec
le motif. Prévoyez une bannière persistante dans ce cas, le message du serveur
l'explique.

---

## Pièges à éviter

1. **Ne pas écraser le `refresh`** après un rafraîchissement : la rotation
   invalide l'ancien, et l'utilisateur sera déconnecté au bout d'une heure.
2. **Recalculer le statut d'une annonce côté client.** Les transitions
   `ACTIVE ↔ OUT_OF_STOCK` sont automatiques : relisez le produit.
3. **Afficher « réservé » après une simple demande.** Le stock n'est
   immobilisé qu'à l'acceptation.
4. **Additionner le chiffre d'affaires et la valeur des réservations.** Ce
   sont deux chiffres de nature différente.
5. **Proposer un avis avant la confirmation de réception.** La vente doit être
   `COMPLETED`.
6. **Traiter un `404` comme une erreur technique.** Sur les routes privées,
   c'est « pas à vous ».
7. **Compter sur le push.** Rechargez l'historique au retour au premier plan.
8. **Afficher `0/5` quand `note_produit` vaut `null`.** Il n'y a pas encore
   d'avis, ce n'est pas une mauvaise note.
9. **Oublier `DELETE /notifications/devices/{jeton}/`** à la déconnexion.
10. **Construire une liste déroulante de provinces.** La localisation est un
    texte libre, et la recherche fonctionne par « contient ».
11. **Recopier un nom de champ de mémoire.** `email_verification_requise`
    s'est déjà fait lire `verification_email_requise` : la valeur devient
    `null`, puis `false`, et l'écran de code n'apparaît jamais. Copiez les
    noms depuis Swagger, et faites échouer bruyamment une clé absente
    plutôt que de la remplacer par une valeur par défaut silencieuse.
12. **Déclarer une session ouverte sans jeton.** Posez l'invariant une
    fois — « pas de jeton en coffre, pas de session » — au seul endroit qui
    fait passer l'application à l'état connecté.

---

## Comptes de démonstration (base locale)

| Identifiant | Mot de passe | Sert à |
| ----------- | ------------ | ------ |
| `vendeur_demo` | `Vendeur@2026` | le parcours vendeur : annonces, stock, réservations reçues, ventes |
| `acheteur_demo` | `Acheteur@2026` | le parcours acheteur : favoris, demandes, achats, avis |

Données déjà en place : une conversation, une demande de réservation en
attente (3 pantalons), une vente terminée (prête à être évaluée) et une
notification non lue.

Pour tout le détail des champs et des codes de retour, Swagger reste la
référence : <http://127.0.0.1:8000/api/docs/>.
