// Onglet Sorties : comptes et sorties de terrain, enregistrés dans PocketBase (Raspberry).
// Dépend du SDK PocketBase (variable globale PocketBase) chargé avant ce fichier.
(function () {
  const root = document.getElementById("sorties-app");
  if (!root || typeof PocketBase === "undefined") {
    if (root) root.innerHTML = '<p class="sx-err">Impossible de charger le module de connexion (pas de réseau ?).</p>';
    return;
  }
  const PB_URL = new URLSearchParams(location.search).get("pb") || root.dataset.pb;
  const pb = new PocketBase(PB_URL);
  pb.autoCancellation(false);

  // --- Outils ---------------------------------------------------------------
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c != null) el.append(c);
    return el;
  }
  function field(label, input, hint) {
    return h("label", { class: "sx-field" }, h("span", {}, label), input, hint ? h("small", {}, hint) : null);
  }
  // Messages d'erreur du serveur, traduits.
  function errorText(err) {
    if (!err || err.status === 0) return "Serveur injoignable. Le Raspberry est peut-être éteint ou hors ligne.";
    const data = (err.response && err.response.data) || {};
    const parts = [];
    for (const [name, e] of Object.entries(data)) {
      const label = { username: "Nom d'utilisateur", password: "Mot de passe", passwordConfirm: "Confirmation" }[name] || name;
      const msg = {
        validation_not_unique: "déjà pris",
        validation_required: "obligatoire",
        validation_values_mismatch: "les deux mots de passe diffèrent",
        validation_invalid_format: "caractères autorisés : lettres, chiffres, point, tiret, tiret bas",
        validation_length_out_of_range: "longueur incorrecte",
        validation_min_text_constraint: "trop court",
        validation_max_text_constraint: "trop long",
      }[e.code] || e.message;
      parts.push(label + " : " + msg);
    }
    if (parts.length) return parts.join(" · ");
    const m = (err.response && err.response.message) || err.message || "";
    if (/failed to authenticate/i.test(m)) return "Nom d'utilisateur ou mot de passe incorrect.";
    if (/too many requests/i.test(m)) return "Trop de tentatives. Réessaie dans quelques minutes.";
    return m || "Erreur inattendue.";
  }
  function show(...nodes) { root.replaceChildren(...nodes); }
  function busy(form, on) { form.querySelectorAll("button, input").forEach((el) => { el.disabled = on; }); }

  // --- Vues -----------------------------------------------------------------
  function viewLogin(message) {
    const err = h("p", { class: "sx-err", role: "alert" }, message || "");
    const user = h("input", { name: "username", autocomplete: "username", required: true, autocapitalize: "none" });
    const pass = h("input", { name: "password", type: "password", autocomplete: "current-password", required: true });
    const form = h("form", { class: "sx-card", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = ""; busy(form, true);
      try {
        await pb.collection("users").authWithPassword(user.value.trim(), pass.value);
        viewHome();
      } catch (x) { err.textContent = errorText(x); busy(form, false); }
    } },
      h("h3", {}, "Connexion"),
      field("Nom d'utilisateur", user),
      field("Mot de passe", pass),
      err,
      h("div", { class: "sx-actions" },
        h("button", { type: "submit", class: "sx-btn" }, "Se connecter"),
        h("a", { href: "#sorties", onclick: (e) => { e.preventDefault(); viewSignup(); } }, "Créer un compte")));
    show(form);
    user.focus();
  }

  function viewSignup() {
    const err = h("p", { class: "sx-err", role: "alert" });
    const user = h("input", { name: "username", autocomplete: "username", required: true, autocapitalize: "none",
      minlength: 3, maxlength: 30, pattern: "[a-zA-Z0-9_.\\-]+" });
    const pass = h("input", { name: "password", type: "password", autocomplete: "new-password", required: true, minlength: 8 });
    const pass2 = h("input", { name: "passwordConfirm", type: "password", autocomplete: "new-password", required: true, minlength: 8 });
    const code = h("input", { name: "code", required: true, autocapitalize: "none", autocomplete: "off" });
    const form = h("form", { class: "sx-card", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      if (pass.value !== pass2.value) { err.textContent = "Les deux mots de passe diffèrent."; return; }
      busy(form, true);
      try {
        await pb.collection("users").create({
          username: user.value.trim(), password: pass.value, passwordConfirm: pass2.value, code_invitation: code.value.trim(),
        });
        await pb.collection("users").authWithPassword(user.value.trim(), pass.value);
        viewHome();
      } catch (x) { err.textContent = errorText(x); busy(form, false); }
    } },
      h("h3", {}, "Créer un compte"),
      field("Nom d'utilisateur", user, "3 à 30 caractères : lettres, chiffres, point, tiret, tiret bas."),
      field("Mot de passe", pass, "Au moins 8 caractères."),
      field("Confirmer le mot de passe", pass2),
      field("Code d'invitation", code, "Demande-le à l'administrateur du site."),
      err,
      h("div", { class: "sx-actions" },
        h("button", { type: "submit", class: "sx-btn" }, "Créer le compte"),
        h("a", { href: "#sorties", onclick: (e) => { e.preventDefault(); viewLogin(); } }, "J'ai déjà un compte")));
    show(form);
    user.focus();
  }

  // --- Sorties ----------------------------------------------------------------
  // Adresses : #sorties (liste), #sorties/nouvelle, #sorties/<id>, #sorties/<id>/modifier.
  const me = () => pb.authStore.record;
  // replace : remplace la page courante dans l'historique (le formulaire enregistré ne revient pas avec « retour »).
  const go = (path, replace) => { if (replace) location.replace("#" + path); else location.hash = path; };
  const day = (d) => (d || "").slice(0, 10);  // date PocketBase « 2026-10-20 12:00:00.000Z » -> « 2026-10-20 »
  function longDate(d) {
    const x = new Date(day(d) + "T12:00:00");
    return isNaN(x) ? "" : x.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }
  function shortDate(d) {
    const x = new Date(day(d) + "T12:00:00");
    return isNaN(x) ? "" : x.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  }
  function today() {
    const t = new Date();
    t.setMinutes(t.getMinutes() - t.getTimezoneOffset());
    return t.toISOString().slice(0, 10);
  }
  const names = (users) => (users || []).map((u) => u.username).join(", ");
  const isAuthor = (s) => s.auteur === me().id;

  function bar() {
    return h("div", { class: "sx-bar" },
      h("span", {}, "Connecté en tant que ", h("b", {}, me().username)),
      h("button", { class: "sx-btn sx-btn-2 sx-btn-sm", onclick: () => { pb.authStore.clear(); go("sorties"); viewLogin(); } }, "Se déconnecter"));
  }
  function loading() { show(bar(), h("p", { class: "note" }, "Chargement…")); }
  function failed(x) {
    show(bar(), h("p", { class: "sx-err", role: "alert" }, errorText(x)),
      h("p", {}, h("a", { href: "#sorties" }, "← Toutes les sorties")));
  }

  async function viewList() {
    loading();
    let items;
    try {
      items = await pb.collection("sorties").getFullList({ sort: "-date,-created", expand: "auteur,participants" });
    } catch (x) { failed(x); return; }
    const head = h("div", { class: "sx-head" }, h("h3", {}, "Mes sorties"),
      h("button", { class: "sx-btn", onclick: () => go("sorties/nouvelle") }, "Nouvelle sortie"));
    if (!items.length) {
      show(bar(), head, h("p", { class: "sx-empty" },
        "Aucune sortie pour l'instant. Crée la première, ou demande à un ami de t'ajouter comme participant à la sienne."));
      return;
    }
    show(bar(), head, h("ul", { class: "sx-list" }, items.map((s) => {
      const ex = s.expand || {};
      const others = [ex.auteur, ...(ex.participants || [])].filter((u) => u && u.id !== me().id);
      return h("li", {}, h("a", { href: "#sorties/" + s.id },
        h("b", {}, s.titre || "Sortie sans titre"),
        h("span", {}, shortDate(s.date) + (others.length ? " · avec " + names(others) : ""))));
    })));
  }

  async function viewSortie(id) {
    loading();
    let s;
    try {
      s = await pb.collection("sorties").getOne(id, { expand: "auteur,participants" });
    } catch (x) {
      failed(x.status === 404 ? { status: 404, response: { message: "Sortie introuvable, ou tu n'en fais pas partie." } } : x);
      return;
    }
    const ex = s.expand || {};
    const del = isAuthor(s) ? h("button", { class: "sx-btn sx-btn-danger", onclick: async () => {
      if (!confirm("Supprimer cette sortie et toutes ses observations ? C'est définitif.")) return;
      try { await pb.collection("sorties").delete(s.id); go("sorties", true); } catch (x) { alert(errorText(x)); }
    } }, "Supprimer") : null;
    show(bar(),
      h("p", {}, h("a", { href: "#sorties" }, "← Toutes les sorties")),
      h("div", { class: "sx-head" }, h("h3", {}, s.titre || "Sortie sans titre"),
        h("div", { class: "sx-actions" },
          h("button", { class: "sx-btn sx-btn-2", onclick: () => go("sorties/" + s.id + "/modifier") }, "Modifier"), del)),
      h("p", { class: "sx-meta" }, longDate(s.date)),
      h("p", { class: "sx-meta" }, "Créée par ", h("b", {}, ex.auteur ? ex.auteur.username : "?"),
        ex.participants && ex.participants.length ? " · avec " + names(ex.participants) : ""),
      s.commentaire ? h("p", { class: "sx-text" }, s.commentaire) : null,
      h("h3", {}, "Observations"),
      h("p", { class: "sx-empty" }, "L'ajout d'observations (photos, position, espèces) arrive à la prochaine étape."));
  }

  // Choix des participants parmi les comptes inscrits : recherche par nom, puis étiquettes.
  function participantsPicker(all, selected) {
    const chosen = new Map(selected.map((u) => [u.id, u]));
    const chips = h("div", { class: "sx-chips" });
    const sugg = h("ul", { class: "sx-sugg" });
    const input = h("input", { type: "search", placeholder: "Rechercher un nom…", autocomplete: "off", autocapitalize: "none" });
    function renderChips() {
      chips.replaceChildren(...[...chosen.values()].map((u) => h("span", { class: "sx-chip" }, u.username,
        h("button", { type: "button", "aria-label": "Retirer " + u.username,
          onclick: () => { chosen.delete(u.id); renderChips(); renderSugg(); } }, "×"))));
    }
    function renderSugg() {
      const q = input.value.trim().toLowerCase();
      const list = q ? all.filter((u) => !chosen.has(u.id) && u.username.toLowerCase().includes(q)).slice(0, 8) : [];
      sugg.replaceChildren(...list.map((u) => h("li", {}, h("button", { type: "button", onclick: () => {
        chosen.set(u.id, u); input.value = ""; renderChips(); renderSugg(); input.focus();
      } }, u.username))));
      if (q && !list.length) sugg.replaceChildren(h("li", {}, h("button", { type: "button", disabled: true }, "Aucun compte trouvé")));
    }
    input.addEventListener("input", renderSugg);
    input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();  // pas d'envoi du formulaire
      const b = sugg.querySelector("button:not([disabled])");
      if (b) b.click();
    });
    renderChips();
    return {
      node: h("div", { class: "sx-field" }, h("span", {}, "Participants"), chips, input, sugg,
        h("small", {}, "Ils verront la sortie et pourront y ajouter leurs observations.")),
      ids: () => [...chosen.keys()],
    };
  }

  async function viewForm(id) {
    loading();
    let s = null, users;
    try {
      [users, s] = await Promise.all([
        pb.collection("users").getFullList({ sort: "username", fields: "id,username" }),
        id ? pb.collection("sorties").getOne(id, { expand: "participants" }) : null,
      ]);
    } catch (x) { failed(x); return; }
    const others = users.filter((u) => u.id !== me().id && (!s || u.id !== s.auteur));
    const err = h("p", { class: "sx-err", role: "alert" });
    const titre = h("input", { name: "titre", maxlength: 200, placeholder: "Ex. : Aigoual, hêtraie", value: s ? s.titre : "" });
    const date = h("input", { name: "date", type: "date", required: true, value: s ? day(s.date) : today() });
    const com = h("textarea", { name: "commentaire", maxlength: 5000 });
    com.value = s ? s.commentaire : "";
    // En modification par un participant, il figure dans la liste (il peut se retirer).
    const picker = participantsPicker(others.concat(s && !isAuthor(s) ? [me()] : []),
      s ? ((s.expand && s.expand.participants) || []) : []);
    const back = id ? "sorties/" + id : "sorties";
    const form = h("form", { class: "sx-card", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = ""; busy(form, true);
      // Midi UTC : la date reste la même quel que soit le fuseau du téléphone.
      const data = { titre: titre.value.trim(), date: date.value + " 12:00:00.000Z",
        commentaire: com.value.trim(), participants: picker.ids() };
      try {
        if (s) {
          await pb.collection("sorties").update(s.id, data);
          // Un participant qui se retire perd l'accès à la sortie.
          go(isAuthor(s) || data.participants.includes(me().id) ? "sorties/" + s.id : "sorties", true);
        } else {
          const n = await pb.collection("sorties").create({ ...data, auteur: me().id });
          go("sorties/" + n.id, true);
        }
      } catch (x) { err.textContent = errorText(x); busy(form, false); }
    } },
      h("h3", {}, s ? "Modifier la sortie" : "Nouvelle sortie"),
      field("Titre", titre, "Lieu ou nom de la sortie (facultatif)."),
      field("Date", date),
      field("Commentaire", com),
      picker.node,
      err,
      h("div", { class: "sx-actions" },
        h("button", { type: "submit", class: "sx-btn" }, s ? "Enregistrer" : "Créer la sortie"),
        h("a", { href: "#" + back }, "Annuler")));
    show(bar(), form);
  }

  // Aiguillage selon l'adresse (bouton « retour » du téléphone compris).
  function route() {
    const parts = location.hash.slice(1).split("/");
    if (parts[0] !== "sorties") return;  // autre onglet
    if (!pb.authStore.isValid) { viewLogin(); return; }
    window.scrollTo(0, 0);
    if (!parts[1]) viewList();
    else if (parts[1] === "nouvelle") viewForm(null);
    else if (parts[2] === "modifier") viewForm(parts[1]);
    else viewSortie(parts[1]);
  }
  window.addEventListener("hashchange", route);
  const viewHome = route;

  // --- Démarrage : session gardée dans le navigateur, revalidée auprès du serveur ---
  async function start() {
    if (!pb.authStore.isValid) { viewLogin(); return; }
    try {
      await pb.collection("users").authRefresh();
      viewHome();
    } catch (x) {
      if (x.status === 0) { viewLogin(errorText(x)); return; }
      pb.authStore.clear();
      viewLogin("Session expirée : reconnecte-toi.");
    }
  }
  start();
})();
