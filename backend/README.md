# Marketplace Burundi — Backend (Django REST Framework)

Monolithe modulaire : un dossier par module métier, chacun avec ses
`models`, `serializers/`, `viewsets/`, `filters/`, `services/`.

## Guides d'intégration

| Guide | Pour qui |
| ----- | -------- |
| [docs/GUIDE_FLUTTER.md](docs/GUIDE_FLUTTER.md) | le développeur de l'application mobile Flutter : parcours module par module, logique métier, corps de requête, droits |
| [docs/GUIDE_ADMIN_WEB.md](docs/GUIDE_ADMIN_WEB.md) | le développeur de la console web d'administration : écrans, permissions exigées, ce que le serveur refuse délibérément |

Les deux renvoient à Swagger (<http://127.0.0.1:8000/api/docs/>) pour la
référence exhaustive des champs ; ils documentent ce que Swagger ne dit pas :
l'ordre des appels et le pourquoi des règles.

## État d'avancement

| Module | Nom | Statut |
| ------ | --- | ------ |
| 1 | Authentication & User Management | ✅ livré |
| 2 | Categories Management | ✅ livré |
| 3 | Product Management | ✅ livré |
| 4 | Product Discovery & Search | ✅ livré |
| 5 | Seller Profile & Following | ✅ livré |
| 6 | Favorites Management | ✅ livré |
| 7 | Messaging & Chat (REST + WebSocket) | ✅ livré |
| 8 | Reservation Management | ✅ livré |
| 9 | Sales & Payment Confirmation | ✅ livré |
| 10 | Seller Dashboard & Analytics | ✅ livré |
| 11 | Rating & Review | ✅ livré |
| 12 | Notifications | ✅ livré |
| 13 | Location Management | ✅ livré **autrement** (voir ci-dessous) |
| 14 | Admin & Moderation | ✅ livré |

## Démarrage

```bash
# 1. Environnement virtuel (déjà créé à la racine du projet)
.venv\Scripts\activate

# 2. Variables d'environnement : adapter .env à la racine du projet
#    (DB_USER, DB_PASSWORD, DB_NAME…)

# 3. Base de données
createdb -U postgres marketplace_local      # ou via pgAdmin
python manage.py migrate

# 4. Groupes et permissions
python manage.py init_groupes

# 5. Redis (temps réel) — déjà lancé dans Docker
python manage.py verifier_redis

# 6. Compte super-administrateur
python manage.py createsuperuser

# 7. Serveur (ASGI grâce à daphne : HTTP + WebSocket)
python manage.py runserver
```

- Swagger : <http://127.0.0.1:8000/api/docs/>
- WebSocket : `ws://127.0.0.1:8000/ws/conversations/{id}/?token=<access>`
- Redoc : <http://127.0.0.1:8000/api/redoc/>
- Admin Django : <http://127.0.0.1:8000/django-admin/>

## Comptes de démonstration (base locale)

| Identifiant | Mot de passe | Rôle | Sert à tester |
| ----------- | ------------ | ---- | ------------- |
| `jospin` | (celui du `createsuperuser`) | superutilisateur | tous les droits |
| `moderateur` | `Modo@2026` | groupe `Moderateur` | consulter et modérer, **sans** supprimer ni configurer |
| `mod_categories` | `Mod@2026` | utilisateur ordinaire | vérifier qu'un compte sans groupe reçoit `403` sur `/admin/...` |
| `vendeur_demo` | `Vendeur@2026` | (aucun) | vendeur : gère ses annonces de démonstration |
| `acheteur_demo` | `Acheteur@2026` | (aucun) | acheteur : suit `vendeur_demo` et a 2 favoris |

## Tests

```bash
# Sur PostgreSQL (base de test créée puis détruite automatiquement)
python manage.py test tests

# Sur SQLite en mémoire, plus rapide, emails capturés
python manage.py test tests --settings=config.settings.test

# Tests de concurrence seuls (PostgreSQL obligatoire : verrous de ligne réels)
python manage.py test tests.test_module8_concurrence
```

Les tests de concurrence sont ignorés automatiquement sous SQLite.

## Conventions respectées

- **Aucune `APIView`** : uniquement des `ViewSet` (`ModelViewSet`,
  `GenericViewSet` + mixins génériques).
- **Un fichier par ViewSet / serializer / filtre**, dans un dossier dédié :
  `viewsets/CategorieViewSet.py`, `serializers/CategorieSerializer.py`,
  `filters/CategorieFilter.py`.
- **Permissions strictement issues des groupes Django**
  (`common/permissions/StrictModelPermission.py`) : la méthode HTTP est mappée
  sur la permission exacte, y compris `view_*` pour les lectures.
- **django-filter** avec lookups explicites : `exact`, `icontains`, `gte`,
  `lte`, `isnull`.
- **Localisation** : un seul champ texte libre, recherché en `icontains`.
  Aucune table ni identifiant de localisation : le vendeur écrit où se trouve
  son produit, le client tape un mot, et on retourne tout ce qui **contient**
  ce mot (insensible à la casse).
- **Connexion par `username` + `password`**, jamais par numéro de téléphone.

## Authentification

- `username` : **obligatoire et unique**, c'est l'identifiant de connexion.
- `email` : **facultatif**. S'il est fourni, un code à 6 chiffres est envoyé à
  cette adresse ; le compte reste inactif (`statut_compte = EN_ATTENTE`) tant
  que le code n'est pas saisi. Si l'utilisateur ne reçoit pas le code, c'est
  que l'adresse n'existe pas : le compte ne devient jamais utilisable.
- Aucune vérification de numéro de téléphone.
- JWT avec rotation et révocation (`/auth/logout/` met le refresh en liste noire).

### Envoi des emails

La configuration SMTP est dans [.env](../.env) (Gmail par défaut).

```bash
# Vérifier la configuration et envoyer un email de test
python manage.py tester_email destinataire@exemple.com
```

- Si `EMAIL_HOST_PASSWORD` est **renseigné** → envoi réel par SMTP.
- Si `EMAIL_HOST_PASSWORD` est **vide** → repli automatique sur la console :
  l'email (et donc le code) s'affiche dans le terminal du serveur, rien n'est
  envoyé. Aucune inscription n'échoue pour autant.

Gmail refuse le mot de passe habituel du compte : il faut un **mot de passe
d'application** de 16 caractères (validation en deux étapes activée, puis
`myaccount.google.com` → Sécurité → Mots de passe des applications).

