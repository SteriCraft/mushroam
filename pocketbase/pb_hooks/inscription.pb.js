/// <reference path="../pb_data/types.d.ts" />
// Inscription : code d'invitation exigé (variable d'environnement MUSHROAM_CODE_INVITATION).
// Sans code configuré, l'inscription est fermée ; l'administrateur peut toujours créer des comptes.

onRecordCreateRequest((e) => {
  if (!e.hasSuperuserAuth()) {
    const attendu = $os.getenv("MUSHROAM_CODE_INVITATION");
    const recu = String(e.requestInfo().body["code_invitation"] || "");
    if (!attendu || recu !== attendu) {
      throw new BadRequestError("Code d'invitation incorrect.");
    }
  }
  e.next();
}, "users");
