// 05: four piles of correct answers on MIMIC-IV (all 127 questions); Xiaohei measures the tallest with a tape.

const floor = 900, scale = 620;
line(120, floor, 1700, floor, { strokeWidth: 2.6 });
const piles = [["none", 0.535, 260, INK], ["facts", 0.543, 560, INK], ["examples", 0.772, 860, INK],
               ["examples + notes", 0.890, 1200, ORANGE]];

// Each pile is a messy stack of answer sheets as tall as its accuracy.
for (const [name, acc, x, color] of piles) {
  const top = floor - acc * scale;
  for (let y = floor; y > top + 18; y -= 18) {
    const wob = ((y * 7) % 13) - 6;
    rect(x - 80 + wob, y - 18, 160, 16, { strokeWidth: 1.3, stroke: color === ORANGE ? ORANGE : INK, roughness: 1.6 });
  }
  text(x, floor + 50, name, 38, color, "middle", 700);
  text(x, top - 20, acc.toFixed(2), 40, color, "middle", 700);
}

// Xiaohei on a little ladder holds the tape measure against the tallest pile.
const topNotes = floor - 0.890 * scale;
line(1380, floor, 1420, 560, { strokeWidth: 2.4 }); line(1460, floor, 1470, 560, { strokeWidth: 2.4 });
for (let y = 860; y > 580; y -= 50) line(1384 + (floor - y) * 0.04, y, 1462 + (floor - y) * 0.01, y, { strokeWidth: 1.8 });
xiaohei(1430, 560, 1.4, [[1310, topNotes + 10], [1320, floor - 10]], [[1415, 560], [1450, 560]]);
line(1305, topNotes + 10, 1310, floor - 6, { stroke: ORANGE, strokeWidth: 4, roughness: 0.6 });
for (let y = floor - 40; y > topNotes + 20; y -= 40) line(1300, y, 1318, y, { stroke: ORANGE, strokeWidth: 2 });

text(910, 200, "MIMIC-IV: share of all 127 questions answered right", 36, INK, "middle", 700);
text(1560, 300, "BIRD formula_1:", 30, BLUE, "middle", 700);
text(1560, 340, "0.59 · 0.62 · 0.71 · 0.73", 30, BLUE, "middle", 600);
text(910, 1010, "results/mimic/v9_summary.md · results/arcwise/v9_formula_1_summary.md", 26, "#666", "middle", 500);

shift(60);
done();
