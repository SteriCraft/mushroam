/// <reference path="../pb_data/types.d.ts" />
// Schéma des sorties de terrain : comptes, espèces, sorties, observations.
// Appliqué automatiquement au démarrage de PocketBase (dossier pb_migrations).

const CONNECTE = '@request.auth.id != ""';
// Membre d'une sortie : son auteur ou un participant.
const MEMBRE = (p) => `(${p}auteur = @request.auth.id || ${p}participants.id ?= @request.auth.id)`;

migrate((app) => {
  // Comptes : connexion par nom d'utilisateur, e-mail facultatif.
  const users = app.findCollectionByNameOrId("users");
  users.fields.getByName("email").required = false;
  users.fields.add(new TextField({
    name: "username", required: true, min: 3, max: 30, pattern: "^[a-zA-Z0-9_.-]+$", presentable: true,
  }));
  users.addIndex("idx_users_username", true, "username COLLATE NOCASE", "");
  users.passwordAuth.identityFields = ["username"];
  // Les comptes se voient entre eux (pour ajouter des participants) ; l'e-mail reste masqué.
  users.listRule = CONNECTE;
  users.viewRule = CONNECTE;
  users.createRule = "";  // inscription ouverte, mais code d'invitation exigé (pb_hooks/inscription.pb.js)
  app.save(users);

  // Espèces : liste commune, enrichie par les utilisateurs.
  const especes = new Collection({
    type: "base", name: "especes",
    listRule: CONNECTE, viewRule: CONNECTE,
    createRule: CONNECTE + " && cree_par = @request.auth.id",
    updateRule: null, deleteRule: null,  // corrections par l'administrateur seulement
    fields: [
      { type: "text", name: "nom", required: true, max: 200, presentable: true },  // nom scientifique
      { type: "text", name: "nom_fr", max: 200 },
      { type: "number", name: "inat_id", onlyInt: true },
      { type: "relation", name: "cree_par", collectionId: users.id, maxSelect: 1 },
      { type: "autodate", name: "created", onCreate: true },
    ],
    indexes: ["CREATE UNIQUE INDEX idx_especes_nom ON especes (nom COLLATE NOCASE)"],
  });
  app.save(especes);

  // Sorties : visibles et modifiables par leurs membres, supprimables par leur auteur.
  const sorties = new Collection({
    type: "base", name: "sorties",
    listRule: MEMBRE(""), viewRule: MEMBRE(""),
    createRule: CONNECTE + " && auteur = @request.auth.id",
    updateRule: MEMBRE("") + " && (@request.body.auteur:isset = false || @request.body.auteur = auteur)",
    deleteRule: "auteur = @request.auth.id",
    fields: [
      { type: "relation", name: "auteur", collectionId: users.id, maxSelect: 1, required: true },
      { type: "text", name: "titre", max: 200, presentable: true },
      { type: "date", name: "date", required: true },
      { type: "text", name: "commentaire", max: 5000 },
      { type: "relation", name: "participants", collectionId: users.id, maxSelect: 50 },
      { type: "autodate", name: "created", onCreate: true },
      { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
    ],
  });
  app.save(sorties);

  // Observations d'une sortie. Sans espèce = « À identifier » ; plusieurs espèces = doute.
  const observations = new Collection({
    type: "base", name: "observations",
    listRule: MEMBRE("sortie."), viewRule: MEMBRE("sortie."),
    createRule: MEMBRE("sortie.") + " && auteur = @request.auth.id",
    updateRule: MEMBRE("sortie.") + " && (@request.body.auteur:isset = false || @request.body.auteur = auteur)"
      + " && (@request.body.sortie:isset = false || @request.body.sortie = sortie)",
    deleteRule: "auteur = @request.auth.id || sortie.auteur = @request.auth.id",
    fields: [
      { type: "relation", name: "sortie", collectionId: sorties.id, maxSelect: 1, required: true, cascadeDelete: true },
      { type: "relation", name: "auteur", collectionId: users.id, maxSelect: 1, required: true },
      { type: "date", name: "date", required: true },  // date et heure de l'observation
      { type: "geoPoint", name: "position" },
      { type: "number", name: "precision_m", min: 0 },  // précision GPS du téléphone
      { type: "relation", name: "especes", collectionId: especes.id, maxSelect: 10 },
      { type: "text", name: "commentaire", max: 5000 },
      // Photos protégées : lisibles seulement avec un jeton de fichier (membres de la sortie).
      { type: "file", name: "photos", maxSelect: 10, maxSize: 10485760, protected: true,
        mimeTypes: ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"],
        thumbs: ["300x300", "1200x0"] },
      { type: "autodate", name: "created", onCreate: true },
      { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
    ],
  });
  app.save(observations);
}, (app) => {
  for (const name of ["observations", "sorties", "especes"]) {
    app.delete(app.findCollectionByNameOrId(name));
  }
  const users = app.findCollectionByNameOrId("users");
  users.passwordAuth.identityFields = ["email"];
  users.removeIndex("idx_users_username");
  users.fields.removeByName("username");
  users.fields.getByName("email").required = true;
  users.listRule = "id = @request.auth.id";
  users.viewRule = "id = @request.auth.id";
  app.save(users);
});
