// Drawing kit for the atlas scenes: rough strokes, handwritten labels and Xiaohei.
const W = 1920, H = 1080;
const INK = "#1b1b1b", ORANGE = "#e8731a", RED = "#d33b2c", BLUE = "#2f6db5";
const svg = document.getElementById("scene");
const rc = rough.svg(svg);
const opts = (o = {}) => ({ stroke: INK, strokeWidth: 2.2, roughness: 1.4, bowing: 1.2, ...o });

function add(node) { svg.appendChild(node); return node; }
function line(x1, y1, x2, y2, o) { return add(rc.line(x1, y1, x2, y2, opts(o))); }
function rect(x, y, w, h, o) { return add(rc.rectangle(x, y, w, h, opts(o))); }
function ellipse(cx, cy, w, h, o) { return add(rc.ellipse(cx, cy, w, h, opts(o))); }
function circle(cx, cy, d, o) { return add(rc.circle(cx, cy, d, opts(o))); }
function path(d, o) { return add(rc.path(d, opts(o))); }
function poly(points, o) { return add(rc.polygon(points, opts(o))); }
function curve(points, o) { return add(rc.curve(points, opts(o))); }

// An open arrowhead at (x, y) pointing along angle (radians).
function head(x, y, angle, o) {
  const a = 0.5, len = 22;
  line(x, y, x - len * Math.cos(angle - a), y - len * Math.sin(angle - a), o);
  line(x, y, x - len * Math.cos(angle + a), y - len * Math.sin(angle + a), o);
}

// A curved arrow through points, with a head at the last point.
function arrow(points, o) {
  curve(points, o);
  const [x1, y1] = points[points.length - 2], [x2, y2] = points[points.length - 1];
  head(x2, y2, Math.atan2(y2 - y1, x2 - x1), o);
}

function text(x, y, s, size = 34, color = INK, anchor = "middle", weight = 600) {
  const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
  t.setAttribute("x", x); t.setAttribute("y", y);
  t.setAttribute("font-family", "Caveat, 'Patrick Hand', cursive");
  t.setAttribute("font-size", size); t.setAttribute("font-weight", weight);
  t.setAttribute("fill", color); t.setAttribute("text-anchor", anchor);
  t.textContent = s;
  return add(t);
}

// A label: Name, then file/symbol, then an optional short behavior.
function label(x, y, name, where, what, color = INK, anchor = "middle") {
  text(x, y, name, 40, color, anchor, 700);
  text(x, y + 32, where, 27, "#555", anchor, 500);
  if (what) text(x, y + 62, what, 29, color === INK ? "#333" : color, anchor, 500);
}

// Xiaohei: small black deadpan figure. (x, y) is between the feet; hands and feet are absolute points.
function xiaohei(x, y, s, hands, feet = [[x - 20 * s, y], [x + 20 * s, y]]) {
  const shoulderY = y - 78 * s, hipY = y - 30 * s;
  const limb = { strokeWidth: 3.2 * s, roughness: 0.9 };
  line(x - 14 * s, shoulderY, hands[0][0], hands[0][1], limb);
  line(x + 14 * s, shoulderY, hands[1][0], hands[1][1], limb);
  line(x - 9 * s, hipY, feet[0][0], feet[0][1], limb);
  line(x + 9 * s, hipY, feet[1][0], feet[1][1], limb);
  const solid = { fill: INK, fillStyle: "solid", stroke: INK, roughness: 0.7 };
  ellipse(x, y - 58 * s, 46 * s, 66 * s, solid);
  circle(x, y - 112 * s, 54 * s, solid);
  const eye = { fill: "#fff", fillStyle: "solid", stroke: "#fff", strokeWidth: 0.5, roughness: 0.2 };
  circle(x - 10 * s, y - 115 * s, 8 * s, eye);
  circle(x + 9 * s, y - 115 * s, 8 * s, eye);
}

// A sheet of paper with a few scribbled lines.
function sheet(x, y, w, h, lines = 4, o = {}, lineColor = "#777") {
  rect(x, y, w, h, { fill: "#fff", fillStyle: "solid", ...o });
  for (let i = 0; i < lines; i++) {
    const ly = y + 22 + i * (h - 34) / Math.max(lines, 1);
    line(x + 14, ly, x + w - 14 - (i % 2) * w * 0.25, ly, { stroke: lineColor, strokeWidth: 1.4, roughness: 1.2 });
  }
}

function done() { document.fonts.ready.then(() => { window.sceneDone = true; }); }

// Shift the visible frame down by dy, to centre a scene drawn low on the canvas.
function shift(dy) { svg.setAttribute("viewBox", `0 ${dy} ${W} ${H}`); }
