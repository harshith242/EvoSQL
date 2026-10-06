// 04: after a miss, Xiaohei carries a draft notes page through a gate that re-checks 2 earlier right answers;
// the page joins the notes only if both stay right, otherwise it drops into the reject bin.

// The miss and the edits proposed from it.
sheet(110, 560, 110, 140, 4);
text(195, 600, "✗", 54, RED, "middle", 700);
sheet(260, 540, 150, 180, 5, { stroke: BLUE, strokeWidth: 2.4 }, "#9bb6dd");
text(335, 760, "+ add   ~ replace   − delete", 26, BLUE, "middle", 600);
label(300, 390, "propose_edits", "notes.py", "edits + evidence", BLUE);

// A sieve drops invalid or leaking edits.
path("M450 600 L590 600 L560 660 L480 660 Z", { strokeWidth: 2.2 });
for (let i = 0; i < 6; i++) line(470 + i * 22, 600, 486 + i * 15, 660, { strokeWidth: 1 });
rect(498, 700, 30, 20, { stroke: RED, strokeWidth: 2 }); rect(535, 730, 30, 20, { stroke: RED, strokeWidth: 2 });
label(520, 820, "validate", "notes.py", "no leak, has evidence");

// Xiaohei carries the draft page through the gate.
xiaohei(800, 860, 1.6, [[760, 650], [840, 650]], [[770, 860], [830, 860]]);
sheet(750, 560, 100, 90, 3, { stroke: BLUE, strokeWidth: 2.6 }, "#9bb6dd");
arrow([[620, 560], [690, 520], [740, 560]], { stroke: ORANGE, strokeWidth: 3 });

// The gate: two posts, a bar, two earlier right answers re-checked on stands, and a size limit sign.
line(940, 860, 940, 470, { strokeWidth: 3 }); line(1180, 860, 1180, 470, { strokeWidth: 3 });
line(940, 470, 1180, 470, { strokeWidth: 3 });
for (const [x, tag] of [[985, "most similar"], [1135, "random"]]) {
  line(x, 860, x, 760, { strokeWidth: 2 });
  sheet(x - 38, 660, 76, 96, 3);
  text(x, 645, "✓", 46, ORANGE, "middle", 700);
  text(x, 900, tag, 25, "#444", "middle", 600);
}
rect(1010, 400, 100, 50, { strokeWidth: 2 }); text(1060, 437, "≤ 100", 30, INK, "middle", 700);
label(1060, 230, "update_notes", "stream.py", "2 earlier right answers re-checked", ORANGE);

// Pass: the page joins the notes. Fail: it drops into the reject bin.
arrow([[1200, 600], [1300, 560], [1400, 600]], { stroke: ORANGE, strokeWidth: 3 });
rect(1420, 480, 230, 300, { fill: "#fff", fillStyle: "solid", stroke: BLUE, strokeWidth: 2.8 });
for (let i = 0; i < 8; i++) line(1440, 520 + i * 32, 1620 - (i % 3) * 40, 520 + i * 32, { stroke: "#9bb6dd", strokeWidth: 1.4 });
label(1535, 380, "applied", "Notes", "edit kept", ORANGE);
arrow([[1180, 700], [1250, 800], [1330, 860]], { stroke: RED, strokeWidth: 2.6 });
path("M1340 840 L1460 840 L1445 960 L1355 960 Z", { strokeWidth: 2.2 });
label(1640, 880, "rejected", "regression", "notes unchanged", RED, "start");

shift(110);
done();