Si le serveur SMTP est injoignable, l'API répond `503` avec un message clair et
le compte **n'est pas créé** — un compte dont l'email ne peut jamais être
vérifié serait inutilisable.

## Modèle d'accès : deux niveaux, pas plus

```bash
python manage.py init_groupes             # crée / met à jour le groupe
python manage.py init_groupes --nettoyer  # supprime les autres groupes
```

| Niveau | Comment | Peut |
| ------ | ------- | ---- |
| **Superutilisateur** | `manage.py createsuperuser` | tout, y compris les **suppressions**, la **configuration** (`/admin/settings/`) et les **statistiques globales** (`/admin/statistics/`) |
| Groupe **`Moderateur`** | `init_groupes` puis ajout du compte au groupe | consulter tout l'espace d'administration, suspendre un compte, modérer une annonce ou un avis, traiter les signalements, lire le journal d'audit et les historiques de litige |
| Utilisateur ordinaire | aucun groupe | tout le reste de l'application : publier, réserver, vendre, évaluer, discuter |

Ce que le groupe `Moderateur` ne peut **pas** faire, délibérément :

| Interdit | Pourquoi |
| -------- | -------- |
| toute suppression (`delete_*`) | un modérateur masque, suspend ou retire ; il n'efface pas |
| créer du contenu (`add_user`, `add_produit`, `add_evaluation`) | il n'agit pas à la place des utilisateurs |
| écrire dans `/admin/settings/` | la configuration de la plateforme relève du superutilisateur |
| lire `/admin/statistics/` | les chiffres globaux relèvent du superutilisateur |
| écrire dans le journal d'audit | aucune route d'écriture n'existe, pour personne |

Un compte **sans groupe** reçoit `403` sur tout `/api/v1/admin/...` — et
continue de vendre normalement, puisque vendre ne demande aucune permission.

### Deux mécanismes de protection distincts

| Endpoints | Protection | Pourquoi |
| --------- | ---------- | -------- |
| `/products/` (vendeur) | **propriété** : `owner=request.user` | le CD prévoit un compte unique acheteur/vendeur : tout utilisateur peut publier, mais uniquement ses propres annonces (scénario 9) |
| `/admin/...` (tout l'espace d'administration) | **permissions** (`StrictModelPermission`) | réservé au superutilisateur et au groupe `Moderateur`, chaque route exigeant la permission de son effet réel |

Les actions personnalisées sont mappées sur la permission de leur effet réel :
`POST /admin/categories/{id}/deactivate/` exige `change_categorie`, pas
`add_categorie`.

## Endpoints livrés

### Module 1 — Auth et comptes

| Méthode | Endpoint | Accès |
| ------- | -------- | ----- |
| POST | `/api/v1/auth/register/` | public |
| POST | `/api/v1/auth/login/` | public |
| POST | `/api/v1/auth/logout/` | authentifié |
| POST | `/api/v1/auth/token/refresh/` | public |
| POST | `/api/v1/auth/email/verify/` | public |
| POST | `/api/v1/auth/email/resend/` | public |
| POST | `/api/v1/auth/password/change/` | authentifié |
| POST | `/api/v1/auth/password/reset/` | public |
| POST | `/api/v1/auth/password/reset/confirm/` | public |
| GET / PUT / PATCH / DELETE | `/api/v1/me/` | authentifié |
| GET | `/api/v1/me/settings/` | authentifié |
| GET / POST | `/api/v1/admin/users/` | permission `accounts.view_user` / `add_user` |
| GET / PUT / PATCH / DELETE | `/api/v1/admin/users/{id}/` | permissions correspondantes |
| POST | `/api/v1/admin/users/{id}/suspend/` | `accounts.change_user` |
| POST | `/api/v1/admin/users/{id}/activate/` | `accounts.change_user` |

### Module 2 — Catégories

| Méthode | Endpoint | Accès |
| ------- | -------- | ----- |
| GET | `/api/v1/public/categories/` | public |
| GET | `/api/v1/public/categories/{id}/` | public |
| GET | `/api/v1/public/categories/tree/` | public |
| GET | `/api/v1/public/categories/{id}/children/` | public |
| GET / POST | `/api/v1/admin/categories/` | `categories.view_categorie` / `add_categorie` |
| GET / PUT / PATCH / DELETE | `/api/v1/admin/categories/{id}/` | permissions correspondantes |
| POST | `/api/v1/admin/categories/{id}/deactivate/` | `categories.change_categorie` |
| POST | `/api/v1/admin/categories/{id}/activate/` | `categories.change_categorie` |

### Module 3 — Mes annonces (vendeur)

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| POST | `/api/v1/products/` | créer une annonce (statut `DRAFT`) |
| GET | `/api/v1/products/` · `/products/my-products/` | mes annonces, tous statuts |
| GET / PUT / PATCH | `/api/v1/products/{id}/` | consulter / modifier mon annonce |
| DELETE | `/api/v1/products/{id}/` | archiver (suppression douce) |
| POST | `/api/v1/products/{id}/publish/` | publier → `ACTIVE`, ou `OUT_OF_STOCK` si stock nul |
| POST | `/api/v1/products/{id}/pause/` | suspendre temporairement |
| GET / PATCH | `/api/v1/products/{id}/stock/` | lire / déclarer `quantite_totale` |
| POST | `/api/v1/products/{id}/images/` | ajouter des images (max 10, 5 Mo, jpg/png/webp) |
| DELETE | `/api/v1/products/{id}/images/{image_id}/` | supprimer une image |

Modération (permissions de groupe) : `GET`/`PATCH`/`DELETE /api/v1/admin/products/`
et `POST /api/v1/admin/products/{id}/moderate/` (exige `products.change_produit`,
motif obligatoire pour un retrait).

