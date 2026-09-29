# Format des réponses

Toute réponse JSON de l'API (hors téléchargement de fichier, voir plus
bas) est enveloppée dans une forme standard, façon Rivet. `data` (ou
`errors`) ne contient QUE la réponse réelle — toute métadonnée
(statut, code HTTP, durée, pagination) va dans `meta`, jamais mélangée
dedans.

## Succès

```json
{
  "data": { ... },
  "meta": {
    "status": "success",
    "code": 200,
    "duration_ms": 4.2
  }
}
```

- `data` contient la vraie réponse — un objet pour une ressource
  unique, un tableau pour une liste. Rien d'autre n'y est mélangé.
- `meta.status`/`meta.code` répètent le statut et le code HTTP de la
  réponse (aussi lisibles sur la réponse HTTP elle-même — présents
  ici pour que le corps JSON se suffise à lui-même).
- `meta.duration_ms` : temps de traitement de la requête côté
  serveur, en millisecondes. Toujours présent.

## Listing (pagination)

Pour un listing, `data` reste uniquement le tableau, et `meta` reçoit
en plus les informations de pagination — voir `docs/FILTERS.md` pour
le détail complet (`?page=`, `?limit=`, etc.) :

```json
{
  "data": [ ... ],
  "meta": {
    "status": "success",
    "code": 200,
    "duration_ms": 5.1,
    "total": 25,
    "page": 1,
    "limit": 10,
    "total_pages": 3,
    "previous_page": null,
    "next_page": 2
  }
}
```

## Erreur

```json
{
  "errors": {
    "detail": "..."
  },
  "meta": {
    "status": "error",
    "code": 400,
    "duration_ms": 0.8
  }
}
```

Le contenu de `errors` reprend exactement ce que l'erreur renvoyait
avant l'enveloppe (le plus souvent `{"detail": "..."}`) — aucune
information perdue, juste déplacée sous cette clé.

## Contraintes de la base (422 / 409)

Un champ obligatoire absent, une valeur déjà utilisée, une référence
inexistante : la base refuse, et Forge le traduit en réponse claire
plutôt qu'en `500` (sans jamais montrer le SQL ni les valeurs).

- **422** — champ obligatoire manquant, avec son nom :
  `{"errors": {"detail": "Champ obligatoire manquant : label"}, ...}`
- **409** — conflit avec une contrainte (valeur déjà utilisée, référence
  inexistante) : `Conflit avec une contrainte de la base (...)`.

Un contrôleur avec un schéma Pydantic (comme `BookController`) répond
déjà `422` plus tôt, avec le détail de chaque champ invalide.

## Ce qui n'est jamais enveloppé

Le contenu binaire d'un fichier (`GET /files/{id}` une fois l'upload
terminé, `GET /files/{id}/download`) reste tel quel — jamais transformé
en JSON. Repéré par le `Content-Type` de la réponse (tout ce qui n'est
pas `application/json` passe sans y toucher) : envelopper un fichier
casserait purement et simplement le téléchargement.

`GET /openapi.json` non plus, même s'il est en JSON — Swagger/Redoc
s'attendent à trouver `openapi`/`info`/`paths` à la racine du document,
pas sous `data` (sinon "version field missing", le lecteur ne
reconnaît plus le document du tout).

## Comment ça marche

Un seul middleware (`forge/middleware/envelope.py`,
`ResponseEnvelopeMiddleware`) s'occupe de tout — aucun Controller n'a
besoin de connaître ce format, il continue de renvoyer ses données
normalement (un objet, une liste, un `ListResult`...). Le middleware
intercepte la réponse juste avant qu'elle parte au client, mesure le
temps écoulé, et construit l'enveloppe autour.
