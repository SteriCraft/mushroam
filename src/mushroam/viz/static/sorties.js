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
  // Adresses : #sorties (liste), #sorties/nouvelle, #sorties/<id>, #sorties/<id>/modifier (observations : plus bas).
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
    let obs = [];
    try {
      obs = await pb.collection("observations").getFullList({
        filter: pb.filter("sortie = {:s}", { s: s.id }), sort: "date,created", expand: "especes,auteur" });
    } catch (x) { failed(x); return; }
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
      h("div", { class: "sx-head" }, h("h3", {}, "Observations" + (obs.length ? " (" + obs.length + ")" : "")),
        h("button", { class: "sx-btn", onclick: () => go("sorties/" + s.id + "/obs/nouvelle") }, "Ajouter une observation")),
      obs.length ? obsMap(obs) : null,
      obs.length ? h("ul", { class: "sx-obs" }, obs.map((o) => obsItem(s, o))) :
        h("p", { class: "sx-empty" }, "Aucune observation. Ajoute la première : photo, position et espèce (facultative)."));
    loadThumbs(obs);
  }

  // --- Observations -------------------------------------------------------------
  // Adresses : #sorties/<id>/obs/nouvelle, #sorties/<id>/obs/<oid>.
  const pbDate = (d) => new Date((d || "").replace(" ", "T"));  // « 2026-10-20 12:34:00.000Z » -> Date
  const toPb = (d) => d.toISOString().replace("T", " ");
  function localInput(d) {  // Date -> valeur d'un champ datetime-local (heure du téléphone)
    const t = new Date(d);
    t.setMinutes(t.getMinutes() - t.getTimezoneOffset());
    return t.toISOString().slice(0, 16);
  }
  const hasPos = (p) => p && (p.lat || p.lon);  // PocketBase : position vide = 0, 0
  function speciesLabel(e) { return e.nom_fr ? e.nom_fr + " (" + e.nom + ")" : e.nom; }
  function speciesText(o) {
    const sp = (o.expand && o.expand.especes) || [];
    if (!sp.length) return h("i", {}, "À identifier");
    return sp.map((e, i) => [i ? (sp.length > 1 ? " ou " : "") : "", e.nom_fr || h("i", {}, e.nom),
      e.nom_fr ? h("i", { class: "sx-sci" }, " " + e.nom) : null]);
  }
  const canDelete = (s, o) => o.auteur === me().id || s.auteur === me().id;

  function obsItem(s, o) {
    const p = o.position;
    return h("li", { id: "obs-" + o.id },
      h("div", { class: "sx-photos", "data-obs": o.id }),
      h("div", { class: "sx-obs-body" },
        h("b", {}, speciesText(o)),
        h("span", { class: "sx-meta" }, pbDate(o.date).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
          " · ", (o.expand && o.expand.auteur ? o.expand.auteur.username : "?"),
          hasPos(p) ? [" · ", h("a", { href: "https://www.google.com/maps/search/?api=1&query=" + p.lat + "," + p.lon,
            target: "_blank", rel: "noopener" }, "position" + (o.precision_m ? " (± " + Math.round(o.precision_m) + " m)" : ""))]
            : " · sans position"),
        o.commentaire ? h("p", { class: "sx-text" }, o.commentaire) : null,
        h("div", { class: "sx-actions" },
          h("button", { class: "sx-btn sx-btn-2 sx-btn-sm", onclick: () => go("sorties/" + s.id + "/obs/" + o.id) }, "Modifier"),
          canDelete(s, o) ? h("button", { class: "sx-btn sx-btn-danger sx-btn-sm", onclick: async () => {
            if (!confirm("Supprimer cette observation et ses photos ?")) return;
            try { await pb.collection("observations").delete(o.id); route(); } catch (x) { alert(errorText(x)); }
          } }, "Supprimer") : null)));
  }

  // Photos protégées : adresse valable avec un jeton de fichier (quelques minutes).
  async function loadThumbs(obs) {
    if (!obs.some((o) => o.photos && o.photos.length)) return;
    let token;
    try { token = await pb.files.getToken(); } catch (x) { return; }
    for (const o of obs) {
      const box = root.querySelector('.sx-photos[data-obs="' + o.id + '"]');
      if (!box) continue;
      box.replaceChildren(...(o.photos || []).map((f) => h("button", { type: "button", class: "sx-thumb",
        "aria-label": "Agrandir la photo", onclick: () => openPhoto(o, f) },
        h("img", { src: pb.files.getURL(o, f, { thumb: "300x300", token }), alt: "", loading: "lazy" }))));
    }
  }
  async function openPhoto(o, f) {
    let token;
    try { token = await pb.files.getToken(); } catch (x) { alert(errorText(x)); return; }
    const full = pb.files.getURL(o, f, { token });
    const dlg = h("dialog", { class: "sx-lightbox", onclick: () => dlg.close(), onclose: () => dlg.remove() },
      h("img", { src: pb.files.getURL(o, f, { thumb: "1200x0", token }), alt: "" }),
      h("a", { href: full, target: "_blank", rel: "noopener", onclick: (e) => e.stopPropagation() }, "Taille réelle"));
    document.body.append(dlg);
    dlg.showModal();
  }

  // Petite carte Leaflet (chargée par la page) : fond Esri, sans les tuiles OSM.
  function baseMap(el) {
    const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    const plan = L.tileLayer(ESRI + "World_Topo_Map/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "© Esri" });
    const sat = L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "© Esri, Maxar" });
    const map = L.map(el, { layers: [plan] }).setView([43.61, 3.88], 9);
    L.control.layers({ "Plan": plan, "Satellite": sat }, null, { position: "topright" }).addTo(map);
    setTimeout(() => map.invalidateSize(), 0);
    return map;
  }
  function obsMap(obs) {
    const pts = obs.filter((o) => hasPos(o.position));
    if (!pts.length || typeof L === "undefined") return null;
    const el = h("div", { class: "sx-map" });
    setTimeout(() => {
      const map = baseMap(el);
      const latlngs = pts.map((o) => {
        const ll = [o.position.lat, o.position.lon];
        const sp = (o.expand && o.expand.especes) || [];
        L.circleMarker(ll, { radius: 7, color: "#fff", weight: 2, fillColor: "#d9822b", fillOpacity: 1 }).addTo(map)
          .bindTooltip(sp.length ? sp.map((e) => e.nom_fr || e.nom).join(" ou ") : "À identifier")
          .on("click", () => { const li = document.getElementById("obs-" + o.id); if (li) li.scrollIntoView({ behavior: "smooth" }); });
        return ll;
      });
      map.fitBounds(latlngs, { maxZoom: 15, padding: [24, 24] });
    }, 0);
    return el;
  }

  // Choix des espèces : liste commune (PocketBase) + recherche iNaturalist (champignons, noms français).
  function speciesPicker(known, selected) {
    const chosen = selected.map((e) => ({ ...e }));
    const chips = h("div", { class: "sx-chips" });
    const sugg = h("ul", { class: "sx-sugg" });
    const input = h("input", { type: "search", placeholder: "Nom français ou scientifique…", autocomplete: "off", autocapitalize: "none" });
    const norm = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    const isChosen = (nom) => chosen.some((e) => norm(e.nom) === norm(nom));
    let inat = [], timer = null, seq = 0;
    function renderChips() {
      chips.replaceChildren(...chosen.map((e, i) => h("span", { class: "sx-chip" }, speciesLabel(e),
        h("button", { type: "button", "aria-label": "Retirer " + e.nom,
          onclick: () => { chosen.splice(i, 1); renderChips(); renderSugg(); } }, "×"))));
      if (!chosen.length) chips.append(h("span", { class: "sx-chip sx-chip-none" }, "À identifier"));
    }
    function pick(e) { chosen.push(e); input.value = ""; inat = []; renderChips(); renderSugg(); input.focus(); }
    function renderSugg() {
      const q = norm(input.value.trim());
      if (!q) { sugg.replaceChildren(); return; }
      const local = known.filter((e) => !isChosen(e.nom) && (norm(e.nom).includes(q) || norm(e.nom_fr).includes(q))).slice(0, 6);
      const remote = inat.filter((e) => !isChosen(e.nom) && !local.some((k) => norm(k.nom) === norm(e.nom))).slice(0, 8 - local.length);
      const items = [...local, ...remote].map((e) => h("li", {}, h("button", { type: "button", onclick: () => pick(e) },
        e.nom_fr || h("i", {}, e.nom), e.nom_fr ? h("i", { class: "sx-sci" }, " " + e.nom) : null,
        e.id ? null : h("small", { class: "sx-src" }, " iNat"))));
      const raw = input.value.trim();
      if (raw.length >= 3 && !isChosen(raw) && ![...local, ...remote].some((e) => norm(e.nom) === norm(raw)))
        items.push(h("li", {}, h("button", { type: "button", onclick: () => pick({ nom: raw, nom_fr: "" }) },
          "Ajouter « " + raw + " » tel quel")));
      sugg.replaceChildren(...items);
    }
    async function searchInat(q, n) {
      try {
        const r = await fetch("https://api.inaturalist.org/v1/taxa/autocomplete?per_page=8&locale=fr&taxon_id=47170&q="
          + encodeURIComponent(q));
        const js = await r.json();
        if (n !== seq) return;  // réponse dépassée par une frappe plus récente
        inat = (js.results || []).filter((t) => t.name).map((t) => ({
          nom: t.name, nom_fr: t.preferred_common_name ? t.preferred_common_name.charAt(0).toUpperCase() + t.preferred_common_name.slice(1) : "",
          inat_id: t.id }));
        renderSugg();
      } catch (x) { /* hors ligne : liste commune seulement */ }
    }
    input.addEventListener("input", () => {
      inat = []; renderSugg();
      clearTimeout(timer);
      const q = input.value.trim(), n = ++seq;
      if (q.length >= 3) timer = setTimeout(() => searchInat(q, n), 350);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const b = sugg.querySelector("button");
      if (b) b.click();
    });
    renderChips();
    return {
      node: h("div", { class: "sx-field" }, h("span", {}, "Espèce"), chips, input, sugg,
        h("small", {}, "Aucune = « À identifier ». Plusieurs = hésitation entre elles.")),
      // Identifiants PocketBase ; les espèces nouvelles sont ajoutées à la liste commune.
      async ids() {
        const out = [];
        for (const e of chosen) {
          if (e.id) { out.push(e.id); continue; }
          try {
            const n = await pb.collection("especes").create({ nom: e.nom, nom_fr: e.nom_fr || "", inat_id: e.inat_id || null, cree_par: me().id });
            e.id = n.id;
          } catch (x) {  // déjà ajoutée entre-temps (nom unique)
            const found = await pb.collection("especes").getFirstListItem(pb.filter("nom = {:n}", { n: e.nom }));
            e.id = found.id;
          }
          out.push(e.id);
        }
        return out;
      },
    };
  }

  // Position : GPS du téléphone, ou toucher la carte.
  function positionPicker(initial, initialAcc, auto) {
    let pos = hasPos(initial) ? { lat: initial.lat, lon: initial.lon } : null;
    let acc = pos ? initialAcc || null : null;
    const status = h("small", {});
    const el = h("div", { class: "sx-map sx-map-pick" });
    let map = null, marker = null;
    function render() {
      status.textContent = pos ? pos.lat.toFixed(5) + ", " + pos.lon.toFixed(5) + (acc ? " · précision ± " + Math.round(acc) + " m" : " · placée à la main")
        : "Aucune position. Utilise le GPS ou touche la carte.";
      if (!map) return;
      if (pos) {
        if (!marker) marker = L.marker([pos.lat, pos.lon], { draggable: true }).addTo(map)
          .on("dragend", () => { const ll = marker.getLatLng(); pos = { lat: ll.lat, lon: ll.lng }; acc = null; render(); });
        marker.setLatLng([pos.lat, pos.lon]);
      } else if (marker) { marker.remove(); marker = null; }
    }
    const gpsBtn = h("button", { type: "button", class: "sx-btn sx-btn-2 sx-btn-sm", onclick: () => locate() }, "Ma position (GPS)");
    function locate() {
      if (!navigator.geolocation) { status.textContent = "GPS indisponible sur cet appareil."; return; }
      status.textContent = "Recherche de la position…"; gpsBtn.disabled = true;
      navigator.geolocation.getCurrentPosition((p) => {
        gpsBtn.disabled = false;
        pos = { lat: p.coords.latitude, lon: p.coords.longitude }; acc = p.coords.accuracy;
        render();
        if (map) map.setView([pos.lat, pos.lon], Math.max(map.getZoom(), 15));
      }, (e) => {
        gpsBtn.disabled = false;
        status.textContent = e.code === 1 ? "Accès à la position refusé (réglages du navigateur)." : "Position introuvable. Réessaie, ou touche la carte.";
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    }
    setTimeout(() => {
      if (typeof L === "undefined") { el.remove(); return; }
      map = baseMap(el);
      if (pos) map.setView([pos.lat, pos.lon], 15);
      map.on("click", (e) => { pos = { lat: e.latlng.lat, lon: e.latlng.lng }; acc = null; render(); });
      render();
    }, 0);
    render();
    if (auto) locate();
    return {
      node: h("div", { class: "sx-field" }, h("span", {}, "Position"),
        h("div", { class: "sx-actions" }, gpsBtn,
          h("button", { type: "button", class: "sx-btn sx-btn-2 sx-btn-sm", onclick: () => { pos = null; acc = null; render(); } }, "Effacer")),
        el, status),
      value: () => pos ? { position: pos, precision_m: acc ? Math.round(acc) : null } : { position: { lat: 0, lon: 0 }, precision_m: null },
    };
  }

  // Photos réduites avant l'envoi (2 048 px, JPEG) : envoi rapide depuis le terrain, moins de place sur le Raspberry.
  async function shrink(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 600000) return file;
    try {
      const url = URL.createObjectURL(file);
      const img = await new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = url; });
      URL.revokeObjectURL(url);
      const k = Math.min(1, 2048 / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.85));
      if (!blob || blob.size >= file.size) return file;
      return new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" });
    } catch (x) { return file; }
  }

  function photosPicker(o) {
    const removed = new Set();
    let added = [];
    const existing = h("div", { class: "sx-photos" });
    const fresh = h("div", { class: "sx-photos" });
    const input = h("input", { type: "file", accept: "image/*", multiple: true, class: "sx-file" });
    input.addEventListener("change", () => { added = added.concat([...input.files]); input.value = ""; render(); });
    async function render() {
      const keep = (o ? o.photos || [] : []).filter((f) => !removed.has(f));
      if (o && keep.length) {
        let token = "";
        try { token = await pb.files.getToken(); } catch (x) { /* vignettes sans image */ }
        existing.replaceChildren(...keep.map((f) => h("span", { class: "sx-thumb" },
          h("img", { src: pb.files.getURL(o, f, { thumb: "300x300", token }), alt: "" }),
          h("button", { type: "button", class: "sx-thumb-x", "aria-label": "Retirer la photo", onclick: () => { removed.add(f); render(); } }, "×"))));
      } else existing.replaceChildren();
      fresh.replaceChildren(...added.map((f, i) => h("span", { class: "sx-thumb" },
        h("img", { src: URL.createObjectURL(f), alt: "" }),
        h("button", { type: "button", class: "sx-thumb-x", "aria-label": "Retirer la photo", onclick: () => { added.splice(i, 1); render(); } }, "×"))));
    }
    render();
    return {
      node: h("div", { class: "sx-field" }, h("span", {}, "Photos"), existing, fresh,
        h("label", { class: "sx-btn sx-btn-2 sx-btn-sm sx-file-btn" }, "Prendre ou choisir des photos", input),
        h("small", {}, "10 photos au plus. Elles ne sont visibles que des membres de la sortie.")),
      async value() {
        const out = {};
        if (removed.size) out["photos-"] = [...removed];
        if (added.length) out["photos+"] = await Promise.all(added.map(shrink));
        return out;
      },
    };
  }

  async function viewObsForm(sid, oid) {
    loading();
    let s, o = null, known;
    try {
      [s, o, known] = await Promise.all([
        pb.collection("sorties").getOne(sid),
        oid ? pb.collection("observations").getOne(oid, { expand: "especes" }) : null,
        pb.collection("especes").getFullList({ sort: "nom", fields: "id,nom,nom_fr,inat_id" }),
      ]);
    } catch (x) { failed(x); return; }
    const sameDay = day(s.date) === today();
    // Nouvelle observation : maintenant si la sortie est aujourd'hui, sinon midi le jour de la sortie.
    const when = o ? pbDate(o.date) : sameDay ? new Date() : new Date(day(s.date) + "T12:00:00");
    const err = h("p", { class: "sx-err", role: "alert" });
    const species = speciesPicker(known, o ? ((o.expand && o.expand.especes) || []) : []);
    const date = h("input", { type: "datetime-local", required: true, value: localInput(when) });
    const position = positionPicker(o && o.position, o && o.precision_m, !o && sameDay);
    const photos = photosPicker(o);
    const com = h("textarea", { maxlength: 5000, placeholder: "Milieu, arbres proches, nombre d'exemplaires…" });
    com.value = o ? o.commentaire : "";
    const back = "sorties/" + sid;
    const save = h("button", { type: "submit", class: "sx-btn" }, o ? "Enregistrer" : "Ajouter l'observation");
    const form = h("form", { class: "sx-card", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = ""; busy(form, true);
      save.textContent = "Envoi en cours…";
      try {
        const data = { date: toPb(new Date(date.value)), commentaire: com.value.trim(),
          especes: await species.ids(), ...position.value(), ...(await photos.value()) };
        if (o) await pb.collection("observations").update(o.id, data);
        else await pb.collection("observations").create({ ...data, sortie: sid, auteur: me().id });
        go(back, true);
      } catch (x) {
        err.textContent = errorText(x); busy(form, false);
        save.textContent = o ? "Enregistrer" : "Ajouter l'observation";
      }
    } },
      h("h3", {}, (o ? "Modifier l'observation" : "Nouvelle observation") + " · " + (s.titre || shortDate(s.date))),
      photos.node,
      species.node,
      position.node,
      field("Date et heure", date),
      field("Commentaire", com),
      err,
      h("div", { class: "sx-actions" }, save, h("a", { href: "#" + back }, "Annuler")));
    show(bar(), form);
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
    else if (parts[2] === "obs" && parts[3]) viewObsForm(parts[1], parts[3] === "nouvelle" ? null : parts[3]);
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