### Module 4 — Catalogue public

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| GET | `/api/v1/public/products/` | catalogue des annonces visibles |
| GET | `/api/v1/public/products/{id}/` | fiche produit (incrémente les vues) |
| GET | `/api/v1/public/products/search/` | recherche |
| GET | `/api/v1/public/products/featured/` | produits mis en avant |
| GET | `/api/v1/public/products/latest/` | dernières annonces |
| GET | `/api/v1/public/products/popular/` | annonces les plus consultées |

Seuls les statuts `ACTIVE` et `OUT_OF_STOCK` d'un vendeur actif sont exposés.
Le paramètre `status` est retiré du filtre public : un brouillon ou une annonce
retirée n'est pas accessible, même en forçant l'URL.

### Module 5 — Vendeurs et abonnements

| Méthode | Endpoint | Accès |
| ------- | -------- | ----- |
| GET | `/api/v1/public/sellers/` | public — vendeurs ayant au moins une annonce visible |
| GET | `/api/v1/public/sellers/{id}/` | public — vitrine complète + statistiques |
| GET | `/api/v1/public/sellers/{id}/products/` | public — ses annonces visibles |
| GET | `/api/v1/public/sellers/{id}/reviews/` | public — vide jusqu'au module 11 |
| POST | `/api/v1/following/sellers/{id}/` | authentifié — suivre |
| DELETE | `/api/v1/following/sellers/{id}/` | authentifié — ne plus suivre |
| GET | `/api/v1/following/sellers/` | authentifié — mes vendeurs suivis |
| GET | `/api/v1/following/products/` | authentifié — « Mes vendeurs préférés » |

Sur les endpoints publics, l'authentification est **facultative** : avec un
token, le champ `est_suivi` indique si vous suivez déjà ce vendeur.

### Module 6 — Favoris

| Méthode | Endpoint | Accès |
| ------- | -------- | ----- |
| GET | `/api/v1/favorites/products/` | authentifié — mes favoris (privés) |
| POST | `/api/v1/favorites/products/{id}/` | authentifié — ajouter |
| DELETE | `/api/v1/favorites/products/{id}/` | authentifié — retirer |

`{id}` est l'identifiant du **produit**, pas celui du favori.

### Module 7 — Messagerie

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| POST | `/api/v1/conversations/` | créer **ou retrouver** une conversation |
| GET | `/api/v1/conversations/` | mes conversations (non-lus, dernier message) |
| GET | `/api/v1/conversations/{id}/` | détail |
| GET | `/api/v1/conversations/{id}/messages/` | historique paginé |
| POST | `/api/v1/conversations/{id}/messages/` | envoyer (texte et/ou image) |
| POST | `/api/v1/conversations/{id}/read/` | marquer comme lus |
| POST / DELETE | `/api/v1/conversations/{id}/block/` | bloquer / débloquer |
| POST | `/api/v1/conversations/{id}/report/` | signaler |
| GET | `/api/v1/conversations/unread-count/` | badge global de non-lus |

**WebSocket** : `ws://127.0.0.1:8000/ws/conversations/{id}/?token=<access>`

Le jeton JWT est accepté dans l'en-tête `Authorization`, dans le
sous-protocole, ou en paramètre `?token=` (le plus simple depuis Flutter).

Messages reçus du client :

```json
{"type": "message", "contenu": "Bonjour"}
{"type": "lecture"}
{"type": "saisie", "en_cours": true}
```

Événements émis par le serveur : `connexion.ok`, `message.nouveau`,
`messages.lus`, `saisie`, `erreur`.

Codes de fermeture : `4401` non authentifié, `4403` non participant ou compte
suspendu, `4404` conversation inexistante.

### Module 8 — Réservations

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| POST | `/api/v1/reservations/` | demander une réservation |
| GET | `/api/v1/reservations/` | mes réservations, les deux rôles confondus |
| GET | `/api/v1/reservations/my-requests/` | mes demandes (acheteur) |
| GET | `/api/v1/reservations/my-sales/` | demandes reçues (vendeur) |
| GET | `/api/v1/reservations/summary/` | compteurs (à traiter, immobilisé…) |
| GET | `/api/v1/reservations/{id}/` | détail |
| POST | `/api/v1/reservations/{id}/accept/` | accepter — **immobilise le stock** |
| POST | `/api/v1/reservations/{id}/reject/` | refuser une demande |
| POST | `/api/v1/reservations/{id}/cancel/` | annuler — **libère le stock** |
| POST | `/api/v1/reservations/{id}/quantity/` | modifier la quantité |
| POST | `/api/v1/reservations/{id}/complete/` | transformer en vente |

### Module 9 — Ventes

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| POST | `/api/v1/sales/` | déclarer une vente (sur réservation ou directe) |
| GET | `/api/v1/sales/` | mes ventes et mes achats |
| GET | `/api/v1/sales/my-sales/` | mes ventes (vendeur) |
| GET | `/api/v1/sales/my-purchases/` | mes achats (acheteur) |
| GET | `/api/v1/sales/summary/` | chiffre d'affaires et compteurs |
| GET | `/api/v1/sales/{id}/` | détail |
| POST | `/api/v1/sales/{id}/confirm/` | le vendeur confirme le paiement reçu |
| POST | `/api/v1/sales/{id}/buyer-confirmation/` | l'acheteur confirme la réception |
| POST | `/api/v1/sales/{id}/cancel/` | annuler — **motif obligatoire** |

### Module 10 — Tableau de bord vendeur

Chaque vendeur ne voit que ses propres chiffres : tout part de l'utilisateur
connecté, il n'y a aucun identifiant à falsifier.

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| GET | `/api/v1/seller-dashboard/overview/` | vue générale |
| GET | `/api/v1/seller-dashboard/revenue/` | revenus (jour, semaine, mois, par produit, par catégorie) |
| GET | `/api/v1/seller-dashboard/sales/` | historique des ventes (filtres de `/sales/`) |
| GET | `/api/v1/seller-dashboard/inventory/` | état des stocks |
| GET | `/api/v1/seller-dashboard/reservations/` | compteurs — `?liste=true` pour la liste |
| GET | `/api/v1/seller-dashboard/top-products/` | plus vendus et plus consultés — `?limite=5` |

