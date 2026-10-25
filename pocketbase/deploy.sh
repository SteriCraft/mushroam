#!/usr/bin/env bash
# Met à jour le schéma (pb_migrations) et les règles serveur (pb_hooks) de PocketBase sur le Raspberry.
# À lancer depuis le clone du dépôt sur le Pi : bash pocketbase/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
DEST=/opt/pocketbase
sudo mkdir -p "$DEST/pb_migrations" "$DEST/pb_hooks"
sudo cp -r pocketbase/pb_migrations/. "$DEST/pb_migrations/"
sudo cp -r pocketbase/pb_hooks/. "$DEST/pb_hooks/"
sudo chown -R pocketbase:pocketbase "$DEST"
sudo systemctl restart pocketbase  # les nouvelles migrations s'appliquent au démarrage
sleep 2
curl -s http://127.0.0.1:8090/api/health && echo
