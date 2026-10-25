# Sorties de terrain : serveur PocketBase

Le site (GitHub Pages) est statique. Les comptes, sorties, observations et photos sont dans un
PocketBase installé sur le Raspberry (`/opt/pocketbase`, service systemd `pocketbase`), exposé
par Tailscale Funnel : https://raspberrypi.tailcb6614.ts.net/ (administration : `/_/`).

## Contenu

- `pb_migrations/` : schéma des collections et règles d'accès, appliqués au démarrage.
- `pb_hooks/inscription.pb.js` : code d'invitation exigé à l'inscription
  (variable `MUSHROAM_CODE_INVITATION` du service ; sans elle, inscription fermée).
- `deploy.sh` : copie ces fichiers sur le Pi et redémarre le service.

## Collections

| Collection | Contenu | Accès |
|---|---|---|
| `users` | nom d'utilisateur (identifiant de connexion), e-mail facultatif et masqué | visibles des comptes connectés |
| `especes` | nom scientifique (unique, sans tenir compte de la casse), nom français, id iNat | lecture et ajout : connectés ; correction : administrateur |
| `sorties` | auteur, titre, date, commentaire, participants | membres (auteur + participants) ; suppression : auteur |
| `observations` | sortie, auteur, date et heure, position GPS et précision, espèces (aucune = « À identifier », plusieurs = doute), commentaire, photos | membres de la sortie ; suppression : auteur de l'observation ou de la sortie |

Les photos sont protégées : leur adresse ne marche qu'avec un jeton de fichier
(`/api/files/token`), délivré aux membres de la sortie.

## Mise à jour sur le Pi

```bash
cd ~/mushroam && bash pocketbase/deploy.sh
```

## Test en local

```bash
MUSHROAM_CODE_INVITATION=test ./pocketbase serve --http=127.0.0.1:8091 \
  --migrationsDir=pocketbase/pb_migrations --hooksDir=pocketbase/pb_hooks
```