### Module 11 — Évaluations

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| POST | `/api/v1/reviews/` | déposer un avis sur une vente terminée |
| GET | `/api/v1/reviews/` | les avis qui me concernent (écrits et reçus) |
| GET | `/api/v1/reviews/my-reviews/` | mes avis |
| GET | `/api/v1/reviews/received/` | avis reçus sur mes ventes |
| GET | `/api/v1/reviews/my-rating/` | ma réputation de vendeur |
| GET | `/api/v1/reviews/{id}/` | détail |
| PATCH | `/api/v1/reviews/{id}/` | corriger mon avis (dans le délai) |
| DELETE | `/api/v1/reviews/{id}/` | retirer mon avis (suppression douce) |
| POST | `/api/v1/reviews/{id}/report/` | signaler un avis abusif |
| GET | `/api/v1/public/products/{id}/reviews/` | avis d'un produit (sans authentification) |
| GET | `/api/v1/public/sellers/{id}/reviews/` | avis d'un vendeur (sans authentification) |
| GET | `/api/v1/admin/reviews/` | tous les avis — `reviews.view_evaluation` |
| GET | `/api/v1/admin/reviews/reports/` | signalements en attente — `reviews.view_evaluation` |
| POST | `/api/v1/admin/reviews/{id}/moderate/` | masquer / réafficher — `reviews.change_evaluation` |

### Module 12 — Notifications

| Méthode | Endpoint | Fonction |
| ------- | -------- | -------- |
| GET | `/api/v1/notifications/` | mon historique |
| GET | `/api/v1/notifications/unread-count/` | badge de non-lus |
| GET | `/api/v1/notifications/{id}/` | détail |
| POST | `/api/v1/notifications/read/` | marquer tout (ou `identifiants`) comme lu |
| POST | `/api/v1/notifications/{id}/read/` | marquer une notification comme lue |
| DELETE | `/api/v1/notifications/{id}/` | supprimer de mon historique |
| GET / POST | `/api/v1/notifications/devices/` | mes appareils push / en enregistrer un |
| DELETE | `/api/v1/notifications/devices/{jeton}/` | désinscrire un appareil |
| GET | `/api/v1/notifications/devices/status/` | le push est-il configuré ? |

**WebSocket** : `ws://127.0.0.1:8000/ws/notifications/?token=<access>`

Un seul socket par utilisateur, pour toute l'application. Le client reçoit
`connexion.ok`, `notification.nouvelle`, `notifications.lues`, `compteur`,
`erreur` ; il peut envoyer `{"type":"lecture"}` (avec `identifiants`
facultatifs) et `{"type":"compteur"}`. Fermetures : `4401` non authentifié,
`4403` compte suspendu.

Il n'existe **aucun** moyen de créer une notification par l'API ou par le
socket : c'est toujours la conséquence d'un événement métier.

### Module 14 — Administration

Les autres portes d'administration vivent avec leur module : `/admin/users/`
(module 1), `/admin/categories/` (module 2), `/admin/products/` (module 3),
`/admin/reviews/` (module 11).

| Méthode | Endpoint | Permission exigée |
| ------- | -------- | ----------------- |
| GET | `/api/v1/admin/statistics/` | `moderation.consulter_statistiques` |
| GET | `/api/v1/admin/audit-logs/` | `moderation.view_journalaudit` |
| GET | `/api/v1/admin/audit-logs/actions/` | `moderation.view_journalaudit` |
| GET | `/api/v1/admin/reports/` | `messaging.view_signalementconversation` |
| GET | `/api/v1/admin/reports/conversations/` | `messaging.view_signalementconversation` |
| POST | `/api/v1/admin/reports/conversations/{id}/resolve/` | `messaging.change_signalementconversation` |
| GET | `/api/v1/admin/reports/reviews/` | `reviews.view_evaluation` |
| POST | `/api/v1/admin/reports/reviews/{id}/resolve/` | `reviews.change_evaluation` |
| GET | `/api/v1/admin/stock-movements/` | `products.view_mouvementstock` |
| GET | `/api/v1/admin/sales/` | `sales.view_vente` |
| GET | `/api/v1/admin/reservations/` | `reservations.view_reservation` |
| GET … DELETE | `/api/v1/admin/settings/` | `moderation.*_parametreplateforme` |
| GET | `/api/v1/admin/settings/known-keys/` | `moderation.view_parametreplateforme` |

### Filtres disponibles

**Catégories** : `nom` (icontains), `nom_exact`, `description`, `slug`,
`recherche`, `parent`, `parent_slug`, `racines=true`, `is_active`,
`ordre`/`ordre_gte`/`ordre_lte`, `created_at`/`created_at_gte`/`created_at_lte`,
`updated_at__gte`/`updated_at__lte`, `search=`, `ordering=`.

**Utilisateurs** : `username` (icontains), `nom_complet`, `nom_commercial`,
`email`, `telephone`, `localisation` (icontains), `statut_compte`,
`email_verifie`, `is_active`, `groupe`, `date_joined_gte`, `date_joined_lte`.

**Produits** : `q` (titre + description + catégorie), `titre`, `description`,
`categorie`, `categorie_slug`, `categorie_arbre` (catégorie **et** ses
sous-catégories), `prix_min`, `prix_max`, `prix__gte`, `prix__lte`, `etat`
(`NEUF`/`OCCASION`), `devise`, `localisation` (icontains),
`disponible` (true/false), `quantite_min`,
`owner`, `owner_username`, `est_mis_en_avant`, `nombre_vues__gte`,
`created_at_gte`, `created_at_lte`, `publie_le_gte`, `publie_le_lte`.
Sur `/admin/products/` uniquement : `status`, `status_in`.

**Réservations** : `statut`, `statut_in=PENDING,CONFIRMED`, `actives`,
`expirees`, `acheteur`, `vendeur`, `acheteur_username`, `vendeur_username`,
`produit`, `titre` (icontains), `categorie`, `etat`, `localisation`
(icontains), `prix_min`, `prix_max`,
`quantite_demandee`/`__gte`/`__lte` (idem `quantite_confirmee`,
`quantite_livree`), `confirmee_le__gte`/`__lte`/`__isnull`,
`cloturee_le__gte`/`__lte`/`__isnull`, `created_at_gte`/`_lte`,
`expire_le_gte`/`_lte`, `ordering=`.

