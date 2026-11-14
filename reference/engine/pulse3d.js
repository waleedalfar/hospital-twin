/* Pulse3D: multi-level pixel-art hospital engine (three.js r149, classic script). */
(function () {
  var T = window.THREE;
  if (!T) return;

  var FH = 3.4, SL = 0.3, WH = 3.0, LEVELS = 3;

  // ---------- Simulated patient data ----------
  var SPECIAL = {
    'ICU-3': { id: 'P-0412', score: 0.81, age: 67, note: 'pneumonia, day 2', vitals: [['HR', '118', 1], ['SpO2', '88%', 1], ['BP', '104/66', 0], ['Temp', '38.4', 1], ['RR', '24', 1], ['Lactate', '2.6', 1]], why: [['SpO2 drop, 2h', 0.21], ['HR trend', 0.14], ['Resp. rate', 0.09]] },
    'ICU-4': { id: 'P-0288', score: 0.52, age: 54, note: 'post-op', vitals: [['HR', '98', 0], ['SpO2', '94%', 0], ['BP', '96/60', 1], ['Temp', '37.6', 0], ['RR', '19', 0], ['Lactate', '1.8', 0]], why: [['Low BP', 0.16], ['Post-op day', 0.08], ['HR trend', 0.05]] },
    'WARD-5': { id: 'P-1187', score: 0.64, age: 72, note: 'heart failure', vitals: [['HR', '112', 1], ['SpO2', '92%', 0], ['BP', '142/90', 1], ['Temp', '37.1', 0], ['RR', '21', 0], ['Weight', '+1.8kg', 1]], why: [['HR rising', 0.18], ['Weight gain', 0.12], ['Age', 0.07]] },
    'ER-2': { id: 'P-0930', score: 0.58, age: 41, note: 'fever, triage', vitals: [['HR', '108', 1], ['SpO2', '95%', 0], ['BP', '88/54', 1], ['Temp', '38.9', 1], ['RR', '22', 1], ['Lactate', '-', 0]], why: [['Low BP', 0.19], ['Fever', 0.11], ['HR', 0.08]] },
    'REC-2': { id: 'P-0777', score: 0.47, age: 59, note: 'post-op, hour 3', vitals: [['HR', '94', 0], ['SpO2', '93%', 1], ['BP', '110/70', 0], ['Temp', '37.9', 1], ['RR', '18', 0], ['Pain', '6/10', 1]], why: [['SpO2 dip', 0.13], ['Temp', 0.07], ['Pain', 0.05]] }
  };
  var EMPTY = { 'ICU-6': 1, 'WARD-3': 1, 'WARD-7': 1, 'WARD-12': 1, 'ER-3': 1, 'ER-6': 1, 'REC-3': 1 };
  var CODES = [];
  var i;
  for (i = 1; i <= 6; i++) CODES.push('ER-' + i);
  for (i = 1; i <= 14; i++) CODES.push('WARD-' + i);
  for (i = 1; i <= 3; i++) CODES.push('REC-' + i);
  for (i = 1; i <= 6; i++) CODES.push('ICU-' + i);
  var PATIENTS = {};
  CODES.forEach(function (code, k) {
    if (EMPTY[code]) return;
    var s = SPECIAL[code];
    if (s) { PATIENTS[code] = Object.assign({}, s, { bed: code, i: k }); return; }
    PATIENTS[code] = { id: 'P-' + String(1000 + k * 37).slice(-4), bed: code, i: k, score: 0.1 + (k % 4) * 0.05, age: 30 + (k * 7) % 50, note: 'stable',
      vitals: [['HR', String(72 + k % 9), 0], ['SpO2', '98%', 0], ['BP', '122/78', 0], ['Temp', '36.9', 0], ['RR', '15', 0], ['Pain', '2/10', 0]],
      why: [['Stable vitals', 0.06], ['Age', 0.03], ['Labs normal', 0.02]] };
  });

  // ---------- Color helpers ----------
  function hex2rgb(h) { h = h.replace('#', ''); return [parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)]; }
  function rgb2hex(r) { return '#' + r.map(function (v) { v = Math.max(0, Math.min(255, Math.round(v))); return (v < 16 ? '0' : '') + v.toString(16); }).join(''); }
  function mix(a, b, t) { var x = hex2rgb(a), y = hex2rgb(b); return rgb2hex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t]); }
  function shade(a, t) { return t < 0 ? mix(a, '#000000', -t) : mix(a, '#ffffff', t); }
  function lum(a) { var x = hex2rgb(a); return (0.299 * x[0] + 0.587 * x[1] + 0.114 * x[2]) / 255; }

  var BASE = {
    sky: '#8fd3ff', grass: '#6fbf5a', grass2: '#5ea84c', road: '#4a4e5c', dash: '#f6e7a1', sidewalk: '#d8cfb6', asphalt: '#5a5f6e',
    slab: '#b9bfcc', wallInt: '#f6f2e8', wallExt: '#e9dcc6', wallExt2: '#cdb592', cap: '#3b4560', glass: '#8fd0f0', glassLit: '#ffe28a',
    roof: '#9aa3b8', helipad: '#4a4e5c', helipadMark: '#f6e7a1',
    ER: '#f3e3c3', IMG: '#dfe6f2', PHARM: '#e8f0dc', TRIAGE: '#f6dede', WAIT: '#d9e2ef', RECEP: '#e8e2f4', CORR: '#eceff3',
    WARD: '#d6efe2', OR: '#d4ecf0', RECOV: '#efe4f6', ICU: '#f4dadd', LAB: '#e2ecf6', STAFF: '#f1e6d4', PRAY: '#e6efe0', ADMIN: '#ece7dc',
    wood: '#c99a63', woodDark: '#7a5a36', bedFrame: '#8a93aa', sheet: '#ffffff', pillow: '#eef2f8', blanket: '#8ec0ea', shoulder: '#c9dcef',
    monitor: '#1b2140', pole: '#6b7390', chair: '#6b7890', chairBase: '#4b5266', curtain: '#76c7b9', machine: '#e6e9ef', machineDark: '#9aa3b8',
    trunk: '#7a5a36', tree: '#3f8a3a', tree2: '#56a64b', ambBody: '#f6f7fa', ambStripe: '#e5484d',
    nurse: '#2fa39a', nurse2: '#1f7a73', doc: '#f6f7fa', docPants: '#3b4560', surg: '#4f9c7a', gown: '#8ec0ea', emt: '#e58a2e', emtPants: '#2d3446',
    rug1: '#2f7a55', rug2: '#a8423c', rug3: '#c9a24a', couch: '#c25c5c', plant: '#3f8a3a', pot: '#b56b45', heli: '#e5484d', heliDark: '#2d3446',
    labelBg: '#20324a', labelInk: '#ffffff', low: '#3fb68b', med: '#f0a830', high: '#e5484d', screenOff: '#2c3563', ring: '#2453b0',
    lamp: '#fff6c9', vend: '#7fd0ff', meds: ['#e5484d', '#3d6fd6', '#f0b030', '#3fb68b']
  };
  var SKINS = ['#e8b98f', '#c68a5e', '#8d5a3b', '#f1cfae', '#a86b45'];
  var HAIRS = ['#2b1d14', '#5a3a22', '#111111', '#8c6a3f', '#3b2b4a'];
  var SCARVES = ['#5c4a8a', '#2d6a5a', '#7a3a5c', '#3b5a8a'];
  var TOPS = ['#7a5cc2', '#c25c8a', '#5c8ac2', '#8ac25c', '#c29a5c', '#5cc2b4', '#c25c5c'];

  var GB = ['#0f380f', '#306230', '#8bac0f', '#9bbc0f'];
  var STYLES = {
    classic: { pix: 2, toon: 3, outline: true, outlineColor: '#1d1a2c', texture: true, ortho: false, night: false, fog: [80, 170],
      hemi: ['#ffffff', '#7a9a6a', 0.65], sun: ['#fff1d6', 0.85], map: null, pal: {} },
    neon: { pix: 2, toon: 3, outline: true, outlineColor: '#05060f', texture: true, ortho: false, night: true, fog: [40, 120],
      hemi: ['#8a9cff', '#202a50', 0.8], sun: ['#b4c4ff', 0.45],
      map: function (c) { return mix(mix(c, '#141a3a', 0.32), '#2a1a5a', 0.08); },
      pal: { sky: '#0b1026', glassLit: '#ffd56b', labelBg: '#120a2a', labelInk: '#5ef2ff', dash: '#5ef2ff', lamp: '#ffffff', vend: '#ff5ec4', ring: '#5ef2ff' } },
    iso: { pix: 2, toon: 4, outline: true, outlineColor: '#3b3350', texture: true, ortho: true, night: false, fog: null,
      hemi: ['#ffffff', '#b8a99a', 0.75], sun: ['#fff6e8', 0.7],
      map: function (c) { return mix(c, '#fff4ea', 0.12); },
      pal: { sky: '#f4efe4', labelBg: '#3b3350' } },
    gameboy: { pix: 3, toon: 3, outline: true, outlineColor: GB[0], texture: true, ortho: false, night: false, fog: [70, 150],
      hemi: ['#ffffff', '#888888', 0.7], sun: ['#ffffff', 0.8],
      map: function (c) { var l = lum(c); return l < 0.28 ? GB[0] : l < 0.5 ? GB[1] : l < 0.75 ? GB[2] : GB[3]; },
      pal: { sky: '#9bbc0f', labelBg: '#0f380f', labelInk: '#9bbc0f', low: '#8bac0f', med: '#306230', high: '#0f380f', ring: '#0f380f', glassLit: '#9bbc0f' } }
  };

  function mount(canvas, opts) {
    var st = STYLES[opts.style] || STYLES.classic;
    var P = Object.assign({}, BASE, st.pal);
    var mapC = function (c) { return st.map ? st.map(c) : c; };
    var W = opts.width || 1280, H = opts.height || 744;
    var r = new T.WebGLRenderer({ canvas: canvas, antialias: false });
    r.setPixelRatio(1);
    r.shadowMap.enabled = true;
    var pix = 0;
    function setPixel(n) { n = Number(n) || st.pix; if (n === pix) return; pix = n; r.setSize(Math.max(64, Math.round(W / n)), Math.max(40, Math.round(H / n)), false); }
    setPixel(opts.pixel || st.pix);

    var scene = new T.Scene();
    scene.background = new T.Color(mapC(P.sky));
    if (st.fog) scene.fog = new T.Fog(mapC(P.sky), st.fog[0], st.fog[1]);
    scene.add(new T.HemisphereLight(st.hemi[0], st.hemi[1], st.hemi[2]));
    var sun = new T.DirectionalLight(st.sun[0], st.sun[1]);
    sun.position.set(30, 60, 25);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, { left: -50, right: 50, top: 50, bottom: -50, near: 1, far: 200 });
    sun.shadow.camera.updateProjectionMatrix();
    scene.add(sun);

    // gradient map for banded pixel shading
    var grad = null;
    if (st.toon) {
      var n = st.toon, d = new Uint8Array(n * 4);
      for (var g = 0; g < n; g++) { var v = Math.round(255 * (0.35 + 0.65 * g / (n - 1))); d[g * 4] = v; d[g * 4 + 1] = v; d[g * 4 + 2] = v; d[g * 4 + 3] = 255; }
      grad = new T.DataTexture(d, n, 1, T.RGBAFormat);
      grad.minFilter = T.NearestFilter; grad.magFilter = T.NearestFilter; grad.needsUpdate = true;
    }
    var mats = {}, geos = {}, edges = {};
    var shellMeshes = [], markers = [], xray = false;
    var lineMat = new T.LineBasicMaterial({ color: st.outlineColor });
    function M(c) { var k = 'm' + c; if (!mats[k]) { var col = mapC(c); mats[k] = grad ? new T.MeshToonMaterial({ color: col, gradientMap: grad }) : new T.MeshLambertMaterial({ color: col }); } return mats[k]; }
    function B(c) { return new T.MeshBasicMaterial({ color: st.map && opts.style === 'gameboy' ? mapC(c) : c }); }
    function G(w, h, dd) { var k = w + '_' + h + '_' + dd; if (!geos[k]) { geos[k] = new T.BoxGeometry(w, h, dd); edges[k] = new T.EdgesGeometry(geos[k]); } return k; }
    function box(w, h, dd, c, x, y, z, parent, o) {
      o = o || {};
      var k = G(w, h, dd);
      var m = new T.Mesh(geos[k], typeof c === 'string' ? M(c) : c);
      m.position.set(x, y, z);
      m.castShadow = o.cast !== false;
      m.receiveShadow = true;
      if (st.outline && o.outline !== false) m.add(new T.LineSegments(edges[k], lineMat));
      if (o.shell) { m.userData.shell = o.shell; shellMeshes.push(m); }
      (parent || scene).add(m);
      return m;
    }
    function tileMat(c, w, dd, size) {
      if (!st.texture) return M(c);
      var cv = document.createElement('canvas'); cv.width = 16; cv.height = 16;
      var x = cv.getContext('2d');
      x.fillStyle = mapC(c); x.fillRect(0, 0, 16, 16);
      x.fillStyle = mapC(shade(c, -0.07)); x.fillRect(0, 0, 8, 8); x.fillRect(8, 8, 8, 8);
      x.fillStyle = mapC(shade(c, -0.14)); x.fillRect(0, 0, 16, 1); x.fillRect(0, 0, 1, 16);
      var t = new T.CanvasTexture(cv);
      t.magFilter = T.NearestFilter; t.minFilter = T.NearestFilter;
      t.wrapS = t.wrapT = T.RepeatWrapping;
      t.repeat.set(w / (size || 2), dd / (size || 2));
      return grad ? new T.MeshToonMaterial({ map: t, gradientMap: grad }) : new T.MeshLambertMaterial({ map: t });
    }

    // ---------- Labels ----------
    var labelDraws = [];
    function label(text, sub, subColor, x, y, z, w, parent) {
      var cv = document.createElement('canvas'); cv.width = 512; cv.height = 128;
      var tex = new T.CanvasTexture(cv);
      tex.magFilter = T.NearestFilter; tex.minFilter = T.NearestFilter;
      var draw = function () {
        var g2 = cv.getContext('2d');
        g2.imageSmoothingEnabled = false;
        g2.setTransform(2, 0, 0, 2, 0, 0);
        g2.clearRect(0, 0, 256, 64);
        g2.fillStyle = mapC(P.labelBg); g2.fillRect(0, 4, 256, 54);
        g2.fillStyle = st.outlineColor; g2.fillRect(0, 56, 256, 6);
        g2.textBaseline = 'middle';
        g2.font = '700 26px ' + (opts.font || '"Pixelify Sans", monospace');
        var tw = g2.measureText(text).width;
        g2.font = '400 30px "VT323", monospace';
        var sw = sub ? g2.measureText(sub).width + 12 : 0;
        var x0 = Math.max(6, (256 - tw - sw) / 2);
        g2.font = '700 26px ' + (opts.font || '"Pixelify Sans", monospace');
        g2.fillStyle = P.labelInk; g2.fillText(text, x0, 31);
        if (sub) { g2.font = '400 30px "VT323", monospace'; g2.fillStyle = subColor || P.labelInk; g2.fillText(sub, x0 + tw + 12, 32); }
        tex.needsUpdate = true;
      };
      draw(); labelDraws.push(draw);
      var s = new T.Sprite(new T.SpriteMaterial({ map: tex, depthTest: false }));
      s.renderOrder = 10;
      s.position.set(x, y, z);
      var ww = (w || 5.5) * 1.25;
      s.scale.set(ww, ww / 4, 1);
      (parent || scene).add(s);
      return s;
    }
    if (document.fonts && document.fonts.load) {
      Promise.all([document.fonts.load('700 26px "Pixelify Sans"'), document.fonts.load('30px "VT323"'), document.fonts.load('16px "Press Start 2P"'), document.fonts.load('700 26px "Silkscreen"')])
        .then(function () { labelDraws.forEach(function (f) { f(); }); }).catch(function () {});
    }
    function bangTexture() {
      var cv = document.createElement('canvas'); cv.width = 16; cv.height = 16;
      var g2 = cv.getContext('2d');
      g2.fillStyle = '#ffffff'; g2.fillRect(0, 0, 16, 16);
      g2.fillStyle = P.high; g2.fillRect(1, 1, 14, 14);
      g2.fillStyle = '#ffffff'; g2.fillRect(7, 3, 2, 7); g2.fillRect(7, 11, 2, 2);
      var t = new T.CanvasTexture(cv); t.magFilter = T.NearestFilter; t.minFilter = T.NearestFilter; return t;
    }
    var bangTex = bangTexture();
    var markTex = {};
    function marker(color, parent, x, y, z, size) {
      if (!markTex[color]) {
        var cv = document.createElement('canvas'); cv.width = 12; cv.height = 12;
        var g2 = cv.getContext('2d');
        g2.fillStyle = st.outlineColor; g2.fillRect(2, 0, 8, 12); g2.fillRect(0, 2, 12, 8);
        g2.fillStyle = color; g2.fillRect(3, 1, 6, 10); g2.fillRect(1, 3, 10, 6);
        g2.fillStyle = '#ffffff'; g2.fillRect(3, 3, 2, 2);
        var t = new T.CanvasTexture(cv); t.magFilter = T.NearestFilter; t.minFilter = T.NearestFilter; markTex[color] = t;
      }
      var s = new T.Sprite(new T.SpriteMaterial({ map: markTex[color], depthTest: false }));
      s.renderOrder = 12; s.scale.set(size || 0.5, size || 0.5, 1); s.position.set(x, y, z); s.visible = xray;
      parent.add(s); markers.push(s); return s;
    }

    // ---------- Exterior ----------
    box(220, 0.2, 220, st.texture ? tileMat(P.grass, 220, 220, 4) : P.grass, 0, -0.1, 0, scene, { cast: false, outline: false });
    box(220, 0.06, 8, P.road, 0, 0.03, 28, scene, { cast: false, outline: false });
    for (var dx = -108; dx < 110; dx += 6) box(3, 0.08, 0.3, P.dash, dx, 0.05, 28, scene, { cast: false, outline: false });
    box(44, 0.08, 2, P.sidewalk, 0, 0.04, 15.4, scene, { cast: false });
    box(14, 0.06, 9, P.asphalt, 14, 0.03, 20, scene, { cast: false, outline: false });
    box(14, 0.06, 12, P.asphalt, 33, 0.03, 6, scene, { cast: false, outline: false });
    [['#d64545', 29, 3], ['#3d6fd6', 33, 3], ['#f0b030', 37, 9], ['#7a5cc2', 29, 9]].forEach(function (c) {
      box(1.8, 0.9, 3.6, c[0], c[1], 0.55, c[2]); box(1.6, 0.6, 2, c[0], c[1], 1.3, c[2] - 0.2); box(1.62, 0.45, 0.05, P.glass, c[1], 1.3, c[2] + 0.82, scene, { outline: false });
    });
    [[-30, -22], [-34, 4], [-28, 20], [-42, -8], [30, -22], [36, -8], [46, 14], [-12, -26], [4, -28], [18, -25], [-24, 40], [0, 42], [26, 40], [-48, 32], [48, 34], [-54, -30], [54, -28], [-60, 6], [60, 0]].forEach(function (p) {
      box(0.6, 1.4, 0.6, P.trunk, p[0], 0.7, p[1]);
      box(2.6, 2.2, 2.6, P.tree, p[0], 2.4, p[1]);
      box(1.6, 1.0, 1.6, P.tree2, p[0], 4.0, p[1]);
    });

    // ---------- Building ----------
    var floors = [];
    var pickables = [];
    var blinkers = [];
    var bangs = [];
    var walkers = [];
    var idlers = [];
    var bedPos = {};
    var litWindows = [];

    function person(o, parent) {
      var g2 = new T.Group();
      var legs = [], arms = [];
      [-0.13, 0.13].forEach(function (x) { var p = new T.Group(); p.position.set(x, 0.85, 0); box(0.22, 0.8, 0.26, o.bottom, 0, -0.4, 0, p); g2.add(p); legs.push(p); });
      box(0.6, 0.7, 0.34, o.top, 0, 1.2, 0, g2);
      if (o.detail) box(0.12, 0.12, 0.02, o.detail, 0.15, 1.38, 0.18, g2, { outline: false });
      [-0.4, 0.4].forEach(function (x) { var p = new T.Group(); p.position.set(x, 1.5, 0); box(0.18, 0.62, 0.2, o.top, 0, -0.31, 0, p); box(0.18, 0.12, 0.2, o.skin, 0, -0.68, 0, p, { outline: false }); g2.add(p); arms.push(p); });
      if (o.scarf) {
        box(0.48, 0.52, 0.46, o.scarf, 0, 1.82, -0.02, g2);
        box(0.3, 0.3, 0.03, o.skin, 0, 1.8, 0.22, g2, { outline: false });
        box(0.54, 0.18, 0.42, o.scarf, 0, 1.52, -0.02, g2);
      } else {
        box(0.42, 0.42, 0.42, o.skin, 0, 1.8, 0, g2);
        box(0.44, 0.14, 0.44, o.hair, 0, 2.04, 0, g2);
        box(0.44, 0.34, 0.1, o.hair, 0, 1.86, -0.2, g2);
      }
      g2.position.y = SL;
      parent.add(g2);
      marker(mapC(o.mark || '#b48ead'), g2, 0, 2.75, 0, 0.5);
      return { g: g2, legs: legs, arms: arms };
    }
    var ROLE = {
      nurse: { top: P.nurse, bottom: P.nurse2, detail: '#ffffff', mark: P.nurse },
      doc: { top: P.doc, bottom: P.docPants, detail: P.nurse, mark: '#ffffff' },
      surg: { top: P.surg, bottom: P.surg, detail: '#ffffff', mark: P.surg },
      gown: { top: P.gown, bottom: P.gown, mark: P.gown },
      emt: { top: P.emt, bottom: P.emtPants, detail: '#f3e7b4', mark: P.emt }
    };
    function walker(fl, role, pts, speed, off, idx, scarf) {
      var p = person(Object.assign({}, role, { skin: SKINS[idx % 5], hair: HAIRS[(idx + 1) % 5], scarf: scarf }), fl.g);
      var all = pts.concat(pts.slice(0, -1).reverse());
      var seg = [], L = 0;
      for (var k = 0; k < all.length - 1; k++) { var a = all[k], b = all[k + 1]; var dd = Math.hypot(b[0] - a[0], b[1] - a[1]); seg.push({ ax: a[0], az: a[1], bx: b[0], bz: b[1], d: dd, s0: L }); L += dd; }
      walkers.push(Object.assign(p, { seg: seg, L: L, speed: speed, off: off }));
    }
    function stand(fl, role, x, z, rot, idx, scarf, seated) {
      var p = person(Object.assign({}, role, { skin: SKINS[idx % 5], hair: HAIRS[idx % 5], scarf: scarf }), fl.g);
      p.g.position.set(x, seated ? SL - 0.2 : SL, z);
      p.g.rotation.y = rot;
      if (seated) { p.legs.forEach(function (l) { l.rotation.x = -Math.PI / 2; }); p.arms.forEach(function (a) { a.rotation.x = -0.6; }); }
      p.base = p.g.position.y;
      idlers.push(p);
      return p;
    }
    function chair(fl, x, z, rot) {
      var g2 = new T.Group(); g2.position.set(x, SL, z); g2.rotation.y = rot || 0; fl.g.add(g2);
      box(0.6, 0.1, 0.6, P.chair, 0, 0.6, 0, g2); box(0.6, 0.6, 0.1, P.chair, 0, 0.95, -0.3, g2); box(0.45, 0.5, 0.45, P.chairBase, 0, 0.3, 0, g2);
    }
    function bed(fl, code, x, z, rot) {
      var g2 = new T.Group(); g2.position.set(x, SL, z); g2.rotation.y = rot; fl.g.add(g2);
      var p = PATIENTS[code];
      box(1.1, 0.45, 2.1, P.bedFrame, 0, 0.25, 0, g2);
      box(1.0, 0.15, 2.0, P.sheet, 0, 0.55, 0, g2);
      box(1.1, 0.8, 0.12, P.pole, 0, 0.6, -1.05, g2);
      box(0.7, 0.12, 0.4, P.pillow, 0, 0.68, -0.7, g2, { outline: false });
      box(0.08, 1.6, 0.08, P.pole, 0.78, 0.8, -0.9, g2, { outline: false });
      box(0.5, 0.42, 0.1, P.monitor, 0.78, 1.7, -0.9, g2);
      var risk = p ? (p.score >= 0.7 ? P.high : p.score >= 0.45 ? P.med : P.low) : P.screenOff;
      var glow = box(0.4, 0.3, 0.12, B(risk), 0.78, 1.7, -0.88, g2, { cast: false, outline: false });
      bedPos[code] = { x: x, z: z, rot: rot, fl: fl };
      if (p) {
        var h = box(0.36, 0.36, 0.36, SKINS[p.i % 5], 0, 0.86, -0.72, g2);
        box(0.38, 0.36, 0.1, HAIRS[p.i % 5], 0, 0.86, -0.93, g2, { outline: false });
        box(0.8, 0.2, 0.3, P.shoulder, 0, 0.72, -0.4, g2);
        var bl = box(0.95, 0.25, 1.3, P.blanket, 0, 0.75, 0.3, g2);
        h.userData.code = code; bl.userData.code = code;
        pickables.push(h, bl);
        marker(mapC(risk), fl.g, x, SL + 2.0, z, 0.6);
        if (risk === P.high) {
          blinkers.push({ m: glow, c: risk });
          var s = new T.Sprite(new T.SpriteMaterial({ map: bangTex, depthTest: false }));
          s.renderOrder = 11;
          s.scale.set(0.8, 0.8, 1);
          s.position.set(x, SL + 2.9, z);
          fl.g.add(s);
          bangs.push(s);
        }
      }
    }

    function makeFloor(level) {
      var g2 = new T.Group();
      scene.add(g2);
      var fl = { level: level, g: g2, labels: [], y: level * FH, ty: level * FH };
      g2.position.y = fl.y;
      floors.push(fl);
      box(40.4, SL, 28.4, P.slab, 0, SL / 2, 0, g2, { cast: level > 0, shell: 'floor' });
      return fl;
    }
    function floorRect(fl, x1, x2, z1, z2, c) { box(x2 - x1, 0.02, z2 - z1, tileMat(c, x2 - x1, z2 - z1, 2), (x1 + x2) / 2, SL + 0.01, (z1 + z2) / 2, fl.g, { cast: false, outline: false, shell: 'floor' }); }
    function hwall(fl, z, x1, x2) { box(x2 - x1, WH, 0.3, P.wallInt, (x1 + x2) / 2, SL + WH / 2, z, fl.g, { shell: 'wall' }); box(x2 - x1, 0.12, 0.36, P.cap, (x1 + x2) / 2, SL + WH + 0.06, z, fl.g, { outline: false, shell: 'cap' }); }
    function vwall(fl, x, z1, z2) { box(0.3, WH, z2 - z1, P.wallInt, x, SL + WH / 2, (z1 + z2) / 2, fl.g, { shell: 'wall' }); box(0.36, 0.12, z2 - z1, P.cap, x, SL + WH + 0.06, (z1 + z2) / 2, fl.g, { outline: false, shell: 'cap' }); }
    function segs(gaps, a, b) { var out = [], cur = a; gaps.forEach(function (gp) { if (gp[0] > cur) out.push([cur, gp[0]]); cur = gp[1]; }); if (cur < b) out.push([cur, b]); return out; }
    // exterior wall with a window band
    function extWall(fl, axis, fixed, a, b) {
      var len = b - a, mid = (a + b) / 2;
      var put = function (w, h, y, c, mat) {
        if (axis === 'x') return box(len, h, 0.4, mat || c, mid, y, fixed, fl.g, { shell: 'wall' });
        return box(0.4, h, len, mat || c, fixed, y, mid, fl.g, { shell: 'wall' });
      };
      put(len, 1.0, SL + 0.5, P.wallExt);
      put(len, 0.6, SL + WH - 0.3, P.wallExt2);
      var lit = st.night ? B(P.glassLit) : null;
      var gm = put(len, 1.4, SL + 1.7, P.glass, lit);
      if (lit) litWindows.push(gm);
      for (var p = a + 2.5; p < b - 0.5; p += 2.5) {
        if (axis === 'x') box(0.25, 1.4, 0.46, P.wallExt, p, SL + 1.7, fixed, fl.g, { outline: false, shell: 'wall' });
        else box(0.46, 1.4, 0.25, P.wallExt, fixed, SL + 1.7, p, fl.g, { outline: false, shell: 'wall' });
      }
    }
    function roomLabels(fl, rooms) {
      rooms.forEach(function (rm) { fl.labels.push(label(rm[0], rm[1], rm[2], rm[3], SL + WH + 1.2, rm[4], 5.5, fl.g)); });
    }
    function stairs(fl) {
      for (var s = 0; s < 8; s++) box(1.2, 0.2 + s * 0.4, 0.5, P.slab, -19.2, SL + (0.2 + s * 0.4) / 2, -1.6 + s * 0.45, fl.g, { shell: 'wall' });
    }
    function shaft(fl) {
      var gm = new T.MeshLambertMaterial({ color: mapC(P.glass), transparent: true, opacity: 0.35 });
      box(0.1, WH, 4, gm, 17, SL + WH / 2, 0, fl.g, { cast: false });
      box(3, 0.1, 0.1, P.cap, 18.5, SL + WH, -2, fl.g, { outline: false });
    }
    function common(fl, nDoors, sDoors, nParts, sParts) {
      floorRect(fl, -20, 20, -2, 2, P.CORR);
      segs(nDoors, -20, 17).forEach(function (s) { hwall(fl, -2, s[0], s[1]); });
      segs(sDoors, -20, 17).forEach(function (s) { hwall(fl, 2, s[0], s[1]); });
      nParts.forEach(function (x) { vwall(fl, x, -14, -2); });
      sParts.forEach(function (p) { if (typeof p === 'number') vwall(fl, p, 2, 14); else vwall(fl, p[0], p[1], p[2]); });
      extWall(fl, 'x', -14.2, -20.4, 20.4);
      extWall(fl, 'z', -20.2, -14, 14);
      extWall(fl, 'z', 20.2, -14, 14);
      stairs(fl); shaft(fl);
    }

    // ===== Level 0: ER, imaging, pharmacy / triage, waiting, reception =====
    var f0 = makeFloor(0);
    floorRect(f0, -20, -4, -14, -2, P.ER); floorRect(f0, -4, 8, -14, -2, P.IMG); floorRect(f0, 8, 20, -14, -2, P.PHARM);
    floorRect(f0, -20, -4, 2, 14, P.TRIAGE); floorRect(f0, -4, 8, 2, 14, P.WAIT); floorRect(f0, 8, 20, 2, 14, P.RECEP);
    common(f0, [[-13, -10], [0, 3], [12, 14.5]], [[-13, -10], [-2, 4], [10, 13]], [-4, 8], [-4, [8, 2, 5], [8, 9, 14]]);
    extWall(f0, 'x', 14.2, -20.4, 12);
    extWall(f0, 'x', 14.2, 16, 20.4);
    box(6, 0.5, 1.2, P.ambStripe, 14, SL + WH - 0.2, 15, f0.g, { shell: 'wall' });
    f0.labels.push(label('MERCY GENERAL', '', '', 14, SL + WH + 0.9, 15.4, 8, f0.g));
    for (i = 0; i < 6; i++) {
      bed(f0, 'ER-' + (i + 1), -18 + i * 2.6, -12.4, 0);
      if (i < 5) box(0.05, 2.0, 2.4, P.curtain, -16.7 + i * 2.6, SL + 1.15, -12.2, f0.g, { shell: 'wall' });
    }
    box(2.8, 2.4, 1.0, P.machine, 2, SL + 1.2, -10, f0.g); box(1.2, 1.2, 1.05, P.monitor, 2, SL + 1.3, -10, f0.g, { outline: false });
    box(0.7, 0.7, 3.2, P.machineDark, 2, SL + 0.35, -8.2, f0.g); box(0.8, 0.12, 3.2, P.sheet, 2, SL + 0.76, -8.2, f0.g);
    [11, 14, 17].forEach(function (x) {
      box(0.7, 2.2, 4, P.wood, x, SL + 1.1, -9, f0.g);
      for (var row = 0; row < 3; row++) for (var c2 = 0; c2 < 5; c2++) box(0.2, 0.3, 0.5, P.meds[(row + c2 + x) % 4], x + 0.4, SL + 0.5 + row * 0.7, -10.6 + c2 * 0.8, f0.g, { outline: false });
    });
    box(3, 1.0, 0.9, P.wood, -12, SL + 0.5, 6, f0.g); chair(f0, -16, 9, Math.PI); chair(f0, -14.5, 9, Math.PI);
    box(0.8, 1.0, 4, P.wood, 18, SL + 0.5, 8, f0.g); box(1.0, 0.1, 4.2, P.woodDark, 18, SL + 1.05, 8, f0.g);
    [[9.2, 13], [9.2, 3]].forEach(function (p) { box(0.6, 0.6, 0.6, P.pot, p[0], SL + 0.3, p[1], f0.g); box(0.9, 1.0, 0.9, P.plant, p[0], SL + 1.1, p[1], f0.g); });
    var seated = 0;
    [7, 10].forEach(function (z) { for (var k = 0; k < 6; k++) {
      var x = -2.5 + k * 1.7; chair(f0, x, z, Math.PI);
      if (seated < 7 && (k + z) % 3 !== 1) { var s2 = seated++; stand(f0, { top: TOPS[s2], bottom: P.docPants }, x, z - 0.05, Math.PI, s2, s2 === 2 || s2 === 5 ? SCARVES[s2 % 4] : null, true); }
    } });
    roomLabels(f0, [['ER', '4/6', P.high, -12, -8], ['IMAGING', '', '', 2, -8], ['PHARMACY', '', '', 14, -8], ['TRIAGE', '2', P.med, -12, 8], ['WAITING', '7', P.high, 2, 8], ['RECEPTION', '', '', 14, 8]]);
    walker(f0, ROLE.nurse, [[-16, 0.4], [16, 0.4]], 1.6, 0, 0, SCARVES[0]);
    walker(f0, ROLE.doc, [[15, 1.2], [-16, 1.2]], 1.3, 9, 1);
    walker(f0, ROLE.nurse, [[-17, -9], [-6, -9]], 1.2, 0, 2);
    walker(f0, ROLE.doc, [[-11.5, -0.4], [-11.5, -7], [-7, -7]], 1.0, 3, 3, SCARVES[1]);
    walker(f0, { top: TOPS[0], bottom: P.docPants }, [[14, 24], [14, 11], [9.5, 7], [3.5, 5.3]], 1.3, 0, 3);
    walker(f0, ROLE.emt, [[13, 21], [13, 12], [11.5, 6], [11.5, 0.6], [-11.5, 0.6], [-11.5, -6]], 1.5, 0, 4);
    walker(f0, ROLE.emt, [[15, 21], [15, 12], [12.2, 6], [12.2, 1.0], [-10.8, 1.0], [-10.8, -6]], 1.5, 0, 1);
    walker(f0, ROLE.doc, [[10, -6], [18, -6]], 0.9, 2, 4, SCARVES[3]);
    stand(f0, ROLE.nurse, -12, 5.2, 0, 2, SCARVES[2]);
    stand(f0, { top: TOPS[1], bottom: P.docPants }, -15.25, 9, Math.PI, 0, null, true);
    stand(f0, { top: TOPS[4], bottom: P.docPants }, 19, 8, -Math.PI / 2, 1, SCARVES[2]);

    // ===== Level 1: Ward A, OR / Ward B, Recovery =====
    var f1 = makeFloor(1);
    floorRect(f1, -20, 6, -14, -2, P.WARD); floorRect(f1, 6, 20, -14, -2, P.OR); floorRect(f1, -20, 6, 2, 14, P.WARD); floorRect(f1, 6, 20, 2, 14, P.RECOV);
    common(f1, [[-14, -11], [-1, 2], [10, 13]], [[-14, -11], [-1, 2], [10, 13]], [6], [6]);
    extWall(f1, 'x', 14.2, -20.4, 20.4);
    for (i = 0; i < 8; i++) bed(f1, 'WARD-' + (i + 1), -18.5 + i * 2.9, -12.4, 0);
    for (i = 0; i < 6; i++) bed(f1, 'WARD-' + (i + 9), -18.5 + i * 3.0, 12.4, Math.PI);
    for (i = 0; i < 3; i++) bed(f1, 'REC-' + (i + 1), 9 + i * 3.5, 12.4, Math.PI);
    box(1.0, 0.9, 2.4, P.machineDark, 13, SL + 0.45, -8, f1.g); box(1.0, 0.12, 2.2, P.sheet, 13, SL + 0.96, -8, f1.g);
    box(0.4, 0.3, 1.4, P.gown, 13, SL + 1.17, -7.8, f1.g); box(0.34, 0.34, 0.34, SKINS[3], 13, SL + 1.2, -9, f1.g);
    box(0.1, 1.4, 0.1, P.pole, 13, SL + WH - 0.7, -8, f1.g, { outline: false });
    box(1.4, 0.25, 1.4, P.machine, 13, SL + 2.1, -8, f1.g); box(1.1, 0.06, 1.1, B(P.lamp), 13, SL + 1.96, -8, f1.g, { outline: false, cast: false });
    box(0.8, 1.6, 0.8, P.machineDark, 16.5, SL + 0.8, -9.5, f1.g);
    stand(f1, ROLE.surg, 11.9, -8, Math.PI / 2, 0, SCARVES[1]);
    stand(f1, ROLE.surg, 14.1, -8.4, -Math.PI / 2, 2);
    stand(f1, ROLE.surg, 13, -6.3, Math.PI, 4);
    roomLabels(f1, [['WARD A', '6/8', P.low, -7, -8], ['SURGERY', 'OR-1', P.med, 13, -8], ['WARD B', '5/6', P.med, -7, 8], ['RECOVERY', '2/3', P.low, 13, 8]]);
    walker(f1, ROLE.nurse, [[-16, 0.5], [16, 0.5]], 1.5, 4, 3);
    walker(f1, ROLE.nurse, [[-18, -9], [4, -9]], 1.3, 0, 0, SCARVES[0]);
    walker(f1, ROLE.nurse, [[-18, 9], [4, 9]], 1.2, 6, 1);
    walker(f1, ROLE.gown, [[-6, 1.2], [4, 1.2]], 0.45, 0, 2);
    walker(f1, ROLE.doc, [[8, 9], [18, 9]], 0.9, 2, 4);

    // ===== Level 2: ICU, Lab / Staff, Prayer room, Admin =====
    var f2 = makeFloor(2);
    floorRect(f2, -20, 6, -14, -2, P.ICU); floorRect(f2, 6, 20, -14, -2, P.LAB);
    floorRect(f2, -20, -4, 2, 14, P.STAFF); floorRect(f2, -4, 6, 2, 14, P.PRAY); floorRect(f2, 6, 20, 2, 14, P.ADMIN);
    common(f2, [[-14, -11], [-1, 2], [10, 13]], [[-13, -10], [0, 3], [10, 13]], [6], [-4, 6]);
    extWall(f2, 'x', 14.2, -20.4, 20.4);
    var gl = new T.MeshLambertMaterial({ color: mapC(P.glass), transparent: true, opacity: 0.35 });
    for (i = 0; i < 6; i++) {
      bed(f2, 'ICU-' + (i + 1), -18.5 + i * 3.6, -12.4, 0);
      if (i < 5) box(0.06, 2.4, 2.6, gl, -16.7 + i * 3.6, SL + 1.2, -12.3, f2.g, { cast: false });
    }
    [-9, -6].forEach(function (z) { box(12, 0.9, 1.0, P.machine, 13, SL + 0.45, z, f2.g); for (var x = 8.5; x < 18; x += 2.5) box(0.3, 0.5, 0.3, P.machineDark, x, SL + 1.15, z, f2.g); });
    box(4, 0.7, 1.2, P.couch, -12, SL + 0.35, 11.5, f2.g); box(4, 0.8, 0.3, P.couch, -12, SL + 0.9, 12.1, f2.g);
    box(1.8, 0.5, 1.0, P.wood, -12, SL + 0.25, 9, f2.g);
    box(1.2, 2.2, 0.8, P.machineDark, -18, SL + 1.1, 12.8, f2.g); box(0.9, 1.4, 0.05, B(P.vend), -18, SL + 1.3, 12.37, f2.g, { outline: false, cast: false });
    stand(f2, ROLE.nurse, -13, 11.4, Math.PI, 1, SCARVES[3], true);
    stand(f2, ROLE.doc, -11, 11.4, Math.PI, 3, null, true);
    for (var rr = 0; rr < 2; rr++) for (var rc = 0; rc < 4; rc++) {
      var rx = -2.6 + rc * 2.2, rz = 6 + rr * 3;
      box(1.4, 0.03, 2.4, [P.rug1, P.rug2, P.rug3][(rr + rc) % 3], rx, SL + 0.03, rz, f2.g, { cast: false });
      box(1.0, 0.035, 0.3, P.rug3, rx, SL + 0.04, rz - 0.9, f2.g, { cast: false, outline: false });
    }
    box(2.4, 0.8, 0.5, P.wood, 4.6, SL + 0.4, 12.8, f2.g);
    [[9, 7], [13, 7], [17, 7], [9, 11], [13, 11]].forEach(function (p, k) {
      box(2.2, 0.8, 1.0, P.wood, p[0], SL + 0.4, p[1], f2.g);
      box(0.8, 0.5, 0.08, P.monitor, p[0], SL + 1.1, p[1] - 0.3, f2.g);
      box(0.7, 0.4, 0.09, B(P.vend), p[0], SL + 1.1, p[1] - 0.28, f2.g, { outline: false, cast: false });
      if (k < 3) { chair(f2, p[0], p[1] + 1.0, Math.PI); stand(f2, { top: TOPS[k + 2], bottom: P.docPants }, p[0], p[1] + 0.95, Math.PI, k, k === 1 ? SCARVES[0] : null, true); }
    });
    roomLabels(f2, [['ICU', '5/6', P.med, -7, -8], ['LAB', '', '', 13, -8], ['STAFF', '', '', -12, 8], ['PRAYER', '', '', 1, 8], ['ADMIN', '', '', 13, 8]]);
    walker(f2, ROLE.nurse, [[-18, -9], [4, -9]], 1.2, 0, 2, SCARVES[1]);
    walker(f2, ROLE.doc, [[-12, 0.5], [-12, -7], [0, -7]], 1.0, 3, 3);
    walker(f2, ROLE.doc, [[8, -7.5], [18, -7.5]], 0.8, 1, 0, SCARVES[2]);
    walker(f2, ROLE.nurse, [[-16, 1.0], [16, 1.0]], 1.5, 8, 4);

    // ===== Roof =====
    var roof = new T.Group(); scene.add(roof);
    box(40.4, 0.4, 28.4, P.roof, 0, 0.2, 0, roof, { shell: 'floor' });
    box(40.4, 0.8, 0.4, P.wallExt2, 0, 0.8, -14.2, roof, { shell: 'wall' }); box(40.4, 0.8, 0.4, P.wallExt2, 0, 0.8, 14.2, roof, { shell: 'wall' });
    box(0.4, 0.8, 28.4, P.wallExt2, -20.2, 0.8, 0, roof, { shell: 'wall' }); box(0.4, 0.8, 28.4, P.wallExt2, 20.2, 0.8, 0, roof, { shell: 'wall' });
    box(12, 0.06, 12, P.helipad, 6, 0.43, 0, roof, { cast: false, shell: 'floor' });
    box(0.8, 0.07, 5, P.helipadMark, 4.4, 0.45, 0, roof, { cast: false, outline: false }); box(0.8, 0.07, 5, P.helipadMark, 7.6, 0.45, 0, roof, { cast: false, outline: false }); box(2.4, 0.07, 0.8, P.helipadMark, 6, 0.45, 0, roof, { cast: false, outline: false });
    [[-14, -8], [-14, 6], [-8, -8]].forEach(function (p) { box(3, 1.4, 2, P.machineDark, p[0], 1.1, p[1], roof); box(1.4, 0.2, 1.4, P.pole, p[0], 1.9, p[1], roof); });
    box(3, WH + 1.6, 4, P.wallExt2, 18.5, (WH + 1.6) / 2, 0, roof, { shell: 'wall' });
    var heli = new T.Group(); heli.position.set(6, 0.45, 0); roof.add(heli);
    box(2.0, 1.6, 3.2, P.heli, 0, 1.2, 0, heli); box(1.8, 0.8, 1.2, P.glass, 0, 1.4, 1.4, heli, { outline: false });
    box(0.5, 0.5, 3.6, P.heli, 0, 1.4, -3.2, heli); box(0.1, 1.0, 0.8, P.heli, 0.3, 1.8, -4.8, heli);
    box(0.15, 0.15, 3.4, P.heliDark, -0.8, 0.15, 0, heli); box(0.15, 0.15, 3.4, P.heliDark, 0.8, 0.15, 0, heli);
    var rotor = new T.Group(); rotor.position.set(0, 2.2, 0); heli.add(rotor);
    box(8, 0.06, 0.35, P.heliDark, 0, 0, 0, rotor, { cast: false }); box(0.35, 0.06, 8, P.heliDark, 0, 0, 0, rotor, { cast: false });
    roof.position.y = LEVELS * FH;
    var roofY = LEVELS * FH;

    // Elevator car
    var car = new T.Group(); scene.add(car);
    box(2.6, 2.8, 3.4, P.machine, 0, 1.4, 0, car, { shell: 'wall' }); box(2.4, 0.1, 3.2, P.slab, 0, 0.05, 0, car, { outline: false });
    var rider = person(Object.assign({}, ROLE.nurse, { skin: SKINS[1], hair: HAIRS[0], scarf: SCARVES[3] }), car); rider.g.position.set(0, 0.1, 0); rider.g.rotation.y = -Math.PI / 2;
    car.position.set(18.5, SL, 0);
    var carMat = car.children[0].material;

    // Ambulances
    function ambulance() {
      var g2 = new T.Group();
      box(2.2, 2.0, 3.2, P.ambBody, 0, 1.3, -0.4, g2); box(2.2, 1.4, 1.4, P.ambBody, 0, 1.0, 1.9, g2);
      box(2.0, 0.6, 0.05, P.glass, 0, 1.35, 2.61, g2, { outline: false }); box(2.26, 0.25, 4.6, P.ambStripe, 0, 0.9, 0.3, g2, { outline: false });
      [[-1.05, -1.3], [1.05, -1.3], [-1.05, 1.5], [1.05, 1.5]].forEach(function (p) { box(0.3, 0.6, 0.6, P.monitor, p[0], 0.35, p[1], g2); });
      var a = new T.MeshBasicMaterial({ color: '#e5484d' }), b = new T.MeshBasicMaterial({ color: '#3b6fd6' });
      box(0.4, 0.25, 0.3, a, -0.5, 2.42, 1.0, g2, { outline: false, cast: false }); box(0.4, 0.25, 0.3, b, 0.5, 2.42, 1.0, g2, { outline: false, cast: false });
      scene.add(g2); return { g: g2, a: a, b: b };
    }
    var amb1 = ambulance(); amb1.g.rotation.y = Math.PI / 2;
    var amb2 = ambulance(); amb2.g.position.set(17.5, 0, 20.5); amb2.g.rotation.y = Math.PI;

    // Selection ring
    var ring = new T.Group();
    var rm = B(P.ring);
    box(1.7, 0.08, 0.14, rm, 0, 0.05, -1.35, ring, { outline: false, cast: false }); box(1.7, 0.08, 0.14, rm, 0, 0.05, 1.35, ring, { outline: false, cast: false });
    box(0.14, 0.08, 2.7, rm, -0.85, 0.05, 0, ring, { outline: false, cast: false }); box(0.14, 0.08, 2.7, rm, 0.85, 0.05, 0, ring, { outline: false, cast: false });
    var selCode = opts.selected || 'ICU-3';

    // ---------- View state ----------
    var view = 'all', exploded = false;
    function applyView() {
      floors.forEach(function (f) {
        var vis = view === 'all' || exploded || f.level <= view;
        f.g.visible = vis;
        var showLabels = exploded || (view !== 'all' && f.level === view);
        f.labels.forEach(function (s) { s.visible = showLabels; });
        f.ty = f.level * (exploded ? FH + 6 : (xray && view === 'all') ? FH + 3.5 : FH);
      });
      roof.visible = view === 'all' || exploded;
      // the entrance sign stays visible from outside
      floors[0].labels[0].visible = view === 'all' || exploded || view === 0;
    }
    applyView();

    var xrayCache = {};
    var faintLine = new T.LineBasicMaterial({ color: st.outlineColor, transparent: true, opacity: 0.22 });
    function setXray(on) {
      on = !!on; if (on === xray) return; xray = on;
      shellMeshes.forEach(function (m) {
        if (on) {
          if (!m.userData.orig) m.userData.orig = m.material;
          var o = m.userData.orig, key = o.uuid + m.userData.shell;
          if (!xrayCache[key]) { var c = o.clone(); c.transparent = true; c.opacity = m.userData.shell === 'floor' ? 0.55 : m.userData.shell === 'cap' ? 0.25 : 0.07; c.depthWrite = false; xrayCache[key] = c; }
          m.material = xrayCache[key];
          m.castShadow = false;
          m.children.forEach(function (ch) { if (ch.isLineSegments) ch.material = faintLine; });
        } else if (m.userData.orig) {
          m.material = m.userData.orig; m.castShadow = true;
          m.children.forEach(function (ch) { if (ch.isLineSegments) ch.material = lineMat; });
        }
      });
      markers.forEach(function (s) { s.visible = on; });
      applyView();
    }

    // ---------- Camera ----------
    var aspect = W / H;
    var cam, ortho = !!st.ortho;
    var cs;
    if (ortho) {
      var S = 46;
      cam = new T.OrthographicCamera(-S * aspect / 2, S * aspect / 2, S / 2, -S / 2, -500, 500);
      cs = { tx: 0, ty: 4, tz: 0, az: Math.PI / 4, el: 0.4636, zoom: 1 };
    } else {
      cam = new T.PerspectiveCamera(55, aspect, 0.1, 500);
      cam.rotation.order = 'YXZ';
      cs = { x: -34, y: 26, z: 44, yaw: 0, pitch: 0 };
      var l0 = look(-34, 26, 44, 0, 4, 0); Object.assign(cs, l0);
    }
    function look(px, py, pz, tx, ty, tz) { var dx2 = tx - px, dy = ty - py, dz = tz - pz; return { x: px, y: py, z: pz, yaw: Math.atan2(-dx2, -dz), pitch: Math.atan2(dy, Math.hypot(dx2, dz)) }; }
    var tween = null;
    function flyTo(to) { tween = { t0: performance.now(), from: Object.assign({}, cs), to: to }; }
    var PRESETS = {
      'Outside': { view: 'all', ex: false, p: look(-34, 26, 44, 0, 4, 0), o: { tx: 0, ty: 5, tz: 0, az: Math.PI / 4, el: 0.4636, zoom: 1 } },
      'Ground floor': { view: 0, ex: false, p: look(-4, 20, 26, 0, 0, 0), o: { tx: 0, ty: 0, tz: 0, az: Math.PI / 4, el: 0.62, zoom: 1.25 } },
      'Floor 2 \u00b7 Wards': { view: 1, ex: false, p: look(-4, 20 + FH, 26, 0, FH, 0), o: { tx: 0, ty: FH, tz: 0, az: Math.PI / 4, el: 0.62, zoom: 1.25 } },
      'Floor 3 \u00b7 ICU': { view: 2, ex: false, p: look(-4, 20 + 2 * FH, 26, 0, 2 * FH, 0), o: { tx: 0, ty: 2 * FH, tz: 0, az: Math.PI / 4, el: 0.62, zoom: 1.25 } },
      'Exploded': { view: 'all', ex: true, p: look(-46, 30, 52, 0, 10, 0), o: { tx: 0, ty: 12, tz: 0, az: Math.PI / 4, el: 0.4636, zoom: 0.62 } },
      'Helipad': { view: 'all', ex: false, p: look(22, 22, -26, 6, 3 * FH, 0), o: { tx: 6, ty: 3 * FH, tz: 0, az: -Math.PI / 4 * 3, el: 0.6, zoom: 2.2 } },
      'Front door': { view: 0, ex: false, p: look(14, 1.7, 26, 14, 1.6, 0), o: { tx: 14, ty: 1, tz: 12, az: 0, el: 0.3, zoom: 2.6 } },
      'Side view': { view: 1, ex: false, p: look(-6, FH + 4.5, 30, -6, FH + 2.2, 0), o: { tx: -2, ty: FH + 1, tz: 0, az: 0, el: 0.12, zoom: 1.5 } },
      'ICU close-up': { view: 2, ex: false, p: look(-3, 2 * FH + 7, 4, -10, 2 * FH + 0.6, -11.5), o: { tx: -9, ty: 2 * FH, tz: -9, az: Math.PI / 5, el: 0.7, zoom: 2.8 } }
    };
    function jump(name) {
      var pr = PRESETS[name]; if (!pr) return;
      view = pr.view; exploded = pr.ex; applyView();
      floors.forEach(function (f) { f.y = f.ty; f.g.position.y = f.y; });
      Object.assign(cs, ortho ? pr.o : pr.p);
      if (opts.onView) opts.onView({ view: view, exploded: exploded });
    }
    function preset(name) {
      var pr = PRESETS[name]; if (!pr) return;
      view = pr.view; exploded = pr.ex; applyView();
      flyTo(ortho ? pr.o : pr.p);
      if (opts.onView) opts.onView({ view: view, exploded: exploded });
    }

    // ---------- Input ----------
    var keys = {};
    var drag = null;
    var ray = new T.Raycaster();
    function visibleChain(o) { while (o) { if (!o.visible) return false; o = o.parent; } return true; }
    function pick(nx, ny) {
      ray.setFromCamera({ x: nx, y: ny }, cam);
      var hits = ray.intersectObjects(pickables, false);
      for (var k = 0; k < hits.length; k++) { if (visibleChain(hits[k].object)) { selCode = hits[k].object.userData.code; if (opts.onPick) opts.onPick(selCode); return; } }
    }
    var KEYS = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'];
    var input = {
      keyDown: function (e) { if (KEYS.indexOf(e.code) >= 0) { e.preventDefault(); keys[e.code] = true; } },
      keyUp: function (e) { keys[e.code] = false; },
      blur: function () { keys = {}; },
      pointerDown: function (e) { try { e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId); } catch (er) {} drag = { x: e.clientX, y: e.clientY, moved: 0 }; tween = null; },
      pointerMove: function (e) {
        if (!drag) return;
        var mx = e.clientX - drag.x, my = e.clientY - drag.y;
        drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(mx) + Math.abs(my);
        if (ortho) { cs.az -= mx * 0.006; cs.el = Math.max(0.15, Math.min(1.35, cs.el + my * 0.004)); }
        else { cs.yaw -= mx * 0.005; cs.pitch = Math.max(-1.5, Math.min(1.5, cs.pitch - my * 0.005)); }
      },
      pointerUp: function (e) {
        var d2 = drag; drag = null;
        if (d2 && d2.moved < 5) { var b = e.currentTarget.getBoundingClientRect(); pick(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1); }
      },
      wheel: function (e) {
        tween = null;
        if (ortho) { cs.zoom = Math.max(0.4, Math.min(5, cs.zoom * (e.deltaY > 0 ? 0.9 : 1.1))); return; }
        var s = -e.deltaY * 0.02;
        cs.x += -Math.sin(cs.yaw) * Math.cos(cs.pitch) * s; cs.y += Math.sin(cs.pitch) * s; cs.z += -Math.cos(cs.yaw) * Math.cos(cs.pitch) * s;
      }
    };

    // ---------- Loop ----------
    var dead = false, raf = 0, last = performance.now(), time = 0;
    function frame(now) {
      if (dead) return;
      var dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = Math.max(last, now); time += dt;
      floors.forEach(function (f) { f.y += (f.ty - f.y) * Math.min(1, dt * 6); f.g.position.y = f.y; });
      var topTy = floors[LEVELS - 1].y + FH;
      roof.position.y += ((exploded ? topTy + 6 : (xray && view === 'all') ? topTy + 3.5 : topTy) - roof.position.y) * Math.min(1, dt * 6);
      walkers.forEach(function (w) {
        var s = (w.off + time * w.speed) % w.L;
        var sg = w.seg[0];
        for (var k = 0; k < w.seg.length; k++) { if (s >= w.seg[k].s0 && s <= w.seg[k].s0 + w.seg[k].d) { sg = w.seg[k]; break; } }
        var f = sg.d ? (s - sg.s0) / sg.d : 0;
        w.g.position.x = sg.ax + (sg.bx - sg.ax) * f;
        w.g.position.z = sg.az + (sg.bz - sg.az) * f;
        w.g.rotation.y = Math.atan2(sg.bx - sg.ax, sg.bz - sg.az);
        var sw = Math.sin(time * (2 + w.speed * 3)) * 0.6;
        w.legs[0].rotation.x = sw; w.legs[1].rotation.x = -sw;
        w.arms[0].rotation.x = -sw * 0.8; w.arms[1].rotation.x = sw * 0.8;
      });
      idlers.forEach(function (p, k) { p.g.position.y = p.base + Math.sin(time * 2 + k) * 0.012; });
      var on = Math.floor(time * 6) % 2 === 0;
      [amb1, amb2].forEach(function (a) { a.a.color.set(on ? '#e5484d' : '#5a1418'); a.b.color.set(on ? '#14244a' : '#3b6fd6'); });
      amb1.g.position.set(((time * 12) % 180) - 90, 0, 26.2);
      blinkers.forEach(function (b) { b.m.material.color.set(Math.floor(time * 3) % 2 ? b.c : '#200608'); });
      bangs.forEach(function (s, k) { s.position.y = SL + 2.9 + Math.sin(time * 4 + k) * 0.15; });
      rotor.rotation.y += dt * 9;
      // elevator: ride between floors with pauses
      var cyc = (time % 18) / 18, lv;
      var stops = [0, 1, 2, 1];
      var seg4 = cyc * 4, si = Math.floor(seg4), sf = seg4 - si;
      var a0 = stops[si], a1 = stops[(si + 1) % 4];
      lv = sf < 0.55 ? a0 : a0 + (a1 - a0) * ((sf - 0.55) / 0.45);
      var lo = Math.floor(lv), hi = Math.min(LEVELS - 1, lo + 1), fr = lv - lo;
      car.position.y = floors[lo].y + (floors[hi].y - floors[lo].y) * fr + SL;
      car.visible = view === 'all' || exploded || lv <= view + 0.01;
      var sel = bedPos[selCode];
      if (sel && PATIENTS[selCode]) { ring.visible = true; if (ring.parent !== sel.fl.g) sel.fl.g.add(ring); ring.position.set(sel.x, SL, sel.z); ring.rotation.y = sel.rot; } else ring.visible = false;

      if (tween) {
        var u = Math.min(1, (now - tween.t0) / 1200), e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2, fk = tween.from, tk = tween.to;
        Object.keys(tk).forEach(function (k) {
          var dv = tk[k] - fk[k];
          if (k === 'yaw' || k === 'az') dv = Math.atan2(Math.sin(dv), Math.cos(dv));
          cs[k] = fk[k] + dv * e;
        });
        if (u >= 1) tween = null;
      }
      var sp = (keys.ShiftLeft || keys.ShiftRight ? 30 : 10) * dt;
      var yawN = ortho ? cs.az + Math.PI : cs.yaw;
      var fx = -Math.sin(yawN), fz = -Math.cos(yawN), rx = Math.cos(yawN), rz = -Math.sin(yawN);
      var mvx = 0, mvz = 0, mvy = 0;
      if (keys.KeyW || keys.ArrowUp) { mvx += fx; mvz += fz; }
      if (keys.KeyS || keys.ArrowDown) { mvx -= fx; mvz -= fz; }
      if (keys.KeyD || keys.ArrowRight) { mvx += rx; mvz += rz; }
      if (keys.KeyA || keys.ArrowLeft) { mvx -= rx; mvz -= rz; }
      if (keys.KeyE || keys.Space) mvy += 1;
      if (keys.KeyQ) mvy -= 1;
      if (mvx || mvz || mvy) tween = null;
      if (ortho) {
        var ps = sp / cs.zoom;
        cs.tx += mvx * ps; cs.tz += mvz * ps; cs.ty = Math.max(0, Math.min(30, cs.ty + mvy * ps));
        var dist = 120;
        cam.position.set(cs.tx + Math.sin(cs.az) * Math.cos(cs.el) * dist, cs.ty + Math.sin(cs.el) * dist, cs.tz + Math.cos(cs.az) * Math.cos(cs.el) * dist);
        cam.lookAt(cs.tx, cs.ty, cs.tz);
        if (cam.zoom !== cs.zoom) { cam.zoom = cs.zoom; cam.updateProjectionMatrix(); }
      } else {
        cs.x += mvx * sp; cs.z += mvz * sp; cs.y = Math.max(0.8, Math.min(120, cs.y + mvy * sp));
        cam.position.set(cs.x, cs.y, cs.z);
        cam.rotation.y = cs.yaw; cam.rotation.x = cs.pitch;
      }
      r.render(scene, cam);
      raf = requestAnimationFrame(frame);
    }
    if (opts.xray) setXray(true);
    if (opts.preset) jump(opts.preset);
    raf = requestAnimationFrame(frame);

    return {
      setXray: setXray,
      input: input,
      presets: Object.keys(PRESETS),
      preset: preset,
      setPixel: setPixel,
      select: function (code) { selCode = code; },
      focusSelected: function () {
        var b = bedPos[selCode]; if (!b) return;
        view = b.fl.level; exploded = false; applyView();
        if (opts.onView) opts.onView({ view: view, exploded: exploded });
        var by = b.fl.level * FH;
        if (ortho) flyTo({ tx: b.x, ty: by, tz: b.z, az: cs.az, el: 0.7, zoom: 3.2 });
        else flyTo(look(b.x + 2.5, by + 4.5, b.z + (b.rot ? -4 : 4), b.x, by + 0.8, b.z));
      },
      dispose: function () { dead = true; cancelAnimationFrame(raf); r.dispose(); }
    };
  }

  window.Pulse3D = { mount: mount, patients: PATIENTS, styles: Object.keys(STYLES) };
})();
