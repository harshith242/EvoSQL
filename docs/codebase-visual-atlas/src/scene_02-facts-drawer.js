// 02: after a miss, one fact card is written and stamped; a judge's magnifier lifts at most 2 cards for a new question.

// The miss: a wrong answer sheet, and the fact card written from it.
sheet(120, 600, 110, 140, 4);
text(205, 640, "✗", 54, RED, "middle", 700);
line(240, 690, 300, 690, { stroke: ORANGE, strokeWidth: 2.6 }); head(300, 690, 0, { stroke: ORANGE, strokeWidth: 2.6 });
rect(315, 630, 170, 110, { fill: "#fff", fillStyle: "solid" });
text(400, 670, "1 fact", 30, INK, "middle", 700);
line(335, 695, 465, 695, { stroke: "#777", strokeWidth: 1.4 }); line(335, 718, 440, 718, { stroke: "#777", strokeWidth: 1.4 });
label(300, 820, "propose", "proposer.py", "one fact per miss");

// Xiaohei slams an inspection stamp on the card before it may be filed.
line(400, 520, 400, 610, { strokeWidth: 3 });
rect(355, 600, 90, 26, { fill: INK, fillStyle: "solid" });
ellipse(400, 505, 54, 34, { fill: INK, fillStyle: "solid" });
xiaohei(540, 760, 1.6, [[412, 512], [420, 530]], [[515, 760], [565, 760]]);
text(400, 760, "checked", 30, ORANGE, "middle", 700);
label(560, 330, "check", "facts.py", "real columns, no leak");

// The card drawer: every kept fact.
arrow([[620, 640], [700, 600], [790, 620]], { stroke: ORANGE, strokeWidth: 3 });
poly([[800, 640], [1180, 640], [1220, 600], [840, 600]], { strokeWidth: 2 });
rect(800, 640, 380, 140, { strokeWidth: 2.4 });
line(1180, 780, 1220, 740); line(1220, 600, 1220, 740);
for (let i = 0; i < 9; i++) rect(818 + i * 40, 560 + (i % 3) * 8, 32, 80, { fill: "#fff", fillStyle: "solid", strokeWidth: 1.4 });

// The judge (JEV): a magnifier on a crane that scores every card and lifts at most 2.
line(1300, 780, 1300, 330, { strokeWidth: 2.6 }); line(1300, 330, 1010, 330, { strokeWidth: 2.6 });
line(1010, 330, 1010, 380, { strokeWidth: 1.6 });
circle(1010, 430, 100, { stroke: BLUE, strokeWidth: 3 }); line(1045, 466, 1080, 500, { stroke: BLUE, strokeWidth: 4 });
rect(920, 455, 34, 80, { fill: "#fff", fillStyle: "solid", stroke: ORANGE, strokeWidth: 2.4 });
rect(1062, 455, 34, 80, { fill: "#fff", fillStyle: "solid", stroke: ORANGE, strokeWidth: 2.4 });
label(1010, 210, "fact_scores + pick", "jev.py · memory.py", "score ≥ 2.75, at most 2", BLUE);

// The two picked cards go into the prompt for the new question.
arrow([[1110, 480], [1300, 450], [1440, 520]], { stroke: ORANGE, strokeWidth: 3 });
sheet(1450, 480, 200, 250, 6);
rect(1475, 600, 70, 100, { fill: "#fff", fillStyle: "solid", stroke: ORANGE, strokeWidth: 2.2 });
rect(1560, 600, 70, 100, { fill: "#fff", fillStyle: "solid", stroke: ORANGE, strokeWidth: 2.2 });
text(1550, 465, "prompt for q42", 30, INK, "middle", 600);

// Cards that break answers go to the bin; the drawer is tidied every 15 questions.
path("M1680 820 L1800 820 L1785 940 L1695 940 Z", { strokeWidth: 2.2 });
ellipse(1740, 800, 60, 40, { stroke: RED, strokeWidth: 2.4 });
label(1740, 1000, "credit", "memory.py", "retire if it hurts", RED);
line(950, 830, 1100, 930, { strokeWidth: 2.4 });
for (let i = 0; i < 6; i++) line(1100, 930, 1080 + i * 12, 980, { strokeWidth: 1.6 });
label(1000, 1000, "consolidate", "every 15 questions", "merge · generalize");

shift(80);
done();