**Ventes** : `statut`, `statut_in=PAID,COMPLETED`, `comptabilisables=true`,
`statut_paiement`, `moyen_paiement`, `acheteur`, `vendeur`,
`acheteur_username`, `vendeur_username`, `produit`, `titre` (icontains),
`categorie`, `localisation` (icontains), `montant_min`, `montant_max`,
`montant_total`/`__gte`/`__lte`, `reservation`/`__isnull`,
`confirmee_le__isnull`, `confirmee_par_acheteur_le__isnull`,
`annulee_le__isnull`, `created_at_gte`/`_lte`,
`confirmee_le_gte`/`_lte`, `ordering=`.

Les filtres des ventes s'appliquent aussi à `/sales/summary/` :
`?created_at_gte=2026-01-01` donne le chiffre d'affaires de la période.

**Évaluations** : `statut`, `statut_in`, `signalees=true`, `auteur`,
`vendeur`, `auteur_username`, `vendeur_username`, `produit`, `produit_slug`,
`titre` (icontains), `categorie`, `localisation` (icontains), `commentaire`
(icontains), `avec_commentaire`, `note_produit`/`__gte`/`__lte`,
`note_vendeur`/`__gte`/`__lte`, `vente`, `modifiee_le__isnull`/`__gte`/`__lte`,
`created_at_gte`/`_lte`, `ordering=-created_at`, `-note_produit`.

**Notifications** : `non_lues=true`, `type_notification`,
`type_in=MESSAGE_NOUVEAU,AVIS_NOUVEAU`, `reference_type`, `reference_id`,
`titre` (icontains), `message` (icontains), `lu_le__isnull`/`__gte`/`__lte`,
`created_at_gte`/`_lte`, `ordering=created_at`.

**Journal d'audit** : `action`, `action_in`, `acteur`, `acteur_username`
(icontains), `cible_type`, `cible_id`, `cible_libelle` (icontains), `motif`
(icontains), `adresse_ip`, `created_at_gte`/`_lte`, `search=`, `ordering=`.

**Mouvements de stock** : `type_mouvement`, `type_in`, `produit`, `titre`
(icontains), `owner`, `owner_username` (icontains), `localisation`
(icontains), `effectue_par`, `commentaire` (icontains),
`quantite`/`__gte`/`__lte`, `reference_type`, `reference_id`,
`created_at_gte`/`_lte`.

**Tris produits** : `ordering=prix`, `-prix`, `-publie_le`, `-created_at`,
`-nombre_vues` (popularité), `titre`, `distance_km` (proximité).

**Proximité** : passer `latitude` et `longitude` active le calcul de
`distance_km` (distance orthodromique, loi des cosinus sphérique) ; `rayon_km`
limite le résultat à ce rayon. Les annonces sans coordonnées ont
`distance_km = null` et sont reléguées en fin de tri. Une coordonnée hors
bornes ou malformée renvoie `400`.

## Localisation

Un seul champ texte : `localisation`, sur l'annonce **et** sur le compte.
Pas de table de localisations, pas d'identifiant, pas de hiérarchie.

Le vendeur écrit ce qu'il veut (`Taba`, `Kinindo près du marché de Taba`,
`Gitega centre`) et l'acheteur retrouve l'annonce dès que sa saisie est
contenue dans ce texte :

```
GET /api/v1/public/products/?localisation=taba
GET /api/v1/public/products/?localisation=Taba    → même résultat
GET /api/v1/public/products/?localisation=TABA    → même résultat
```

Le mot est aussi cherché dans la localisation par la recherche générale `q=`.
Les coordonnées GPS restent **facultatives** et servent uniquement au tri par
proximité.

## Favoris produits ≠ vendeurs suivis

Le cahier des charges insiste sur cette distinction, respectée ici :

| | Favori produit (module 6) | Vendeur suivi (module 5) |
| --- | --- | --- |
| Porte sur | un **produit** précis | un **vendeur** |
| Modèle | `favorites.Favori` | `sellers.AbonnementVendeur` |
| Visibilité | privé | nombre d'abonnés public |
| Effet | liste de sauvegardes + alertes | section « Mes vendeurs préférés » |

Suivre un vendeur **n'enlève rien** au catalogue général et ne modifie pas le
classement des recherches : `/following/products/` est une liste
supplémentaire, pas un filtre appliqué au reste de l'API.

## Alertes sur les favoris

Chaque favori enregistre le prix du jour de l'ajout (`prix_a_l_ajout`), ce qui
permet de signaler les changements sans tâche de fond :

| Champ | Signification |
| ----- | ------------- |
| `prix_actuel`, `variation_prix`, `prix_a_change` | hausse ou baisse depuis l'ajout |
| `est_toujours_disponible` | annonce active, vendeur actif et stock disponible |
| `est_retire` | annonce archivée/retirée, ou vendeur désactivé |
| `alerte` | message prêt à afficher dans l'application |

Un favori dont l'annonce est retirée **reste dans la liste** avec son alerte,
au lieu de disparaître sans explication.

## Messagerie : un seul chemin pour écrire

`MessagerieService` est le **seul** point d'entrée qui crée une conversation
ou un message. L'API REST et le consumer WebSocket l'appellent tous les deux,
ce qui garantit que :

- les mêmes règles s'appliquent (participants, blocage, contenu non vide) ;
- un message envoyé en REST arrive sur les sockets ouverts, et inversement ;
- tout message est enregistré dans PostgreSQL — Redis ne sert qu'au transport.

Si Redis devient indisponible, l'envoi REST réussit quand même : le message
est en base, seule la diffusion instantanée est perdue.

### Règles du module 7 appliquées

1. Une conversation démarrée depuis une annonce conserve le produit **et**
   `prix_initial`, figé : changer le prix de l'annonce ne réécrit pas
   l'historique de la négociation (`prix_actuel_produit` permet de comparer).
2. Pas de conversation avec soi-même (contrainte `CheckConstraint` en base).
3. Pas de duplication pour le même couple d'utilisateurs et la même annonce,
   y compris si les rôles sont inversés (deux `UniqueConstraint` partielles).
4. Les rôles sont imposés par l'annonce : le propriétaire est toujours le
   `vendeur`, même quand c'est lui qui écrit le premier.
