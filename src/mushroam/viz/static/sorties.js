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

  function viewHome() {
    const me = pb.authStore.record;
    show(
      h("div", { class: "sx-bar" },
        h("span", {}, "Connecté en tant que ", h("b", {}, me.username)),
        h("button", { class: "sx-btn sx-btn-2", onclick: () => { pb.authStore.clear(); viewLogin(); } }, "Se déconnecter")),
      h("p", { class: "note" }, "La saisie des sorties et des observations arrive bientôt."));
  }

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