5. On n'accède jamais à la conversation d'autrui : `404`, en REST comme en
   WebSocket (code `4403`).
6. Les permissions sont vérifiées avant chaque opération, actions comprises.
7. Une conversation bloquée interdit l'envoi **aux deux** participants, mais
   l'historique reste lisible ; seul l'auteur du blocage peut le lever.

## Réservations et ventes : les trois quantités

Tout le module 8 tient dans une seule invariante, garantie en base par une
`CheckConstraint` :

```
quantite_totale >= quantite_reservee + quantite_vendue
quantite_disponible = quantite_totale - quantite_reservee - quantite_vendue
```

Le vendeur ne saisit jamais que `quantite_totale`. Les deux autres sont
pilotées exclusivement par les services des modules 8 et 9.

### Le stock n'est immobilisé qu'à l'acceptation

Une demande (`PENDING`) n'empêche personne d'acheter : elle est seulement
vérifiée contre le disponible du moment. C'est l'acceptation du vendeur qui
met la quantité de côté. C'est exactement l'exemple du cahier des charges :
10 téléphones, un acheteur en demande 3, **le vendeur confirme**, réservé = 3,
disponible = 7.

### Protection contre les réservations concurrentes

Chaque opération suit le même schéma, dans une seule transaction :

1. `SELECT … FOR UPDATE` sur la ligne d'inventaire ;
2. relecture des quantités **après** le verrou ;
3. décision, application, trace du mouvement.

Sans l'étape 2, deux acceptations simultanées liraient toutes les deux
« 2 disponibles » et le stock partirait en négatif. Le fichier
`tests/test_module8_concurrence.py` lance de vrais threads sur PostgreSQL
pour le prouver (scénario 10 et paragraphe 8.1 du cahier des charges) : sur
les 2 dernières unités, une seule acceptation passe, l'autre reçoit
`400 Stock insuffisant`. Ces tests sont automatiquement ignorés sur SQLite,
où chaque connexion a sa propre base.

### Vente partielle

Le scénario central du cahier des charges, en une seule requête :

```
POST /api/v1/reservations/{id}/complete/   {"quantite": 2}
```

Le client avait réservé 3 pantalons à 35 000 BIF, il n'en prend que 2. Le
serveur, dans une transaction : enregistre la vente de 2 unités (70 000 BIF),
libère les 3 unités réservées, en passe 2 en vendues et rend la 3<sup>e</sup>
disponible. La réservation passe en `FULFILLED` avec
`quantite_livree = 2` et `quantite_non_achetee = 1`.

### Expiration configurable

`RESERVATION_DUREE_HEURES` (défaut 72) dans le `.env`. Le compte à rebours
repart à l'acceptation. Deux filets :

```bash
python manage.py expirer_reservations --simulation   # voir sans rien changer
python manage.py expirer_reservations                # libérer le stock
```

À planifier dans le planificateur de tâches. En plus, la lecture des listes
de réservations déclenche l'expiration des réservations dépassées : une
plateforme sans ordonnanceur ne doit jamais garder du stock bloqué.

Une réservation annulée ou expirée **ne touche jamais `quantite_vendue`**.

### Les revenus ne viennent que des ventes

`GET /api/v1/sales/summary/` ne compte que les ventes `PAID` et `COMPLETED`.
Une réservation acceptée, même de grande valeur, n'entre jamais dans le
chiffre d'affaires — règle explicite du cahier des charges. `valeur_estimee`
sur une réservation est indicatif, au prix du jour.

Chaque `LigneVente` fige son `prix_unitaire`. Changer le prix d'une annonce
ne réécrit donc aucun revenu passé, et le total d'une vente reste celui qui a
été réellement encaissé.

### Historique des mouvements de stock

Aucune quantité ne bouge sans explication. Chaque opération écrit un
`MouvementStock` (`RESERVATION`, `LIBERATION`, `VENTE`, `ANNULATION_VENTE`)
avec son auteur, sa référence et **une photographie du stock résultant** :
l'histoire d'un produit se relit sans rien recalculer. Ces lignes sont en
lecture seule, même dans l'admin Django.

### Qui peut faire quoi

| Action | Acheteur | Vendeur |
| ------ | :------: | :-----: |
| demander une réservation | ✅ | — (pas sur sa propre annonce) |
| accepter / refuser | — | ✅ |
| annuler une réservation | ✅ | ✅ |
| modifier la quantité | ✅ tant que `PENDING` | ✅ une fois `CONFIRMED` |
| déclarer une vente | — | ✅ |
| confirmer le paiement reçu | — | ✅ |
| confirmer la réception | ✅ | — |
| annuler une vente | — | ✅ avec motif |

La protection repose sur la **propriété**, pas sur un groupe : la réservation
ou la vente d'autrui renvoie `404`. Les permissions `view_reservation` et
`view_vente` ne servent qu'à l'administration, pour arbitrer un litige — et
jamais à modifier une vente à la place du vendeur, ce que le cahier des
charges interdit.

L'annulation d'une vente exige un motif, remet les quantités en disponible et
laisse une trace d'audit, sans réécrire ni les lignes ni les prix. Si le
paiement avait été déclaré reçu, la vente part en `REFUNDED` plutôt qu'en
`CANCELLED`, pour que le remboursement reste visible.

### Moyens de paiement

`CASH`, `LUMICASH`, `ECOCASH`, `VIREMENT`, `AUTRE`. Purement **déclaratifs** :
l'application ne prétend pas vérifier un transfert financier, conformément au
cahier des charges. Le double accusé (vendeur puis acheteur) sert justement à
détecter les ventes déclarées à tort.

## Tableau de bord : d'où viennent les chiffres

Le module 10 n'a **ni modèle ni migration** : c'est une vue de lecture sur les
modules 3, 7, 8, 9 et 11. Tout est agrégé en base, donc il n'existe aucun
compteur dénormalisé à resynchroniser le jour où une vente est annulée.

### La règle qui gouverne tout le module

Le paragraphe E du cahier des charges, repris à l'identique dans un test :

| Événement | Quantité | Montant |
| --------- | -------: | ------: |
| Réservations | 5 | 250 000 BIF |
| Ventes confirmées | 3 | 150 000 BIF |

`chiffre_affaires_total` vaut **150 000**, pas 250 000. La valeur des
réservations est renvoyée séparément, dans `valeur_reservations_en_cours`, et
n'entre dans aucun total. Les revenus se lisent toujours sur `LigneVente`
filtrée par les statuts comptabilisables (`PAID`, `COMPLETED`), jamais sur les
réservations.

Les périodes (jour, semaine depuis lundi, mois) se mesurent sur
`confirmee_le` : le moment où l'argent est entré, pas celui où la vente a été
saisie.

`/reservations/` du tableau de bord libère au passage les réservations
périmées : un tableau de bord ne doit pas afficher du stock immobilisé à tort.

## Évaluations : pourquoi le double accusé du module 9 compte

Une évaluation n'est possible que sur une vente **terminée** (`COMPLETED`),
c'est-à-dire confirmée par le vendeur **puis** par l'acheteur. C'est ce qui
donne tout son sens à `/sales/{id}/buyer-confirmation/` : sans cette seconde
confirmation, un vendeur pourrait déclarer de fausses ventes pour se fabriquer
des bonnes notes.

Les autres règles du cahier des charges, toutes testées :

- échelle de 1 à 5, garantie par une `CheckConstraint` en base et pas
  seulement par le serializer ;
- deux notes distinctes, `note_produit` et `note_vendeur` ;
- le produit et le vendeur sont **déduits de la vente**, jamais saisis : on ne
  peut pas noter un vendeur chez qui on n'a rien acheté ;
- un utilisateur n'évalue pas son propre produit (contrainte
  `evaluation_pas_son_propre_produit`) ;
- un seul avis par vente (`UniqueConstraint` sur `vente` + `auteur`) — deux
  achats chez le même vendeur donnent bien droit à deux avis ;
- les moyennes ne comptent que les avis **valides**.

### Masquer plutôt que supprimer

Un avis n'est jamais effacé. Il passe en `RETIREE` (par son auteur) ou en
`MASQUEE` (par la modération) : il sort des moyennes et des listes publiques
mais reste en base. Effacer la ligne rendrait l'historique d'une réputation
invérifiable, et permettrait de faire disparaître un mauvais avis en obtenant
son retrait.

La modération **ne réécrit jamais** les notes ni le texte — ils appartiennent
à leur auteur, y compris dans l'admin Django où ils sont en lecture seule.
Elle masque, et la décision est à la fois explicable et imputable :
`motif_moderation`, `moderee_par` et `moderee_le` sont conservés.

### Délai de modification

`EVALUATION_DELAI_MODIFICATION_HEURES` (48 h par défaut) dans le `.env`.
Passé ce délai, l'avis est définitif : une réputation ne doit pas pouvoir être
réécrite des mois plus tard, par exemple sous la pression du vendeur.

### Signalement

Ouvert à **tout utilisateur connecté**, et pas seulement aux parties
prenantes : un avis insultant nuit à toute la plateforme, et n'importe qui
peut le lire sur la vitrine du vendeur. L'auteur de l'avis, lui, n'a rien à
signaler. Un même avis ne peut être signalé qu'une fois par personne tant que
la modération n'a pas tranché (contrainte unique partielle).

### Deux représentations volontairement différentes

La version publique d'un avis ne contient ni identifiant de vente, ni statut
de modération, ni motif : un visiteur n'a pas à savoir qu'un autre avis a été
masqué, ni à remonter jusqu'à une transaction. Un test vérifie l'absence de
ces champs.

### Les emplacements du module 5 sont désormais remplis

`note_moyenne` et `nombre_evaluations` sur `/public/sellers/{id}/`, et
`/public/sellers/{id}/reviews/`, renvoyaient des valeurs vides en attendant ce
module. Ils sont alimentés, et la note du vendeur est **annotée en une seule
requête** dans la liste des vendeurs, pour ne pas déclencher une agrégation
par carte affichée. La fiche produit publique expose de même un bloc
`reputation` ; la liste du catalogue reste sans note, délibérément, pour la
même raison.

## Notifications : le push ne doit jamais être indispensable

Le cahier des charges l'exige : « les notifications push doivent être une
fonctionnalité complémentaire ; l'application doit continuer à fonctionner
même si les services push ne sont pas disponibles ». D'où la hiérarchie :

1. la **notification interne**, en base, est la seule source de vérité ;
2. le **WebSocket** la transmet instantanément si l'utilisateur est connecté ;
3. le **push** (Firebase ou autre) la pousse si une clé est configurée.

Sans `FCM_SERVER_KEY` dans le `.env`, le service push est simplement inactif :
aucune erreur, aucune exception, et l'historique reste complet.
`GET /notifications/devices/status/` permet à l'application mobile de savoir
si elle doit proposer l'activation du push, au lieu de le deviner.

### Une notification ne casse jamais l'opération qui la déclenche

C'est la garantie la plus importante du module, et elle a demandé deux
mécanismes :

- chaque émetteur d'événement est enveloppé : son échec est journalisé en
  `warning`, jamais propagé ;
- l'écriture en base se fait dans un **point de sauvegarde**
  (`transaction.atomic()` imbriqué). Les émetteurs sont appelés depuis
  l'intérieur des transactions métier : sans ce savepoint, une erreur de
  base dans la notification marquerait toute la transaction comme cassée et
  ferait échouer l'acceptation de la réservation elle-même.

Six tests le vérifient en faisant réellement échouer
`Notification.objects.create` au milieu d'une réservation, d'un message et
d'une vente : l'opération métier aboutit, et aucune notification fantôme ne
subsiste.

### Les événements branchés

| Événement métier | Destinataire |
| ---------------- | ------------ |
| nouveau message | l'interlocuteur |
| nouvelle demande de réservation | le vendeur |
| réservation acceptée / refusée | l'acheteur |
| réservation annulée | la partie qui n'a pas annulé |
| réservation expirée | **les deux** : l'un perd sa réservation, l'autre récupère son stock |
| réception confirmée par le client | le vendeur |
| nouvel avis | le vendeur |
| produit presque épuisé / en rupture | le vendeur |
| favori devenu indisponible | ceux qui l'avaient sauvegardé |
| nouvelle annonce d'un vendeur suivi | ses abonnés |
| compte suspendu / réactivé, annonce ou avis modéré | l'intéressé |

Deux garde-fous appris en écrivant les tests : les alertes de stock ne se
dupliquent pas tant que la précédente n'est pas lue (sinon chaque vente
ferait sonner le téléphone du vendeur), et une annonce mise en pause puis
republiée ne renotifie pas les abonnés — seule la **première** mise en ligne
le fait.

Un détail qui compte : la suspension d'un compte met `is_active` à faux, et
le service refuse normalement de notifier un compte inactif. L'avis de
suspension lève explicitement cette règle, sinon l'intéressé ne saurait
jamais ce qui lui est arrivé.

## Module 13 — ce qui a remplacé la hiérarchie géographique

Le cahier des charges prévoyait des tables Pays / Province / Commune / Zone /
Quartier. Sur votre demande, ce module a été remplacé par **un seul champ
texte libre**, `localisation`, et il n'y a donc ni table ni identifiant de
localisation. Les fonctionnalités attendues sont néanmoins toutes livrées :

| Attendu du module 13 | Où c'est livré |
| -------------------- | -------------- |
| choisir sa localisation | `localisation` sur le compte (module 1) |
| enregistrer la localisation d'un produit | `localisation` sur l'annonce (module 3) |
| rechercher par province / commune | `?localisation=taba` en `icontains` (module 4) |
| rechercher à proximité | `?latitude=&longitude=&rayon_km=` et tri `distance_km` (module 4) |
| afficher une adresse descriptive | le champ texte, écrit librement par le vendeur |
| ouvrir une position sur une carte | `latitude` / `longitude`, facultatives, exposées dans l'API |
| ne pas exiger l'adresse exacte | le champ est optionnel et libre : un point de rencontre suffit |

La règle de confidentialité du cahier des charges est donc respectée plus
simplement qu'avec une hiérarchie : le vendeur écrit ce qu'il veut.

## Administration : constater sans pouvoir réécrire

Le module 14 n'ajoute que deux modèles, parce que l'essentiel de
l'administration est livré avec chaque module métier. Ce qu'il apporte :

### Journal d'audit

Chaque décision d'administration s'inscrit toute seule dans
`/admin/audit-logs/` : suspension et réactivation de compte, modération
d'annonce et d'avis, suppression d'annonce, modification de catégorie,
traitement de signalement, changement de paramètre. Chaque entrée porte
l'acteur (recopié en texte, pour rester lisible même si le compte
disparaît), la cible, le motif, l'adresse IP et l'état **avant / après**.

Le journal est en **lecture seule**, y compris pour un compte détenant
`add_journalaudit` et `change_journalaudit` : un test le vérifie en donnant
ces permissions et en constatant un `405`. Dans l'admin Django, ajout,
modification et suppression sont également désactivés. Un journal que l'on
peut retoucher ne vaut rien devant un litige.

### Consultation en cas de litige

`/admin/stock-movements/`, `/admin/sales/` et `/admin/reservations/`
répondent à l'exigence du cahier des charges. Aucune action d'écriture n'y
existe : corriger une vente reste l'affaire de son vendeur, via
`/sales/{id}/cancel/` et son motif obligatoire. Les trois permissions sont
indépendantes — voir le stock n'ouvre pas les ventes.

### Signalements

Les deux sortes (conversations et avis) ne sont **pas** fusionnées dans une
liste unique : cela imposerait soit une table polymorphe, soit un tri en
mémoire sur deux requêtes, qui mentirait sur la pagination. L'API expose un
résumé commun, puis une liste par sorte.

### Configuration de la plateforme

`/admin/settings/` rend trois réglages métier modifiables sans
redéploiement, et ils prennent effet **immédiatement** :

| Clé | Effet |
| --- | ----- |
| `RESERVATION_DUREE_HEURES` | délai d'expiration d'une réservation |
| `EVALUATION_DELAI_MODIFICATION_HEURES` | fenêtre de correction d'un avis |
| `STOCK_SEUIL_ALERTE` | seuil de l'alerte « produit presque épuisé » |

Ordre de priorité : base de données, puis `.env`, puis la valeur par défaut
du code. **La table peut rester vide** : la plateforme se comporte alors
exactement comme avant l'existence du module. Une valeur incompatible avec
son type est refusée en `400` plutôt qu'acceptée puis ignorée silencieusement,
et `/admin/settings/known-keys/` liste les clés que le code sait réellement
lire — pour éviter les réglages fantômes.

### Statistiques globales

`/admin/statistics/` couvre les indicateurs du chapitre 11 : utilisateurs
(dont comptes suspendus et vendeurs réels), annonces par statut, réservations
et leur taux de transformation, ventes et chiffre d'affaires, messagerie,
notes moyennes, file de modération. Même règle qu'au module 10 : le chiffre
d'affaires ne compte que les ventes confirmées. La permission
`moderation.consulter_statistiques` est dédiée, pour qu'un groupe puisse voir
les chiffres sans accéder au journal ni à la configuration.

## Règles métier du module 3 appliquées

1. `quantite_disponible = quantite_totale - quantite_reservee - quantite_vendue`
2. Chaque annonce appartient obligatoirement à un utilisateur ; `owner` est
   imposé par le serveur et ne peut pas être envoyé par le client.
3. Un vendeur ne voit et ne modifie que ses propres annonces (`404` sinon).
4. Le vendeur ne modifie jamais `quantite_reservee` ni `quantite_vendue` :
   ces champs sont en lecture seule et appartiennent aux modules 8 et 9.
5. `quantite_totale` ne peut pas descendre sous `réservé + vendu`.
6. Un produit sans stock disponible passe automatiquement en `OUT_OF_STOCK`,
   et revient en `ACTIVE` dès qu'il est réapprovisionné.
7. `status` n'est pas modifiable directement : il passe par `publish`,
   `pause`, `DELETE` (archivage) ou la modération.
8. Une annonce retirée par l'administration (`REMOVED`) ne peut pas être
   republiée par son vendeur.
9. Le prix de l'annonce est modifiable librement : les ventes déjà
   enregistrées conserveront leur propre prix unitaire (module 9).
10. Suppression douce : `DELETE` archive l'annonce pour préserver
    l'historique des réservations et des ventes.
